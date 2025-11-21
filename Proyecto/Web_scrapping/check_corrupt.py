# check_corrupt.py
check_corrupt.py
from PIL import Image
import os

bad = []
for root, _, files in os.walk('dataset'):
    for f in files:
        path = os.path.join(root, f)
        try:
            # verify() detecta corrupciones; reabrimos para asegurar
            with Image.open(path) as im:
                im.verify()
        except Exception as e:
            bad.append(path)

print('Corruptas:', len(bad))
for p in bad[:50]:
    print(p)
