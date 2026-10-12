"""Replace every exact OLD span with NEW in one PDF, left-aligned in place.
Method = TitleBlockFix_PDF.py (text-only redaction, insert at span origin,
ToUnicode patch, font subset). Writes <src folder>/Updated/<name>.pdf."""
import sys, os
sys.path.insert(0, r"C:\SK\OneDrive\Netbuild\scripts")
import pymupdf as fitz
from TitleBlockFix_PDF import (to_raw, to_raw_point, to_visual, fix_embedded_font_tounicode,
                               ARIAL_PATH, FONTNAME)

OLD, NEW = "06-Sep-2026", "06/09/2026"
src = sys.argv[1]
out_dir = os.path.join(os.path.dirname(src), "Updated")
os.makedirs(out_dir, exist_ok=True)
dst = os.path.join(out_dir, os.path.basename(src))

doc = fitz.open(src)
total = 0
for page in doc:
    edits = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["text"] == OLD:
                    edits.append({"bbox": to_visual(fitz.Rect(s["bbox"]), page),
                                  "origin": fitz.Point(s["origin"]) * page.rotation_matrix,
                                  "size": s["size"]})
    if not edits:
        continue
    for e in edits:                       # pass 1: all redactions, text only
        page.add_redact_annot(to_raw(e["bbox"], page), fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                          graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    # pass 2: insert at the span's own origin (left edge kept). NOTE: on
    # PyMuPDF 1.28.2 page.insert_text(fontfile=arial.ttf) embeds a broken
    # glyph map (tofu boxes, text extracts as \x00) -- TextWriter with a
    # fitz.Font object embeds Arial correctly (verified live 2026-09-18).
    arial = fitz.Font(fontfile=ARIAL_PATH)
    tw = fitz.TextWriter(page.rect)
    for e in edits:
        tw.append(to_raw_point(e["origin"], page), NEW, font=arial, fontsize=e["size"])
    tw.write_text(page)
    total += len(edits)
    print("page %d: replaced %d" % (page.number, len(edits)))

patched = fix_embedded_font_tounicode(doc)
doc.subset_fonts(verbose=False)
doc.save(dst, garbage=4, deflate=True)
doc.close()

# verify on the saved file
chk = fitz.open(dst)
old_left = sum(len(p.search_for(OLD)) for p in chk)
new_found = sum(len(p.search_for(NEW)) for p in chk)
print("replaced %d | ToUnicode patched %d | saved %s (%.0f KB)" % (total, patched, dst, os.path.getsize(dst) / 1024))
print("verify: %r remaining = %d, %r found = %d" % (OLD, old_left, NEW, new_found))
