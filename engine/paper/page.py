# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re

from . import ctx
from .algo import ALGO_RE, algo_box
from .crop import save_crop
from .equations import equations
from .geom import GAP_TABLE, alone, area, band, cluster, cy, follow, inside, overlap, pad, same_row, spaced, stacked, union, xov
from .inline_tex import tidy
from .tables import table_md
from .texcheck import page_chars, tex_ok, tex_rect
from .text import caption_label, is_upper, join, key, slug

HEAD2_RE = re.compile(r"^(?:[IVX]+\.\s+)?[A-Z][A-Z ,\-]*[A-Z]$")
HEAD3_RE = re.compile(r"^[A-Z]\.\s+\S")
NUM_RE = re.compile(r"^(?:\d{1,2}|[A-Z])(?:\.\d{1,2})?$")
HEADN_RE = re.compile(r"^(?:\d{1,2}|[A-Z](?=\.\d))(?:\.\d{1,2}){0,2}\.?\s+[A-Z]")
TERM_RE = re.compile(r"[.!?:;][\"”’)\]]*$")
REF_RE = re.compile(r"^\[\d+\]")
BIB_RE = re.compile(r"#+ (?:[\dIVX]+\.?\s*)?(?:references?|bibliography|參考文獻|參考資料)\s*", re.I)
BULLET_RE = re.compile(r"^(?:[•●○■▪◦]\s*|-\s+)")
PAGE_NUM_RE = re.compile(r"^[\d\s/.\-:]*\d[\d\s/.\-:]*$")
DASH_RE = re.compile(r"^[-–—]+$")


def band_of(P, b):
    c = cy(b["rect"])
    return "header" if c < 0.1 * P["H"] else "footer" if c > 0.9 * P["H"] else None


def strip_targets(line):
    for t in ctx.targets:
        k = key(line)
        if k == t:
            return ""
        if k.endswith(t):
            i = next((i for i in range(len(line) - 1, -1, -1) if key(line[i:]) == t), None)
            line = line[:i].rstrip()
        elif k.startswith(t):
            i = next((i for i in range(1, len(line) + 1) if key(line[:i]) == t), None)
            line = line[i:].lstrip()
    return line


def prose(b, width):
    if b["size"] < ctx.BODY - 0.5 or b["chars"] < 30 or b["rect"][2] - b["rect"][0] < 0.6 * width:
        return False
    if not stacked(b):
        return False
    if sum(l["rect"][0] - b["rect"][0] <= 15 for l in b["lines"]) < 0.5 * len(b["lines"]):
        return False
    text = "".join(l["text"] for l in b["lines"]).replace(" ", "")
    if sum(c.isalpha() for c in text) < 0.6 * len(text):
        return False
    for l in b["lines"]:
        rs = sorted(s["rect"] for s in l["spans"] if not s["blank"])
        if any(q[0] - p[2] > 1.5 * l["size"] for p, q in zip(rs, rs[1:])):
            return False
    return True


def anchor(b, width=None):
    if b["img"] or caption_label(b["lines"][0]["text"]):
        return True
    return b["size"] >= ctx.BODY - 1 and b["chars"] >= 30 if width is None else prose(b, width)


