# streamlit_app.py
import streamlit as st
import threading, queue, time, os
import cv2
import numpy as np
from collections import OrderedDict
from scipy.spatial import distance as dist

# Optional: ultralytics YOLO
try:
    from ultralytics import YOLO
    ULTRALYTICS_AVAILABLE = True
except Exception:
    ULTRALYTICS_AVAILABLE = False

# ----------------------------
# Simple CentroidTracker
# ----------------------------
class CentroidTracker:
    def __init__(self, max_disappeared=50, max_distance=60):
        self.nextObjectID = 0
        self.objects = OrderedDict()
        self.disappeared = OrderedDict()
        self.history = OrderedDict()
        self.maxDisappeared = max_disappeared
        self.maxDistance = max_distance

    def register(self, centroid):
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.history[self.nextObjectID] = [centroid]
        self.nextObjectID += 1

    def deregister(self, objectID):
        if objectID in self.objects: del self.objects[objectID]
        if objectID in self.disappeared: del self.disappeared[objectID]
        if objectID in self.history: del self.history[objectID]

    def update(self, rects):
        if len(rects) == 0:
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)
            return self.objects

        inputCentroids = np.zeros((len(rects), 2), dtype="int")
        for (i, (sx, sy, ex, ey)) in enumerate(rects):
            cX = int((sx + ex) / 2.0)
            cY = int((sy + ey) / 2.0)
            inputCentroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(len(inputCentroids)):
                self.register(tuple(inputCentroids[i]))
        else:
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())
            if len(objectCentroids) == 0:
                for i in range(len(inputCentroids)):
                    self.register(tuple(inputCentroids[i]))
                return self.objects
            D = dist.cdist(np.array(objectCentroids), inputCentroids)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            usedRows, usedCols = set(), set()
            for (row, col) in zip(rows, cols):
                if row in usedRows or col in usedCols:
                    continue
                if D[row, col] > self.maxDistance:
                    continue
                objectID = objectIDs[row]
                self.objects[objectID] = tuple(inputCentroids[col])
                self.disappeared[objectID] = 0
                self.history[objectID].append(tuple(inputCentroids[col]))
                if len(self.history[objectID]) > 30:
                    self.history[objectID].pop(0)
                usedRows.add(row)
                usedCols.add(col)
            unusedRows = set(range(0, D.shape[0])).difference(usedRows)
            unusedCols = set(range(0, D.shape[1])).difference(usedCols)
            if D.shape[0] >= D.shape[1]:
                for row in unusedRows:
                    objectID = objectIDs[row]
                    self.disappeared[objectID] += 1
                    if self.disappeared[objectID] > self.maxDisappeared:
                        self.deregister(objectID)
            else:
                for col in unusedCols:
                    self.register(tuple(inputCentroids[col]))
        return self.objects

def calc_speed_m_s(history, pixels_to_m=0.005, window_seconds=0.5):
    if len(history) < 2:
        return 0.0
    ptA = history[-1]
    ptB = history[0]
    d_pixels = np.linalg.norm(np.array(ptA) - np.array(ptB))
    d_meters = d_pixels * pixels_to_m
    speed = d_meters / window_seconds
    return speed
# ----------------------------
# Shared video capture thread
# ----------------------------
class VideoCaptureThread(threading.Thread):
    # MODIFICADO: Acepta dos colas para duplicar el frame
    def __init__(self, src, person_q, comp_q, stop_event):
        super().__init__(daemon=True)
        self.src = src
        self.person_q = person_q
        self.comp_q = comp_q
        self.stop_event = stop_event
        self.cap = None

    def run(self):
        self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            print("Capture open failed")
            return
        while not self.stop_event.is_set():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # Enviar copia a Personas
            if not self.person_q.full():
                self.person_q.put(frame.copy())

            # Enviar copia a Componentes (YOLO)
            if not self.comp_q.full():
                self.comp_q.put(frame.copy())

            # Control de velocidad de captura ligero
            time.sleep(0.01)
        self.cap.release()

