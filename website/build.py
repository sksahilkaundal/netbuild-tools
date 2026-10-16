"""Build website/index.html from src/index.template.html.

Fills in the inline Netbuild logo (from brand/netbuild-logo.svg, wordmark recoloured to currentColor so it
follows the light / dark theme), the licence agreement (the repository's root LICENSE, copied byte for byte
to website/LICENSE.txt as well) and the contact address.

    python website/build.py            # write index.html + LICENSE.txt
    python website/build.py --check    # exit 1 if index.html / LICENSE.txt are out of date
"""
import html
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTACT_EMAIL = "info@skaec.com"      # the address shown in the Contact section


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def logo_svg():
    svg = read(os.path.join(ROOT, "brand", "netbuild-logo.svg")).strip()
    svg = re.sub(r"<title>.*?</title>", "", svg)
    svg = re.sub(r' width="[\d.]+" height="[\d.]+"', "", svg, count=1)
    svg = svg.replace('role="img" aria-label="Netbuild"', 'aria-hidden="true" focusable="false"')
    return svg.replace('fill="#212121"', 'fill="currentColor"')


def build():
    licence = read(os.path.join(ROOT, "LICENSE"))
    page = read(os.path.join(HERE, "src", "index.template.html"))
    page = (page.replace("{{LOGO}}", logo_svg())
                .replace("{{LICENSE}}", html.escape(licence.rstrip("\n"), quote=False))
                .replace("{{EMAIL}}", CONTACT_EMAIL))
    assert "{{" not in page, "unfilled placeholder"
    return {"index.html": page, "LICENSE.txt": licence}


def main(argv):
    out = build()
    stale = []
    for name, text in out.items():
        path = os.path.join(HERE, name)
        current = read(path) if os.path.exists(path) else None
        if current != text:
            stale.append(name)
            if "--check" not in argv:
                with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    if "--check" in argv:
        if stale:
            print("out of date: " + ", ".join(stale) + " -- run python website/build.py")
            return 1
        print("website up to date")
        return 0
    print("wrote " + (", ".join(stale) if stale else "nothing (up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
