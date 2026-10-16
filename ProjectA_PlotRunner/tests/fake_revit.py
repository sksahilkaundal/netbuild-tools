"""A stand-in for Revit + the pyRevit MCP listener, for tests (no Revit needed).

Serves POST /revit_mcp/execute_code/ like the real route: runs the posted code
with ``doc`` bound to the active document and ``print`` captured, one call at
a time (Revit's API is single-threaded). The Revit API pieces the export
scripts import are stubbed, and Document.Export writes small PDF / DWG files
(plus the FP_*.pat / .pcp / .png byproducts a real DWG export leaves).

Knobs for tests: ``delay`` {sheet number: seconds}, ``fail`` {sheet numbers},
``stale_calls`` {call index: answer with the previous call's output},
``paused``.
"""

import builtins
import json
import os
import sys
import threading
import time
import types
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ------------------------------------------------------------ Revit API stubs

class ElementId(object):
    def __init__(self, n):
        self.n = n


class Param(object):
    def __init__(self, v):
        self.v = v

    def AsString(self):
        return self.v


class View(object):
    def __init__(self, n, view_type, name="view"):
        self.Id, self.ViewType, self.Name = ElementId(n), view_type, name


class ViewSheet(object):
    def __init__(self, n, number, name, params, views=(), placeholder=False):
        self.Id, self.SheetNumber, self.Name = ElementId(n), number, name
        self.params, self.views, self.IsPlaceholder = params, list(views), placeholder

    def LookupParameter(self, name):
        return Param(self.params[name]) if name in self.params else None

    def GetAllPlacedViews(self):
        return [v.Id for v in self.views]


class Collector(object):
    def __init__(self, doc):
        self.doc = doc

    def OfClass(self, cls):
        return self

    def ToElements(self):
        return list(self.doc.sheets)


class Opts(object):
    def __init__(self):
        self.FileName = None


class Enum(object):
    def __init__(self, *names):
        for n in names:
            setattr(self, n, n)


class GenericList(object):
    def __getitem__(self, t):
        return list


class App(object):
    def __init__(self):
        self.Documents = []


class Doc(object):
    def __init__(self, server, title, sheets, app):
        self.server, self.Title, self.sheets, self.Application = server, title, sheets, app
        self.PathName = r"C:\Revit_Local\%s.rvt" % title
        self.IsLinked = self.IsFamilyDocument = self.IsReadOnly = False
        app.Documents.append(self)
        self._by_id = {}
        for s in sheets:
            self._by_id[s.Id.n] = s
            for v in s.views:
                self._by_id[v.Id.n] = v

    def GetElement(self, eid):
        return self._by_id.get(eid.n)

    def Export(self, folder, *args):
        if len(args) == 2:                      # PDF: (folder, ids, PDFExportOptions)
            ids, opts = args
            kind, fname = "PDF", opts.FileName
        else:                                   # DWG: (folder, name, ids, DWGExportOptions)
            fname, ids, opts = args
            kind = "CAD"
        sheet = self._by_id[ids[0].n]
        self.server.exports.append((kind, sheet.SheetNumber))
        time.sleep(self.server.delay.get(sheet.SheetNumber, 0))
        if sheet.SheetNumber in self.server.fail:
            raise Exception("export failed for %s" % sheet.SheetNumber)
        if not os.path.isdir(folder):
            raise IOError("folder missing: %s" % folder)
        if kind == "PDF":
            with open(os.path.join(folder, fname + ".pdf"), "wb") as f:
                f.write(b"%PDF-1.7 fake A0 " + sheet.SheetNumber.encode())
        else:
            with open(os.path.join(folder, fname + ".dwg"), "wb") as f:
                f.write(b"AC1032 fake " + sheet.SheetNumber.encode())
            for junk in ("FP_Hatch1.pat", "Revit.pcp", "logo.png"):
                with open(os.path.join(folder, junk), "wb") as f:
                    f.write(b"x")


