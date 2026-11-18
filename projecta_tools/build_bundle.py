# -*- coding: utf-8 -*-
"""
Build the offline ProjectA Tools package: dist/ProjectA_Tools_<YYMMDD>.zip

    python build_bundle.py [--python 3.14.7] [--out dist]

Runs on any OS with internet access (it cross-installs the Windows wheels). The zip holds
    runtime/   the official Windows embeddable Python (python.org) + the requirements.txt
               packages in runtime/Lib/site-packages -- no installer, no admin, no registry
    app/       projecta_launcher.py, projecta_helpers.py
    Netbuild/  the ProjectA issue scripts (same layout as C:\\SK\\OneDrive\\Netbuild)
    ProjectA Issue Report.bat, Install.bat, Uninstall.bat, README.md, VERSION.txt
so the target PC needs no internet, no Python and no admin rights.
"""
import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.join(HERE, "package")
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
# import name -> must exist in site-packages after the install
IMPORTS = ["pymupdf", "reportlab", "PIL", "win32com", "openpyxl", "pip"]


def download(url, dest):
    if os.path.exists(dest):
        return dest
    print("download %s" % url)
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    return dest


def crlf(path):
    """Batch files must have CRLF line endings."""
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(path, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", default="3.14.7", help="embeddable Python version (python.org)")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    a = ap.parse_args()
    major_minor = "".join(a.python.split(".")[:2])              # 3.14.7 -> 314

    build = os.path.join(HERE, "build")
    cache = os.path.join(build, "cache")
    stage = os.path.join(build, "ProjectA_Tools")
    os.makedirs(cache, exist_ok=True)
    shutil.rmtree(stage, ignore_errors=True)

    # 1. package files (launcher, scripts, batch files)
    shutil.copytree(PACKAGE, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy(os.path.join(HERE, "README.md"), stage)
    for root, _, files in os.walk(stage):
        for n in files:
            if n.lower().endswith(".bat"):
                crlf(os.path.join(root, n))

    # 2. embeddable Python
    runtime = os.path.join(stage, "runtime")
    embed = download(EMBED_URL.format(v=a.python), os.path.join(cache, "python-%s-embed-amd64.zip" % a.python))
    zipfile.ZipFile(embed).extractall(runtime)
    pth = os.path.join(runtime, "python%s._pth" % major_minor)
    if not os.path.isfile(pth):
        sys.exit("no %s in the embeddable zip" % os.path.basename(pth))
    with open(pth, "w", newline="\r\n") as f:                     # site-packages + site (for pywin32's .pth)
        f.write("python%s.zip\n.\nLib\\site-packages\nimport site\n" % major_minor)

    # 3. Windows wheels, cross-installed into runtime/Lib/site-packages
    site = os.path.join(runtime, "Lib", "site-packages")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
                           "--target", site, "--platform", "win_amd64", "--python-version", a.python.rsplit(".", 1)[0],
                           "--implementation", "cp", "--only-binary=:all:", "-r", os.path.join(HERE, "requirements.txt")])
    shutil.rmtree(os.path.join(site, "bin"), ignore_errors=True)   # posix entry-point stubs, unused on Windows
    for name in IMPORTS:
        if not (os.path.isdir(os.path.join(site, name)) or os.path.isfile(os.path.join(site, name + ".py"))):
            sys.exit("missing after install: %s" % name)
    installed = sorted(n[:-len(".dist-info")] for n in os.listdir(site) if n.endswith(".dist-info"))

    # 4. version stamp + zip
    stamp = dt.date.today().strftime("%y%m%d")
    with open(os.path.join(stage, "VERSION.txt"), "w", newline="\r\n") as f:
        f.write("ProjectA Tools %s\nPython %s (embeddable, win_amd64)\n%s\n" % (stamp, a.python, "\n".join(installed)))
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, "ProjectA_Tools_%s.zip" % stamp)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(stage):
            for n in sorted(files):
                p = os.path.join(root, n)
                z.write(p, os.path.join("ProjectA_Tools", os.path.relpath(p, stage)))
    print("packages: %s" % ", ".join(installed))
    print("wrote %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
