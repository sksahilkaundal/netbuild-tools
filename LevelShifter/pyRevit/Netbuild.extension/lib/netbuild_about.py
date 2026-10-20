"""About and Licence screens for the Netbuild products in this extension (pyRevit, IronPython 2.7).

Every Netbuild product ships an ``about`` module (PRODUCT, VERSION, OWNER, COPYRIGHT, WEBSITE, DESCRIPTION,
FEATURES, requirements_text(), LICENSE_NAME, LICENSE_KIND, LICENCE_KEY, LICENSE_TEXT, about_text()) and is
listed in PRODUCTS. The ribbon's About / Licence buttons and each tool's own About button show it.
"""

from pyrevit import forms

from System.Diagnostics import Process
from System.Windows import Clipboard

from bua_update import about as bua_update_about
from clear_warnings import about as clear_warnings_about
from element_remover import about as element_remover_about
from level_shift import about as level_shift_about
from stair_path import about as stair_path_about
import levelshift_ui as ui

PRODUCTS = [level_shift_about, bua_update_about, clear_warnings_about, stair_path_about, element_remover_about]


class AboutWindow(forms.WPFWindow):
    def __init__(self, info):
        forms.WPFWindow.__init__(self, ui.about_xaml(info.PRODUCT), literal_string=True)
        self.info = info
        self.Title = "About " + info.PRODUCT
        self.product_tb.Text = info.PRODUCT
        self.version_tb.Text = u"Version %s   |   %s   |   %s" % (info.VERSION, info.COPYRIGHT, info.WEBSITE)
        self.desc_tb.Text = info.DESCRIPTION
        self.features_tb.Text = u"\n".join(u"- " + f for f in info.FEATURES)
        self.req_tb.Text = info.requirements_text()
        self.licence_line_tb.Text = u"Licence: %s -- %s. See Licence." % (info.LICENSE_NAME, info.LICENSE_KIND)
        self.web_btn.Content = "Open " + info.WEBSITE
        self.copy_btn.Click += self.copy
        self.licence_btn.Click += self.licence
        self.web_btn.Click += self.web
        self.close_btn.Click += self.close

    def copy(self, sender, args):
        Clipboard.SetText(self.info.about_text())
        self.copy_btn.Content = "Copied"

    def licence(self, sender, args):
        show_licence(self.info, owner=self)

    def web(self, sender, args):
        Process.Start(self.info.WEBSITE)

    def close(self, sender, args):
        self.Close()


class LicenceWindow(forms.WPFWindow):
    """The licensing page: ownership, website, licence-key status and the full agreement."""

    def __init__(self, info):
        forms.WPFWindow.__init__(self, ui.licence_xaml(info.PRODUCT), literal_string=True)
        self.info = info
        self.Title = "Licence -- " + info.PRODUCT
        self.product_tb.Text = u"%s  version %s" % (info.PRODUCT, info.VERSION)
        self.kind_tb.Text = info.LICENSE_KIND
        self.owner_tb.Text = u"%s   |   Website: %s" % (info.COPYRIGHT, info.WEBSITE)
        self.key_tb.Text = info.LICENCE_KEY
        self.license_gb.Header = info.LICENSE_NAME
        self.license_tb.Text = info.LICENSE_TEXT
        self.web_btn.Content = "Open " + info.WEBSITE
        self.copy_btn.Click += self.copy
        self.web_btn.Click += self.web
        self.close_btn.Click += self.close

    def copy(self, sender, args):
        Clipboard.SetText(self.info.LICENSE_TEXT)
        self.copy_btn.Content = "Copied"

    def web(self, sender, args):
        Process.Start(self.info.WEBSITE)

    def close(self, sender, args):
        self.Close()


def _pick(title, button):
    """The only product, or the one picked from the list (None if cancelled)."""
    if len(PRODUCTS) == 1:
        return PRODUCTS[0]
    name = forms.SelectFromList.show([p.PRODUCT for p in PRODUCTS], title=title, button_name=button)
    return ([p for p in PRODUCTS if p.PRODUCT == name] or [None])[0]


def show(info=None, owner=None):
    """Show one product's About window (the only product, or the one picked from the list)."""
    info = info or _pick("About Netbuild", "About")
    if info is None:
        return None
    win = AboutWindow(info)
    if owner is not None:
        win.Owner = owner
    win.show_dialog()
    return win


def show_licence(info=None, owner=None):
    """Show one product's Licence window."""
    info = info or _pick("Netbuild licences", "Licence")
    if info is None:
        return None
    win = LicenceWindow(info)
    if owner is not None:
        win.Owner = owner
    win.show_dialog()
    return win
