# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
MARGIN = 4
GAP_UP, GAP_DOWN, GAP_TABLE, GAP_EQ = 5, 20, 15, 2.5


def union(rs):
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def xov(a, b):
    return a[0] < b[2] and a[2] > b[0]


def cx(r):
    return (r[0] + r[2]) / 2


def cy(r):
    return (r[1] + r[3]) / 2


def near(a, b, gap, gy=None):
    gy = gap if gy is None else gy
    return a[0] <= b[2] + gap and b[0] <= a[2] + gap and a[1] <= b[3] + gy and b[1] <= a[3] + gy


def vov(a, b):
    return min(a[3], b[3]) - max(a[1], b[1])


def pad(r):
    return (r[0] - MARGIN, r[1] - MARGIN, r[2] + MARGIN, r[3] + MARGIN)


def cluster(items, gap, gy=None):
    groups = []
    for k, r in items:
        members, rect, keep = [k], r, []
        for gm, gr in groups:
            if near(gr, rect, gap, gy):
                members, rect = members + gm, union([rect, gr])
            else:
                keep.append((gm, gr))
        groups = keep + [(members, rect)]
    return groups


def inside(r, z):
    return z[0] - 2 <= (r[0] + r[2]) / 2 <= z[2] + 2 and z[1] - 2 <= cy(r) <= z[3] + 2


def same_row(a, b, gap=25):
    ov = vov(a, b)
    return ov >= 0.5 * min(a[3] - a[1], b[3] - b[1]) and max(a[0], b[0]) - min(a[2], b[2]) <= gap


def spaced(rows, top, bottom=None):
    up = [q[3] for q in rows if q[3] <= top[1] + 1 and xov(q, top)]
    down = [q[1] for q in rows if bottom and q[1] >= bottom[3] - 1 and xov(q, bottom)]
    return (not up or top[1] - max(up) >= GAP_UP) and (not down or min(down) - bottom[3] <= GAP_DOWN)


def alone(rows, r):
    return not any(q != r and same_row(q, r) for q in rows)


def follow(free, l, used):
    tail = []
    while l["bold"]:
        nxt = [(m, mi, t) for m, mi, t in free if (m, mi) not in used and t["bold"] and abs(t["size"] - l["size"]) <= 0.3
               and -1 <= t["rect"][1] - l["rect"][3] <= 3 and xov(t["rect"], l["rect"])]
        if not nxt:
            break
        m, mi, l = min(nxt, key=lambda x: x[2]["rect"][1])
        used.add((m, mi))
        tail.append(l["text"])
    return tail


def area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def overlap(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def band(blocks, drawings, skip, cr, lo, hi):
    ks = [k for k, b in enumerate(blocks) if k not in skip and lo - 1 <= cy(b["rect"]) <= hi and xov(b["rect"], cr)]
    ds = [dk for dk, d in enumerate(drawings) if lo - 1 <= cy(d) <= hi and xov(d, cr) and not (d[1] < lo - 1 and d[3] > hi + 1)]
    return ks, ds


def stacked(b):
    rs = [l["rect"] for l in b["lines"]]
    return not any(vov(p, q) > 0.5 * min(p[3] - p[1], q[3] - q[1]) for i, p in enumerate(rs) for q in rs[i + 1:])