def process_page(pno, pg):
    P = ctx.pages[pno]
    n = pno + 1
    W, H, blocks, drawings = P["W"], P["H"], P["blocks"], P["drawings"]
    if P["chars"] < 20 and any(b["img"] for b in blocks):
        link = save_crop(pg, tuple(pg.rect), f"page-{n:02d}.png", 150)
        return [("img", f"![第 {n} 頁]({link})")] if link else []
    skip = {k for k, b in enumerate(blocks) if not b["img"] and b["rot"] and (b["rect"][2] < 0.1 * W or b["rect"][0] > 0.9 * W)}
    skip |= ctx.PNUM.get(pno, set())
    algos = algo_box(blocks, drawings, skip)
    for a in algos.values():
        skip.update(a["ks"])

    caps, cap_idx = [], set()
    for i, b in enumerate(blocks):
        if b["img"] or i in skip:
            continue
        lab = caption_label(b["lines"][0]["text"])
        if not lab:
            continue
        is_table = lab.upper().startswith("TAB")
        idx, rect = [i], b["rect"]
        if is_table:
            j = i + 1
            while (j < len(blocks) and not blocks[j]["img"] and j not in skip and blocks[j]["size"] < ctx.BODY - 1
                   and xov(blocks[j]["rect"], rect) and is_upper(" ".join(l["text"] for l in blocks[j]["lines"]))
                   and not caption_label(blocks[j]["lines"][0]["text"])):
                idx.append(j)
                rect = union([rect, blocks[j]["rect"]])
                j += 1
        for j, o in enumerate(blocks):
            if (j not in idx and j not in skip and j not in cap_idx and not o["img"] and xov(o["rect"], rect)
                    and rect[1] <= o["rect"][1] < rect[3] - 1 and not caption_label(o["lines"][0]["text"]) and not PAGE_NUM_RE.match(o["lines"][0]["text"])):
                idx.append(j)
                rect = union([rect, o["rect"]])
        caps.append({"kind": "table" if is_table else "fig", "label": lab, "idx": idx, "rect": rect})
        cap_idx.update(idx)

    consumed, dused, tables, figs = set(), set().union(*(a["dks"] for a in algos.values())), [], []
    for g in caps:
        if g["kind"] != "table":
            continue
        cr = g["rect"]
        top = max(blocks[k]["rect"][3] for k in g["idx"])
        bottom = H - 36
        below = sorted([(b["rect"], k) for k, b in enumerate(blocks) if k not in skip and k not in g["idx"] and b["rect"][1] >= top - 1 and xov(b["rect"], cr)]
                       + [(d, None) for d in drawings if d[1] >= top - 1 and xov(d, cr)], key=lambda x: x[0][1])
        cur = top
        for r, k in below:
            if r[1] - cur > GAP_TABLE or (k is not None and (k in cap_idx or anchor(blocks[k], cr[2] - cr[0]))):
                bottom = min(bottom, r[1])
                break
            cur = max(cur, r[3])
        rules = [d[3] for d in drawings if top - 1 <= cy(d) <= bottom and xov(d, cr) and d[3] - d[1] <= 2 and d[2] - d[0] >= 20]
        after = [r[1] for r, k in below if rules and k is not None and r[1] >= max(rules) - 1 and r[1] < bottom]
        if after and min(after) - max(rules) >= 8:
            bottom = max(rules) + 1
        ks, ds = band(blocks, drawings, skip | cap_idx, cr, top, bottom)
        above = False
        if not ds and all(blocks[k]["size"] >= ctx.BODY - 1 and not blocks[k]["img"] for k in ks):
            head = min(blocks[k]["rect"][1] for k in g["idx"])
            upper = max([b["rect"][3] for k, b in enumerate(blocks) if k not in skip and k not in cap_idx
                         and b["rect"][3] <= head + 1 and xov(b["rect"], cr) and anchor(b, cr[2] - cr[0])], default=0)
            ka, da = band(blocks, drawings, skip | cap_idx, cr, upper, head)
            if da or any(blocks[k]["size"] < ctx.BODY - 1 or blocks[k]["img"] for k in ka):
                ks, ds, above = ka, da, True
        rects = [blocks[k]["rect"] for k in ks] + [drawings[dk] for dk in ds]
        consumed.update(ks)
        dused.update(ds)
        tables.append({"g": g, "crop": union(rects) if rects else None, "bottom": top if above or not rects else max(r[3] for r in rects)})

    for g in caps:
        if g["kind"] != "fig":
            continue
        cr = g["rect"]
        band_bottom = cr[1]
        band_top = 0.0
        for t in tables:
            if t["bottom"] <= band_bottom + 1 and xov(t["g"]["rect"], cr):
                band_top = max(band_top, t["bottom"])
        for k, b in enumerate(blocks):
            if k not in skip and k not in consumed and not b["img"] and anchor(b) and stacked(b) and b["rect"][3] <= band_bottom + 1 and xov(b["rect"], cr):
                band_top = max(band_top, b["rect"][3])
        objs, used, dd = [], [], []
        for k, b in enumerate(blocks):
            if k in skip or k in consumed or k in cap_idx:
                continue
            if (b["img"] or b["size"] < ctx.BODY - 1) and xov(b["rect"], cr) and band_top - 1 <= cy(b["rect"]) <= band_bottom + 1:
                objs.append(b["rect"])
                used.append(k)
        for dk, d in enumerate(drawings):
            if dk not in dused and xov(d, cr) and band_top - 1 <= cy(d) <= band_bottom + 1:
                objs.append(d)
                dd.append(dk)
        if objs:
            box = union(objs)
            used += [k for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx and k not in used
                     and inside(b["rect"], box) and band_top - 1 <= cy(b["rect"]) <= band_bottom + 1 and (b["img"] or not anchor(b) or not stacked(b))]
            consumed.update(used)
            dused.update(dd)
        figs.append({"g": g, "crop": union(objs) if objs else None})

    conts = {}
    prev = ctx.tab_end.get(pno - 1)
    if prev and prev[0] >= 0.8 * H:
        rules = [d for dk, d in enumerate(drawings) if dk not in dused and d[3] - d[1] <= 2 and d[2] - d[0] >= 0.3 * W and 0.1 * H < cy(d) < 0.9 * H]
        if rules:
            rw = max(d[2] for d in rules) - min(d[0] for d in rules)
            first = min((b["rect"][1] for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx
                         and not b["img"] and not band_of(P, b) and prose(b, rw)), default=H)
            rules = [d for d in rules if cy(d) < first]
        if len(rules) >= 2:
            zone = union(rules)
            ks = [k for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx and not b["img"]
                  and zone[1] - 1 <= cy(b["rect"]) <= zone[3] + 1 and xov(b["rect"], zone)]
            if ks and not ALGO_RE.match(blocks[min(ks)]["lines"][0]["text"]):
                conts[min(ks)] = (prev[1], union([zone] + [blocks[k]["rect"] for k in ks]))
                consumed.update(ks)
    ends = [(t["crop"][3], t["g"]["label"]) for t in tables if t["crop"]] + [(c[3], lab) for lab, c in conts.values()]
    if ends:
        ctx.tab_end[pno] = max(ends)

    rest = [(k, b["rect"]) for k, b in enumerate(blocks) if b["img"] and k not in consumed and k not in skip]
    fb = {min(m): r for m, r in cluster(rest, 12)}

    heads = {g["idx"][0]: g for g in caps}
    figs_by = {f["g"]["idx"][0]: f for f in figs}
    tabs_by = {t["g"]["idx"][0]: t for t in tables}
    zones = [t["crop"] for t in tables if t["crop"]] + [f["crop"] for f in figs if f["crop"]] + [c for _, c in conts.values()] + [a["box"] for a in algos.values()]
    eqs = equations(blocks, zones, consumed | skip | cap_idx)
    pchars = page_chars(pg) if (ctx.TEX or {}).get(pno) else []
    for e in (ctx.TEX or {}).get(pno, []):
        tr = tex_rect(e, pg)
        if any(inside(tr, z) for z in zones):
            ctx.saved["tex_drop"] += 1
            continue
        taken = {x for g in eqs for x in g["lines"]}
        lines = [(k, li) for k, b in enumerate(blocks) if k not in consumed | skip | cap_idx and not b["img"] and not b["rot"]
                 for li, l in enumerate(b["lines"]) if (k, li) not in taken
                 and any(not s["blank"] for s in l["spans"]) and all(inside(s["rect"], tr) for s in l["spans"] if not s["blank"])]
        g = max(eqs, key=lambda g: overlap(g["rect"], tr), default=None)
        m = re.search(r"\\tag\{([^}]*)\}", e["latex"])
        if not g or overlap(g["rect"], tr) < 0.5 * min(area(g["rect"]), area(tr)):
            if not lines or any(same_row(l["rect"], tr, 8) for b in blocks if not b["img"] for l in b["lines"]
                                if any(not s["blank"] and not inside(s["rect"], tr) for s in l["spans"])):
                ctx.saved["tex_drop"] += 1
                continue
            g = {"rect": None, "label": f"({m.group(1)})" if m else None, "lines": [], "tex": []}
            eqs.append(g)
        elif m and not g["label"]:
            g["label"] = f"({m.group(1)})"
        for o in [o for o in eqs if o is not g and o["label"] == g["label"] and not o.get("tex") and overlap(o["rect"], tr) >= 0.5 * area(o["rect"])]:
            g["rect"] = union([r for r in [g["rect"], o["rect"]] if r])
            g["lines"] = sorted(set(g["lines"]) | set(o["lines"]))
            eqs.remove(o)
        if lines:
            g["rect"] = union([r for r in [g["rect"]] if r] + [s["rect"] for k, li in lines for s in blocks[k]["lines"][li]["spans"] if not s["blank"]])
            g["lines"] = sorted(g["lines"] + lines)
        if tex_ok(pchars, tr, e["latex"]):
            g.setdefault("tex", []).append((tr[1], e["latex"]))
        else:
            ctx.saved["tex_bad"] += 1
            g["bad"] = True
    eq_head = {min(g["lines"]): (i, g) for i, g in enumerate(eqs, 1) if g["lines"]}
    eq_skip = {x for g in eqs for x in g["lines"]}
    rows = [l["rect"] for b in blocks if not b["img"] and not b["rot"] for l in b["lines"] if 0.1 * H <= cy(l["rect"]) <= 0.9 * H]
    free = [(k, li, l) for k, b in enumerate(blocks) if not b["img"] and not b["rot"] and k not in skip and k not in consumed and k not in cap_idx
            for li, l in enumerate(b["lines"]) if (k, li) not in eq_skip]
    num_head, num_skip = {}, set()
    for k, li, l in free:
        if not NUM_RE.match(l["text"]) or l["size"] < ctx.BODY or any(s["math"] for s in l["spans"] if not s["blank"]):
            continue
        right = [(m, mi, t) for m, mi, t in free if t["rect"][0] >= l["rect"][2] - 1 and same_row(l["rect"], t["rect"]) and (m, mi) not in num_head]
        if not right:
            continue
        m, mi, t = min(right, key=lambda x: x[2]["rect"][0])
        if (re.search(r"[A-Za-z]{3,}", t["text"]) and t["text"][:1].isupper() and not t["text"].endswith(",")
                and max(l["size"], t["size"]) < ctx.HS_MIN and spaced(rows, l["rect"], t["rect"])):
            num_head[(m, mi)] = ("h3" if "." in l["text"] else "h2", l["text"])
            num_skip.add((k, li))
    cont = set()
    out = []
    for k, b in enumerate(blocks):
        if k in algos:
            a = algos[k]
            out.append(("caption", a["title"]))
            link = save_crop(pg, pad(a["box"]), slug(a["label"]) + ".png", auto=True)
            ctx.saved["algo"] += 1
            if link and a["code"] and ctx.NOEQ:
                ctx.saved["algo_nolink"] += 1
            elif link:
                out.append(("img", f"![{a['label']}]({link})"))
            if a["code"]:
                out.append(("algo", a["code"]))
            continue
        if k in fb:
            link = save_crop(pg, pad(fb[k]), f"p{n:02d}-img{k}.png", auto=True)
            if link:
                out.append(("img", f"![第 {n} 頁]({link})"))
            continue
        if k in conts:
            label, crop = conts[k]
            name = f"{label} (continued)"
            out.append(("caption", name))
            link = save_crop(pg, pad(crop), slug(label) + "-cont.png", auto=True)
            md = table_md(pg, crop, drawings)
            if link and md and ctx.NOTAB:
                ctx.saved["tab_nolink"] += 1
            elif link:
                out.append(("img", f"![{name}]({link})"))
            if md:
                out.append(("table", md))
            continue
        if k in skip or k in consumed:
            continue
        if k in heads:
            g = heads[k]
            text = ""
            for m in g["idx"]:
                for l in blocks[m]["lines"]:
                    text = join(text, l["text"]) if text else l["text"]
            crop = figs_by[k]["crop"] if g["kind"] == "fig" else tabs_by[k]["crop"]
            r = pad(crop) if crop else None
            if r and g["kind"] == "table":
                cr = g["rect"]
                if crop[1] >= cr[3] - 1:
                    r = (r[0], max(r[1], cr[3]), r[2], r[3])
                elif crop[3] <= cr[1] + 1:
                    r = (r[0], r[1], r[2], min(r[3], cr[1]))
                elif cy(crop) > cy(cr):
                    r = (r[0], crop[1], r[2], r[3])
                else:
                    r = (r[0], r[1], r[2], crop[3])
            link = save_crop(pg, r, slug(g["label"]) + ".png", auto=True) if r else None
            md = table_md(pg, crop, drawings) if crop and g["kind"] == "table" else None
            if link and md and ctx.NOTAB:
                ctx.saved["tab_nolink"] += 1
                link = None
            seq = [("caption", text)]
            if link:
                img = ("img", f"![{g['label']}]({link})")
                seq = [img] + seq if g["kind"] == "fig" else seq + [img]
            if md:
                seq.append(("table", md))
            out += seq
            continue
        if b["img"] or k in cap_idx:
            continue
        where = band_of(P, b)
        last = not where and len(b["lines"]) == 1 and cy(b["rect"]) > 0.88 * H and not any(o is not b and not o["img"] and o["rect"][1] >= b["rect"][3] - 1 for o in blocks)
        for li, l in enumerate(b["lines"]):
            if (k, li) in eq_head:
                i, g = eq_head[(k, li)]
                alt = f"Eq. {g['label']}" if g["label"] else "Equation"
                er, r = g["rect"], pad(g["rect"])
                others = [o["rect"] for m, bb in enumerate(blocks) if not bb["img"] for mi, o in enumerate(bb["lines"]) if (m, mi) not in g["lines"] and xov(o["rect"], r)]
                r = (r[0], max([r[1]] + [min(o[3], er[1]) for o in others if cy(o) < er[1]]), r[2], min([r[3]] + [max(o[1], er[3]) for o in others if cy(o) > er[3]]))
                link = save_crop(pg, r, f"eq-p{n:02d}-{i}.png")
                tex = [] if g.get("bad") else sorted(g.get("tex", []))
                if link:
                    ctx.saved["eq"] += 1
                    if tex and ctx.NOEQ:
                        ctx.saved["eq_nolink"] += 1
                    else:
                        out.append(("img", f"![{alt}]({link})"))
                for _, t in tex:
                    ctx.saved["tex"] += 1
                    out.append(("tex", f"$$\n{tidy(t)}\n$$"))
            if (k, li) in eq_skip or (k, li) in num_skip or (k, li) in cont or (where and (key(l["text"]) in ctx.band_keys[where] or PAGE_NUM_RE.match(l["text"]) or DASH_RE.match(l["text"]))) or (last and l["text"].replace(" ", "") == str(n)):
                continue
            text = strip_targets(l["text"])
            if not text:
                continue
            mdt = l["md"] if l["md"] is not None and text == l["text"] else text
            if not mdt:
                continue
            head = None
            if (k, li) in num_head:
                kind, num = num_head[(k, li)]
                head = (kind, num + " " + text)
            elif BULLET_RE.match(text):
                out.append(("bullet", BULLET_RE.sub("", mdt, count=1)))
            elif b["size"] >= ctx.HS_MIN:
                out.append(("title", min(ctx.HSIZES.index(b["size"]), 2) + 1 if b["size"] in ctx.HSIZES else 3, text))
            elif (HEAD2_RE.match(text) and len(text) <= 60 and ctx.BODY <= l["size"] < ctx.HS_MIN
                  and (len(text.split()) > 1 or sum(c.isalpha() for c in text) >= 5) and spaced(rows, l["rect"], l["rect"]) and alone(rows, l["rect"])):
                head = ("h2", text)
            elif HEADN_RE.match(text) and l["bold"] and ctx.BODY - 0.5 <= l["size"] < ctx.HS_MIN and len(text) <= 100 and spaced(rows, l["rect"]):
                head = ("h3" if "." in text.split()[0].rstrip(".") else "h2", text)
            elif HEAD3_RE.match(text) and l["size"] >= ctx.BODY - 0.5 and len(text) <= 90 and not text.endswith(",") and spaced(rows, l["rect"]):
                head = ("h3", text)
            elif ((l["bold"] or BIB_RE.fullmatch("# " + text)) and ctx.BODY + 1.5 <= l["size"] < ctx.HS_MIN and len(b["lines"]) == 1 and len(text.split()) <= 5
                  and text[:1].isupper() and re.search(r"[A-Za-z]{3,}", text) and not text.endswith((".", ",")) and spaced(rows, l["rect"], l["rect"]) and alone(rows, l["rect"])):
                head = ("h2", text)
            else:
                foot = b["size"] < ctx.BODY - 1 and cy(b["rect"]) > 0.9 * H
                small = b["size"] < ctx.BODY - 1
                lead = next((sp for sp in l["spans"] if not sp["blank"]), None)
                out.append(("body", mdt, li == 0 or (small and REF_RE.match(text) is not None), small, foot, text, lead is not None and lead["katex"]))
            if head:
                for t in follow(free, l, cont):
                    head = (head[0], join(head[1], t))
                out.append(head)
    return out


