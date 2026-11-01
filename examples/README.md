# Examples

Eight finished assets. Each folder: `spec.json`, `prompt.txt`, `layout.json`, `painted.png` (raw image model
output), `texture.png` (after `template.py clean`) and `export/<name>.glb` plus `export/<name>_fold.glb`.

| Example | Nets | Notes |
|---|---|---|
| crate | box (cross) | the painting came back 15 percent taller, `clean` fitted it |
| window | card, double, not opaque | panes cut out by alpha |
| table | box (tray) top, 4 box legs | one leg net placed 4 times |
| tree | frustum trunk and branches, leaf cards | also `leaf_prompt.txt`, `leaf_sheet.png`, `leaves.json` |
| morris_column | 5 frustums | the cornice is a frustum turned upside down |
| market_stall | box, extrude awning, boxes | see below |
| handcart | box, cylinders with both caps, boxes | wheels are short capped cylinders |
| water_tower | capped cylinder, cone, boxes, card ladder | ladder gaps cut by alpha |

`market_stall/layout.json` comes from an earlier version of the extrude net. Its painting fits that layout, so the
layout is kept as painted. `net.py` on its spec now gives a different awning layout: rerun it only to repaint.

Rebuild any example for free (no image call):

```bash
blender --background --factory-startup --python scripts/run_fold.py -- examples/crate review/01
```
