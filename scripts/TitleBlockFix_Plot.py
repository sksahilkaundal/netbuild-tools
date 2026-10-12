# -*- coding: utf-8 -*-
"""
Optional step: plot the CORRECTED DWGs back out to PDF, for visual sign-off.

This is NOT the deliverable PDF -- Step 1 produces that by editing the
exported PDFs directly. This step exists so you can eyeball what the CAD
edit actually looks like on a plotted sheet, independently of Step 1.
It is slow (AutoCAD opens and plots every drawing) and off by default.

Reads  <dwg folder>\\Updated   (Step 2's output)
Writes <issue folder>\\PDF_from_CAD

TWO THINGS THIS GETS RIGHT, BOTH LEARNED THE HARD WAY:

1. THE PLOTTER SEARCH PATH MUST BE RESTORED, WITH RETRIES.
   On this machine AutoCAD's plotter path points ONLY at Bluebeam's
   folder, so the stock PDF plotters are invisible to automation. We
   append the stock Plotters folder, and MUST put it back afterwards --
   it is the user's config, not ours. The restore is itself a COM call,
   so a busy-rejection can fail it and leave the setting modified. It
   gets its own generous retry, and a startup sweep removes a leftover
   append from a previous crashed run.

2. ISO_full_bleed_A0 WITH CENTRED EXTENTS AT 1:1.
   Plain ISO_A0 with PlotType = acLayout clips the right-hand column --
   including part of the title block -- off the sheet.

RefreshPlotDeviceInfo() is called after changing the device: without it
the layout does not see the newly-visible plotter.
"""
import glob
import os
import sys

import pythoncom
import win32com.client

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from TitleBlockFix_DWG import com_retry, wait_quiescent

# set by the caller (launcher / pipeline)
SRC_FOLDER = ""          # the Updated DWG folder
OUT_FOLDER = ""
DRY_RUN = True

DEVICE = "DWG To PDF.pc3"
MEDIA_PREFERENCE = ("full_bleed_A0", "A0")

acExtents = 1
acWindow = 4
ac1_1 = 16
ac90degrees = 1

# 248 of 250 ProjectA layouts carry 90deg; the two exceptions carried a stale
# page setup from another user's machine (0deg, foreign plotter) and
# plotted portrait, dropping the title block off the page. Set it.
PLOT_ROTATION = ac90degrees


def frame_window(ps, count):
    """((x0, y0), (x1, y1)) of the sheet frame -- the largest block
    reference in paper space -- or None.

    Plotting raw EXTENTS trusts every object in paper space. One sheet
    (T00O-L53-210002) had something stray far to the left, so centred
    extents shifted the whole sheet and clipped the title block at the
    right edge. The frame is what the sheet IS; plot that window.
    """
    best, best_area = None, 0.0
    for i in range(count):
        try:
            e = com_retry(lambda: ps.Item(i))
            if com_retry(lambda: e.ObjectName) != "AcDbBlockReference":
                continue
            lo, hi = com_retry(lambda: e.GetBoundingBox())
            area = (hi[0] - lo[0]) * (hi[1] - lo[1])
            if area > best_area:
                best, best_area = ((lo[0], lo[1]), (hi[0], hi[1])), area
        except Exception:
            continue
    return best


def stock_plotters_dir():
    """%APPDATA%\\Autodesk\\AutoCAD <ver>\\R<rel>\\enu\\Plotters -- newest found."""
    pat = os.path.join(os.environ.get("APPDATA", ""), "Autodesk",
                       "AutoCAD*", "R*", "enu", "Plotters")
    hits = sorted(p for p in glob.glob(pat) if os.path.isdir(p))
    return hits[-1] if hits else None


def _strip(path, stock):
    """Remove a trailing ';<stock>' left by a previous run."""
    tail = ";" + stock.lower()
    while path.lower().endswith(tail):
        path = path[: -len(tail)]
    return path


