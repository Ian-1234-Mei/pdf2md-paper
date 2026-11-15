# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
from .geom import GAP_EQ, cluster, cy, inside, same_row, union, vov, xov

OPS = "=≈≠∈≤≥→←↔∝−∑∏∫⊗⊕⇒≜"


def isolated(blocks, talk, rect):
    tl = [l["rect"] for k, b in enumerate(blocks) for li, l in enumerate(b["lines"]) if (k, li) in talk and xov(l["rect"], rect)]
    if any(vov(r, rect) > 0.5 * min(r[3] - r[1], rect[3] - rect[1]) for r in tl):
        return False
    up = [r[3] for r in tl if r[3] <= rect[1] + 1]
    dn = [r[1] for r in tl if r[1] >= rect[3] - 1]
    return (not up or rect[1] - max(up) >= GAP_EQ) and (not dn or min(dn) - rect[3] >= GAP_EQ)


def equations(blocks, zones, blocked):
    ink = [((k, li, si), s) for k, b in enumerate(blocks) if k not in blocked and not b["img"] and not b["rot"]
           for li, l in enumerate(b["lines"]) for si, s in enumerate(l["spans"])
           if not s["blank"] and not any(inside(s["rect"], z) for z in zones)]
    spans = dict(ink)
    talk = set()
    for k, b in enumerate(blocks):
        for li, l in enumerate(b["lines"]):
            n = sum(len(s["text"].strip()) for s in l["spans"])
            if n and sum(len(s["text"].strip()) for s in l["spans"] if s["prose"]) >= 0.5 * n:
                talk.add((k, li))
    talk_rects = {(k, li): blocks[k]["lines"][li]["rect"] for k, li in talk}
    groups = cluster([(i, s["rect"]) for i, s in ink if s["math"] and i[:2] not in talk], 12, 6)
    prose = [s["rect"] for i, s in ink if s["prose"] and i[:2] in talk]
    merged = []
    for mem, rect in groups:
        for j, (gm, gr) in enumerate(merged):
            if same_row(gr, rect) and not any(inside(p, union([rect, gr])) for p in prose):
                merged[j] = (mem + gm, union([rect, gr]))
                break
        else:
            merged.append((mem, rect))
    out = []
    for mem, rect in merged:
        if len(mem) < 2 or any(s["prose"] and i[:2] in talk and same_row(s["rect"], rect, 8) for i, s in ink):
            continue
        label, tag = None, []
        for _, s in ink:
            if s["eqno"] and rect[1] - 3 <= cy(s["rect"]) <= rect[3] + 3 and 0 <= s["rect"][0] - rect[2] <= 150:
                rect, label, tag = union([rect, s["rect"]]), s["text"].strip(), [s["rect"]]
        if not any(c.isalpha() for i in mem for c in spans[i]["text"]) or (not label and not any(c in OPS for i in mem for c in spans[i]["text"])):
            continue
        if not label and not isolated(blocks, talk, rect):
            continue
        mem_in = [i for i in mem if not any(same_row(blocks[i[0]]["lines"][i[1]]["rect"], t, 8) for q, t in talk_rects.items() if q != i[:2])]
        if mem_in and len(mem_in) < len(mem):
            rect = union([spans[i]["rect"] for i in mem_in] + tag)
        lines = sorted({(k, li) for k, b in enumerate(blocks) if k not in blocked and not b["img"] and not b["rot"]
                        for li, l in enumerate(b["lines"])
                        if (k, li) not in talk and any(not s["blank"] for s in l["spans"]) and all(inside(s["rect"], rect) for s in l["spans"] if not s["blank"])})
        out.append({"rect": rect, "label": label, "lines": lines})
    return out