# ----------------------------
# Person processing thread
# ----------------------------
class PersonProcessor(threading.Thread):
    def __init__(self, frame_q, out_q, stop_event, pixels_to_m=0.005, person_detector=None):
        super().__init__(daemon=True)
        self.frame_q = frame_q
        self.out_q = out_q
        self.stop_event = stop_event
        self.pixels_to_m = pixels_to_m
        self.detector = person_detector
        self.ct = CentroidTracker(max_disappeared=20, max_distance=80)

    def detect_persons(self, frame):
        rects = []
        if self.detector is None:
            return rects

        if isinstance(self.detector, tuple):
            net = self.detector[0]
            h, w = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300,300)), 0.007843, (300,300), 127.5)
            net.setInput(blob)
            detections = net.forward()
            for i in range(detections.shape[2]):
                conf = float(detections[0,0,i,2])
                cls_id = int(detections[0,0,i,1])
                if conf > 0.4 and cls_id == 15:
                    box = detections[0,0,i,3:7] * np.array([w,h,w,h])
                    sx, sy, ex, ey = box.astype(int)
                    rects.append((sx,sy,ex,ey))
        else:
            try:
                res = self.detector(frame, conf=0.45, verbose=False)
                for r in res:
                    if r.boxes is None: 
                        continue
                    for b in r.boxes:
                        cls_id = int(b.cls[0])
                        name = self.detector.names.get(cls_id, str(cls_id))
                        if name == "person":
                            x1,y1,x2,y2 = map(int, b.xyxy[0])
                            rects.append((x1,y1,x2,y2))
            except Exception:
                pass
        return rects

    def run(self):
        while not self.stop_event.is_set():
            try:
                frame = self.frame_q.get(timeout=0.5)
            except:
                continue
            rects = self.detect_persons(frame)
            objects = self.ct.update(rects)
            out = {"frame": frame, "persons": [], "timestamp": time.time()}
            for oid, centroid in objects.items():
                hist = self.ct.history.get(oid, [])
                speed = calc_speed_m_s(hist, pixels_to_m=self.pixels_to_m, window_seconds=0.6)
                out["persons"].append({"id": oid, "centroid": centroid, "speed": speed})

            if not self.out_q.full():
                self.out_q.put(out)
            else:
                try:
                    _ = self.out_q.get_nowait()
                    self.out_q.put(out)
                except: pass

# ----------------------------
# YOLO components processing thread
# ----------------------------
class ComponentsProcessor(threading.Thread):
    def __init__(self, frame_q, out_q, stop_event, yolo_model=None):
        super().__init__(daemon=True)
        self.frame_q = frame_q
        self.out_q = out_q
        self.stop_event = stop_event
        self.model = yolo_model

    def run(self):
        while not self.stop_event.is_set():
            try:
                frame = self.frame_q.get(timeout=0.5)
            except:
                continue

            results = []
            if self.model is not None:
                try:
                    # verbose=False evita spam en consola
                    res = self.model(frame, conf=0.4, verbose=False) 
                    for r in res:
                        if r.boxes is None:
                            continue
                        for b in r.boxes:
                            cls_id = int(b.cls[0])
                            name = self.model.names.get(cls_id, str(cls_id))
                            conf = float(b.conf[0])
                            x1,y1,x2,y2 = map(int, b.xyxy[0])
                            results.append({"name": name, "conf": conf, "box": (x1,y1,x2,y2)})
                except Exception:
                    results = []

            out = {"frame": frame, "objects": results, "timestamp": time.time()}

            if not self.out_q.full():
                self.out_q.put(out)
            else:
                try:
                    _ = self.out_q.get_nowait()
                    self.out_q.put(out)
                except: pass

