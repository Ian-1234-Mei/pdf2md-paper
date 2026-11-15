# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sys

from mineru.parser import parse


def walk(blocks):
    for b in blocks:
        yield b
        yield from walk(b.get("blocks") or [])


def build(d, tier):
    eqs = [{"page": p["page_idx"], "bbox": b["bbox"], "latex": b["content"].strip()}
           for p in d["pages"] for b in walk(p["blocks"]) if b["type"] == "equation" and b.get("bbox") and b.get("content", "").strip()]
    inline = []
    for p in d["pages"]:
        for b in walk(p["blocks"]):
            c = b.get("content")
            if b["type"] == "code" and isinstance(c, list):
                c = [s for x in c if x.get("type") == "algorithm_body" and isinstance(x.get("content"), list) for s in x["content"]]
            if isinstance(c, list) and b.get("bbox") and any(s.get("type") == "equation_inline" for s in c):
                parts = [["e" if s["type"] == "equation_inline" else "t", s["content"]] for s in c if s.get("type") in ("text", "hyperlink", "equation_inline") and isinstance(s.get("content"), str)]
                inline.append({"page": p["page_idx"], "bbox": b["bbox"], "parts": parts})
    return {"tier": tier, "equations": eqs, "inline": inline}


def main():
    src, out, tier = sys.argv[1:4]
    d = json.loads(parse(src, tier=tier).to_json())
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(build(d, tier), fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
