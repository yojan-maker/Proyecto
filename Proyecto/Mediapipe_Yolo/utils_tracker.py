 utils_tracker.py
from scipy.spatial import distance as dist
from collections import OrderedDict
import numpy as np
import math

class CentroidTracker:
    def __init__(self, max_disappeared=50, max_distance=50):
        self.nextObjectID = 0
        self.objects = OrderedDict()
        self.disappeared = OrderedDict()
        self.history = OrderedDict()  # Para guardar historial de posiciones
        self.maxDisappeared = max_disappeared
        self.maxDistance = max_distance

    def register(self, centroid):
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.history[self.nextObjectID] = [centroid]
        self.nextObjectID += 1

    def deregister(self, objectID):
        del self.objects[objectID]
        del self.disappeared[objectID]
        del self.history[objectID]

    def update(self, rects):
        if len(rects) == 0:
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)
            return self.objects

        inputCentroids = np.zeros((len(rects), 2), dtype="int")
        for (i, (startX, startY, endX, endY)) in enumerate(rects):
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            inputCentroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(0, len(inputCentroids)):
                self.register(inputCentroids[i])
        else:
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())
            D = dist.cdist(np.array(objectCentroids), inputCentroids)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]
            usedRows = set()
            usedCols = set()

            for (row, col) in zip(rows, cols):
                if row in usedRows or col in usedCols:
                    continue
                if D[row, col] > self.maxDistance:
                    continue

                objectID = objectIDs[row]
                self.objects[objectID] = inputCentroids[col]
                self.disappeared[objectID] = 0

                # Actualizar historial
                self.history[objectID].append(inputCentroids[col])
                if len(self.history[objectID]) > 20: # Limitar historial
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
                    self.register(inputCentroids[col])

        return self.objects

def calc_speed_m_s(history, pixels_to_m=0.005, window_seconds=0.5):
 """
    Calcula velocidad estimada basada en el historial de centroides.
    pixels_to_m: Metros por cada pixel (calibración).
    window_seconds: Tiempo aproximado entre frames para cálculo.
    """
    if len(history) < 2:
        return 0.0
    
    # Tomar punto actual y uno anterior
    ptA = history[-1]
    ptB = history[0] # O history[-5] para suavizar
    
    d_pixels = np.linalg.norm(np.array(ptA) - np.array(ptB))
    d_meters = d_pixels * pixels_to_m
    
    # Esto es una estimación burda asumiendo FPS constantes
    # En una app real usaríamos timestamps reales del history
    speed = d_meters / window_seconds 
    return speed