def install_stubs():
    db = types.ModuleType("Autodesk.Revit.DB")
    db.FilteredElementCollector = Collector
    db.ViewSheet = ViewSheet
    db.ElementId = ElementId
    db.PDFExportOptions = Opts
    db.DWGExportOptions = Opts
    db.ExportPaperFormat = Enum("ISO_A0")
    db.PaperPlacementType = Enum("Center")
    db.ZoomType = Enum("Zoom")
    db.ACADVersion = Enum("Default")
    revit_mod = types.ModuleType("Autodesk.Revit")
    revit_mod.DB = db
    autodesk = types.ModuleType("Autodesk")
    autodesk.Revit = revit_mod
    generic = types.ModuleType("System.Collections.Generic")
    generic.List = GenericList()
    collections = types.ModuleType("System.Collections")
    collections.Generic = generic
    system = types.ModuleType("System")
    system.Collections = collections
    sys.modules.update({"Autodesk": autodesk, "Autodesk.Revit": revit_mod, "Autodesk.Revit.DB": db,
                        "System": system, "System.Collections": collections,
                        "System.Collections.Generic": generic})
    return db


# ------------------------------------------------------------ ProjectA-like models

SBFX = ["SBFX_SHEET_01_Project ID/WorkPackage Code", "SBFX_SHEET_02_Originating Org Code",
        "SBFX_SHEET_03_Drawing Type", "SBFX_SHEET_04_Location/Zone", "SBFX_SHEET_05_Level Code",
        "SBFX_SHEET_06_Discipline Code", "SBFX_SHEET_07_Number"]


def sbfx(zone, level, number, date, rev):
    vals = ["ProjectC", "Studio", "DWG", zone, level, "AR", number]
    p = dict(zip(SBFX, vals))
    p["Current Revision Date"] = date
    p["Current Revision"] = rev
    return p


