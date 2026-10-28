"""The pyRevit MCP listener for tests: serves POST /revit_mcp/execute_code/ like the real route and runs the posted
code with ``doc`` / ``uidoc`` bound to the stand-in model (LevelShifter/tests/fake_stairs.py, which the button's
tests use too) and ``print`` captured, as revit_mcp/code_execution.py does.
"""

import builtins
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "LevelShifter", "tests"))

import fake_stairs  # noqa: E402


class FakeListener(object):
    def __init__(self, model=None):
        fake_stairs.install_stubs()
        self.m = model or fake_stairs.Model()
        self.paused = False
        self.calls = 0
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = "http://127.0.0.1:%d/revit_mcp/execute_code/" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def doc(self):
        return self.m.doc

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def run(self, code):
        out = []
        ns = {"doc": self.m.doc, "uidoc": self.m.uidoc, "DB": None, "revit": None, "__builtins__": builtins,
              "print": lambda *a: out.append(" ".join(str(x) for x in a) + "\n")}
        try:
            exec(compile(code, "<revit>", "exec"), ns)
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
                    fake.calls += 1
                    if fake.paused:
                        status, data = 503, {"status": "paused", "error": "Revit MCP has been manually stopped"}
                    else:
                        status, data = fake.run(code)
                raw = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return H
