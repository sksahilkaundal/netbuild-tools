# -*- coding: utf-8 -*-
"""About / licence / --version checks for Remote Router by Netbuild (no Revit, no network).

    py -3.14 -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, HERE]

import remote_about  # noqa: E402
import revit_mcp_remote as rmr  # noqa: E402


class AboutTests(unittest.TestCase):
    def test_license_text_is_license_file(self):
        with open(os.path.join(ROOT, "LICENSE.txt"), encoding="utf-8") as f:
            self.assertEqual(remote_about.LICENSE_TEXT, f.read())     # the About screen shows the real LICENSE.txt
        self.assertTrue(remote_about.LICENSE_TEXT.startswith("Remote Router by Netbuild -- Licence Agreement\n"))
        self.assertIn("Copyright (c) 2026 SKAEC.COM. All rights reserved.", remote_about.LICENSE_TEXT)

    def test_product_info(self):
        self.assertEqual(remote_about.PRODUCT, "Remote Router by Netbuild")
        self.assertEqual(remote_about.PUBLISHER, "SKAEC.COM")
        self.assertEqual(remote_about.WEBSITE, "https://skaec.com")
        self.assertEqual(remote_about.COPYRIGHT, u"© 2026 SKAEC.COM. All rights reserved.")
        self.assertEqual(remote_about.LICENSE_NAME, "Proprietary -- SKAEC.COM licence agreement")
        self.assertEqual(rmr.VERSION, remote_about.VERSION)
        self.assertEqual(remote_about.title("slot 1"), "Remote Router by Netbuild %s -- slot 1" % rmr.VERSION)

    def test_about_text(self):
        text = remote_about.about_text()
        for want in ("Remote Router by Netbuild  version " + remote_about.VERSION,
                     u"© 2026 SKAEC.COM. All rights reserved.", "https://skaec.com",
                     "Features", "Requirements", "Revit MCP Router by Netbuild", "RevitMcpRouter",
                     "mcp[cli] below 2.0", "cloudflared", "custom connectors",
                     "Licence: Proprietary -- SKAEC.COM licence agreement", "This software is licensed, not sold."):
            self.assertIn(want, text)
        self.assertNotIn("This software is licensed", remote_about.about_text(license=False))

    def test_cli_version(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            rmr.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(buf.getvalue().strip(), "Remote Router by Netbuild " + remote_about.VERSION)

    def test_cli_about(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(rmr.main(["--about"]), 0)
        out = buf.getvalue()
        self.assertIn("Remote Router by Netbuild  version " + remote_about.VERSION, out)
        self.assertIn("SKAEC.COM", out)
        self.assertIn("Requirements", out)

    def test_cli_about_on_a_console_without_the_copyright_sign(self):
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="ascii")                  # strict, like an old code page
        with redirect_stdout(out):
            self.assertEqual(rmr.main(["--about"]), 0)
        out.flush()
        self.assertIn(b"? 2026 SKAEC.COM", raw.getvalue())

    def test_help_names_product_and_copyright(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            rmr.main(["--help"])
        self.assertIn("Remote Router by Netbuild " + remote_about.VERSION, buf.getvalue())
        self.assertIn("2026 SKAEC.COM", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
