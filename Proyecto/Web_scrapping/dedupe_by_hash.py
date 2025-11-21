# dedupe_by_hash.py
import os
import csv
import hashlib

meta_in = 'metadata.csv'
seen = {}   # sha256 -> first filepath
removed = []

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

# Leer metadata.csv y mapear sha -> file (ruta absoluta relativa a dataset/)
if not os.path.exists(meta_in):
    print(f"Error: {meta_in} no encontrado.")
    raise SystemExit(1)

with open(meta_in, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

for row in rows:
    filename = row['filename']
    label = row['label']
    filepath = os.path.join('dataset', label.replace(' ', '_'), filename)
    h = row.get('sha256') or ''
    if not h:
        # si no hay hash en CSV, calculamos desde archivo si existe
        if os.path.exists(filepath):
            h = sha256_of_file(filepath)
        else:
            continue
    if h in seen:
        # duplicado: eliminar archivo actual (mantener primer ocurrencia)
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                removed.append(filepath)
        except Exception as e:
            print("No se pudo eliminar:", filepath, e)
    else:
        seen[h] = filepath

print('Eliminados:', len(removed))

