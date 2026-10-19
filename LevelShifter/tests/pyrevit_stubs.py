"""Just enough pyRevit + WPF to run the extension's button scripts outside Revit.

``forms.WPFWindow`` parses the real XAML (so a malformed layout fails the test), binds every
``x:Name`` element as an attribute, and fires Click / TextChanged / SelectionChanged / Checked
the way WPF does when a property changes.  ``show_dialog`` hands the window to a test hook
instead of blocking.
"""

import sys
import types
import xml.etree.ElementTree as ET

X_NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"


class Event(object):
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self, sender=None):
        for h in list(self.handlers):
            h(sender, None)


class Items(list):
    def Add(self, x):
        self.append(x)

    def Clear(self):
        del self[:]


class Control(object):
    def __init__(self, window, el):
        d = self.__dict__
        d["window"], d["tag"] = window, el.tag.split("}")[-1]
        d["GroupName"] = el.get("GroupName")
        d["Content"] = el.get("Content")
        d["_text"] = el.get("Text") or ""
        d["_checked"] = el.get("IsChecked") == "True"
        d["_selected"] = None
        d["Items"] = Items()
        for name in ("Click", "TextChanged", "SelectionChanged", "Checked"):
            d[name] = Event()

    # Text / SelectedItem / IsChecked fire their events like WPF
    @property
    def Text(self):
        return self._text

    @Text.setter
    def Text(self, v):
        if v != self._text:
            self.__dict__["_text"] = v
            self.TextChanged.fire(self)

    @property
    def SelectedItem(self):
        return self._selected

    @SelectedItem.setter
    def SelectedItem(self, v):
        v = v if v in self.Items else None
        if v != self._selected:
            self.__dict__["_selected"] = v
            self.SelectionChanged.fire(self)

    @property
    def IsChecked(self):
        return self._checked

    @IsChecked.setter
    def IsChecked(self, v):
        v = bool(v)
        was = self._checked
        self.__dict__["_checked"] = v
        if v and self.GroupName:
            for other in self.window._named.values():
                if other is not self and other.GroupName == self.GroupName:
                    other.__dict__["_checked"] = False
        if v and not was:
            self.Checked.fire(self)

    def click(self):
        self.Click.fire(self)

    def type(self, text):
        self.Text = text


class WPFWindow(object):
    shown = []                  # every window passed to show_dialog
    on_dialog = None            # test hook: fn(window) runs "while the dialog is open"

    def __init__(self, xaml, literal_string=False, handle_esc=True, set_owner=True):
        assert literal_string, "the scripts pass XAML text"
        root = ET.fromstring(xaml)
        self._named = {}
        for el in root.iter():
            name = el.get(X_NAME)
            if name:
                assert name not in self._named, "duplicate x:Name %s" % name
                self._named[name] = Control(self, el)
                object.__setattr__(self, name, self._named[name])
        self.Title = root.get("Title")
        self.closed = False

    def FindName(self, name):
        return self._named.get(name)

    def show_dialog(self):
        WPFWindow.shown.append(self)
        if WPFWindow.on_dialog:
            WPFWindow.on_dialog(self)

    ShowDialog = show_dialog

    def Close(self):
        self.closed = True


class ScriptExit(Exception):
    pass


class Config(object):
    def __init__(self):
        object.__setattr__(self, "values", {})

    def get_option(self, name, default=None):
        return self.values.get(name, default)

    def __setattr__(self, name, value):
        self.values[name] = value


def install(doc, answers=None):
    """Put stub pyrevit / System modules in sys.modules. Returns a namespace the test inspects."""
    state = types.SimpleNamespace(alerts=[], started=[], config=Config(), saved=0, answers=answers or {},
                                  picked=None, clipboard=[], switch=[], reloaded=0, printed=[])

    def alert(msg, title="", yes=False, no=False, exitscript=False, **kw):
        state.alerts.append((title, msg))
        if exitscript:
            raise ScriptExit(msg)
        return state.answers.get("alert", True)

    def save_config():
        state.saved += 1

    def exit_():
        raise ScriptExit("script.exit()")

    forms = types.ModuleType("pyrevit.forms")
    forms.WPFWindow = WPFWindow
    forms.alert = alert
    forms.ask_for_string = lambda prompt="", title="", **kw: state.answers.get("ask")
    forms.pick_file = lambda **kw: state.picked
    forms.pick_folder = lambda **kw: state.answers.get("folder")
    forms.CommandSwitchWindow = types.SimpleNamespace(
        show=lambda options, message="", **kw: state.switch.append((options, message)) or
        state.answers.get("switch"))
    revit_mod = types.ModuleType("pyrevit.revit")
    revit_mod.doc = doc
    revit_mod.uidoc = None
    script = types.ModuleType("pyrevit.script")
    script.get_config = lambda: state.config
    script.save_config = save_config
    script.exit = exit_
    script.get_output = lambda: types.SimpleNamespace(print_md=state.printed.append)
    pyrevit = types.ModuleType("pyrevit")
    pyrevit.forms, pyrevit.revit, pyrevit.script = forms, revit_mod, script
    pyrevit.DB = types.ModuleType("Autodesk.Revit.DB")
    userconfig = types.ModuleType("pyrevit.userconfig")
    userconfig.user_config = types.SimpleNamespace(get_thirdparty_ext_root_dirs=lambda: [])
    sessionmgr = types.ModuleType("pyrevit.loader.sessionmgr")
    sessionmgr.reload_pyrevit = lambda: setattr(state, "reloaded", state.reloaded + 1)
    loader = types.ModuleType("pyrevit.loader")
    loader.sessionmgr = sessionmgr
    pyrevit.userconfig, pyrevit.loader = userconfig, loader

    class ProcessStartInfo(object):
        def __init__(self, exe, args=""):
            self.FileName, self.Arguments = exe, args
            self.WorkingDirectory, self.UseShellExecute = None, False

    class Process(object):
        @staticmethod
        def Start(x):
            state.started.append(x)

    class BrushConverter(object):
        def ConvertFromString(self, s):
            return s

    class ListBoxItem(object):
        Content = Foreground = None

    diag = types.ModuleType("System.Diagnostics")
    diag.Process, diag.ProcessStartInfo = Process, ProcessStartInfo
    controls = types.ModuleType("System.Windows.Controls")
    controls.ListBoxItem = ListBoxItem
    inp = types.ModuleType("System.Windows.Input")
    inp.Cursors = types.SimpleNamespace(Wait="wait")
    inp.Mouse = types.SimpleNamespace(OverrideCursor=None)
    media = types.ModuleType("System.Windows.Media")
    media.BrushConverter = BrushConverter
    windows = types.ModuleType("System.Windows")
    windows.Clipboard = types.SimpleNamespace(SetText=lambda text: state.clipboard.append(text))
    system = types.ModuleType("System")
    sys.modules.update({"pyrevit": pyrevit, "pyrevit.forms": forms, "pyrevit.revit": revit_mod,
                        "pyrevit.script": script, "pyrevit.userconfig": userconfig,
                        "pyrevit.loader": loader, "pyrevit.loader.sessionmgr": sessionmgr, "System": system, "System.Windows": windows,
                        "System.Diagnostics": diag, "System.Windows.Controls": controls,
                        "System.Windows.Input": inp, "System.Windows.Media": media})
    WPFWindow.shown, WPFWindow.on_dialog = [], None
    sys.modules.pop("netbuild_about", None)       # binds the stubs above when a button imports it
    return state
