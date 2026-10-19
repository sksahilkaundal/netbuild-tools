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
        found = ns.scan([self.share, os.path.join(self.tmp, "offline")])
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
