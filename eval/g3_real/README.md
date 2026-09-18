# G3 real photos

The six G3 images in `eval/g3/` are synthetic. Real photos of handwritten spray logs go here and are scored the
same way (stratum `real`) by `python eval/build_g3.py`, which picks up every `*.json` file in this folder.

## Before adding a photo

- Get the grower's permission to use the photo in a public repository.
- Cover or crop out names, phone numbers, farm names and anything else that identifies a person or a farm.
- Remove location data: re-save the photo (for example with `python -c "from PIL import Image; Image.open('in.jpg').save('out.jpg')"`), which drops EXIF.

## Files

For a photo `farm1_p1.jpg`, add `farm1_p1.json` next to it, written by hand from the photo:

```json
{
  "image": "eval/g3_real/farm1_p1.jpg",
  "synthetic": false,
  "split": "dev",
  "crop": "Agrumes",
  "crop_code": "0110020",
  "defects": ["describe what makes it hard, e.g. glare, fold"],
  "rows": [
    {"n": 1, "date": "2026-09-03", "date_as_written": "3/9", "product_as_written": "Actara",
     "product": "ACTARA 25 WG", "dose": "20 g/hl", "target": "Mineuse", "crossed_out": false,
     "unreadable": [], "hidden": {}}
  ]
}
```

- One row per written line, in page order, including crossed-out lines (`"crossed_out": true`).
- `product` is the ONSSA trade name the grower meant (ask them if unsure); `product_as_written` is the text as written.
- If a cell really cannot be read, put its field name in `unreadable`, set the field to `null`, and leave `hidden`
  empty unless the grower told you the value.
- Put about one photo in three in `"split": "heldout"` before looking at any model output, and do not change that later.
