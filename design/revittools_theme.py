"""Revit Tools design system for Tkinter apps: As per system / Light / Dark, switchable live.

Usage (every new app):

    import revittools_theme as rt
    root = tk.Tk()
    rt.apply(root)                           # the saved choice; default "As per system"
    rt.theme_picker(bar).pack(side="right")  # Theme: [As per system | Light | Dark]  (saved for ALL apps)
    ttk.Label(f, text="...", style=rt.style_for("text-dim"))   # colour via styles -> follows a switch
    log = rt.console(frame)                  # dark run log with ok / err / hdr tags
    rt.tag_tree(tree)                        # connected / partial / down / nobridge row colours
    rt.footer(root, APP, VERSION, COPYRIGHT, right_text="Machine ID ...")
    rt.on_change(widget, lambda p: ...)      # anything else that must be repainted on a switch

Never pass foreground=<hex> or palette[...] to a widget: it will not follow a theme switch.
The choice is saved in %APPDATA%\\RevitTools\\settings.json; REVITTOOLS_THEME=light|dark|system overrides it.
Values come from design/tokens.json (the "Revit Tools" Design System artifact).
Self-contained on purpose so Nuitka / PyInstaller builds need no data files.
"""
import sys
import tkinter as tk
from tkinter import ttk

LIGHT = {
    "surface": "#f9f9f9", "paper": "#ffffff", "ink": "#212121", "ink-muted": "#666666",
    "text-dim": "#666666", "text-meta": "#666666", "text-faint": "#666666", "rule": "#cccccc",
    "grid-line": "#cccccc", "grid-line-light": "#e6e6e6", "table-header": "#f2f2f2", "table-header-deep": "#e6e6e6",
    "row-alt": "#f2f2f2", "row-alt-neutral": "#f9f9f9", "row-total": "#e8e8e8", "note-bg": "#fff9e8",
    "note-border": "#ffc21a", "on-fill": "#212121", "accent": "#5f60ff", "on-accent": "#ffffff",
    "on-status": "#000000", "state-connected": "#00a85d", "state-partial": "#8a5a00", "state-down": "#c34922",
    "state-inactive": "#666666", "tray-connected": "#2bc275", "tray-partial": "#ffc21a", "tray-down": "#d95529",
    "licence-ok": "#00a85d", "licence-offline": "#8a5a00", "licence-error": "#c34922", "success-text": "#00a85d",
    "status-open": "#d95529", "status-progress": "#ffc21a", "status-done": "#2bc275", "status-draft": "#cccccc",
    "console-bg": "#161616", "console-fg": "#dedede", "console-ok": "#2bc275", "console-err": "#d95529",
    "console-head": "#8080ff",
}

DARK = {
    "surface": "#161616", "paper": "#262626", "ink": "#dedede", "ink-muted": "#a2a2a2",
    "text-dim": "#a2a2a2", "text-meta": "#a2a2a2", "text-faint": "#a2a2a2", "rule": "#666666",
    "grid-line": "#666666", "grid-line-light": "#454545", "table-header": "#212121", "table-header-deep": "#333333",
    "row-alt": "#212121", "row-alt-neutral": "#212121", "row-total": "#333333", "note-bg": "#453817",
    "note-border": "#ffc21a", "on-fill": "#dedede", "accent": "#5f60ff", "on-accent": "#ffffff",
    "on-status": "#000000", "state-connected": "#2bc275", "state-partial": "#ffc21a", "state-down": "#d95529",
    "state-inactive": "#a2a2a2", "tray-connected": "#2bc275", "tray-partial": "#ffc21a", "tray-down": "#d95529",
    "licence-ok": "#2bc275", "licence-offline": "#ffc21a", "licence-error": "#d95529", "success-text": "#2bc275",
    "status-open": "#d95529", "status-progress": "#ffc21a", "status-done": "#2bc275", "status-draft": "#cccccc",
    "console-bg": "#000000", "console-fg": "#dedede", "console-ok": "#2bc275", "console-err": "#d95529",
    "console-head": "#8080ff",
}

# Tk point sizes (tokens.json gives the 96-dpi px equivalents)
# Helvetica is the house face. Tk on Windows ALWAYS aliases the family name "Helvetica" to Arial, even when
# Helvetica is installed, so ask for an installed Helvetica family by its own name first (see _resolve_ui).
UI_CANDIDATES = ("Helvetica World", "Helvetica Neue LT Pro", "HelveticaNeueLT Pro 55 Roman", "Helvetica Neue", "Helvetica")
UI, MONO = "Helvetica", "Consolas"
FONTS = {}


