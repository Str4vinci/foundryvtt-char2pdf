"""Download the open-licensed fonts the sheet themes use (dev tool, not needed at runtime).

Fetches Latin-subset WOFF2 files and license texts from Fontsource and writes
them, plus a ``fonts.json`` manifest, to the output directory (default:
``fonts/`` next to the generator). The generator embeds the faces a theme
needs into each sheet, so sheets and PDFs look the same on every machine
without any network access.

    python tools/fetch_fonts.py [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

API = "https://api.fontsource.org/v1/fonts/{id}"
VARIABLE_URL = "https://cdn.jsdelivr.net/fontsource/fonts/{id}:vf@latest/latin-wght-{style}.woff2"
STATIC_URL = "https://cdn.jsdelivr.net/fontsource/fonts/{id}@latest/latin-{weight}-{style}.woff2"
LICENSE_URL = "https://cdn.jsdelivr.net/npm/@fontsource/{id}@latest/LICENSE"
ALLOWED_LICENSES = {"OFL-1.1", "Apache-2.0"}
STATIC_WEIGHTS = (400, 700)

# Family name -> whether italics are needed. Body text and subtitles use the
# serif role, which is the only one set in italic.
FAMILIES: dict[str, bool] = {
    # Layouts
    "Source Serif 4": True, "Inter": False, "IBM Plex Mono": False,
    "EB Garamond": True, "Playfair Display": False, "Source Sans 3": False,
    "Cormorant Garamond": True, "Cinzel": False,
    # Curated palettes
    "Literata": True, "Space Grotesk": False, "IBM Plex Sans": False,
    "Fraunces": True, "Sora": False,
    "IBM Plex Sans Condensed": False,
    "Bitter": True, "Quicksand": False, "Mulish": False,
    "Zilla Slab": True, "Work Sans": False,
    "Spectral": True, "Chakra Petch": False,
    "Newsreader": True, "Manrope": False,
    "Marcellus": False, "Jost": False,
    "Shippori Mincho": True, "Zen Old Mincho": False, "Zen Kaku Gothic New": False,
    "Rubik": False,
    "Roboto Slab": True, "Roboto Condensed": False, "Roboto": False,
}


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "char2pdf-fetch-fonts"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _font_id(family: str) -> str:
    return family.lower().replace(" ", "-")


def fetch_family(family: str, want_italic: bool, output_dir: Path) -> dict:
    font_id = _font_id(family)
    meta = json.loads(_fetch(API.format(id=font_id)))
    if meta["license"] not in ALLOWED_LICENSES:
        raise SystemExit(f"{family}: license {meta['license']} is not in {sorted(ALLOWED_LICENSES)}")
    styles = ["normal"] + (["italic"] if want_italic and "italic" in meta["styles"] else [])
    faces = []
    for style in styles:
        if meta["variable"]:
            weights = [f"{min(meta['weights'])} {max(meta['weights'])}"]
            urls = [VARIABLE_URL.format(id=font_id, style=style)]
        else:
            # Nearest available static weight to each one the sheet uses.
            picked = sorted({min(meta["weights"], key=lambda w: abs(w - target)) for target in STATIC_WEIGHTS})
            weights = [str(w) for w in picked]
            urls = [STATIC_URL.format(id=font_id, weight=w, style=style) for w in picked]
        for weight, url in zip(weights, urls, strict=True):
            data = _fetch(url)
            if data[:4] != b"wOF2":
                raise SystemExit(f"{family}: {url} is not a WOFF2 file")
            name = f"{font_id}-{weight.replace(' ', '-')}-{style}.woff2"
            (output_dir / name).write_bytes(data)
            faces.append({"file": name, "style": style, "weight": weight})
    (output_dir / "licenses").mkdir(exist_ok=True)
    (output_dir / "licenses" / f"{font_id}.txt").write_bytes(_fetch(LICENSE_URL.format(id=font_id)))
    return {"license": meta["license"], "faces": faces}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent.parent / "fonts")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for family, want_italic in FAMILIES.items():
        manifest[family] = fetch_family(family, want_italic, args.output_dir)
        print(f"{family}: {len(manifest[family]['faces'])} face(s), {manifest[family]['license']}")
    (args.output_dir / "fonts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
