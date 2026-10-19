"""The script folder (lib/netbuild_scripts.py): settings, finding button folders at any depth, running a button's
script from the folder, Update Scripts, and the two Scripts-panel buttons (stub pyRevit, see pyrevit_stubs.py).

    python -m unittest discover -s LevelShifter/tests -v
"""

import io
import os
import runpy
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXT = os.path.join(ROOT, "pyRevit", "Netbuild.extension")
sys.path.insert(0, HERE)
sys.path.append(os.path.join(EXT, "lib"))

import pyrevit_stubs  # noqa: E402
from fake_revit import FakeRevit  # noqa: E402
import netbuild_scripts as ns  # noqa: E402

HEADER = "import netbuild_scripts\nnetbuild_scripts.run_live(globals())\n"


def write(path, text, mtime=None):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


class ScriptFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {"APPDATA": os.path.join(self.tmp, "appdata")}
        self.share = os.path.join(self.tmp, "share")
        self.ext = os.path.join(self.tmp, "installed", "Tools.extension")
        self.button = os.path.join(self.ext, "Tools.tab", "A.panel", "Hello.pushbutton")
        self.local = write(os.path.join(self.button, "script.py"), HEADER + "RAN.append('local')\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_button(self):
        ran = []
        try:
            runpy.run_path(self.local, init_globals={"RAN": ran}, run_name="__main__")
        except SystemExit:
            ran.append("exit")
        return ran

    def test_settings_order(self):
        write(os.path.join(self.ext, ns.SETTINGS_NAME), '{"folders": ["%TEAM%/scripts"], "live": false}')
        env = dict(self.env, TEAM=self.tmp)
        s = ns.settings(self.ext, env)
        self.assertEqual((s["folders"], s["live"], s["from"]),
                         ([os.path.normpath(os.path.join(self.tmp, "scripts"))], False, "extension default"))
        env[ns.ENV] = "  %s ; %s;" % (self.share, self.tmp)
        self.assertEqual(ns.settings(self.ext, env)["folders"], [self.share, self.tmp])
        ns.save_settings(folders=[self.share], live=True, env=env)
        s = ns.settings(self.ext, env)
        self.assertEqual((s["folders"], s["live"], s["from"]), ([self.share], True, "your setting"))
        ns.save_settings(folders=[], env=env)                       # cleared -> back to the variable
        self.assertEqual(ns.settings(self.ext, env)["from"], ns.ENV)
        self.assertEqual(ns.settings(None, {})["folders"], [])

    def test_scan_finds_buttons_in_any_sub_folder(self):
        old = write(os.path.join(self.share, "2025", "Hello.pushbutton", "script.py"), "", time.time() - 100)
        new = write(os.path.join(self.share, "a", "b", "c", "hello.PUSHBUTTON", "script.py"), "")
        write(os.path.join(self.share, ".git", "Hello.pushbutton", "script.py"), "")
        write(os.path.join(self.share, "x", "Net.extension", "N.tab", "S.splitbutton", "Two.pushbutton", "script.py"), "")
        found = ns.scan([self.share, os.path.join(self.share, "a"), os.path.join(self.tmp, "offline")])  # nested
        self.assertEqual(found["hello.pushbutton"], [os.path.dirname(new), os.path.dirname(old)])   # newest first
        self.assertIn("two.pushbutton", found)
        self.assertIn("net.extension", found)
        text = ns.describe({"folders": [self.share], "live": True, "from": "your setting"}, found)
        self.assertIn("2 button folders found", text)
        self.assertIn("Hello.pushbutton is there 2 times", text.replace("hello.PUSHBUTTON", "Hello.pushbutton"))

    def test_live_runs_the_folder_copy(self):
        self.assertEqual(self.run_button(), ["local"])               # no folder set
        os.environ["APPDATA"] = self.env["APPDATA"]
        try:
            ns.save_settings(folders=[self.share])
            self.assertEqual(self.run_button(), ["local"])           # the button is not in the folder
            src = write(os.path.join(self.share, "Team", "Revit", "Hello.pushbutton", "script.py"),
                        HEADER + "RAN.append('shared:' + __file__)\n")
            self.assertEqual(self.run_button(), ["local"])           # recently looked: not looked again yet
            ns.rescan([self.share])                                  # Script Folder > Look in the folder again
            self.assertEqual(self.run_button(), ["shared:" + src, "exit"])
            ns.save_settings(live=False)
            self.assertEqual(self.run_button(), ["local"])
            ns.save_settings(live=True, folders=[os.path.dirname(self.ext)])   # only the installed copy there
            self.assertEqual(self.run_button(), ["local"])
            ns.save_settings(folders=[os.path.join(self.tmp, "offline")])
            self.assertEqual(self.run_button(), ["local"])
        finally:
            os.environ.pop("APPDATA", None)

    def test_update(self):
        write(os.path.join(self.button, "icon.png"), "old icon")
        write(os.path.join(self.ext, "lib", "tools.py"), "VERSION = 1\n")
        other = write(os.path.join(self.ext, "Tools.tab", "A.panel", "Other.pushbutton", "script.py"), "same\n")
        src_ext = os.path.join(self.share, "masters", "Tools.extension")
        write(os.path.join(src_ext, "lib", "tools.py"), "VERSION = 2\n")
        write(os.path.join(src_ext, "lib", "__pycache__", "tools.cpython-312.pyc"), "x")
        write(os.path.join(self.share, "deep", "er", "Hello.pushbutton", "script.py"), "new script\n")
        write(os.path.join(self.share, "deep", "er", "Hello.pushbutton", "icon.png"), "new icon")
        write(os.path.join(self.share, "Other.pushbutton", "script.py"), "same\n")
        exts = ns.installed_extensions(self.ext)
        self.assertEqual(exts, [self.ext])
        plan = ns.plan_update([self.share], exts, self.env)
        self.assertEqual(sorted(dst for src, dst in plan),
                         sorted([os.path.join(self.ext, "lib", "tools.py"), self.local,
                                 os.path.join(self.button, "icon.png")]))
        copied, errors, backup = ns.apply_update(plan, self.env)
        self.assertEqual((copied, errors), (3, []))
        self.assertEqual(read(self.local), "new script\n")
        self.assertEqual(read(os.path.join(self.ext, "lib", "tools.py")), "VERSION = 2\n")
        self.assertEqual(read(os.path.join(backup, "Tools.extension", "lib", "tools.py")), "VERSION = 1\n")
        self.assertEqual(read(other), "same\n")
        self.assertEqual(ns.plan_update([self.share], exts, self.env), [])          # up to date now
        self.assertEqual(ns.plan_update([os.path.dirname(self.ext)], exts, self.env), [])   # never from itself


class HeaderTests(unittest.TestCase):
    """Adding the run_live lines to the buttons of other extensions (Netbuild 01 / 02)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = {"APPDATA": os.path.join(self.tmp, "appdata")}
        self.lib = os.path.join(EXT, "lib", "netbuild_scripts.py")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_header_position(self):
        cases = [
            ('"""Doc\nmore"""\n__title__ = "A"\n__author__ = ("x",\n    "y")\nimport os\n', 5),
            ("# -*- coding: utf-8 -*-\nfrom pyrevit import forms\n", 1),
            ("#! python3\nfrom __future__ import print_function\n__doc__ = \'\'\'a\nb\'\'\'\n\nx = 1\n", 4),
            ("import os\n", 0),
            ("__context__ = 'zero-doc'  # comment ) (\n__title__ = 'a\\\'b'\nprint('x')\n", 2),
        ]
        for src, at in cases:
            self.assertEqual(ns.header_position(src.splitlines(True)), at, src)
        out = ns.with_header('"""Doc"""\r\n__author__ = "a"\r\nimport os\r\n')
        self.assertEqual(out, '"""Doc"""\r\n__author__ = "a"\r\n\r\n' + ns.HEADER.replace("\n", "\r\n") +
                         "\r\nimport os\r\n")
        self.assertIsNone(ns.with_header(out))
        compile(ns.with_header(cases[0][0]), "x", "exec")

    def test_add_header_to_other_extensions(self):
        ext = os.path.join(self.tmp, "exts", "Netbuild 01.extension")
        tab = os.path.join(ext, "Netbuild 01.tab", "Walls.panel")
        btn = write(os.path.join(tab, "Tags.pulldown", "Wall Tags.pushbutton", "script.py"),
                    '# -*- coding: utf-8 -*-\n"""Tag walls."""\n__title__ = "Wall Tags"\nRAN.append("local")\n')
        cfg = write(os.path.join(tab, "Tags.pulldown", "Wall Tags.pushbutton", "config.py"), "print('cfg')\n")
        bom = write(os.path.join(tab, "Bom.pushbutton", "script.py"), "")
        with io.open(bom, "wb") as f:                                   # UTF-8 with BOM, Windows line ends
            f.write(b"\xef\xbb\xbf# -*- coding: utf-8 -*-\r\nx = 1\r\n")
        smart = write(os.path.join(tab, "Toggle.smartbutton", "script.py"), "def __selfinit__(*a):\n    pass\n")
        done = write(os.path.join(tab, "Done.pushbutton", "script.py"), ns.HEADER)
        other = os.path.join(self.tmp, "exts", "Netbuild 02.extension")
        write(os.path.join(other, "N2.tab", "P.panel", "B.pushbutton", "script.py"), "x = 2\n")

        exts = ns.extensions_in(os.path.join(self.tmp, "exts"))
        self.assertEqual([os.path.basename(e) for e in exts], ["Netbuild 01.extension", "Netbuild 02.extension"])
        todo, skipped, backup = ns.add_header(exts, self.lib, env=self.env)       # report only
        self.assertIsNone(backup)
        self.assertEqual(read(cfg), "print('cfg')\n")
        self.assertEqual(len(todo), 6)                  # 3 scripts + config in 01, 1 script in 02, lib in each
        self.assertEqual(sorted(p for p, why in skipped), sorted([smart, done]))

        changed, skipped, backup = ns.add_header(exts, self.lib, apply=True, env=self.env)
        self.assertEqual(sorted(changed), sorted(todo))
        self.assertIn(ns.HEADER, read(btn))
        self.assertTrue(read(btn).startswith('# -*- coding: utf-8 -*-\n"""Tag walls."""\n__title__ = "Wall Tags"\n'))
        with io.open(bom, "rb") as f:
            self.assertTrue(f.read().startswith(b"\xef\xbb\xbf# -*- coding: utf-8 -*-\r\n\r\nimport netbuild_scripts\r\n"))
        self.assertEqual(read(os.path.join(ext, "lib", "netbuild_scripts.py")), read(self.lib))
        self.assertEqual(read(os.path.join(backup, "Netbuild 01.extension", "Netbuild 01.tab", "Walls.panel",
                                           "Tags.pulldown", "Wall Tags.pushbutton", "config.py")), "print('cfg')\n")
        self.assertEqual(ns.add_header(exts, self.lib, env=self.env)[0], [])        # nothing left to do

        share = os.path.join(self.tmp, "share")                                    # the button now runs live
        write(os.path.join(share, "x", "Wall Tags.pushbutton", "script.py"), ns.HEADER + "RAN.append('shared')\n")
        os.environ["APPDATA"] = self.env["APPDATA"]
        try:
            ns.save_settings(folders=[share])
            ran = []
            with self.assertRaises(SystemExit):
                runpy.run_path(btn, init_globals={"RAN": ran}, run_name="__main__")
            self.assertEqual(ran, ["shared"])
        finally:
            os.environ.pop("APPDATA", None)

    def test_command_line(self):
        sys.path.insert(0, os.path.join(ROOT, "pyRevit"))
        import add_live_header
        ext = os.path.join(self.tmp, "Netbuild 02.extension")
        btn = write(os.path.join(ext, "T.tab", "P.panel", "B.pushbutton", "script.py"), "x = 2\n")
        os.environ["APPDATA"] = self.env["APPDATA"]
        try:
            self.assertEqual(add_live_header.main([ext]), 0)
            self.assertEqual(read(btn), "x = 2\n")
            self.assertEqual(add_live_header.main([ext, "--apply"]), 0)
            self.assertIn(ns.HEADER, read(btn))
            self.assertEqual(add_live_header.main([os.path.join(self.tmp, "nothing-here")]), 1)
        finally:
            os.environ.pop("APPDATA", None)


class ShippedDefaultTests(unittest.TestCase):
    def test_default_folders(self):
        s = ns.settings(EXT, {"USERPROFILE": r"C:\Users\user"})
        self.assertEqual(s["from"], "extension default")
        self.assertTrue(s["live"])
        self.assertEqual([p.replace("\\", "/") for p in s["folders"]],
                         ["C:/Users/user/OneDrive - Studio/Netbuild",
                          "C:/Users/user/OneDrive - Studio/Netbuild/scripts"])


class ScriptsPanelButtonTests(unittest.TestCase):
    """The Script Folder and Update Scripts buttons, run from a copy of the extension."""

    def setUp(self):
        self.fake = FakeRevit()
        self.tmp = tempfile.mkdtemp()
        self._env = dict(os.environ)
        os.environ["APPDATA"] = os.path.join(self.tmp, "appdata")
        os.environ.pop(ns.ENV, None)
        self.ext = os.path.join(self.tmp, "installed", "Netbuild.extension")
        shutil.copytree(EXT, self.ext, ignore=shutil.ignore_patterns("__pycache__"))
        write(os.path.join(self.ext, ns.SETTINGS_NAME), '{"folders": [], "live": true}')   # no shipped default
        panel = os.path.join(self.ext, "Netbuild.tab", "Scripts.panel")
        self.folder_btn = os.path.join(panel, "Script Folder.pushbutton", "script.py")
        self.update_btn = os.path.join(panel, "Update Scripts.pushbutton", "script.py")
        self.share = os.path.join(self.tmp, "share")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def press(self, path, **answers):
        st = pyrevit_stubs.install(self.fake.doc, answers=answers)
        try:
            runpy.run_path(path, run_name="__main__")
        except (pyrevit_stubs.ScriptExit, SystemExit):     # SystemExit: a live run ended
            pass
        return st

    def test_script_folder_button(self):
        write(os.path.join(self.share, "Revit", "Levels", "Level Shift.pushbutton", "script.py"), "")
        st = self.press(self.folder_btn, switch="Choose the folder...", folder=self.share)
        self.assertIn("No script folder set", st.switch[0][1])
        self.assertEqual(ns.settings(self.ext)["folders"], [self.share])
        self.assertIn("1 button folder found", st.alerts[-1][1])
        st = self.press(self.folder_btn, switch="Live scripts: turn off")
        self.assertIn("Live scripts: turn off", st.switch[0][0])
        self.assertFalse(ns.settings(self.ext)["live"])
        st = self.press(self.folder_btn, switch=None)                  # cancelled: nothing changes
        self.assertEqual(st.alerts, [])
        other = os.path.join(self.tmp, "installed", "Netbuild 01.extension")
        btn = write(os.path.join(other, "N.tab", "P.panel", "B.pushbutton", "script.py"), "x = 1\n")
        st = self.press(self.folder_btn, switch="Add live scripts to other extensions...",
                        folder=os.path.dirname(other))                    # Netbuild.extension itself is left out
        self.assertIn("these 2 file(s)", st.alerts[0][1])
        self.assertIn("2 file(s) changed", st.alerts[-1][1])
        self.assertIn(ns.HEADER, read(btn))

    def test_update_button_and_live_level_shift(self):
        st = self.press(self.update_btn)
        self.assertIn("No script folder set", st.alerts[-1][1])
        direct = os.path.join(self.ext, "Netbuild.tab", "Levels.panel", "Level Shift.pushbutton", "script.py")
        shared = write(os.path.join(self.share, "any", "depth", "Level Shift.pushbutton", "script.py"),
                       read(direct).replace("LevelShiftWindow(doc).show_dialog()",
                                            "forms.alert('from the share', title='Live')"))
        ns.save_settings(folders=[self.share])
        st = self.press(direct)                                        # live: the share's copy runs
        self.assertEqual(st.alerts[-1], ("Live", "from the share"))
        st = self.press(self.update_btn)                               # confirm (alert -> True), copy, reload
        self.assertIn("Copy 1 changed file from the script folder?", st.alerts[0][1])
        self.assertIn("1 file updated", st.alerts[-1][1])
        self.assertEqual(st.reloaded, 1)
        self.assertEqual(read(direct), read(shared))
        st = self.press(self.update_btn)
        self.assertIn("Everything is up to date", st.alerts[-1][1])


if __name__ == "__main__":
    unittest.main()
