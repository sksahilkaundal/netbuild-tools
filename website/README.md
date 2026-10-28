# skaec.com -- Netbuild website

Static single-page site: `index.html` + `assets/` + `LICENSE.txt`. No build tools, no tracking, no cookies.
Fonts (Archivo, IBM Plex Mono) load from Google Fonts with Helvetica / Arial / Consolas fallbacks.

- Edit **`src/index.template.html`**, then run `python website/build.py`. It fills in the inline logo
  (`brand/netbuild-logo.svg`), the full licence agreement and `LICENSE.txt` (both from the root `LICENSE`, so
  they never drift) and the contact address (`CONTACT_EMAIL` in `build.py`).
- `python website/build.py --check` exits 1 when `index.html` / `LICENSE.txt` are out of date.
- Deploy: upload the `website/` folder (without `src/`, `build.py`, `README.md`) to any static host
  (GitHub Pages, Cloudflare Pages, Netlify, cPanel) and point skaec.com at it.

Product facts on the page (versions, Revit versions, requirements, licence-key status) are taken from each
product's `about.py` / README. Update the page when a product's version or requirements change.
