# Examples

Nine finished assets. Each folder: `spec.json`, `prompt.txt`, `layout.json`, `painted.png` (raw image model
output), `texture.png` (after `template.py clean`) and `export/<name>.glb` plus `export/<name>_fold.glb`.

| Example | Nets | Notes |
|---|---|---|
| crate | box (cross) | the painting came back 15 percent taller, `clean` fitted it |
| window | card, 6 cm `thick`, not opaque | panes cut out by alpha |
| table | box (tray) top, 4 box legs | one leg net placed 4 times |
| tree | frustum trunk and branches, leaf cards | also `leaf_prompt.txt`, `leaf_sheet.png`, `leaves.json` |
| morris_column | 5 frustums | the cornice is a frustum turned upside down |
| market_stall | box, extrude awning, boxes | see below |
| handcart | open box 2.5 cm `thick`, cylinders with both caps, boxes | wheels are short capped cylinders |
| water_tower | capped cylinder, cone, boxes, `thick` card ladder | ladder gaps cut by alpha |
| flintlock | extruded profiles, cylinders, `thick` card guard | no dieline painting: `prompt.txt` made `swatches.png`, placed by `swatch.py` with `assign.json` |

`market_stall/layout.json` comes from an earlier version of the extrude net. Its painting fits that layout, so the
layout is kept as painted. `net.py` on its spec now gives a different awning layout: rerun it only to repaint.

flintlock repaints for free: `python3 scripts/swatch.py examples/flintlock/layout.json examples/flintlock/swatches.png
examples/flintlock/assign.json examples/flintlock/painted.png`, then `template.py clean` as usual.

Rebuild any example for free (no image call):

```bash
blender --background --factory-startup --python scripts/run_fold.py -- examples/crate review/01
```