def _build_fonts():
    FONTS.update({
        "ui-title": (UI, 14, "bold"), "ui-heading": (UI, 11, "bold"), "ui-body-strong": (UI, 10, "bold"),
        "ui-body": (UI, 10), "ui-label": (UI, 9), "ui-table-heading": (UI, 9, "bold"), "ui-caption": (UI, 8),
        "mono-id": (MONO, 11, "bold"), "mono-body": (MONO, 10), "mono-console": (MONO, 9), "mono-caption": (MONO, 8),
    })


_build_fonts()


def _resolve_ui(root):
    """Pick the first installed Helvetica family; plain 'Helvetica' (-> Arial in Tk) is the fallback."""
    global UI
    import tkinter.font as tkfont
    have = set(tkfont.families(root))
    UI = next((f for f in UI_CANDIDATES if f in have), "Helvetica")
    _build_fonts()
SPACE = {2: 2, 3: 3, 4: 4, 6: 6, 8: 8, 10: 10, 12: 12, 14: 14, 16: 16, 22: 22}
ROW_HEIGHT = 24

MODES = (("system", "As per system"), ("light", "Light"), ("dark", "Dark"))

palette = dict(LIGHT)   # the active palette after apply()
_state = {"pref": None, "effective": None, "roots": []}
_hooks = []             # (widget, fn(palette)) re-run on every switch; dead widgets are pruned


def system_mode():
    """'dark' or 'light' from Windows 'Choose your app mode' (AppsUseLightTheme)."""
    if sys.platform != "win32":
        return "light"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


# ------------------------------------------------------------------ saved choice
def _settings_path():
    import os
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "RevitTools", "settings.json")


def load_pref():
    """The saved choice ('system' | 'light' | 'dark'), shared by every Revit Tools app."""
    import json
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            v = json.load(f).get("theme", "system")
        return v if v in dict(MODES) else "system"
    except Exception:
        return "system"


def save_pref(mode):
    import json
    import os
    path = _settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        data["theme"] = mode
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ------------------------------------------------------------------ applying
def style_for(key):
    """ttk label style painting text in palette[key]: 'text-dim' -> 'TextDim.TLabel'.
    Colour labels through styles (not foreground=) so they follow a live switch."""
    return "".join(part.capitalize() for part in key.split("-")) + ".TLabel"


def licence_style(state):
    return style_for({"ok": "licence-ok", "offline": "licence-offline"}.get(state, "licence-error"))


def on_change(widget, fn):
    """Run fn(palette) now and after every switch: for tk widgets and tags that ttk styles cannot reach."""
    fn(palette)
    _hooks.append((widget, fn))


def apply(root, mode=None):
    """Style the whole app. mode None = the saved choice (default 'As per system').
    Both themes are drawn from the palette ('clam' recoloured). Call again to switch live."""
    import os
    pref = os.environ.get("REVITTOOLS_THEME") or mode or load_pref()
    effective = system_mode() if pref == "system" else pref
    _state["pref"], _state["effective"] = pref, effective
    p = DARK if effective == "dark" else LIGHT
    palette.clear()
    palette.update(p)
    if root not in _state["roots"]:
        _state["roots"].append(root)
        root.after(3000, lambda: _watch_system(root))
    _style(root, effective, p)
    alive = []
    for w, fn in _hooks:
        try:
            if w.winfo_exists():
                fn(p)
                alive.append((w, fn))
        except tk.TclError:
            pass
    _hooks[:] = alive
    return palette


def _watch_system(root):
    """While 'As per system' is chosen, follow Windows when its app mode changes."""
    try:
        if not root.winfo_exists():
            return
    except tk.TclError:
        return
    if _state["pref"] == "system" and system_mode() != _state["effective"]:
        apply(root, "system")
    root.after(3000, lambda: _watch_system(root))


