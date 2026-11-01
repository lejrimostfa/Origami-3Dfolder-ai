"""Papercraft tree spec: a cone trunk, cone branches, leaf cards at the branch ends. Pure Python.

    tree.py OUT_spec.json [--height 3.2] [--trunk-r 0.14] [--branches 6] [--leaves 75] [--leaf-size 0.32] [--seed 3]
                     [--crown 0.62]

Writes a net.py spec (nets "trunk" and "branch", parts placed with rot) plus "leaf_cards": one entry per leaf with
position, Euler rotation (degrees, XYZ) and size in metres. bp_fold.add_leaves() builds them from a cut leaf sheet.
Every branch shares one bark net, so the bark texture costs one strip of the atlas.
"""
import argparse
import json
import math
import random


def rot(v, rx, ry, rz):
    """Rotate v by Euler XYZ (radians), Blender order: X first, then Y, then Z."""
    x, y, z = v
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    return (x, y, z)


def tree(height=3.2, trunk_r=0.14, branches=6, leaves=75, leaf_size=0.32, seed=3, crown=0.62):
    """crown: leaf ball radius per branch length. The pilot (0.55, 45 leaves, outer shell only) read sparse."""
    rnd = random.Random(seed)
    blen = height * 0.42
    spec = {"name": "tree", "atlas_px": 1024, "pad_px": 12, "opaque": True,
            "nets": {"trunk": {"type": "frustum", "r0": trunk_r, "r1": trunk_r * 0.25, "h": height, "seg": 10},
                     "branch": {"type": "frustum", "r0": trunk_r * 0.45, "r1": trunk_r * 0.08, "h": blen, "seg": 6}},
            "parts": [{"net": "trunk", "at": [0, 0, 0]}], "leaf_cards": []}
    tips = [((0, 0, height * 1.02), (0, 0, 1), blen)]        # above the trunk tip, so the crown hides it
    for i in range(branches):
        zb = height * (0.42 + 0.45 * i / max(1, branches - 1))
        tilt = math.radians(rnd.uniform(38, 62) - 18 * i / max(1, branches - 1))
        yaw = i * 2.39996 + rnd.uniform(-0.3, 0.3)          # golden angle spread
        scale = 1.0 - 0.35 * i / max(1, branches - 1)
        spec["parts"].append({"net": "branch", "at": [0, 0, zb], "rot": [0, math.degrees(tilt), math.degrees(yaw)],
                              "scale": scale})
        d = rot((0, 0, 1), 0, tilt, yaw)
        tips.append(((d[0] * blen * scale, d[1] * blen * scale, zb + d[2] * blen * scale), d, blen * scale))
    for (tx, ty, tz), d, ln in tips:
        r = ln * crown
        for _ in range(leaves):
            # leaves fill a squashed ball around the tip, denser outside, some inside so no hole shows through
            u, v = rnd.uniform(-1, 1), rnd.uniform(0, 2 * math.pi)
            k = rnd.uniform(0.15, 1.0) ** 0.5
            p = (tx + r * k * math.sqrt(1 - u * u) * math.cos(v), ty + r * k * math.sqrt(1 - u * u) * math.sin(v),
                 tz + r * k * u * 0.7)
            out = math.degrees(math.atan2(p[1] - ty, p[0] - tx))
            spec["leaf_cards"].append({"at": [round(c, 4) for c in p],
                                       "rot": [rnd.uniform(-35, 65), rnd.uniform(-40, 40), out + 90 + rnd.uniform(-50, 50)],
                                       "size": round(leaf_size * rnd.uniform(0.75, 1.2), 4), "pick": rnd.random()})
    return spec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--height", type=float, default=3.2)
    ap.add_argument("--trunk-r", type=float, default=0.14)
    ap.add_argument("--branches", type=int, default=6)
    ap.add_argument("--leaves", type=int, default=75)
    ap.add_argument("--leaf-size", type=float, default=0.32)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--crown", type=float, default=0.62)
    a = ap.parse_args()
    s = tree(a.height, a.trunk_r, a.branches, a.leaves, a.leaf_size, a.seed, a.crown)
    json.dump(s, open(a.out, "w"), indent=1)
    print(f"tree: {len(s['parts'])} cones, {len(s['leaf_cards'])} leaf cards")