# ----------------------------
# Helper: draw overlays
# ----------------------------
def draw_persons_overlay(frame, persons):
    for p in persons:
        cid = p["id"]; (cx,cy)=p["centroid"]; spd=p["speed"]
        cv2.circle(frame, (int(cx),int(cy)), 5, (0,255,255), -1)
        cv2.putText(frame, f"ID {cid} {spd:.2f} m/s", (int(cx)-25, int(cy)-15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)

def draw_components_overlay(frame, objects):
    for obj in objects:
        name = obj["name"]; conf=obj["conf"]
        x1,y1,x2,y2 = obj["box"]
        color = (0,200,0) if "multimetro" in name.lower() else (200,0,0) if "osciloscopio" in name.lower() else (0,128,255)
        cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
        cv2.putText(frame, f"{name} {conf:.2f}", (x1, y1-8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


# ----------------------------
# Streamlit app
# ----------------------------
st.set_page_config(layout="wide", page_title="Demo: Velocidad + YOLO", initial_sidebar_state="expanded")

st.title("Demo en tiempo real — Velocidad (personas)  |  Detección de componentes (YOLO)")

col1, col2 = st.columns([1,1])

with st.sidebar:
    st.header("Configuración")
    cam_idx = st.number_input("Índice de cámara", min_value=0, max_value=10, value=0, step=1)
    pixels_to_m = st.number_input("pixels_to_m (m/pixel)", value=0.004, format="%.6f")
    start_btn = st.button("Iniciar demo")
    stop_btn = st.button("Detener demo")
    st.markdown("---")

# containers to display video frames
people_view = col1.empty()
components_view = col2.empty()
status_area = st.empty()

# GLOBAL VARIABLES FOR STATE
if 'running' not in st.session_state:
    st.session_state.running = False

# Queues
# MODIFICADO: Creamos dos colas de entrada, una para cada proceso
frame_q_person = queue.Queue(maxsize=2)
frame_q_comp = queue.Queue(maxsize=2)
person_out_q = queue.Queue(maxsize=2)
comp_out_q = queue.Queue(maxsize=2)

stop_event = threading.Event()

# Global thread references (simple implementation)
if 'threads_started' not in st.session_state:
    st.session_state.threads_started = False

def start_system():
    global stop_event
    stop_event.clear()
    
    # load person detector
    prototxt = "MobileNetSSD_deploy.prototxt"
    caffemodel = "MobileNetSSD_deploy.caffemodel"
    person_detector = None
    
    if os.path.exists(prototxt) and os.path.exists(caffemodel):
        net = cv2.dnn.readNetFromCaffe(prototxt, caffemodel)
        person_detector = (net, True)
        st.sidebar.success("Personas: MobileNetSSD Loaded")
    elif ULTRALYTICS_AVAILABLE:
        try:
            ymodel = YOLO("yolov11n.pt")
            person_detector = ymodel
            st.sidebar.success("Personas: YOLOv11n Loaded")
        except:
            st.sidebar.warning("Person detector failed")
    
    # load components YOLO
    user_best = "/home/----/best.pt" 
    components_model = None
    if ULTRALYTICS_AVAILABLE and os.path.exists(user_best):
        try:
            components_model = YOLO(user_best)
            st.sidebar.success("Componentes: Custom YOLO Loaded")
        except Exception as e:
            st.sidebar.error(f"Comp Model Error: {e}")
    else:
        st.sidebar.warning("Componentes: Modelo no encontrado")

    # create threads
    # MODIFICADO: Pasamos las dos colas al hilo de captura
    capture_thread = VideoCaptureThread(cam_idx, frame_q_person, frame_q_comp, stop_event)
    person_thread = PersonProcessor(frame_q_person, person_out_q, stop_event, pixels_to_m=pixels_to_m, person_detector=person_detector)
    comp_thread = ComponentsProcessor(frame_q_comp, comp_out_q, stop_event, yolo_model=components_model)

    capture_thread.start()
    person_thread.start()
    comp_thread.start()
    
    st.session_state.running = True
    st.session_state.threads_started = True
    status_area.info("Sistema iniciado.")

def stop_system():
    stop_event.set()
    st.session_state.running = False
    status_area.info("Sistema detenido.")

if start_btn and not st.session_state.running:
    start_system()

if stop_btn and st.session_state.running:
    stop_system()

# Variables para persistencia de imagen
last_person_img = None
last_comp_img = None

# Live display loop
if st.session_state.running:
    try:
        while True:
            if stop_event.is_set():
                break

            # 1. Intentar obtener frame de personas
            try:
                p = person_out_q.get_nowait()
                frame_p = p["frame"]
                draw_persons_overlay(frame_p, p["persons"])
                last_person_img = cv2.cvtColor(frame_p, cv2.COLOR_BGR2RGB)
            except queue.Empty:
                pass # Si está vacío, mantenemos la imagen anterior (last_person_img)

            # 2. Intentar obtener frame de componentes
            try:
                c = comp_out_q.get_nowait()
                frame_c = c["frame"]
                draw_components_overlay(frame_c, c["objects"])
                last_comp_img = cv2.cvtColor(frame_c, cv2.COLOR_BGR2RGB)
            except queue.Empty:
                pass # Si está vacío, mantenemos la imagen anterior (last_comp_img)

            # 3. Mostrar imágenes (SOLO si existen)
            if last_person_img is not None:
                people_view.image(last_person_img, channels="RGB", use_column_width=True, caption="Velocidad / Personas")
            else:
                people_view.info("Cargando modelo personas...")

            if last_comp_img is not None:
                components_view.image(last_comp_img, channels="RGB", use_column_width=True, caption="Componentes (YOLO)")
            else:
                components_view.info("Cargando modelo YOLO...")

            time.sleep(0.03) # ~30 FPS refresco UI

    except Exception as e:
        st.error(f"Error en loop: {e}")
        stop_system()