class FakeRevit(object):
    def __init__(self):
        install_stubs()
        self.app = App()
        self.delay, self.fail, self.stale_calls = {}, set(), set()
        self.paused = False
        self.exports, self.calls = [], 0
        self._last_output = ""
        self.lock = threading.Lock()
        ids = iter(range(1000, 100000))

        def sheet(number, name, params, view_types=(), **kw):
            return ViewSheet(next(ids), number, name, params,
                             [View(next(ids), vt) for vt in view_types], **kw)

        # Master SW0O: dates DD/MM/YYYY, routed by "Studio_03 - Browser Filter"
        m = []
        for i, (bf, name, date) in enumerate([
                ("Site", "Site GA 01", "06/09/2026"), ("Site", "Site GA 02", "06/09/2026"),
                ("Site", "Solar Shading 01", "06/09/2026"), ("Site", "Site Plan", "06/09/2026"),
                ("B2 B5_1-200", "B2 GA", "06/09/2026"), ("B2 B5_1-200", "B5 GA", "06/09/2026"),
                ("B2 B5_1-200", "B3 GA", "01/08/2026"), ("Other", "Misc", "06/09/2026"),
                ("Site", "Site GA 16", "16/09/2026")]):
            p = sbfx("SW0O", "ZZZ", "1000%02d" % (i + 1), date, "C")
            p["Studio_03 - Browser Filter"] = bf
            m.append(sheet("SW-%02d" % (i + 1), name, p, ["FloorPlan"]))
        m.append(sheet("SW-PH", "placeholder", {}, placeholder=True))
        self.master = Doc(self, "ProjectC-Studio-BIM-SW0O-ZZZ-BM-950001_user", m, self.app)

        # Podium B001: dates DD-Mon-YYYY, routed by placed view type (Legend placed first)
        b = []
        for number, vts, rev in [("210001", ["Legend", "FloorPlan"], "D"), ("210002", ["FloorPlan"], "D"),
                                 ("210003", ["FloorPlan"], "E"), ("210004", ["FloorPlan"], "D"),
                                 ("220001", ["Legend", "Elevation"], "D"), ("220002", ["Elevation"], "D"),
                                 ("230001", ["Legend", "Section"], "D")]:
            b.append(sheet("B001-AR-" + number, "Sheet " + number,
                           sbfx("B001", "GFL", number, "06-Sep-2026", rev), vts))
        # superseded duplicate: same drawing number, older date, "(1)" sheet number
        b.append(sheet("B001-AR-210001(1)", "Sheet 210001", sbfx("B001", "GFL", "210001", "20-Aug-2026", "C"),
                       ["FloorPlan"]))
        b.append(sheet("B001-AR-900001", "Cover", sbfx("B001", "ZZZ", "900001", "06-Sep-2026", "D"), ["Legend"]))
        self.b001 = Doc(self, "ProjectC-Studio-BIM-B001-ZZZ-BM-950001_user", b, self.app)

        # Tower plans (T00O BM-950001): every sheet's browser filter is 'Tower'; FloorPlan sheets
        t = []
        for i, (vts, bf) in enumerate([(["FloorPlan"], "Tower")] * 3 + [(["CeilingPlan"], "Tower"),
                                                                      (["Legend"], "Other")]):
            p = sbfx("T00O", "L%02d" % (i + 10), "4000%02d" % (i + 1), "06/09/2026", "B")
            p["Studio_03 - Browser Filter"] = bf
            t.append(sheet("T-P%02d" % (i + 1), "Tower Plan %d" % i, p, vts))
        self.tower_plans = Doc(self, "ProjectC-Studio-BIM-T00O-ZZZ-BM-950001_user", t, self.app)
        # Tower elevations + sections (T00O BM-950002)
        e = []
        for i, vts in enumerate([["Legend", "Elevation"], ["Elevation"], ["Section"], ["Section"]]):
            e.append(sheet("T-E%02d" % (i + 1), "Tower %s %d" % (vts[-1], i),
                           sbfx("T00O", "ZZZ", "5000%02d" % (i + 1), "06/09/2026", "B"), vts))
        self.tower_elev = Doc(self, "ProjectC-Studio-BIM-T00O-ZZZ-BM-950002_user", e, self.app)
        # Areas (SW00 AR-970002 -- note SW00 with zeros, unlike the SW0O master)
        a = []
        for i, vts in enumerate([["AreaPlan"], ["Legend", "AreaPlan"], ["AreaPlan"]]):
            a.append(sheet("A-%02d" % (i + 1), "Area Plan %d" % i,
                           sbfx("SW00", "L%02d" % i, "6000%02d" % (i + 1), "06-Sep-2026", "A"), vts))
        self.areas = Doc(self, "ProjectC-Studio-BIM-SW00-ZZZ-AR-970002_user", a, self.app)
        self.active = self.master

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d/revit_mcp/execute_code/" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def run(self, code):
        out = []
        ns = {"doc": self.active, "uidoc": None, "__builtins__": builtins,
              "print": lambda *a: out.append(" ".join(str(x) for x in a) + "\n")}
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                compiled = compile(code, "<revit>", "exec")
            exec(compiled, ns)
            return 200, {"status": "success", "output": "".join(out) or "Code executed successfully (no output)"}
        except Exception as e:
            return 500, {"status": "error", "error": "%s: %s" % (type(e).__name__, e),
                         "partial_output": "".join(out)}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                code = json.loads(body.decode("utf-8"))["code"]
                with fake.lock:
                    idx = fake.calls
                    fake.calls += 1
                    if fake.paused:
                        status, data = 503, {"status": "paused", "error": "Revit MCP has been manually stopped"}
                    else:
                        status, data = fake.run(code)
                        if idx in fake.stale_calls:
                            data = {"status": "success", "output": fake._last_output}
                            status = 200
                        else:
                            fake._last_output = data.get("output") or data.get("partial_output") or ""
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return H
