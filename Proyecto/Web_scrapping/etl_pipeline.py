#!/usr/bin/env python3
"""
etl_pipeline.py

ETL pipeline for the dataset:
- EXTRACT: build task queue from current dataset/ folders or metadata.csv
- TRANSFORM: multithreaded image validation, normalization (RGB), resize to 256x256,
             compute sha256, optionally compute small perceptual hash,
             and save to dataset_preprocessed/
- LOAD: write metadata_processed.csv and prepare dataset_split/ (optional separate script)

Usage:
    python3 etl_pipeline.py --workers 8 --maxsim 4 --size 256

Notes:
- Designed for I/O-bound workload: uses threading + Queue.
- Uses a Semaphore (maxsim) to limit simultaneous open-image operations to avoid IO thrash.
- Uses Lock to protect metadata writes and counters (mutex).
"""
import os
import argparse
import threading
from queue import Queue
from PIL import Image
import hashlib
from io import BytesIO
import csv
import time

# ---------- CONFIG ----------
SRC_DIR = "dataset"               # source raw images (already deduped)
DST_DIR = "dataset_preprocessed"  # output normalized images
META_OUT = "metadata_processed.csv"
MIN_WIDTH = 32
MIN_HEIGHT = 32

# ---------- HELPERS ----------
def sha256_bytes_data(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()

def compute_sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

# optional simple perceptual-ish hash (dHash-like small)
def quick_phash(img: Image.Image, hash_size=8) -> str:
    # convert to grayscale and resize
    img = img.convert("L").resize((hash_size+1, hash_size), Image.LANCZOS)
    pixels = list(img.getdata())
    # compare columns
    diff = []
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size+1) + col]
            right = pixels[row * (hash_size+1) + col + 1]
            diff.append(1 if left > right else 0)
    # pack to hex
    value = 0
    for bit in diff:
        value = (value << 1) | bit
    return format(value, 'x')
# ---------- Worker ----------
def worker_thread(q: Queue, sem: threading.Semaphore, meta_lock: threading.Lock, args):
    while True:
        item = q.get()
        if item is None:
            q.task_done()
            break
        src_path, label = item
        rel_path = os.path.relpath(src_path)
        try:
            # Limit concurrent heavy I/O ops (control file descriptors)
            sem.acquire()
            try:
                with Image.open(src_path) as im:
                    im.load()  # ensure loaded
                    im_rgb = im.convert("RGB")
            finally:
                sem.release()
        except Exception as e:
            # corrupt or unreadable
            print(f"[SKIP][ERROR] {rel_path} -> {e}")
            q.task_done()
            continue

        # Validate size
        w,h = im_rgb.size
        if w < args.minsize or h < args.minsize:
            print(f"[SKIP][TOO_SMALL] {rel_path} ({w}x{h})")
            q.task_done()
            continue

        # Transform: resize to target
        try:
            im_resized = im_rgb.resize((args.size, args.size), Image.LANCZOS)
            out_folder = os.path.join(DST_DIR, label)
            os.makedirs(out_folder, exist_ok=True)
            # filename: keep original name to traceability
            filename = os.path.basename(src_path)
            dst_path = os.path.join(out_folder, filename)
            # Save to bytes first to compute sha256
            buf = BytesIO()
            im_resized.save(buf, format="JPEG", quality=90)
            b = buf.getvalue()
            sha = sha256_bytes_data(b)
            phash = quick_phash(im_resized)
            # write file (if exists with same sha skip)
            if os.path.exists(dst_path):
                # If file exists, check if same content
                existing_sha = compute_sha256_file(dst_path)
                if existing_sha == sha:
                    print(f"[DUP_DEST] already exists identical: {dst_path}")
                    # still record metadata but skip overwrite
                    pass
                else:
                    # create unique filename
                    base, ext = os.path.splitext(filename)
                    dst_path = os.path.join(out_folder, f"{base}_{sha[:8]}{ext}")
            with open(dst_path, "wb") as fo:
                fo.write(b)

        except Exception as e:
            print(f"[ERROR_SAVE] {rel_path} -> {e}")
q.task_done()
            continue

        # Update metadata under lock
        with meta_lock:
            with open(META_OUT, "a", newline="", encoding="utf-8") as mf:
                writer = csv.writer(mf)
                writer.writerow([os.path.relpath(dst_path), label, w, h, args.size, sha, phash, src_path])
        print(f"[OK] {label} <- {os.path.relpath(dst_path)} (sha={sha[:8]})")
        q.task_done()

# ---------- MAIN ----------
def main():
    parser = argparse.ArgumentParser(description="ETL pipeline: extract -> transform (multithread) -> load")
    parser.add_argument("--workers", type=int, default=8, help="number of worker threads")
    parser.add_argument("--maxsim", type=int, default=4, help="semaphore: max simultaneous image open/save")
    parser.add_argument("--size", type=int, default=256, help="resize target (square)")
    parser.add_argument("--minsize", type=int, default=MIN_WIDTH, help="min width/height to accept")
    parser.add_argument("--src", type=str, default=SRC_DIR, help="source dataset folder")
    parser.add_argument("--dst", type=str, default=DST_DIR, help="destination preprocessed folder")
    parser.add_argument("--metaout", type=str, default=META_OUT, help="output metadata CSV")
    parser.add_argument("--limit", type=int, default=0, help="limit total files processed (0 = all)")
    args = parser.parse_args()

    # Use local variables assigned from args (avoid globals)
    src_dir = args.src
    dst_dir = args.dst
    meta_out = args.metaout

    # Prepare output
    os.makedirs(dst_dir, exist_ok=True)

    # Initialize metadata CSV (use the local meta_out path)
    with open(meta_out, "w", newline="", encoding="utf-8") as mf:
        w = csv.writer(mf)
        w.writerow(["dst_path","label","orig_width","orig_height","resized","sha256","phash","src_path"])

    # Build queue (EXTRACT)
    q = Queue()
    total = 0
    for label in sorted(os.listdir(src_dir)):
        label_dir = os.path.join(src_dir, label)
        if not os.path.isdir(label_dir):
            continue
        for fn in sorted(os.listdir(label_dir)):
            src_path = os.path.join(label_dir, fn)
            if not os.path.isfile(src_path):
                continue
            q.put((src_path, label))
            total += 1
            if args.limit and total >= args.limit:
                break
        if args.limit and total >= args.limit:
            break

    print(f"[EXTRACT] Enqueued {total} files from {src_dir}")

    # Start workers
    meta_lock = threading.Lock()
    sem = threading.Semaphore(args.maxsim)
    workers = []
    for i in range(args.workers):
        t = threading.Thread(target=worker_thread, args=(q, sem, meta_lock, args), daemon=True)
        t.start()
 workers.append(t)

    # Wait until done
    q.join()
    # stop workers
    for _ in workers:
        q.put(None)
    for t in workers:
        t.join(timeout=1)

    print("[ETL] Completed.")

    # Start workers
    meta_lock = threading.Lock()
    sem = threading.Semaphore(args.maxsim)
    workers = []
    for i in range(args.workers):
        t = threading.Thread(target=worker_thread, args=(q, sem, meta_lock, args), daemon=True)
        t.start()
        workers.append(t)

    # Wait until done
    q.join()
    # stop workers
    for _ in workers:
        q.put(None)
    for t in workers:
        t.join(timeout=1)

    print("[ETL] Completed.")

if __name__ == "__main__":
    main()
