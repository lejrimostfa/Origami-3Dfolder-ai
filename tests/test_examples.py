"""Every shipped example: the fold animation math holds on its layout, and the layout matches its spec."""
import glob
import json
import os

import numpy as np
import pytest

import net
from helpers import flatness, fold_error, stretch
from conftest import ROOT

# names relative to examples/, so the assets of a level (examples/pumpkin_hollow/<asset>) are tested too
EXAMPLES = sorted(os.path.relpath(os.path.dirname(p), os.path.join(ROOT, "examples"))
                  for pat in ("*/layout.json", "*/*/layout.json") for p in glob.glob(os.path.join(ROOT, "examples", pat)))
# market_stall was painted on a layout from an earlier extrude net. Its texture fits the shipped layout.json,
# so the layout stays as painted. net.py now lays the awning out differently.
PAINTED_ON_OLDER_NET = {"market_stall"}


def load(name, f="layout.json"):
    return json.load(open(os.path.join(ROOT, "examples", name, f)))


def test_examples_found():
    assert len(EXAMPLES) >= 8


@pytest.mark.parametrize("name", EXAMPLES)
def test_fold_t1_is_folded_mesh(name):
    assert fold_error(load(name)) < 1e-6


@pytest.mark.parametrize("name", EXAMPLES)
def test_edges_keep_length_mid_fold(name):
    # cones roll through cones of the same development; coarse cones (3 to 6 sides: ears, tails) bend their flat
    # facets a little mid roll, up to about 1 cm (1.1 cm for the 26 cm four-sided lamp post cap). t=1 is exact
    # (test above).
    assert stretch(load(name), 0.5) < 0.012


@pytest.mark.parametrize("name", EXAMPLES)
def test_t0_is_flat(name):
    cos, res = flatness(load(name))
    assert cos < 1e-3
    assert res < 1e-3                                  # a cylinder strip keeps a 0.5 mm curl at t=0


@pytest.mark.parametrize("name", EXAMPLES)
def test_layout_matches_spec(name):
    spec, lay = load(name, "spec.json"), load(name)
    assert lay["name"] == spec["name"] == os.path.basename(name)
    assert set(lay["nets"]) == set(spec["nets"])
    assert all(p["net"] in lay["nets"] for p in lay["parts"])
    if name in PAINTED_ON_OLDER_NET:
        return
    fresh = net.layout(spec)
    for k, n in fresh["nets"].items():
        for f, g in zip(n["faces"], lay["nets"][k]["faces"]):
            assert f["name"] == g["name"]
            for a, b in zip(f["co"] + f["uv"], g["co"] + g["uv"]):
                assert max(abs(x - y) for x, y in zip(a, b)) < 1e-9


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_files(name):
    d, b = os.path.join(ROOT, "examples", name), os.path.basename(name)
    for f in ("spec.json", "prompt.txt", "painted.png", "texture.png",
              f"export/{b}.glb", f"export/{b}_fold.glb"):
        assert os.path.exists(os.path.join(d, f)), f


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_glbs(name):
    import glb_check
    d = os.path.join(ROOT, "examples", name, "export")
    b = os.path.basename(name)
    static, fold = glb_check.info(f"{d}/{b}.glb"), glb_check.info(f"{d}/{b}_fold.glb")
    extra = set(static["animations"])                  # Blink, Talk (expressions.json), Flow (spec "water")
    assert static["images"] == ["image/webp"] and extra <= {"Blink", "Talk", "Flow"}
    assert set(fold["animations"]) == {"Fold"} | extra and all(n > 0 for n in fold["morph_targets"])


def test_water_textures_tile():
    """A scrolling water texture must wrap: its first and last rows and columns differ like any neighbours."""
    import water
    rng = np.random.default_rng(1)
    for img in (water.surface(128, rng), water.fall(128, rng)):
        a = img.astype(float)
        rows, cols = np.abs(np.diff(a, axis=0)).mean(), np.abs(np.diff(a, axis=1)).mean()
        assert np.abs(a[0] - a[-1]).mean() < 3 * rows and np.abs(a[:, 0] - a[:, -1]).mean() < 3 * cols
