# scraper_dataset.py  (versión para Chrome / chromedriver)
import os
import time
import csv
import hashlib
import threading
from queue import Queue
import requests
from PIL import Image
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.common.by import By

# --- Chrome webdriver imports ---
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
# -----------------------------------

from tqdm import tqdm
import random

# CONFIGURACION
KEYWORDS = [
    "multimeter",
    "oscilloscope",
    "breadboard",
    "soldering iron",
    "bench power supply",
    "function generator",
    "stepper motor",
    "transformer electrical",
    "resistor electronic component",
    "capacitor electronic component"
]
IMAGES_PER_LABEL = 200
OUTPUT_DIR = "dataset"
CSV_META = "metadata.csv"
NUM_DOWNLOADER_THREADS = 8
MAX_SIMULTANEOUS_DOWNLOADS = 5
MIN_WIDTH = 200
MIN_HEIGHT = 200
REQUEST_TIMEOUT = 15

# sincronización
counter_lock = threading.Lock()
download_semaphore = threading.Semaphore(MAX_SIMULTANEOUS_DOWNLOADS)
print_lock = threading.Lock()

download_queue = Queue()

# preparar carpetas
os.makedirs(OUTPUT_DIR, exist_ok=True)
for kw in KEYWORDS:
    os.makedirs(os.path.join(OUTPUT_DIR, kw.replace(" ", "_")), exist_ok=True)

# CSV
with open(CSV_META, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["filename", "label", "source_url", "width", "height", "sha256"])

def sha256_bytes(b):
    import hashlib
    m = hashlib.sha256()
    m.update(b)
    return m.hexdigest()

def downloader_worker():
    while True:
        item = download_queue.get()
        if item is None:
            download_queue.task_done()
            break
        url, label = item
        label_dir = os.path.join(OUTPUT_DIR, label.replace(" ", "_"))

        with counter_lock:
            cur_count = len([name for name in os.listdir(label_dir) if os.path.isfile(os.path.join(label_dir, name))])
            if cur_count >= IMAGES_PER_LABEL:
                download_queue.task_done()
                continue
download_semaphore.acquire()
        try:
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                img = Image.open(BytesIO(resp.content)).convert("RGB")
            except Exception as e:
                with print_lock:
                    print(f"[ERROR] descargar {url}: {e}")
                continue
            finally:
                download_semaphore.release()

            w, h = img.size
            if w < MIN_WIDTH or h < MIN_HEIGHT:
                with print_lock:
                    print(f"[SKIP] {url} (too small {w}x{h})")
                continue

            img_bytes = BytesIO()
            img.save(img_bytes, format="JPEG", quality=85)
            b = img_bytes.getvalue()
            hsh = sha256_bytes(b)

            with counter_lock:
                cur_count = len([name for name in os.listdir(label_dir) if os.path.isfile(os.path.join(label_dir, name))])
                if cur_count >= IMAGES_PER_LABEL:
                    continue
                filename = f"{label.replace(' ','_')}_{cur_count+1:05d}.jpg"
                path = os.path.join(label_dir, filename)
                with open(path, "wb") as f:
                    f.write(b)
                with open(CSV_META, "a", newline="", encoding="utf-8") as f_meta:
                    writer = csv.writer(f_meta)
                    writer.writerow([filename, label, url, w, h, hsh])

            with print_lock:
                print(f"[SAVED] {path} from {url}")

        finally:
            download_queue.task_done()

def fetch_image_urls_for_keyword(keyword, max_urls=1000, sleep_between_scrolls=1):
    urls = set()
    # configurar Selenium con Chrome
    options = webdriver.ChromeOptions()
    # headless puede ser True o False
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Opcional: user-agent
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        search_url = "https://www.bing.com/images/search?q=" + keyword.replace(" ", "+")
        driver.get(search_url)
        time.sleep(1)
        last_height = driver.execute_script("return document.body.scrollHeight")
        scrolls = 0
        while len(urls) < max_urls and scrolls < 200:
            thumbs = driver.find_elements(By.CSS_SELECTOR, "img.mimg")
            for t in thumbs:
                src = t.get_attribute("src")
                data_src = t.get_attribute("data-src")
                if data_src and data_src.startswith("http"):
                    urls.add(data_src)
                elif src and src.startswith("http"):
                    urls.add(src)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(sleep_between_scrolls)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scrolls += 1

        thumbs = driver.find_elements(By.CSS_SELECTOR, "a.iusc")
        for a in thumbs:
            try:
                a.click()
                time.sleep(0.2)
                imgs = driver.find_elements(By.CSS_SELECTOR, "img.nofocus")
                for img in imgs:
                    src = img.get_attribute("src")
                    if src and src.startswith("http"):
                        urls.add(src)
            except Exception:
                continue

    finally:
        driver.quit()
    return list(urls)

if __name__ == "__main__":
    threads = []
    for _ in range(NUM_DOWNLOADER_THREADS):
        t = threading.Thread(target=downloader_worker, daemon=True)
        t.start()
        threads.append(t)

    for kw in KEYWORDS:
        print(f"\n[SEARCH] Procurando URLs para: '{kw}'")
        urls = fetch_image_urls_for_keyword(kw, max_urls=2000)
        print(f"[FOUND] {len(urls)} image urls for '{kw}'")
        random.shuffle(urls)

        for url in urls:
            label_dir = os.path.join(OUTPUT_DIR, kw.replace(" ", "_"))
            with counter_lock:
                cur_count = len([name for name in os.listdir(label_dir) if os.path.isfile(os.path.join(label_dir, name))])
            if cur_count >= IMAGES_PER_LABEL:
                print(f"[DONE] {kw} tiene {cur_count} imágenes")
                break
            download_queue.put((url, kw))

        while True:
            label_dir = os.path.join(OUTPUT_DIR, kw.replace(" ", "_"))
            with counter_lock:
                cur_count = len([name for name in os.listdir(label_dir) if os.path.isfile(os.path.join(label_dir, name))])
            if cur_count >= IMAGES_PER_LABEL:
                break
            if download_queue.empty():
                print("[INFO] cola vacía pero no acabado, reextrayendo otras urls...")
                extra_urls = fetch_image_urls_for_keyword(kw, max_urls=2000)
                random.shuffle(extra_urls)
                for url in extra_urls:
                    download_queue.put((url, kw))
            time.sleep(1)

    for _ in threads:
        download_queue.put(None)
    download_queue.join()
    for t in threads:
        t.join(timeout=1)

    print("Proceso completado.")
