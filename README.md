# foundryvtt-char2pdf

`foundryvtt-char2pdf` converts Foundry VTT actor exports into interactive HTML sheets and printable PDFs.

Current support is for Foundry's `dnd5e` system, including D&D 2024-style character data. It is character-agnostic within that system: if you feed it a different `dnd5e` actor export, it should generate a sheet for that character too.

Current release: `v0.3.0`

## Screenshots

The same character — `Xano`, a level 3 Life Domain Cleric — rendered by the generator. Every sheet keeps a two-column, print-ready layout and ships with an in-browser `light` / `dark` / `mono` toggle.

<p align="center">
  <img src="docs/screenshots/sheet-cleric-light.png" alt="Xano character sheet rendered in the cleric theme, light mode" width="820"><br>
  <sub>Auto-selected class theme (Cleric) · light</sub>
</p>

A few of the built-in themes and color modes:

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/sheet-cleric-dark.png" alt="Cleric theme in dark mode" width="100%"><br>
      <sub>Class theme · dark</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/sheet-dracula-dark.png" alt="Dracula curated palette in dark mode" width="100%"><br>
      <sub>Dracula palette · dark</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshots/sheet-solarized-light.png" alt="Solarized curated palette in light mode" width="100%"><br>
      <sub>Solarized palette · light</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshots/sheet-cleric-mono.png" alt="Mono mode tuned for grayscale printing" width="100%"><br>
      <sub>Mono · tuned for grayscale printing</sub>
    </td>
  </tr>
</table>

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

<p align="center">
  <img src="docs/screenshots/web-ui.png" alt="The char2pdf local web UI with a sidebar of themes and a live sheet preview" width="900"><br>
  <sub>The local web UI — pick a theme from the sidebar and see a live preview before downloading</sub>
</p>

If you would rather not use the terminal, launch the built-in web UI:

```bash
python3 generate_character_sheet.py --serve
```

This starts a small local server (bound to `127.0.0.1`, so nothing is exposed to your network) and opens your browser. From there you can:

- drop in or browse for your Foundry actor JSON,
- preview every theme live before choosing one,
- pick the color mode, paper size, and footer toggle,
- and download the generated HTML (plus a PDF, if a Chromium-compatible browser is installed).

Your character data never leaves your machine. Use `--port N` to change the port or `--no-browser` to skip auto-opening the browser. A basic Windows executable build is available below; polished cross-platform desktop builds are still planned.

## Windows executable

A basic Windows executable build is available through the `Windows EXE` GitHub Actions workflow. Run the workflow, download the `char2pdf-windows-exe` artifact, unzip it, and double-click `char2pdf.exe`.

The executable starts the same local web UI as `--serve`, opens your browser, and writes generated sheets to an `output/` folder next to the executable. PDF export still requires a Chromium-compatible browser, such as Chrome or Edge, to be installed on the machine.

To build it locally on Windows:

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean char2pdf.spec
```

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

Force the game system instead of auto-detecting it (only `dnd5e` is supported today):

```bash
python3 generate_character_sheet.py path/to/actor.json --system dnd5e
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

- **Polished desktop app packaging.** A basic Windows PyInstaller build exists; remaining work includes validating the artifact on Windows, adding icon/version metadata, deciding whether to ship macOS/Linux builds, and considering signing or installer packaging. Build-time tooling only — the generator runtime stays standard-library-only.
- **Cross-platform PDF parity.** Make browser detection and PDF export work out of the box on Linux, macOS, and Windows without per-OS manual setup.
- **More curated palettes.** Building on the shipped set (Solarized, Gruvbox, Tokyo Night, Kanagawa, …), add further popular schemes (Gruvbox Light, Ayu, Material, etc.) and more dedicated daytime light themes.
- **More tabletop RPG systems.** A system-adapter boundary now separates system-specific schema/layout code from the shared framework (themes, color modes, paper profiles, PDF export, web UI). `dnd5e` is the first and currently only adapter. Adding another system (Pathfinder 2e, Call of Cthulhu, Shadowdark, etc.) means writing a new adapter — see [Adding a new game system](#adding-a-new-game-system).
- **Per-system print tuning.** A4 and US Letter profiles already ship; future work should tune page density and content priorities per game system.

## Contributing

Issues and pull requests are welcome.

- Open an issue first for anything non-trivial so the approach can be agreed before code is written.
- Keep the generator dependency-free: the Python side must run on the standard library only. Browser/PDF tooling is the only external runtime requirement.
- Match the existing code style. Small, focused PRs are easier to review than sweeping changes.
- When fixing a rendering bug, include a sanitized actor JSON (or a minimal repro) that triggers it.
- Do not commit private actor exports, generated `output/`, or third-party copyrighted artwork.
- New themes should add an entry to `THEMES` in `generate_character_sheet.py` and follow the existing `light_accent` / `dark_accent` pattern.
- New TTRPG-system support should live behind the system-adapter boundary so the existing `dnd5e` path is not regressed. See [Adding a new game system](#adding-a-new-game-system).

## Adding a new game system

The generator understands more than one Foundry game system through a small
**system-adapter boundary**, defined in `systems.py`. That module is the framework
side: it detects which system an actor export came from and looks up the adapter
that handles it, but it contains no knowledge of any specific system.

A system adapter is any object satisfying the `systems.SystemAdapter` protocol:

| Member | Responsibility |
| --- | --- |
| `system_id: str` | The Foundry `systemId` this adapter handles (e.g. `"dnd5e"`). Used for auto-detection and the `--system` flag, so it must match Foundry's real id. |
| `display_name: str` | Human-readable name for messages and docs. |
| `matches(actor) -> bool` | Recognize the actor's schema shape. Called only when the export carries no usable `_stats.systemId` hint. |
| `build_context(actor) -> dict` | Parse the raw actor export into a render-ready context dict. |
| `default_theme(actor) -> str \| None` | The theme to use when the caller did not request one. |
| `render(context, sheet_id, *, style, initial_theme, theme_palette, palette_decoration, include_footer, paper) -> str` | Render one themed sheet (a full HTML document). |

Everything else is **shared framework that every adapter inherits for free**: the
`THEMES` registry and palettes, the `light` / `dark` / `mono` color modes, the A4
and US Letter paper profiles, PDF export, browser detection, the local web UI, and
the browser `localStorage` trackers.

To add a system:

1. Write an adapter object implementing the protocol above. The `dnd5e` adapter
   (`Dnd5eAdapter` in `generate_character_sheet.py`) is the reference; a new
   system can live in its own module.
2. Register it with `systems.register(YourAdapter())` at import time.
3. Detection then works automatically: an export whose `_stats.systemId` matches
   your `system_id`, or whose schema your `matches()` recognizes, routes to your
   adapter. Unsupported exports raise a clear `systems.UnsupportedSystemError`
   naming the detected system in both the CLI and the web UI.
