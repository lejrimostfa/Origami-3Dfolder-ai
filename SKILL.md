---
name: origami-3dfolder-ai
description: "Papercraft 3D assets: unfold a simple shape (box, slab, cone, cylinder, card, extruded profile, any low-poly mesh) into a UV dieline, have an image model paint the dieline, then fold it back in headless Blender into a textured low-poly GLB plus a fold animation GLB (morph targets, clip Fold). Also trees (cone trunk and branches plus leaf cards from a leaf sheet), a swatch-sheet fallback and an extruded profile from one side photo. Use when the user wants a cheap textured low-poly prop or game asset: crate, table, shelf, window, door, sign, fence, column, stall, cart, tower, tree, papercraft, dieline, unfold, origami, fold animation, low-poly GLB for Three.js."
---

# origami-3dfolder-ai

Textured low-poly props for a few cents each. Good for boxy, round or flat things: crates, tables, shelves,
windows, doors, signs, fences, columns, carts, towers, and trees made of cones with leaf cards. Not for organic
shapes (characters, rocks, roots): use a mesh generator for those.

Install: copy this folder to `~/.claude/skills/origami-3dfolder-ai/` (all projects) or to a project's
`.claude/skills/origami-3dfolder-ai/`. Needs Python 3.10+ with numpy, opencv-python-headless and Pillow
(`pip install -r requirements.txt`), Blender 4.x, and `OPENAI_API_KEY` in the environment for the paint step.

## Tools

All in `scripts/`. Pure Python except `bp_fold.py`, `bp_thick.py`, `bp_unfold.py`, `blender_io.py` and `run_fold.py` (Blender).

| File | Does |
|---|---|
| `net.py spec.json layout.json` | unfolds every net, packs them in one atlas at one texel density |
| `tree.py spec.json` | writes a tree spec: cone trunk, cone branches, `leaf_cards` |
| `template.py draw layout.json DIR` | `template.png` (guide for the painter) and `mask.png` |
| `image.py edit painted.png "prompt" template.png --transparent` | the paid call: paints the dieline (`--dry-run` first) |
| `template.py clean layout.json painted.png texture.png --review RD` | fits, erases painted fold lines, cleans, bleeds, writes `RD/checks/papercraft.json` |
| `leaves.py leaf_sheet.png leaves.json` | one convex card per leaf blob |
| `maps.py A [--strength 3]` | normal map inferred from `texture.png`, picked up by `run_fold.py` |
| `expressions.py sheet/split cells.json IMG` | face variants (eyes closed, mouth open) for many characters in one image edit |
| `bp_expr.py` | variants as collapsed disks opened by shape keys, clips `Blink` and `Talk` (glTF morph targets, step) |
| `water.py A` | looping water textures by code: `water_surface.png`, `water_fall.png` |
| `bp_water.py` | spec `"water"`: disks and falling veils, uv scrolled in clip `Flow` (KHR_texture_transform + KHR_animation_pointer) |
| `bp_look.py` | render look: warm key, cool fill, rim light, sky gradient, EEVEE ray traced AO and reflections |
| `holes.py layout.json texture.png` | outlines of alpha holes in thick see-through nets, so they get rims too |
| `run_fold.py -- A [review/NN]` | headless fold: `export/<name>.glb` (WEBP), `build/<name>.blend`, 4 review views, `export/<name>_fold.glb` |
| `glb_check.py export/*.glb` | reads the GLB JSON: meshes, morph targets, clip names, image types |
| `unfold.py layout.json` | fold animation math (hinge tree for boxes and cards, isometric roll for cones). Self check |
| `swatch.py`, `silhouette.py` | fallbacks: atlas from material swatches, extruded profile from one side photo |

## Spec

```json
{"name": "table", "atlas_px": 1024, "pad_px": 12, "opaque": true,
 "nets": {"top": {"type": "box", "size": [1.2, 0.7, 0.05]},
          "leg": {"type": "box", "size": [0.07, 0.07, 0.7], "faces": ["left", "front", "right", "back", "bottom"]}},
 "parts": [{"net": "top", "at": [0, 0, 0.7]}, {"net": "leg", "at": [0.52, 0.28, 0]}]}
```

Metres, Z up, the front faces -Y. The folder name and `"name"` should match: outputs are `export/<name>.glb`.
- `box`: `size` [w, d, h], base on z=0. Cross net, or tray net (top in the middle, sides around it) when h is under
  half the smaller side. `"layout": "cross" | "tray"` forces it. `faces` keeps a subset of left, front, right,
  back, top, bottom.
- `frustum`: `r0` (base), `r1` (tip, 0 = cone), `h`, `seg`. Unrolled as a true annulus sector, so the texture is not
  stretched. r0 = r1 gives a cylinder. `"cap": true` closes the tip, `"both"` also the base (wheels, tanks).
  A flare (wider at the top, a cornice) is a frustum turned upside down: `"rot": [180, 0, 0]`.
