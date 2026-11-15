# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

import pymupdf

from . import ctx
from .geom import area, overlap
from .texcheck import outer_bars, page_chars, tex_fix, tex_ok, tex_rect

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIER = "basic"
RETRY_TIER = "standard"
GPU_PY = os.path.join(HERE, "venv-mineru-gpu", "bin", "python")


def run_mineru(path, out, tier, what, pages):
    runs = [("GPU", GPU_PY, {"MINERU_MODEL_SMALL_BACKEND": "torch", "MINERU_DEVICE_MODE": "cuda"})] if os.path.exists(GPU_PY) else []
    runs.append(("CPU", os.path.join(HERE, "venv-mineru", "bin", "python"), {}))
    for name, py, env in runs:
        print(f"MinerU {what}（{pages} 頁，{name}）…", file=sys.stderr, flush=True)
        try:
            r = subprocess.run([py, "-I", os.path.join(HERE, "mineru_eq.py"), path, out, tier],
                               capture_output=True, text=True, env={**os.environ, **env})
        except OSError as e:
            r = subprocess.CompletedProcess([], 1, "", str(e))
        if not r.returncode:
            return True
        print(f"MinerU（{name}）失敗：" + (r.stderr.strip().splitlines() or ["?"])[-1], file=sys.stderr)
    return False


def load_tex():
    with tempfile.TemporaryDirectory() as tmp:
        out = ctx.KEEP or os.path.join(tmp, "eq.json")
        if not os.path.exists(out) and not run_mineru(ctx.src, out, TIER, "辨識公式中", ctx.total):
            print("MinerU 失敗，公式只輸出 PNG", file=sys.stderr)
            return None
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
    tex = defaultdict(list)
    for e in data["equations"]:
        tex[e["page"]].append(e)
    for e in data.get("inline", []):
        ctx.INLINE[e["page"]].append(e)
    return tex


def retry_tex():
    chars, bad, fixed = {p: page_chars(ctx.doc[p]) for p in ctx.TEX}, [], 0
    for p, es in ctx.TEX.items():
        for e in es:
            tr = tex_rect(e, ctx.doc[p])
            if tex_ok(chars[p], tr, e["latex"]):
                continue
            f = tex_fix(chars[p], tr, e["latex"])
            if tex_ok(chars[p], tr, f):
                e["latex"] = f
                fixed += 1
            else:
                bad.append(e)
    pages = sorted({e["page"] for e in bad})
    if not pages:
        return fixed, 0
    with tempfile.TemporaryDirectory() as tmp:
        out = f"{os.path.splitext(ctx.KEEP)[0]}-{RETRY_TIER}.json" if ctx.KEEP else os.path.join(tmp, "retry.json")
        data = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("pages") != pages:
                data = None
        if data is None:
            sub = pymupdf.open()
            for p in pages:
                sub.insert_pdf(ctx.doc, from_page=p, to_page=p)
            sub.save(os.path.join(tmp, "retry.pdf"))
            if not run_mineru(os.path.join(tmp, "retry.pdf"), out, RETRY_TIER, f"{RETRY_TIER} 重新辨識沒通過檢查的公式", len(pages)):
                return fixed, 0
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            data["pages"] = pages
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
    new = defaultdict(list)
    for x in data["equations"]:
        new[pages[x["page"]]].append(x)
    n = 0
    for e in bad:
        pg = ctx.doc[e["page"]]
        tr = tex_rect(e, pg)
        x = max(new[e["page"]], key=lambda x: overlap(tex_rect(x, pg), tr), default=None)
        if not x or overlap(tex_rect(x, pg), tr) < 0.5 * min(area(tex_rect(x, pg)), area(tr)):
            continue
        latex, m = outer_bars(x["latex"]), re.search(r"\\tag\s*\{[^}]*\}", e["latex"])
        if m and not re.search(r"\\tag\s*\{", latex):
            latex += m.group()
        for t in (latex, tex_fix(chars[e["page"]], tr, latex)):
            if tex_ok(chars[e["page"]], tr, t):
                e["latex"] = t
                n += 1
                break
    return fixed, n
