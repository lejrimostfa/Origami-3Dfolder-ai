#!/usr/bin/env python3
"""Read the JSON chunk of a GLB and report what a viewer will get. Pure Python, no Blender.

    glb_check.py export/crate.glb export/crate_fold.glb

Per file: size, mesh names, morph targets per primitive, animation names, image types and the generator string.
Exit code 1 when a *_fold.glb has no morph targets or no "Fold" clip (Blink, Talk and Flow may come along).
"""
import json
import os
import struct
import sys


def read_json(path):
    with open(path, "rb") as f:
        magic, _version, _length = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError(f"{path}: not a GLB")
        size, kind = struct.unpack("<I4s", f.read(8))
        if kind != b"JSON":
            raise ValueError(f"{path}: first chunk is not JSON")
        return json.loads(f.read(size))


def info(path):
    g = read_json(path)
    prims = [p for m in g.get("meshes", []) for p in m["primitives"]]
    return {"file": os.path.basename(path), "kb": os.path.getsize(path) // 1024,
            "meshes": [m.get("name") for m in g.get("meshes", [])],
            "morph_targets": [len(p.get("targets", [])) for p in prims],
            "animations": [a.get("name") for a in g.get("animations", [])],
            "images": sorted({i.get("mimeType", "?") for i in g.get("images", [])}),
            "generator": g.get("asset", {}).get("generator")}


def ok(r):
    if not r["file"].endswith("_fold.glb"):
        return bool(r["meshes"])
    return any(r["morph_targets"]) and "Fold" in r["animations"]          # plus Blink, Talk, Flow when present


if __name__ == "__main__":
    bad = 0
    for p in sys.argv[1:]:
        r = info(p)
        r["ok"] = ok(r)
        bad += not r["ok"]
        print(json.dumps(r))
    sys.exit(1 if bad else 0)
