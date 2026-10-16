"""Evaluate the stacking sheet's formulas in Python and draw an approximate PNG preview.

No LibreOffice on this PC, so this is a home-made renderer: column widths, row heights,
merges, static fills, conditional-format fills (cellIs equal), borders, text (Arial Narrow
stands in for Aptos Narrow), 90-degree rotation. It also reports text that overflows.
"""
import colorsys
import datetime
import re
import sys
import zipfile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string as CI
from openpyxl.utils import get_column_letter as CL
from openpyxl.utils.cell import range_boundaries
from PIL import Image, ImageDraw, ImageFont

path = sys.argv[1]
png = sys.argv[2]
wb = load_workbook(path)
ws = wb["Unit Stacking"]

# ------------------------------------------------------------- formulas
def cells_in(rng):
    c1, r1, c2, r2 = range_boundaries(rng.replace("$", ""))
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            yield r, c


vals = {}
for row in ws.iter_rows():
    for c in row:
        if c.value is not None:
            vals[(c.row, c.column)] = c.value


def ev(f):
    f = f.lstrip("=")
    terms = re.findall(r'COUNTIF\([$A-Z0-9:]+,"[^"]+"\)', f)
    if terms and "+".join(terms) == f:
        tot = 0
        for tm in terms:
            rng, crit = re.fullmatch(r'COUNTIF\(([$A-Z0-9:]+),"([^"]+)"\)', tm).groups()
            tot += sum(1 for rc in cells_in(rng) if isinstance(get(rc), str) and get(rc).lower() == crit.lower())
        return tot
    m = re.fullmatch(r"SUM\(([$A-Z0-9:]+)\)", f)
    if m:
        return sum(get(rc) for rc in cells_in(m.group(1)) if isinstance(get(rc), (int, float)))
    if re.fullmatch(r"[A-Z]+[0-9]+(\+[A-Z]+[0-9]+)*", f):
        tot = 0
        for ref in f.split("+"):
            cc, rr = re.fullmatch(r"([A-Z]+)([0-9]+)", ref).groups()
            v = get((int(rr), CI(cc)))
            tot += v if isinstance(v, (int, float)) else 0
        return tot
    raise ValueError("unsupported formula " + f)


cache = {}


def get(rc):
    v = vals.get(rc)
    if isinstance(v, str) and v.startswith("="):
        if rc not in cache:
            cache[rc] = ev(v)
        return cache[rc]
    return v


formulas = {rc: v for rc, v in vals.items() if isinstance(v, str) and v.startswith("=")}
errors = []
for rc in formulas:
    try:
        get(rc)
    except Exception as e:  # noqa
        errors.append((rc, str(e)))
print("formulas:", len(formulas), "errors:", errors)
for rc in sorted(formulas):
    if rc[0] == 94 or rc[1] >= 50:
        print(f"  {CL(rc[1])}{rc[0]:<3} {formulas[rc]:<34} = {get(rc)}")

# ------------------------------------------------------------- colours
with zipfile.ZipFile(path) as z:
    theme = z.read("xl/theme/theme1.xml").decode()
scheme = {}
for name in ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"):
    m = re.search(rf"<a:{name}>.*?(?:srgbClr val|lastClr)=\"(\w+)\"", theme, re.S)
    scheme[name] = m.group(1)
TH = [scheme[k] for k in ("lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6")]


def rgb_of(color):
    if color is None:
        return None
    if color.type == "rgb":
        h = color.rgb[-6:]
        base = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        tint = 0
    elif color.type == "theme":
        h = TH[color.theme]
        base = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        tint = color.tint or 0
    else:
        return None
    if tint:
        hh, ll, ss = colorsys.rgb_to_hls(*(x / 255 for x in base))
        ll = ll * (1 + tint) if tint < 0 else ll * (1 - tint) + tint
        base = tuple(round(x * 255) for x in colorsys.hls_to_rgb(hh, ll, ss))
    return base


cf = []
for rng in ws.conditional_formatting:
    for rule in rng.rules:
        crit = rule.formula[0].strip('"')
        cf.append((rng.sqref, crit, rgb_of(rule.dxf.fill.bgColor)))


def cf_fill(r, c, v):
    if not isinstance(v, str):
        return None
    for sq, crit, col in cf:
        if v.lower() == crit.lower():
            for cr in sq.ranges:
                if cr.min_row <= r <= cr.max_row and cr.min_col <= c <= cr.max_col:
                    return col
    return None


# ------------------------------------------------------------- geometry
MAXR, MAXC = 95, 55
colw = []
for c in range(1, MAXC + 1):
    w = ws.column_dimensions[CL(c)].width if CL(c) in ws.column_dimensions and ws.column_dimensions[CL(c)].customWidth else None
    w = w or 8.43
    colw.append(int(w * 7 + 5))
rowh = []
for r in range(1, MAXR + 1):
    h = ws.row_dimensions[r].height or 15
    rowh.append(round(h * 4 / 3))
X = [0]
for w in colw:
    X.append(X[-1] + w)
Y = [0]
for h in rowh:
    Y.append(Y[-1] + h)
PAD = 20
img = Image.new("RGB", (X[-1] + 2 * PAD, Y[-1] + 2 * PAD), "white")
d = ImageDraw.Draw(img)
FD = r"C:\Windows\Fonts"
_fonts = {}


