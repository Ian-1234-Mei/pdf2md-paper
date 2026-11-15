# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import math
import os
import re

import pymupdf

from . import ctx

DPI = 300
TEXT_PX, DPI_MIN = 14, 200


def crop_dpi(pg, clip):
    sizes = [s["size"] for b in pg.get_text("dict", clip=clip)["blocks"] for l in b.get("lines", []) for s in l["spans"]
             if s["size"] > 0 and re.search(r"\w", s["text"])]
    if sizes:
        return math.ceil(min(DPI, max(DPI_MIN, TEXT_PX * 72 / min(sizes))))
    native = []
    for im in pg.get_image_info():
        r = pymupdf.Rect(im["bbox"])
        if r.intersects(clip) and r.get_area() > 0:
            native.append(72 * math.sqrt(im["width"] * im["height"] / r.get_area()))
    return math.ceil(min(DPI, max(native))) if native else DPI


def save_crop(pg, rect, name, dpi=DPI, auto=False):
    clip = pymupdf.Rect(rect) & pg.rect
    if clip.is_empty:
        return None
    if name in ctx.used_names:
        name = f"{name[:-4]}-p{pg.number + 1:02d}.png"
    ctx.used_names.add(name)
    os.makedirs(ctx.figdir, exist_ok=True)
    pg.get_pixmap(clip=clip, dpi=crop_dpi(pg, clip) if auto else dpi).save(os.path.join(ctx.figdir, name))
    ctx.saved["img"] += 1
    return f"{os.path.basename(ctx.figdir)}/{name}"