def render(entries):
    out, cur, held, title, tail = [], None, [], None, None

    def flush():
        nonlocal cur, held, tail
        if cur is not None:
            tail = (len(out), len(held))
            out.append(cur)
        out.extend(held)
        cur, held = None, []

    def flush_title():
        nonlocal title
        if title:
            out.append("#" * title[0] + " " + " ".join(title[1]))
            title = None

    for e in entries:
        if e[0] == "title":
            if title and title[0] != e[1]:
                flush_title()
            if title is None:
                title = [e[1], []]
            title[1].append(e[2])
            continue
        flush_title()
        if e[0] == "body":
            text, new, small, foot, flat, kat = e[1], e[2], e[3], e[4], e[5], e[6]
            if foot and cur is not None and not TERM_RE.search(cur):
                if not new and held:
                    held[-1] = join(held[-1], text)
                else:
                    held.append(text)
                continue
            if cur is not None and (not new or (not TERM_RE.search(cur) and (flat[:1].islower() or kat or (small and len(flat) <= 12)))):
                cur = join(cur, text)
            else:
                flush()
                cur = text
            continue
        flush()
        if e[0] == "bullet":
            cur = "- " + e[1]
        elif e[0] == "h2":
            out.append("## " + e[1])
        elif e[0] == "h3":
            out.append("### " + e[1])
        else:
            out.append(e[1])
    flush_title()
    flush()
    first = entries[0][1:7] if entries and entries[0][0] == "body" else None
    return out, tail[0] if tail and len(out) == tail[0] + 1 + tail[1] else None, first