def tt(sz, b, i):
    key = (round(sz * 4 / 3), b, i)
    if key not in _fonts:
        fn = {(0, 0): "ARIALN.TTF", (1, 0): "ARIALNB.TTF", (0, 1): "ARIALNI.TTF", (1, 1): "ARIALNBI.TTF"}[(int(b), int(i))]
        _fonts[key] = ImageFont.truetype(f"{FD}\\{fn}", key[0])
    return _fonts[key]


merged = {}
inside = set()
for mr in ws.merged_cells.ranges:
    merged[(mr.min_row, mr.min_col)] = (mr.max_row, mr.max_col)
    for r in range(mr.min_row, mr.max_row + 1):
        for c in range(mr.min_col, mr.max_col + 1):
            if (r, c) != (mr.min_row, mr.min_col):
                inside.add((r, c))


def rect(r1, c1, r2, c2):
    return (PAD + X[c1 - 1], PAD + Y[r1 - 1], PAD + X[c2], PAD + Y[r2])


# fills
for r in range(1, MAXR + 1):
    for c in range(1, MAXC + 1):
        if (r, c) in inside:
            continue
        cell = ws.cell(r, c)
        r2, c2 = merged.get((r, c), (r, c))
        col = None
        if cell.fill and cell.fill.fill_type == "solid":
            col = rgb_of(cell.fill.fgColor)
        cfc = cf_fill(r, c, get((r, c)))
        if cfc:
            col = cfc
        if col:
            d.rectangle(rect(r, c, r2, c2), fill=col)

# text
overflow = []


def text_of(cell, v):
    if isinstance(v, datetime.datetime):
        return v.strftime("%-d-%b-%y") if sys.platform != "win32" else v.strftime("%#d-%b-%y")
    return str(v)


for r in range(1, MAXR + 1):
    for c in range(1, MAXC + 1):
        if (r, c) in inside:
            continue
        v = get((r, c))
        if v is None:
            continue
        cell = ws.cell(r, c)
        r2, c2 = merged.get((r, c), (r, c))
        x1, y1, x2, y2 = rect(r, c, r2, c2)
        f = cell.font
        font = tt(f.sz or 11, f.b, f.i)
        al = cell.alignment
        s = text_of(cell, v)
        rot = al.textRotation or 0
        W, H = x2 - x1, y2 - y1
        if rot == 90:
            W, H = H, W
        lines = [s]
        if al.wrap_text:
            words, lines, cur = s.split(" "), [], ""
            for wd in words:
                t = (cur + " " + wd).strip()
                if d.textlength(t, font=font) <= W - 4 or not cur:
                    cur = t
                else:
                    lines.append(cur)
                    cur = wd
            lines.append(cur)
        asc, desc = font.getmetrics()
        lh = asc + desc
        tw = max(d.textlength(ln, font=font) for ln in lines)
        th = lh * len(lines)
        neighbours_empty = all(get((r, cc)) is None and (r, cc) not in inside for cc in (c2 + 1, c2 + 2))
        if tw > W - 2 or th > H + 2:
            single = (r, c) not in merged and not al.wrap_text and rot == 0
            if not (single and neighbours_empty):
                overflow.append((f"{CL(c)}{r}", s[:40], round(tw), W, round(th), H))
        tile = Image.new("RGBA", (max(int(tw) + 4, W), max(th + 2, H)), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        ha = al.horizontal or ("right" if isinstance(v, (int, float, datetime.datetime)) else "left")
        va = al.vertical or "bottom"
        TWd, THd = tile.size
        ty = {"center": (THd - th) / 2, "top": 1}.get(va, THd - th - 1)
        for k, ln in enumerate(lines):
            lw = d.textlength(ln, font=font)
            tx = {"center": (TWd - lw) / 2, "right": TWd - lw - 3}.get(ha, 3)
            td.text((tx, ty + k * lh), ln, font=font, fill=rgb_of(f.color) or (0, 0, 0))
        if rot == 90:
            tile = tile.rotate(90, expand=True)
        px = x1 + ((x2 - x1) - tile.size[0]) // 2 if (ha == "center" or rot) else (x1 if ha != "right" else x2 - tile.size[0])
        py = y1 + ((y2 - y1) - tile.size[1]) // 2
        img.paste(tile, (int(px), int(py)), tile)

# borders (Excel does not draw interior borders of a merged area)
owner = {}
for (mr1, mc1), (mr2, mc2) in merged.items():
    for r in range(mr1, mr2 + 1):
        for c in range(mc1, mc2 + 1):
            owner[(r, c)] = (mr1, mc1, mr2, mc2)
for r in range(1, MAXR + 1):
    for c in range(1, MAXC + 1):
        b = ws.cell(r, c).border
        x1, y1, x2, y2 = rect(r, c, r, c)
        o = owner.get((r, c))
        for side, seg in (("left", (x1, y1, x1, y2)), ("right", (x2, y1, x2, y2)),
                          ("top", (x1, y1, x2, y1)), ("bottom", (x1, y2, x2, y2))):
            if o and not {"left": c == o[1], "right": c == o[3], "top": r == o[0], "bottom": r == o[2]}[side]:
                continue
            sd = getattr(b, side)
            st = sd.style if sd is not None else None
            if st:
                d.line(seg, fill=(0, 0, 0), width=1 if st == "thin" else 3)

img.save(png)
print("PNG", png, img.size)
print("overflow:", overflow if overflow else "none")
