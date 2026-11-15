# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re

from .geom import cx, cy, inside, union, vov, xov
from .inline_pdf import ACCENT, scripts
from .text import caption_label, norm

NUM_TOK = re.compile(r"^[(+\-−±]*\d*[.,]?\d+(?:e[+\-−]?\d+)?%?\)?$")


def merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a < out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def table_md(pg, rect, drawings):
    rot = [(tuple(l["bbox"]), norm("".join(s["text"] for s in l["spans"])))
           for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) if tuple(l["dir"]) != (1, 0) and inside(l["bbox"], rect)]
    ws = [(w[0], w[1], w[2], w[3], norm(w[4])) for w in pg.get_text("words") if inside(w[:4], rect) and not any(inside(w[:4], r) for r, _ in rot)]
    ws = sorted((w for w in ws + [r + (t,) for r, t in rot] if w[4]), key=lambda w: (cy(w), w[0]))
    if len(ws) < 2:
        return None
    mk = {}
    rl = [l for b in pg.get_text("rawdict")["blocks"] for l in b.get("lines", []) if tuple(l["dir"]) == (1, 0) and inside(l["bbox"], rect)]
    txt = lambda l: [dict(s, text="".join(c["c"] for c in s["chars"])) for s in l["spans"]]
    for l in rl:
        z = max(s["size"] for s in l["spans"])
        ref = [s for o in rl if o is not l and xov(o["bbox"], l["bbox"]) and vov(o["bbox"], l["bbox"]) > 0
               and max(s["size"] for s in o["spans"]) >= 1.2 * z for s in txt(o)]
        kinds = scripts(txt(l), ref)
        cs = [c for s in l["spans"] for c in s["chars"]]
        if not any(kinds) or len(cs) != len(kinds):
            continue
        for w in ws:
            sel = [(c["c"], k) for c, k in zip(cs, kinds) if not c["c"].isspace() and w[0] - 0.5 <= cx(c["bbox"]) <= w[2] + 0.5 and w[1] - 0.5 <= cy(c["bbox"]) <= w[3] + 0.5]
            if not sel or norm("".join(c for c, _ in sel)) != w[4]:
                continue
            text, i = "", 0
            while i < len(sel):
                j = i
                while j < len(sel) and sel[j][1] == sel[i][1]:
                    j += 1
                seg, k = norm("".join(c for c, _ in sel[i:j])), sel[i][1]
                text += f"<{k}>{seg}</{k}>" if k and any(c.isalnum() for c in seg) else seg
                i = j
            if text != w[4]:
                mk[w[:4]] = text
    h = sorted(w[3] - w[1] for w in ws)[len(ws) // 2]
    hr = []
    for d in sorted((d for d in drawings if d[3] - d[1] <= 2 and xov(d, rect) and rect[1] - 2 <= cy(d) <= rect[3] + 2), key=lambda d: (round(cy(d)), d[0])):
        if hr and abs(cy(hr[-1]) - cy(d)) <= 1 and d[0] <= hr[-1][2] + 2:
            hr[-1] = union([hr[-1], d])
        else:
            hr.append(d)
    hr = [d for d in hr if d[2] - d[0] >= 20]
    vr = [d for d in drawings if d[2] - d[0] <= 2 and d[3] - d[1] >= h and inside(d, rect)]
    xs = merge([(w[0], w[2]) for w in ws] + [(d[0], d[2]) for d in hr])
    cuts = [(a[1] + b[0]) / 2 for a, b in zip(xs, xs[1:])
            if b[0] - a[1] >= 0.5 * h and any(d[2] <= b[0] for d in hr) and any(d[0] >= a[1] for d in hr)]
    if cuts:
        xs = [rect[0]] + cuts + [rect[2]]
        parts = [table_md(pg, (a, rect[1], b, rect[3]), drawings) for a, b in zip(xs, xs[1:])]
        return "\n\n".join(p for p in parts if p) or None

    def mid_y(r):
        core = [cy(v) for v in r if v[3] - v[1] <= 1.3 * h] or [cy(v) for v in r]
        return sum(core) / len(core)

    rows = []
    for w in ws:
        if rows and (abs(cy(w) - mid_y(rows[-1])) <= 0.3 * h or (w[3] - w[1] > 1.3 * h and w[1] <= mid_y(rows[-1]) <= w[3])):
            rows[-1].append(w)
        else:
            rows.append([w])
    if len(rows) < 2:
        return None

    def cells_of(r, split_nums):
        cells = [[r[0][0], r[0][2], r[0][4], r[0][3], [r[0]]]]
        for w in r[1:]:
            c = cells[-1]
            if w[0] - c[1] > 0.5 * h or any(c[1] - 1 <= cx(d) <= w[0] + 1 and d[1] <= cy(w) <= d[3] for d in vr) or (split_nums and NUM_TOK.match(c[2].split()[-1]) and NUM_TOK.match(w[4]) and not w[4].startswith("(")):
                cells.append([w[0], w[2], w[4], w[3], [w]])
            else:
                c[1], c[2], c[3] = max(c[1], w[2]), c[2] + " " + w[4], max(c[3], w[3])
                c[4].append(w)
        return cells

    for r in rows:
        r.sort(key=lambda w: w[0])
    table = [(mid_y(r), cells_of(r, False)) for r in rows]
    if any(sum(bool(NUM_TOK.match(t)) for t in c[2].split()) >= 3 for _, cells in table for c in cells):
        table = [(mid_y(r), cells_of(r, True)) for r in rows]
    full = sorted(cy(d) for d in hr if d[2] - d[0] >= 0.9 * (rect[2] - rect[0]))
    mid = next((y for y in full if y > table[0][0]), None)
    nh = sum(y < mid for y, _ in table) if mid else 1
    if nh >= len(table):
        nh = 1
    most = max(len(c) for _, c in table[nh:])
    if most < 2:
        return None
    cols = merge([(c[0], c[1]) for _, cells in table[nh:] if len(cells) == most for c in cells])
    cols = sorted(cols + merge([(c[0], c[1]) for _, cells in table[nh:] for c in cells if not any(c[0] < b and c[1] > a for a, b in cols)]))

    def base(x0, x1):
        ov = [max(0, min(x1, b) - max(x0, a)) for a, b in cols]
        if not max(ov):
            return min(range(len(cols)), key=lambda i: abs(cols[i][0] + cols[i][1] - x0 - x1))
        covered = [i for i, (a, b) in enumerate(cols) if ov[i] >= 0.6 * (b - a)]
        return covered[0] if len(covered) > 1 else ov.index(max(ov))

    occ = [{base(c[0], c[1]) for c in cells} for _, cells in table[:nh]]
    grid = []
    for n, (y, cells) in enumerate(table):
        row = [""] * len(cols)
        for x0, x1, t, y1, cw in cells:
            hit = [base(x0, x1)]
            k = len(cw)
            if n >= nh and len(cells) > 1 and x0 == cells[0][0]:
                k = next((j for j, w in enumerate(cw) if base(w[0], w[2]) != base(cw[0][0], cw[0][2])), k)
            if k < len(cw):
                for part in (cw[:k], cw[k:]):
                    i = base(part[0][0], part[-1][2])
                    row[i] = (row[i] + " " + " ".join(mk.get(w[:4], w[4]) for w in part).replace("|", "\\|")).strip()
                continue
            if n < nh:
                under = [d for d in hr if d[2] - d[0] < 0.9 * (rect[2] - rect[0]) and y1 - 1 <= cy(d) <= y1 + h and d[0] - 2 <= (x0 + x1) / 2 <= d[2] + 2
                         and sum(d[0] - 2 <= (c[0] + c[1]) / 2 <= d[2] + 2 for c in cells) == 1]
                sides = [cx(d) for d in vr if d[1] <= y1 and d[3] >= y1 - h]
                left = max([x for x in sides if x <= x0], default=None)
                right = min([x for x in sides if x >= x1], default=None)
                span = []
                if under:
                    span = [i for i, (a, b) in enumerate(cols) if under[0][0] - 2 <= (a + b) / 2 <= under[0][2] + 2]
                elif left is not None and right is not None and sum(left < (c[0] + c[1]) / 2 < right for c in cells) == 1:
                    span = [i for i, (a, b) in enumerate(cols) if left < (a + b) / 2 < right]
                if not span and not under:
                    cc = (x0 + x1) / 2
                    nb = [(c[0] + c[1]) / 2 for c in cells if c[0] != x0]
                    ds = ([cc - max((cc + v) / 2 for v in nb if v < cc)] if any(v < cc for v in nb) else []) + ([min((cc + v) / 2 for v in nb if v > cc) - cc] if any(v > cc for v in nb) else [])
                    if ds:
                        taken = {base(c[0], c[1]) for c in cells if c[0] != x0}
                        span = [i for i, (a, b) in enumerate(cols) if abs((a + b) / 2 - cc) <= min(ds) and i not in taken]
                        me = base(x0, x1)
                        if me not in span or not all(i in occ[nh - 1] for i in span if i != me) or abs((cols[span[0]][0] + cols[span[-1]][1]) / 2 - cc) > 0.1 * (cols[span[-1]][1] - cols[span[0]][0]):
                            span = []
                if len(span) > 1 and all(any(i in occ[m] for m in range(nh) if m != n) for i in span):
                    hit = span
            for i in hit:
                row[i] = (row[i] + " " + " ".join(mk.get(w[:4], w[4]) for w in cw).replace("|", "\\|")).strip()
        grid.append((y, row))
    head = [" ".join(r[i] for _, r in grid[:nh] if r[i]) for i in range(len(cols))]
    body = grid[nh:]
    for a, b in zip(full, full[1:]):
        band = [r for y, r in body if a < y < b]
        labels = [r for r in band if r[0]]
        if len(band) > 1 and len(labels) == 1:
            lab = labels[0]
            if not any(lab[1:]):
                body = [(y, r) for y, r in body if r is not lab]
            for r in band:
                r[0] = lab[0]
    lines = ["| " + " | ".join(r) + " |" for r in [head] + [r for _, r in body]]
    lines = [re.sub(r"(</su[bp]>) (?=<su[bp]>)", r"\1", l) for l in lines]
    lines = [re.sub("([ˆ˜¯´`¨˙ˇ])([A-Za-z])", lambda m: m.group(2) + ACCENT[m.group(1)], l) for l in lines]
    return "\n".join(lines[:1] + ["|" + "---|" * len(cols)] + lines[1:])


def split_at_rule(b, drawings):
    ls, rect = b["lines"], tuple(b["bbox"])
    lab = caption_label(norm("".join(s["text"] for s in ls[0]["spans"]))) if ls else None
    if not lab or not lab.upper().startswith("TAB"):
        return [(rect, ls)]
    for ry in sorted(cy(d) for d in drawings if d[3] - d[1] <= 2 and d[2] - d[0] >= 0.3 * (rect[2] - rect[0]) and xov(d, rect) and rect[1] < cy(d) < rect[3]):
        up = [l for l in ls if l["bbox"][3] <= ry + 1]
        dn = [l for l in ls if l["bbox"][3] > ry + 1]
        if up and dn and all(l["bbox"][1] >= ry - 1 for l in dn):
            return [(union([l["bbox"] for l in up]), up), (union([l["bbox"] for l in dn]), dn)]
    return [(rect, ls)]