def _dark_title_bar(root, dark):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+ / older builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def _style(root, mode, p):
    """Both themes use 'clam' fully recoloured from the palette (native 'vista' ignores most colours)."""
    import tkinter.font as tkfont
    _resolve_ui(root)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name, root=root).configure(family=UI)      # Helvetica everywhere
        except tk.TclError:
            pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=p["surface"], foreground=p["ink"], fieldbackground=p["paper"],
                    bordercolor=p["grid-line"], lightcolor=p["surface"], darkcolor=p["surface"],
                    troughcolor=p["paper"], selectbackground=p["accent"], selectforeground=p["on-accent"],
                    insertcolor=p["ink"], focuscolor=p["accent"], font=FONTS["ui-label"])
    style.configure("TButton", background=p["paper"], padding=(10, 3))
    style.map("TButton", background=[("pressed", p["row-total"]), ("active", p["row-total"])],
              foreground=[("disabled", p["text-faint"])])
    style.configure("Toolbutton", background=p["paper"])
    style.map("Toolbutton", background=[("selected", p["accent"]), ("active", p["row-total"])],
              foreground=[("selected", p["on-accent"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        style.configure(w, indicatorbackground=p["paper"], indicatorforeground=p["ink"])
        style.map(w, background=[("active", p["surface"])],
                  indicatorbackground=[("disabled", p["surface"]), ("selected", p["accent"])],
                  indicatorforeground=[("selected", p["on-accent"])],
                  foreground=[("disabled", p["text-faint"])])
    style.configure("TSeparator", background=p["rule"])
    for w in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(w, background=p["row-total"], troughcolor=p["paper"], bordercolor=p["paper"],
                        lightcolor=p["row-total"], darkcolor=p["row-total"], arrowcolor=p["ink"])
        style.map(w, background=[("active", p["accent"])])
    style.configure("TNotebook", background=p["surface"], bordercolor=p["grid-line"])
    style.configure("TNotebook.Tab", background=p["surface"], foreground=p["text-dim"], padding=(8, 3))
    style.map("TNotebook.Tab", background=[("selected", p["paper"])], foreground=[("selected", p["ink"])])
    style.configure("TEntry", fieldbackground=p["paper"], foreground=p["ink"])
    style.map("TEntry", fieldbackground=[("readonly", p["surface"])])
    style.configure("TCombobox", fieldbackground=p["paper"], foreground=p["ink"], arrowcolor=p["ink"],
                    background=p["paper"])
    style.map("TCombobox", fieldbackground=[("readonly", p["paper"])], foreground=[("readonly", p["ink"])],
              selectbackground=[("readonly", p["paper"])], selectforeground=[("readonly", p["ink"])])
    style.configure("TLabelframe", background=p["surface"], bordercolor=p["grid-line"])
    style.configure("TLabelframe.Label", background=p["surface"], foreground=p["ink"])
    style.configure("Treeview", background=p["paper"], fieldbackground=p["paper"], foreground=p["ink"])
    style.map("Treeview", background=[("selected", p["accent"])], foreground=[("selected", p["on-accent"])])
    style.configure("Treeview.Heading", background=p["table-header"], foreground=p["on-fill"])
    style.map("Treeview.Heading", background=[("active", p["row-total"])])
    style.configure("Horizontal.TProgressbar", background=p["accent"])
    root.option_add("*TCombobox*Listbox.background", p["paper"])
    root.option_add("*TCombobox*Listbox.foreground", p["ink"])
    root.configure(background=p["surface"])
    for key in p:                                    # TextDim.TLabel, StateDown.TLabel, LicenceOk.TLabel, ...
        style.configure(style_for(key), foreground=p[key])
    style.configure("Big.TLabel", font=FONTS["ui-title"])
    style.configure("Heading.TLabel", font=FONTS["ui-heading"])
    style.configure("Dim.TLabel", foreground=p["text-dim"])
    style.configure("Faint.TLabel", foreground=p["text-faint"], font=FONTS["ui-caption"])
    style.configure("FaintMono.TLabel", foreground=p["text-faint"], font=FONTS["mono-caption"])
    style.configure("Mono.TLabel", font=FONTS["mono-body"])
    style.configure("Treeview", rowheight=ROW_HEIGHT, font=FONTS["ui-body"])
    style.configure("Treeview.Heading", font=FONTS["ui-table-heading"])
    style.configure("Mode.Toolbutton", padding=(22, 10))
    _dark_title_bar(root, mode == "dark")


# ------------------------------------------------------------------ widgets
def theme_picker(parent, root=None, label="Theme"):
    """'Theme [As per system | Light | Dark]': saves the choice for every Revit Tools app and switches live."""
    root = root or parent.winfo_toplevel()
    frame = ttk.Frame(parent)
    ttk.Label(frame, text=label).pack(side="left", padx=(0, 6))
    names = dict(MODES)
    var = tk.StringVar(value=names.get(_state["pref"] or load_pref(), names["system"]))
    box = ttk.Combobox(frame, textvariable=var, values=[n for _, n in MODES], state="readonly", width=14)
    box.pack(side="left")

    def chosen(_e=None):
        mode = next(k for k, n in MODES if n == var.get())
        save_pref(mode)
        apply(root, mode)
        box.selection_clear()
    box.bind("<<ComboboxSelected>>", chosen)
    return frame


def console(parent, wrap="none", **kw):
    """ConsoleLog: dark in both themes. Tags: ok, err, hdr."""
    t = tk.Text(parent, wrap=wrap, font=FONTS["mono-console"], relief="flat", borderwidth=0, **kw)

    def paint(p):
        t.configure(background=p["console-bg"], foreground=p["console-fg"], insertbackground=p["console-fg"])
        t.tag_config("ok", foreground=p["console-ok"])
        t.tag_config("err", foreground=p["console-err"])
        t.tag_config("hdr", foreground=p["console-head"])
    on_change(t, paint)
    return t


def text_box(parent, **kw):
    """Plain multi-line output box on `paper` (e.g. generated keys), following the theme."""
    t = tk.Text(parent, relief="flat", highlightthickness=1, **kw)
    on_change(t, lambda p: t.configure(background=p["paper"], foreground=p["ink"], insertbackground=p["ink"],
                                       highlightbackground=p["grid-line"], highlightcolor=p["table-header"]))
    return t


def tag_tree(tree):
    """SessionTable row tags."""
    def paint(p):
        for tag, key in (("connected", "state-connected"), ("active", "state-connected"), ("partial", "state-partial"),
                         ("down", "state-down"), ("revoked", "state-down"), ("nobridge", "state-inactive")):
            tree.tag_configure(tag, foreground=p[key])
    on_change(tree, paint)


def licence_colour(state):
    return {"ok": palette["licence-ok"], "offline": palette["licence-offline"]}.get(state, palette["licence-error"])


def footer(root, app, version, copyright_text, right_text=""):
    """AppFooter: pack this FIRST so it survives a short window. Returns the right-hand label."""
    foot = ttk.Frame(root, padding=(10, 0, 10, 6))
    foot.pack(side="bottom", fill="x")
    ttk.Label(foot, text="%s v%s   %s" % (app, version, copyright_text), style="Faint.TLabel").pack(side="left")
    right = ttk.Label(foot, text=right_text, style="FaintMono.TLabel")
    right.pack(side="right")
    return right


if __name__ == "__main__":   # quick visual check: python revittools_theme.py
    r = tk.Tk()
    r.title("Revit Tools theme")
    r.geometry("880x520")
    apply(r)
    footer(r, "Theme demo", "1.0", "(c) the developer", "Machine ID 0000-0000-0000")
    nb = ttk.Notebook(r)
    nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
    f = ttk.Frame(nb, padding=10)
    nb.add(f, text="  Status  ")
    top = ttk.Frame(f)
    top.pack(fill="x")
    ttk.Label(top, text="Licensed", style=licence_style("ok"), font=FONTS["ui-title"]).pack(side="left")
    theme_picker(top).pack(side="right")
    ttk.Label(f, text="Verified online just now.", style="Dim.TLabel").pack(anchor="w", pady=(0, 8))
    tv = ttk.Treeview(f, columns=("port", "doc"), show="headings", height=3)
    tv.heading("port", text="Port")
    tv.heading("doc", text="Document / model")
    tag_tree(tv)
    for row, tag in ((("48884", "B002_AR_Central.rvt"), "connected"), (("48885", "(no document)"), "partial"),
                     (("48886", "-"), "down")):
        tv.insert("", "end", values=row, tags=(tag,))
    tv.pack(fill="x")
    bar = ttk.Frame(f)
    bar.pack(fill="x", pady=8)
    ttk.Button(bar, text="Run").pack(side="left")
    ttk.Button(bar, text="Open output folder").pack(side="left", padx=8)
    ttk.Checkbutton(bar, text="Dry run — report only, write nothing").pack(side="left", padx=8)
    lg = console(f, height=6)
    lg.pack(fill="both", expand=True)
    lg.insert("end", "=== Step 1  Read profile ===\n", "hdr")
    lg.insert("end", "OK  42 / 42 PDFs updated\n", "ok")
    lg.insert("end", "FAIL  A-117  title block moved 0.8 mm\n", "err")
    r.mainloop()
