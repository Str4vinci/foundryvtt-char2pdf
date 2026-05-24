# foundryvtt-char2pdf

`foundryvtt-char2pdf` converts Foundry VTT actor exports into interactive HTML sheets and printable PDFs.

Current support is for Foundry's `dnd5e` system, including D&D 2024-style character data. It is character-agnostic within that system: if you feed it a different `dnd5e` actor export, it should generate a sheet for that character too.

Current release: `v0.2.0`

## Themes

By default the generator picks a theme based on the actor's primary class. You can override with `--theme NAME` or pass a custom `#RRGGBB` accent.

Layout themes (typography + ornaments):

- `ledger`
- `gazette`
- `grimoire`

Curated palette themes (ledger layout + bespoke decoration):

- `dracula`
- `catppuccin` / `catppuccin-latte`
- `nord`
- `hearth`
- `solarized`
- `everforest`
- `gruvbox`
- `tokyo-night`
- `one-dark`
- `rose-pine` / `rose-pine-dawn`
- `kanagawa`

Class themes (ledger layout + class accent color):

- `artificer`, `barbarian`, `bard`, `cleric`, `druid`, `fighter`, `monk`, `paladin`, `ranger`, `rogue`, `sorcerer`, `warlock`, `wizard`

## Color modes

`--mode` sets the initial color mode of the generated HTML/PDF:

- `light` (default for layout/curated themes)
- `dark`
- `mono` — pure black-and-white, intended for grayscale printing

Every generated HTML sheet also includes an in-browser theme toggle that cycles `light` → `dark` → `mono` regardless of the initial mode.

## Requirements

- Python `3.10+`. Older Python versions are not supported because the generator uses modern type-hint syntax.
- No third-party Python packages; the generator uses only the Python standard library
- A Chromium-compatible browser for PDF export: Chromium, Google Chrome, or Microsoft Edge

HTML generation works with vanilla Python alone. PDF generation additionally requires a local Chromium-compatible browser. The generator looks for common Linux commands plus standard macOS and Windows Chrome/Edge install paths. If autodetection does not find your browser, pass it explicitly with `--print-browser /path/to/browser` or the legacy `--chromium /path/to/browser`. CI checks the minimum supported Python version, currently Python 3.10.

## Graphical interface (no command line)

If you would rather not use the terminal, launch the built-in web UI:

```bash
python3 generate_character_sheet.py --serve
```

This starts a small local server (bound to `127.0.0.1`, so nothing is exposed to your network) and opens your browser. From there you can:

- drop in or browse for your Foundry actor JSON,
- preview every theme live before choosing one,
- pick the color mode, paper size, and footer toggle,
- and download the generated HTML (plus a PDF, if a Chromium-compatible browser is installed).

Your character data never leaves your machine. Use `--port N` to change the port or `--no-browser` to skip auto-opening the browser. A double-click desktop build (no Python install needed) is planned — see Roadmap.

## Usage

From this directory:

```bash
python3 generate_character_sheet.py path/to/actor.json
```

Generate HTML + PDF using the actor's class theme:

```bash
python3 generate_character_sheet.py path/to/actor.json --pdf
```

Pick an explicit theme:

```bash
python3 generate_character_sheet.py path/to/actor.json --theme dracula --pdf
```

Use a custom accent color:

```bash
python3 generate_character_sheet.py path/to/actor.json --theme "#2A50A1" --pdf
```

Generate a pure black-and-white printable PDF:

```bash
python3 generate_character_sheet.py path/to/actor.json --mode mono --pdf
```

Generate for US Letter paper instead of A4:

```bash
python3 generate_character_sheet.py path/to/actor.json --paper letter --pdf
```

Omit the generated attribution/disclaimer footer:

```bash
python3 generate_character_sheet.py path/to/actor.json --no-footer
```

Render every registered theme in one run:

```bash
python3 generate_character_sheet.py path/to/actor.json --all-themes
```

Use a specific browser for PDF export:

```bash
python3 generate_character_sheet.py path/to/actor.json --pdf --print-browser /path/to/browser
```

Outputs are written to `output/` (override with `--output-dir`).

## Tests

Run the smoke tests with:

```bash
python3 -m unittest discover -s tests
```

## Notes

- Any Foundry `dnd5e` actor export should work; output filenames are derived from the actor name in the export.
- The HTML sheets include editable trackers and notes stored in browser `localStorage`.
- The exported sheet tries to emulate the official D&D character sheet layout.
- The PDF is rendered from the same HTML, so opening the HTML in Chromium and using Print produces the same layout.
- Light-mode print output is tuned to stay legible when a printer falls back to grayscale.
- Foundry exports do not always include every derived value, so the script computes core values such as proficiency bonus, skill bonuses, AC, initiative, and spell save DC from the actor data.

## Roadmap

Planned or wanted directions for the project. Contributions in any of these areas are welcome.

- **Cross-platform parity.** Make browser detection and PDF export work out of the box on Linux, macOS, and Windows without per-OS manual setup.
- **Semantic D&D resource trackers.** Foundry's `uses` data is not always a player-spendable resource. Trackers should appear for real limited-use class/subclass resources, such as Channel Divinity, Wild Shape, Bardic Inspiration, Rage, Second Wind, Action Surge, Focus/Ki points, Lay on Hands, Divine Sense, and Sorcery Points, while passive/source-granted features stay plain text.
- **More curated palettes.** Solarized, Everforest, Gruvbox, Tokyo Night, One Dark, Catppuccin Latte, Rosé Pine (+ Dawn), and Kanagawa now ship. Further popular schemes (Gruvbox Light, Ayu, Material, etc.) and more dedicated daytime light themes are still welcome.
- **More tabletop RPG systems.** Today the renderer only understands Foundry's `dnd5e` actor schema. Adding adapters for other systems (Pathfinder 2e, Call of Cthulhu, Shadowdark, etc.) would make the project useful beyond D&D.
- **Plug-and-play UI.** Shipped as a local web UI (`--serve`) — pick the actor JSON, theme, and output mode without touching the CLI. The remaining piece is a double-click desktop build (a frozen binary via PyInstaller, distributed per-OS) so users without Python installed can run it.
- **Theme preview gallery.** Shipped — the web UI renders a live preview of every theme before generating.
- **Per-system print tuning.** The generator supports A4 and Letter paper profiles today; future work should tune page density and content priorities per game system.

## Contributing

Issues and pull requests are welcome.

- Open an issue first for anything non-trivial so the approach can be agreed before code is written.
- Keep the generator dependency-free: the Python side must run on the standard library only. Browser/PDF tooling is the only external runtime requirement.
- Match the existing code style. Small, focused PRs are easier to review than sweeping changes.
- When fixing a rendering bug, include a sanitized actor JSON (or a minimal repro) that triggers it.
- Do not commit private actor exports, generated `output/`, or third-party copyrighted artwork.
- New themes should add an entry to `THEMES` in `generate_character_sheet.py` and follow the existing `light_accent` / `dark_accent` pattern.
- New TTRPG-system support should live behind a clear adapter boundary so the existing `dnd5e` path is not regressed.
