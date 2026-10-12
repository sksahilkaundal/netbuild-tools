"""Replace OLD with NEW in every MText/Text/attribute of a DWG (all layouts +
block defs) via AutoCAD COM; Width=0 after edit (MText keeps its wrap width);
SaveAs to <src folder>/Updated/<name>.dwg; re-open read-only and verify."""
import sys, os, collections
sys.path.insert(0, r"C:\SK\OneDrive\Netbuild\scripts")
import win32com.client
from TitleBlockFix_DWG import com_retry, wait_quiescent

OLD, NEW = "06-Sep-2026", "06/09/2026"
src = sys.argv[1]
out_dir = os.path.join(os.path.dirname(src), "Updated")
os.makedirs(out_dir, exist_ok=True)
dst = os.path.join(out_dir, os.path.basename(src))
if os.path.exists(dst):
    os.remove(dst)

acad = win32com.client.GetActiveObject("AutoCAD.Application")
if com_retry(lambda: acad.Documents.Count):
    raise SystemExit("close all drawings in AutoCAD first (SaveAs conflicts with an open same-name doc)")


def walk(doc, fn):
    """fn(entity, where) for every entity in every layout block + non-anonymous block def."""
    for li in range(com_retry(lambda: doc.Layouts.Count)):
        lay = com_retry(lambda: doc.Layouts.Item(li))
        blk = com_retry(lambda: lay.Block)
        for i in range(com_retry(lambda: blk.Count)):
            fn(com_retry(lambda: blk.Item(i)), "layout:" + com_retry(lambda: lay.Name))
    for bi in range(com_retry(lambda: doc.Blocks.Count)):
        b = com_retry(lambda: doc.Blocks.Item(bi))
        bn = com_retry(lambda: b.Name)
        if bn.startswith("*Model_Space") or bn.startswith("*Paper_Space"):
            continue
        for i in range(com_retry(lambda: b.Count)):
            fn(com_retry(lambda: b.Item(i)), "blockdef:" + bn)


def count_hits(doc, needle):
    c = collections.Counter()
    def fn(e, where):
        on = com_retry(lambda: e.ObjectName)
        if on in ("AcDbText", "AcDbMText", "AcDbAttributeDefinition"):
            if needle in com_retry(lambda: e.TextString): c[(where, on)] += 1
        elif on == "AcDbBlockReference" and com_retry(lambda: e.HasAttributes):
            for a in com_retry(lambda: e.GetAttributes()):
                if needle in com_retry(lambda: a.TextString): c[(where, "AttributeRef")] += 1
    walk(doc, fn)
    return c


# ---- edit
doc = com_retry(lambda: acad.Documents.Open(src, False))
wait_quiescent(acad)
changed = collections.Counter(); attach = collections.Counter(); widths = collections.Counter()

def edit(e, where):
    on = com_retry(lambda: e.ObjectName)
    targets = []
    if on in ("AcDbText", "AcDbMText", "AcDbAttributeDefinition"):
        targets = [e]
    elif on == "AcDbBlockReference" and com_retry(lambda: e.HasAttributes):
        targets = list(com_retry(lambda: e.GetAttributes()))
    for t in targets:
        s = com_retry(lambda: t.TextString)
        if OLD in s:
            if on == "AcDbMText":
                attach[com_retry(lambda: t.AttachmentPoint)] += 1
                widths[round(com_retry(lambda: t.Width), 2)] += 1
            com_retry(lambda: setattr(t, "TextString", s.replace(OLD, NEW)))
            if on == "AcDbMText":
                com_retry(lambda: setattr(t, "Width", 0))
            changed[(where, on)] += 1

walk(doc, edit)
com_retry(lambda: doc.SaveAs(dst))
com_retry(lambda: doc.Close(False))
print("changed:", dict(changed), "| MText AttachmentPoint:", dict(attach), "| MText Width before:", dict(widths))
print("saved:", dst, "(%.0f KB)" % (os.path.getsize(dst) / 1024))

# ---- verify on the saved file
doc = com_retry(lambda: acad.Documents.Open(dst, True))
wait_quiescent(acad)
try:
    old = count_hits(doc, OLD); new = count_hits(doc, NEW)
finally:
    com_retry(lambda: doc.Close(False))
print("verify: %r remaining = %d, %r found = %d %s" % (OLD, sum(old.values()), NEW, sum(new.values()), dict(new)))
