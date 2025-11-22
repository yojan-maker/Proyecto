                                                                                                                                    
#!/usr/bin/env python3
import os
import json
import argparse

def generate_from_split(train_dir, out_path="class_names.json"):
    # list subfolders in sorted order (same order Keras uses)
    classes = [d for d in sorted(os.listdir(train_dir)) if os.path.isdir(os.path.join(train_dir, d))]
    # Keras ImageDataGenerator.flow_from_directory builds class_indices in sorted order
    idx_to_class = {i: classes[i] for i in range(len(classes))}
    # Save as strings for JSON compatibility
    idx_to_class_str = {str(k): v for k, v in idx_to_class.items()}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(idx_to_class_str, f, indent=2, ensure_ascii=False)
    print(f"Saved {out_path} with {len(classes)} classes.")
    for k,v in idx_to_class_str.items():
        print(k, "->", v)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data_dir", default="dataset_split", help="dataset split folder (contains train/)")
    p.add_argument("--train_sub", default="train", help="train subfolder name")
    p.add_argument("--out", default="class_names.json")
    args = p.parse_args()
    train_dir = os.path.join(args.data_dir, args.train_sub)
    if not os.path.isdir(train_dir):
        raise SystemExit(f"Train folder not found: {train_dir}")
    generate_from_split(train_dir, args.out)