def main():
    src = SRC_FOLDER
    out = OUT_FOLDER
    if not os.path.isdir(src):
        print("No corrected DWG folder at %s -- run Step 2 first." % src)
        return

    dwgs = sorted(f for f in os.listdir(src) if f.lower().endswith(".dwg"))
    print("Found %d corrected DWG(s) to plot" % len(dwgs))
    if not dwgs:
        return
    if DRY_RUN:
        for f in dwgs:
            print("  would plot %s" % f)
        print("\n--- Summary ---")
        print("Would plot: %d (dry run, nothing written)" % len(dwgs))
        return

    stock = stock_plotters_dir()
    if not stock:
        print("ERROR: could not find AutoCAD's stock Plotters folder.")
        return

    os.makedirs(out, exist_ok=True)
    pythoncom.CoInitialize()
    acad = com_retry(lambda: win32com.client.GetActiveObject("AutoCAD.Application"))
    prefs = com_retry(lambda: acad.Preferences.Files)

    original = _strip(com_retry(lambda: prefs.PrinterConfigPath), stock)
    com_retry(lambda: setattr(prefs, "PrinterConfigPath", original + ";" + stock))
    print("plotter path += %s" % stock)

    done = errors = 0
    try:
        for f in dwgs:
            path = os.path.join(src, f)
            pdf = os.path.join(out, os.path.splitext(f)[0] + ".pdf")
            doc = com_retry(lambda: acad.Documents.Open(path, True))   # read-only
            wait_quiescent(acad)
            try:
                lay = com_retry(lambda: doc.ActiveLayout)
                com_retry(lambda: lay.RefreshPlotDeviceInfo())
                com_retry(lambda: setattr(lay, "ConfigName", DEVICE))
                com_retry(lambda: lay.RefreshPlotDeviceInfo())   # or device not seen
                names = list(com_retry(lambda: lay.GetCanonicalMediaNames()))
                media = None
                for want in MEDIA_PREFERENCE:
                    hit = [m for m in names if want in m]
                    if hit:
                        media = hit[0]
                        break
                if not media:
                    raise RuntimeError("no A0 media on %s" % DEVICE)
                com_retry(lambda: setattr(lay, "CanonicalMediaName", media))
                com_retry(lambda: setattr(lay, "PlotRotation", PLOT_ROTATION))
                ps = com_retry(lambda: doc.PaperSpace)
                win = frame_window(ps, com_retry(lambda: ps.Count))
                if win:
                    lo = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, list(win[0]))
                    hi = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, list(win[1]))
                    com_retry(lambda: lay.SetWindowToPlot(lo, hi))
                    com_retry(lambda: setattr(lay, "PlotType", acWindow))
                else:
                    print("    (no frame block found -- plotting extents)")
                    com_retry(lambda: setattr(lay, "PlotType", acExtents))
                com_retry(lambda: setattr(lay, "UseStandardScale", True))
                com_retry(lambda: setattr(lay, "StandardScale", ac1_1))
                com_retry(lambda: setattr(lay, "CenterPlot", True))
                com_retry(lambda: lay.RefreshPlotDeviceInfo())
                com_retry(lambda: doc.SetVariable("BACKGROUNDPLOT", 0))
                # PlotToFile silently leaves an EXISTING target untouched
                # (returns True, file unchanged). Remove it first, or a
                # re-run appears to succeed while changing nothing.
                if os.path.exists(pdf):
                    os.remove(pdf)
                com_retry(lambda: doc.Plot.PlotToFile(pdf, DEVICE))
                wait_quiescent(acad, timeout=180)
                size = os.path.getsize(pdf) if os.path.exists(pdf) else 0
                if not size:
                    raise RuntimeError("no PDF produced")
                print("  %-46s %6.2f MB" % (f, size / 1e6))
                done += 1
            except Exception as exc:
                print("  ERROR %s -> %s" % (f, exc))
                errors += 1
            finally:
                try:
                    com_retry(lambda: doc.Close(False))
                except Exception as exc:
                    print("    (close failed: %s)" % exc)
                wait_quiescent(acad)
    finally:
        # the user's config -- put it back even if everything else failed
        try:
            com_retry(lambda: setattr(prefs, "PrinterConfigPath", original),
                      tries=60, delay=1.0)
            print("plotter path restored")
        except Exception as exc:
            print("ERROR: plotter path NOT restored (%s).\n"
                  "       Options > Files > Printer Support File Path >\n"
                  "       Printer Configuration Search Path -- remove:\n"
                  "       %s" % (exc, stock))
        pythoncom.CoUninitialize()

    print("\n--- Summary ---")
    print("Plotted: %d, Errors: %d" % (done, errors))
    print("Output : %s" % out)


if __name__ == "__main__":
    main()