- `extrude`: `outline` [[y, z], ...] extruded along X by `length` (gable roof, awning, sign). Rotate the part to
  turn the profile. `faces` keeps a subset of capL, capR, side0, side1...
- `poly`: `verts` and outward `faces` of any low-poly mesh. Unfolded by shared edges. A face that would overlap
  starts a new piece.
- `card`: `size` [w, h], vertical quad facing -Y. `"double": true` adds the back. Set `"opaque": false` on the spec
  or the net when the alpha cuts holes (window panes, ladder rungs).
- Any net: `"thick"` (metres) gives its faces a real thickness, inward, with rims on free edges that show the
  dieline colour at the boundary. For planks and cards: window frame 0.06, open cart walls 0.025, ladder 0.03.
  A `double` card does not need its back face once thick. For a thick net that is not opaque, run
  `python3 scripts/holes.py layout.json texture.png` after `template.py clean`: it stores the alpha hole outlines
  (panes, ladder gaps, a trigger guard) and `bp_fold` adds rims around them, kept by the fold animation.
- Any net: `"flip": true` turns its sheet 180 degrees, so a part hanging down (`rot` [180, 0, 0]: arms, legs) paints
  upright. A frustum lying along +y needs `rot` [-90, 180, 0], else its end disk paints upside down.
- Round characters: a head is three frustums along y (front bevel with the face on its cap, a band, a back bevel).
  Tell the painter where each band starts: a band around a lying cylinder has its ends at the bottom.
- One net placed many times shares its pixels (4 legs, 6 branches). Parts take `at`, `rot` (degrees XYZ), `scale`.

## Steps

```bash
S=~/.claude/skills/origami-3dfolder-ai/scripts      # or the project copy
A=assets/papercraft/<name>                          # one folder per asset, named like the spec
BLENDER=blender                                     # macOS: /Applications/Blender.app/Contents/MacOS/Blender
```
1. Write `$A/spec.json` (trees: `python3 $S/tree.py $A/spec.json`). Then `python3 $S/net.py $A/spec.json $A/layout.json`.
2. `python3 $S/template.py draw $A/layout.json $A`. Look at `template.png`: thin strips mean a wasted atlas.
3. Write `$A/prompt.txt`: the dieline rules (below), then the object, one line per labelled face.
4. `python3 $S/image.py edit $A/painted.png "$(cat $A/prompt.txt)" $A/template.png --transparent --dry-run`.
   Show the request and the cost (about $0.10 to $0.25). Ask the user. Only after a yes, run it again without
   `--dry-run`. Trees also need a leaf sheet: `image.py gen $A/leaf_sheet.png "$(cat $A/leaf_prompt.txt)"
   --transparent` (same dry run and question), then `python3 $S/leaves.py $A/leaf_sheet.png $A/leaves.json`.
5. `python3 $S/template.py clean $A/layout.json $A/painted.png $A/texture.png --review $A/review/01`.
   A thick net that is not opaque: then `python3 $S/holes.py $A/layout.json $A/texture.png`.
   Then `python3 $S/maps.py $A` for the normal and AO maps (`"normal_strength": 1.5` in the spec for characters).
   Water: `python3 $S/water.py $A` when the spec has `"water"`. Faces: one edit for every variant
   (`expressions.py sheet`, image edit, `expressions.py split`), then `run_fold.py` adds Blink and Talk.
6. `$BLENDER --background --factory-startup --python $S/run_fold.py -- $A review/01`.
7. `python3 $S/glb_check.py $A/export/*.glb`, then look at `$A/review/01/front.png`, `left`, `back`, `right`.

## Prompts that worked

Dieline (Nov 2026, gpt-image-2.5-sunburst edit). Start every prompt with:

> This image is a papercraft dieline (an unfolded 3D object). Paint a texture INSIDE every grey face, edge to edge,
> and keep the exact same layout, positions and outlines. Do not move, resize or add faces. Keep everything outside
> the faces fully transparent. Remove the grey fill, the dark fold lines and the text labels: they are guides only,
> never draw any text. Flat even lighting, albedo only, no cast shadows, no ambient occlusion, no perspective, seen
> straight on. Details run so that the top of each face is up, except faces labelled TOP and BOTTOM.

Then a style line, `Object: ...`, and one sentence per label (`FRONT: ...`, `SHAFT, the big striped rectangle: ...`).
Name each face by its label. Describe a curved net by its shape on the sheet (the fan, the arc, the circles).
Cut-outs: "the gaps between the rungs fully transparent (alpha zero)". See `examples/*/prompt.txt`.

Leaf sheet (gen, transparent):

