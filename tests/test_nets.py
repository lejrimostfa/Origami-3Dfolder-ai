"""Nets: extrude and poly on a few shapes, frustum caps, box layouts. Each must fold back, keep its edges and
lay out without overlaps or mirrored faces."""
import math

import pytest

import net
import polynet
from helpers import flatness, fold_error, signed_area, stretch, uv_overlaps

PROFILES = {
    "triangle": [[-0.6, 0], [0.6, 0], [0, 0.45]],
    "gable": [[-0.5, 0], [0.5, 0], [0.5, 0.6], [0, 0.9], [-0.5, 0.6]],
    "l_shape": [[0, 0], [0.4, 0], [0.4, 0.1], [0.1, 0.1], [0.1, 0.5], [0, 0.5]],
    "clockwise": [[0, 0], [0, 0.3], [0.3, 0.3], [0.3, 0]],
    "disc40": [[0.2 * math.cos(2 * math.pi * i / 40), 0.2 + 0.2 * math.sin(2 * math.pi * i / 40)] for i in range(40)],
}


def one(nt, **kw):
    return net.layout({"name": "t", "nets": {"a": nt}, "parts": [{"net": "a", "at": [0, 0, 0]}], **kw})


def check(lay, flat=True):
    assert fold_error(lay) < 1e-6
    assert stretch(lay, 0.5) < 0.003
    if flat:
        assert flatness(lay)[0] < 1e-3
    for n in lay["nets"].values():
        assert not uv_overlaps(n)
        for f in n["faces"]:
            assert signed_area(f["uv"]) > 0, f["name"]          # never mirrored on the sheet
            assert all(0 <= c <= 1 for uv in f["uv"] for c in uv)


@pytest.mark.parametrize("shape", sorted(PROFILES))
def test_extrude(shape):
    lay = one({"type": "extrude", "outline": PROFILES[shape], "length": 0.8})
    names = [f["name"] for f in lay["nets"]["a"]["faces"]]
    assert names[:2] == ["capL", "capR"] and len(names) == 2 + len(PROFILES[shape])
    check(lay)


def test_extrude_keep_subset():
    lay = one({"type": "extrude", "outline": PROFILES["gable"], "length": 1.0, "faces": ["side0", "side1", "capR"]})
    assert [f["name"] for f in lay["nets"]["a"]["faces"]] == ["capR", "side0", "side1"]


def test_extrude_faces_point_outward():
    faces = polynet.extrude_net(PROFILES["gable"], 1.0)
    cap = dict(faces)["capR"]
    assert all(abs(c[0] - 0.5) < 1e-9 for c, _ in cap)
    n = polynet._normal([c for c, _ in cap])
    assert n[0] > 0.99


CUBE_V = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]]
CUBE_F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
TETRA_V = [[0, 0, 0], [1, 0, 0], [0.5, 0.866, 0], [0.5, 0.289, 0.816]]
TETRA_F = [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
OCTA_V = [[1, 0, 0.5], [-1, 0, 0.5], [0, 1, 0.5], [0, -1, 0.5], [0, 0, 1.5], [0, 0, -0.5]]
OCTA_F = [[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]]
PYRAMID_V = [[-0.5, -0.5, 0], [0.5, -0.5, 0], [0.5, 0.5, 0], [-0.5, 0.5, 0], [0, 0, 0.8]]
PYRAMID_F = [[0, 3, 2, 1], [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]]


@pytest.mark.parametrize("shape", ["cube", "tetra", "octa", "pyramid"])
def test_poly(shape):
    v, f = {"cube": (CUBE_V, CUBE_F), "tetra": (TETRA_V, TETRA_F), "octa": (OCTA_V, OCTA_F),
            "pyramid": (PYRAMID_V, PYRAMID_F)}[shape]
    lay = one({"type": "poly", "verts": v, "faces": f})
    assert len(lay["nets"]["a"]["faces"]) == len(f)
    check(lay)


def test_poly_cube_is_one_piece():
    pieces = polynet.poly_net(CUBE_V, CUBE_F)
    us = sorted({round(u, 6) for _, poly in pieces for _, (u, _) in poly})
    assert us[-1] - us[0] <= 4 + 1e-9                    # one cross: at most 4 faces wide, no second piece beside


@pytest.mark.parametrize("cap", [False, True, "both"])
def test_frustum_caps(cap):
    lay = one({"type": "frustum", "r0": 0.4, "r1": 0.25, "h": 0.6, "seg": 12, "cap": cap})
    faces = {f["name"]: f for f in lay["nets"]["a"]["faces"]}
    assert ("cap" in faces) == bool(cap)
    assert ("capBase" in faces) == (cap == "both")
    if cap:
        assert all(abs(c[2] - 0.6) < 1e-9 and abs(math.hypot(c[0], c[1]) - 0.25) < 1e-9 for c in faces["cap"]["co"])
        assert polynet._normal(faces["cap"]["co"])[2] > 0.99          # tip cap faces up
    if cap == "both":
        assert all(abs(c[2]) < 1e-9 for c in faces["capBase"]["co"])
        assert polynet._normal(faces["capBase"]["co"])[2] < -0.99     # base cap faces down
    check(lay, flat=False)


def test_cone_gets_no_tip_cap():
    lay = one({"type": "frustum", "r0": 0.3, "r1": 0.0, "h": 0.5, "seg": 12, "cap": True})
    assert [f["name"] for f in lay["nets"]["a"]["faces"]] == [f"side{i}" for i in range(12)]
    check(lay)


def test_cylinder_both_caps():
    lay = one({"type": "frustum", "r0": 0.42, "r1": 0.42, "h": 0.06, "seg": 16, "cap": "both"})
    assert {"cap", "capBase"} <= {f["name"] for f in lay["nets"]["a"]["faces"]}
    check(lay, flat=False)


@pytest.mark.parametrize("size,expect", [([0.6, 0.6, 0.6], "cross"), ([1.2, 0.7, 0.05], "tray")])
def test_box_layout_choice(size, expect):
    lay = one({"type": "box", "size": size})
    faces = {f["name"]: f for f in lay["nets"]["a"]["faces"]}
    edges = lambda f: {frozenset((tuple(map(lambda c: round(c, 9), f["uv"][i - 1])),
                                  tuple(map(lambda c: round(c, 9), f["uv"][i])))) for i in range(len(f["uv"]))}
    # tray: the top is hinged to all four sides. cross: only to the front
    hinged = [k for k in ("left", "front", "right", "back") if edges(faces["top"]) & edges(faces[k])]
    assert hinged == (["left", "front", "right", "back"] if expect == "tray" else ["front"])
    check(lay)


def test_one_texel_density():
    lay = net.layout({"name": "t", "nets": {"a": {"type": "box", "size": [1, 1, 1]},
                                            "b": {"type": "box", "size": [0.1, 0.1, 0.5]}},
                      "parts": [{"net": "a"}, {"net": "b"}]})
    k = lay["atlas_px"] * lay["texel_m"]
    for n in lay["nets"].values():
        for f in n["faces"]:
            e3 = math.dist(f["co"][0], f["co"][1])
            e2 = math.dist(f["uv"][0], f["uv"][1]) * k
            assert abs(e3 - e2) < 1e-9
