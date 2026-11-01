#!/usr/bin/env python3
"""OpenAI image calls for papercraft: paint a dieline (edit) or make a leaf or swatch sheet (gen). Costs money.

    image.py edit OUT.png "prompt" template.png [--transparent] [--model M] [--size 1024x1024] [--quality high]
    image.py gen  OUT.png "prompt" [--transparent] [--model M] ...
    add --dry-run first: it prints the request and calls nothing

The key comes from the OPENAI_API_KEY environment variable only. It is never printed or saved.
Model: --model, else OPENAI_IMAGE_MODEL, else gpt-image-2.5-sunburst for edit (most precise, keeps the layout)
and gpt-image-2.5-flare for gen (fast). Same token price.
OUT.json next to the image keeps the model, prompt, parameters, input file names and the token usage.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

API = "https://api.openai.com/v1/"
DEFAULT = {"edit": "gpt-image-2.5-sunburst", "gen": "gpt-image-2.5-flare"}


def _key():
    k = os.environ.get("OPENAI_API_KEY")
    if not k:
        sys.exit("OPENAI_API_KEY is not set in the environment")
    return k


def _send(req):
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        # the error body never holds the key, but cut it short: moderation messages can be long
        sys.exit(f"OpenAI HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")


def post_json(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    return _send(req)


def post_multipart(path, fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, p in files:
        mime = mimetypes.guess_type(p)[0] or "image/png"
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{os.path.basename(p)}"\r\n'
                f"Content-Type: {mime}\r\n\r\n").encode()
        parts.append(head + open(p, "rb").read() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(API + path, data=b"".join(parts),
                                 headers={"Authorization": f"Bearer {_key()}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return _send(req)


def save(resp, out, meta):
    """Writes OUT.png (and OUT_1.png ... when n > 1) plus OUT.json. File names only, no local paths."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    stem, ext = os.path.splitext(out)
    paths = []
    for i, d in enumerate(resp.get("data", [])):
        p = out if i == 0 else f"{stem}_{i}{ext}"
        open(p, "wb").write(base64.b64decode(d["b64_json"]))
        paths.append(p)
    meta["usage"] = resp.get("usage")
    json.dump(meta, open(stem + ".json", "w"), indent=1)
    return paths


def request(cmd, prompt, model=None, size="1024x1024", quality="high", transparent=False):
    body = {"model": model or os.environ.get("OPENAI_IMAGE_MODEL") or DEFAULT[cmd],
            "prompt": prompt, "size": size, "quality": quality, "n": 1}
    if transparent:
        body["background"] = "transparent"
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "edit"])
    ap.add_argument("out")
    ap.add_argument("prompt")
    ap.add_argument("images", nargs="*", help="edit: the template (and optional references)")
    ap.add_argument("--model")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--transparent", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "edit" and not a.images:
        sys.exit("edit needs at least one input image (the template)")
    body = request(a.cmd, a.prompt, a.model, a.size, a.quality, a.transparent)
    names = [os.path.basename(p) for p in a.images]
    print(json.dumps({"endpoint": "images/" + ("edits" if a.cmd == "edit" else "generations"),
                      **body, "images": names}, indent=1))
    if a.dry_run:
        print("dry run: nothing sent. Billed per image token (about $0.10 to $0.25 per 1024 px image at high).")
        return
    if a.cmd == "gen":
        resp = post_json("images/generations", body)
    else:
        resp = post_multipart("images/edits", body, [("image[]", p) for p in a.images])
    paths = save(resp, a.out, {**body, "images": names})
    print("saved", [os.path.basename(p) for p in paths], "usage", json.dumps(resp.get("usage")))


if __name__ == "__main__":
    main()
