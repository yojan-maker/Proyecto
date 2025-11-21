# preprocess_resize.py
from PIL import Image
import os

SRC = "dataset"
DST = "dataset_preprocessed"
SIZE = (256, 256)

os.makedirs(DST, exist_ok=True)
for label in os.listdir(SRC):
    srcdir = os.path.join(SRC, label)
    if not os.path.isdir(srcdir): 
        continue
    dstdir = os.path.join(DST, label)
    os.makedirs(dstdir, exist_ok=True)
    for fn in os.listdir(srcdir):
        srcpath = os.path.join(srcdir, fn)
        dstpath = os.path.join(dstdir, fn)
        try:
            with Image.open(srcpath) as im:
                im = im.convert("RGB")
                im = im.resize(SIZE, Image.LANCZOS)
                im.save(dstpath, format="JPEG", quality=90)
        except Exception as e:
            print("skip:", srcpath, e)

