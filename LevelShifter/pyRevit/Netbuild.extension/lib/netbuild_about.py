"""About screens for the Netbuild products in this extension (pyRevit, IronPython 2.7).

Every Netbuild product ships an ``about`` module (PRODUCT, VERSION, COPYRIGHT, WEBSITE, DESCRIPTION,
FEATURES, requirements_text(), LICENSE_NAME, LICENSE_TEXT, about_text()) and is listed in PRODUCTS.
The ribbon's About button and each tool's own About button show it.
"""

from pyrevit import forms

from System.Diagnostics import Process
from System.Windows import Clipboard

from level_shift import about as level_shift_about
import levelshift_ui as ui

PRODUCTS = [level_shift_about]


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
        self.license_gb.Header = "License -- " + info.LICENSE_NAME
        self.license_tb.Text = info.LICENSE_TEXT
        self.web_btn.Content = "Open " + info.WEBSITE
        self.copy_btn.Click += self.copy
        self.web_btn.Click += self.web
        self.close_btn.Click += self.close

    def copy(self, sender, args):
        Clipboard.SetText(self.info.about_text())
        self.copy_btn.Content = "Copied"

    def web(self, sender, args):
        Process.Start(self.info.WEBSITE)

    def close(self, sender, args):
        self.Close()


def show(info=None, owner=None):
    """Show one product's About window (the only product, or the one picked from the list)."""
    if info is None:
        if len(PRODUCTS) == 1:
            info = PRODUCTS[0]
        else:
            name = forms.SelectFromList.show([p.PRODUCT for p in PRODUCTS], title="About Netbuild",
                                             button_name="About")
            info = ([p for p in PRODUCTS if p.PRODUCT == name] or [None])[0]
            if info is None:
                return None
    win = AboutWindow(info)
    if owner is not None:
        win.Owner = owner
    win.show_dialog()
    return win