> A sprite sheet of 9 separate stylized hand-painted game-art oak leaf sprigs on a fully transparent background, in
> a 3 by 3 grid, well spaced, never touching each other. Each sprig: 3 to 5 green oak leaves on a short brown twig,
> upright with the twig stem at the bottom, seen flat from the front, varied greens. Flat even lighting, no
> shadows, no text, crisp clean edges.

## Fold animation

`<name>_fold.glb` holds the clip `Fold`. Its basis is the folded mesh, so it shows the object without the clip.
- Box and card faces turn about their shared UV edges. Each root face lies flat, then turns about its lowest edge.
- Cones roll up through cones of the same development: the paper never stretches (1 to 3 mm from the facets).
- Parts fold one after the other in spec order (table top, then legs). A placed part lifts and turns from the ground.
- Leaves grow from their stem at the end, low leaves first. The flat sheet floats 3 mm above z=0 to avoid flicker.
- 15 morph targets, 4 s at 24 fps. Play it backwards in Three.js for an unfold. Tree: 2.3 MB (5240 verts x 15
  targets). Lower `steps` in `fold_anim` to shrink it.

## Refused objects

The image model's moderation refused a painted dieline of a steam pistol (category violence, 2026-11-01). Ask the
user before rewording a refused prompt. Do not reword it to slip past the filter.
Fallback that worked: one `gen` image of plain material swatches (no object drawn), then
`swatch.py layout.json sheet.png assign.json painted.png` places them per net or face (fit, face, or tile at real
scale, a cut-out loop for a guard), then `template.py clean` as usual.

## From one side photo

`silhouette.py photo.png ASSET_DIR --length 0.36 --thick 0.03 --angle -27.5` cuts the white background (enclosed
blobs too: a trigger guard), turns the long axis level, extrudes the outline and projects the photo on both caps.
No image call. A primitive pistol built from boxes read as a toy. A flintlock from a side photo read as the real
thing (303 faces, 110 KB). Someone else's photo is a look test only: repaint before shipping.
The extrude net is linear (caps plus a band in rows) and fold poses compose transforms once per face: a 300 face
profile builds and checks in a second.

## Gate

- `review/NN/checks/papercraft.json`: `iou_fit` >= 0.9 (painted silhouette vs nets, holes filled) and
  `coverage_pct` >= 85. `pass` is false otherwise: repaint or fix the prompt, do not ship.
- `glb_check.py`: the static GLB has WEBP images, the `_fold` GLB has morph targets and one clip `Fold`.
- Look at the four review views before calling it done.

## Alive assets

- Face variants: one image edit with the current disks on top and grey disks below paints every variant at once.
  `split` fits each one back. In the GLB each variant is a disk 0.6 mm in front, collapsed at rest, opened by a
  shape key with constant steps: a flipbook through standard morph targets, read by every glTF viewer.
- Water: `KHR_animation_pointer` on the `KHR_texture_transform` offset. Blender exports it (pointer=True). Three.js
  needs a loader plugin for KHR_animation_pointer, or scroll the `map.offset` of the `Water` materials in code.
  Each loop ends on a whole tile, so it has no seam.
- Look: `setup_look(centre, radius)` before the camera. Small key light for readable shadows, world at 0.45.

## Lessons

- The painter keeps the dark fold lines of the template even when told not to. `clean` repaints a 7 px band
  along every face edge from its surroundings (inpainting), so no line shows on the folded mesh. `--keep-lines`
  keeps them (a cartoon outline look). (crate, window, table, tree, then a steampunk batch, 2026-11-01)

- The painter keeps shapes but not scale: the crate cross came back 15 percent taller (IoU 0.57), the window
  square instead of 1.0 x 1.3. `clean` fits the painted box onto the template per axis: IoU 0.98 to 1.0. Never skip it.
- The painter can leave gaps in narrow strips (table legs). `clean` inpaints holes in opaque nets.
- Glass panes came back truly transparent with "panes completely transparent, alpha zero". Mark the net not opaque.
- A cross net of a thin slab wastes the atlas (table top 3.8 mm/px). The tray net gave 2.5 mm/px.
- Steampunk batch: Morris column, market stall, handcart, water tower. Overlap 0.96 to 0.99 with no fit needed,
  1 image each. The painter respects multi-net layouts with arcs, fans and circles well.
- An open box (no top) encloses a hole in its net. The check fills holes in both masks, else it reads 0.80.
- Leaf cards get normals pointing out of the crown centre, so the crown shades as one volume.
- 5 images for the first four assets, about $0.50. WEBP textures: static GLBs 25 to 420 KB (PNG gave 0.5 to 2 MB).
- The first crown (45 leaves per cluster, outer shell only) read sparse and showed the trunk tip. Now 75 leaves,
  some inside, and the top cluster sits above the tip. Leaf cards do not change the atlas: no repaint.
- A layout is tied to its painting. Changing `net.py` changes layouts: keep the painted `layout.json`
  (examples/market_stall was painted on an earlier extrude net and keeps that layout).
