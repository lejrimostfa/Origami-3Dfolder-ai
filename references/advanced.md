# Papercraft: advanced techniques

Learned on two whole levels built from these tools (Pumpkin Hollow, a Slavic winter town), 2026-11-03. Tools in `scripts/`.

## Before any paid image

- Dry fold for free. Copy `template.png` to `texture.png` in a scratch folder and run `run_fold.py`. Read the four
  views: a floating head, a missing neck, a cone that should be an onion show up here, not after the painting.
  The reindeer head floated 20 cm above its body. the winter town dry-folded 21 assets in 2 minutes.
- A frustum strip starts its seam at the front (-Y). A door or a face painted in the middle of the strip needs the
  part at `"rot": [0, 0, 180]`, then the strip middle faces the front. Parts turned upside down (`rot` [180, 0, 0])
  already have the seam at the back. Say "its middle panels face the front" in the prompt.
- Architecture: first one concept image of the whole ensemble, front elevation, orthographic. Measure it (pick one
  known height, for example a wall body of 5 m, gives px per metre) and set every net size from it. Then send the
  concept as the SECOND image of each architecture edit, with "copy its bricks, trim, colours, but paint only on the
  faces of the FIRST image". the winter town: one gen at 1536x1024, 41 px per metre, four fortress assets.

## Rounded shapes (`bp_round.py`)

Stacked frustums read square: 12 sides and a corner at every band. No real-time engine tessellates (WebGL, WebGPU),
so the rounding is baked before the export:

```json
"round": {"nets": ["low", "belly", "top"], "cuts": 3, "bulge": 0.07, "lobe": 0.04, "chaikin": 3}
```

- `fold()` tags each face with its part (`pc_part`). `round_parts` welds the listed nets, subdivides them `cuts`
  times (UVs follow: no new image) and moves every vertex in cylindrical coordinates around ONE vertical axis.
- Profile: the original rings smoothed by Chaikin cuts, plus `bulge` times the largest radius as a sine bottom to
  top. Ribs: 1 mid panel, 1 - `lobe` on each fold line (where the painter draws grooves).
- One axis per asset. Several domes on one building: round only the main dome, keep the small ones faceted.
  Stacked balls on one axis (snowman, matryoshka) work: `bulge` 0, `lobe` 0, `chaikin` 2.
- Doors and faces span two panels: a strong `lobe` puts a groove through them. House 0.015, jack-o'-lantern 0.04.
- The fold clip still folds faceted paper. The demo swaps to the rounded mesh at the end of each fold (hide keys):
  a small visible puff.
- Faces: pumpkin house 134 to 597, jack-o'-lantern 92 to 489, snowman about 800.

## Band seams (`seamfade.py`)

Once the bands are welded, two things still draw a line at each seam:
1. The painter shades each band a little differently. `seamfade.py layout texture_src.png texture.png --nets ...`
   reads the colour of an 8 px strip on both sides of every shared 3D edge (12 points along it) and moves each side
   halfway, fading out over `--depth` 40 px. Then it bleeds again outside the nets: maps.py reads a stale bleed as a
   ridge.
2. A band turned upside down in the atlas turns its tangent frame. After `maps.py`, run
   `seamfade.py layout normal.png normal.png --nets ... --flat --depth 12`: the normal map goes flat near the seams.
Keep the painter output as `texture_src.png`.

## Leaf cards

`"leaf_card": "quad"` (default): each leaf is its bounding rectangle, 2 triangles, alpha clip cuts the shape. The
hull mode (outline, about 7 triangles) cost 3.5 times the triangles for the same look. A tree went 3,979 to 571 faces.

## Fixing the painting by code (free)

| Defect | Fix |
|---|---|
| Little village scenes painted inside faces (snowman balls, bear back, fir tiers) | fill the net's faces with noise of the material (snow, fur), or tile a clean crop of another face of the same texture (fir tiers from the top tier) |
| Feature on the wrong net (matryoshka face on the body band) | crop the panels, resize, paste into the right net's front panels, cover the old place with a copy of a neighbour panel |
| Roof slope painted as underside planks | copy the good slope onto it, turned 90 degrees when the shingle rows run along the slope in the atlas |
| Cut-out card with a painted background (antlers, star) | key out the border colour (median of a 4 px frame), or keep the largest blobs of the right hue |
| Square frame around a transparent card | drop `"thick"`: its rims run along the card's outer edge, also where the card is transparent |
Always keep the painter output (`texture_painted.png`) and re-run `maps.py` (and `holes.py` for thick cut-outs).

## Normal maps: what they can and cannot do

`maps.py` guesses height from brightness: bright = raised. On painted textures that is often inverted:
- Light mortar between dark bricks comes out raised, the bricks sunk. Dark chocolate tiles become hollows.
- It works where bright really is raised: icing, stars, beads, snow on ledges.
- The painting already carries its own light, so a second light from the normal map can disagree with it.
- Big buildings sit at 10 to 16 mm per px: a brick is a few px, the relief blurs.
What helps for free: `normal_strength` 5 on props and buildings (3 on characters), Blender normal strength 2,
a roughness map per material from the texture (icing, lacquer, glazed domes, ice shine; brick, logs, fur matte),
and a low raking light that grazes the facades facing the camera. A real fix needs a painted height map per dieline
(one more image per asset, quote it first).
