"""Build tool: write the sha256 manifest the app verifies at startup, or build an Offline Model Pack.

    python tools/make_manifest.py manifest MODELS_DIR                 -> MODELS_DIR/manifest.json
    python tools/make_manifest.py pack OUT_DIR NAME MODEL_ID:DIR ...  -> OUT_DIR/sabhalekh-pack.json (+ copies)
"""
import hashlib
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(8 << 20):
            h.update(b)
    return h.hexdigest()


def files_under(root):
    for d, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(d, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            if rel in ("manifest.json", "sabhalekh-pack.json") or f.startswith(".") or f.endswith(".part"):
                continue
            yield rel, p


def manifest(models_dir):
    files = {rel: {"sha256": sha256(p), "size": os.path.getsize(p)} for rel, p in files_under(models_dir)}
    out = os.path.join(models_dir, "manifest.json")
    json.dump({"created": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}, open(out, "w"), indent=1)
    print(f"{out}: {len(files)} files, {sum(f['size'] for f in files.values()) / 1e9:.2f} GB")


def pack(out_dir, name, specs):
    from sabhalekh.models import BUILTIN

    by_id = {m["id"]: m for m in BUILTIN}
    os.makedirs(out_dir, exist_ok=True)
    models, files = [], {}
    for spec in specs:
        mid, src = spec.split(":", 1)
        meta = dict(by_id[mid])
        rel_dir = meta["dir"]
        dst = os.path.join(out_dir, rel_dir)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        models.append({k: meta[k] for k in ("id", "kind", "engine", "label", "dir", "translate", "notes")})
        for rel, p in files_under(dst):
            files[f"{rel_dir}/{rel}"] = {"sha256": sha256(p), "size": os.path.getsize(p)}
    json.dump({"name": name, "models": models, "files": files}, open(os.path.join(out_dir, "sabhalekh-pack.json"), "w",
                                                                     encoding="utf-8"), indent=1)
    with open(os.path.join(out_dir, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"Sabhalekh Offline Model Pack: {name}\n\nIn Sabhalekh open Settings > Models > "
                "'Import Offline Model Pack...' and choose this folder (it can stay on a USB drive).\n"
                "Every file is checked against its SHA-256 before it is copied.\n\nModels:\n"
                + "".join(f"  - {m['label']}: {m['notes']}\n" for m in models))
    print(f"pack {name}: {len(files)} files, {sum(v['size'] for v in files.values()) / 1e9:.2f} GB -> {out_dir}")


if __name__ == "__main__":
    if sys.argv[1] == "manifest":
        manifest(sys.argv[2])
    elif sys.argv[1] == "pack":
        pack(sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        sys.exit(__doc__)
