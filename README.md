# foundryvtt-char2pdf

`foundryvtt-char2pdf` converts Foundry VTT actor exports into interactive HTML sheets and printable PDFs.

Current support is for Foundry's `dnd5e` system, including D&D 2024-style character data. It is character-agnostic within that system: if you feed it a different `dnd5e` actor export, it should generate a sheet for that character too.

Current release: `v0.1.0`

## Themes

By default the generator picks a theme based on the actor's primary class. You can override with `--theme NAME` or pass a custom `#RRGGBB` accent.

Layout themes (typography + ornaments):

- `ledger`
- `gazette`
- `grimoire`

Curated palette themes (ledger layout + bespoke decoration):

- `dracula`
- `catppuccin`
- `nord`
- `hearth`

Class themes (ledger layout + class accent color):

- `artificer`, `barbarian`, `bard`, `cleric`, `druid`, `fighter`, `monk`, `paladin`, `ranger`, `rogue`, `sorcerer`, `warlock`, `wizard`

## Color modes

`--mode` sets the initial color mode of the generated HTML/PDF:

- `light` (default for layout/curated themes)
- `dark`
- `mono` — pure black-and-white, intended for grayscale printing

Every generated HTML sheet also includes an in-browser theme toggle that cycles `light` → `dark` → `mono` regardless of the initial mode.

## Requirements

- Python `3.10+`
- No third-party Python packages; the generator uses only the Python standard library
- A Chromium-family browser for PDF export: `chromium`, `chromium-browser`, `google-chrome`, or `google-chrome-stable`

HTML generation works with vanilla Python alone. PDF generation additionally requires a local Chromium-compatible browser. If autodetection does not find your browser, pass it explicitly with `--chromium /path/to/browser`.

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

Omit the generated attribution/disclaimer footer:

```bash
python3 generate_character_sheet.py path/to/actor.json --no-footer
```

Render every registered theme in one run:

```bash
python3 generate_character_sheet.py path/to/actor.json --all-themes
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
- **More curated palettes.** Popular color schemes such as Everforest, Tokyo Night, Gruvbox, Solarized, and One Dark, as well as dedicated light themes for daytime use.
- **More tabletop RPG systems.** Today the renderer only understands Foundry's `dnd5e` actor schema. Adding adapters for other systems (Pathfinder 2e, Call of Cthulhu, Shadowdark, etc.) would make the project useful beyond D&D.
- **Plug-and-play UI.** A small graphical front-end so users can pick the actor JSON, theme, and output mode without touching the CLI.
- **Theme preview gallery.** Visual previews of every theme/mode combination so users can choose before generating.
- **Per-system print profiles.** Optional Letter layout in addition to the current A4-first design.

## Contributing

Issues and pull requests are welcome.

- Open an issue first for anything non-trivial so the approach can be agreed before code is written.
- Keep the generator dependency-free: the Python side must run on the standard library only. Browser/PDF tooling is the only external runtime requirement.
- Match the existing code style. Small, focused PRs are easier to review than sweeping changes.
- When fixing a rendering bug, include a sanitized actor JSON (or a minimal repro) that triggers it.
- Do not commit private actor exports, generated `output/`, or third-party copyrighted artwork.
- New themes should add an entry to `THEMES` in `generate_character_sheet.py` and follow the existing `light_accent` / `dark_accent` pattern.
- New TTRPG-system support should live behind a clear adapter boundary so the existing `dnd5e` path is not regressed.
