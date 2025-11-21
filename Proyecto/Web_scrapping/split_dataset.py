# split_dataset.py
import os, random, shutil

SRC = "dataset_preprocessed"
DST = "dataset_split"
RATIOS = (0.8, 0.1, 0.1)  # train, val, test
SEED = 42

random.seed(SEED)
os.makedirs(DST, exist_ok=True)
for subset in ("train","val","test"):
    os.makedirs(os.path.join(DST, subset), exist_ok=True)

for label in sorted(os.listdir(SRC)):
    srcdir = os.path.join(SRC, label)
    if not os.path.isdir(srcdir): continue
    files = [f for f in os.listdir(srcdir) if os.path.isfile(os.path.join(srcdir,f))]
    random.shuffle(files)
    n = len(files)
    n_train = int(n * RATIOS[0])
    n_val = int(n * RATIOS[1])
    train_files = files[:n_train]
    val_files = files[n_train:n_train+n_val]
    test_files = files[n_train+n_val:]
    for subset, flist in (("train", train_files), ("val", val_files), ("test", test_files)):
        target_dir = os.path.join(DST, subset, label)
        os.makedirs(target_dir, exist_ok=True)
        for f in flist:
            shutil.copy2(os.path.join(srcdir, f), os.path.join(target_dir, f))

    print(f"{label}: total={n}, train={len(train_files)}, val={len(val_files)}, test={len(test_files)}")
