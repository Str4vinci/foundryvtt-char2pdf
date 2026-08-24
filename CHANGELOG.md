# Changelog

All notable changes to `foundryvtt-char2pdf` are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries below were reconstructed from the commit history for releases that predate
this file.

> **Upgrading between versions:** the `localStorage` keys embedded in a generated
> sheet include the generator version (`foundry-sheet-v0-4-0-data:…`). Sheets you
> already generated keep working and keep their trackers and notes. But if you
> regenerate a character with a newer version, the new file starts with empty
> trackers, notes, and theme selection rather than inheriting what you had saved.

## [Unreleased]

### Security

- The local web UI now rejects requests whose `Host` header does not name the
  running server (defeats DNS rebinding against 127.0.0.1) and cross-site POSTs
  carrying a foreign `Origin` header (defeats drive-by requests that could
  replace or read the loaded character).
- Fight Club XML containing DTD/entity declarations is rejected before parsing
  instead of being expanded, closing an entity-expansion denial-of-service
  vector for uploaded (and CLI-loaded) files.
- Web UI request bodies are capped at 64 MiB; malformed or negative
  `Content-Length` headers now get a clean 400 instead of stalling or killing
  the request thread.
- `--to-fightclub` now strips control characters from exported text; they are
  legal in JSON but illegal in XML 1.0 and used to produce XML that no parser
  would re-read.

### Changed

- PDF export no longer passes `--allow-file-access-from-files` to the browser
  (the generated sheet is self-contained; file:// read access stays locked
  down). A failing or hung browser now raises a clear error that includes the
  browser's last stderr lines — surfaced as a soft warning in the web UI's PDF
  download panel and a clean `error:` line in the CLI instead of a traceback.
  Headless printing is bounded by a 120-second timeout.
- The desktop launcher reuses the web UI's argument parser instead of
  duplicating it; both now document their live defaults via `%(...)s`.
- CI now runs the test suite on Python 3.10–3.13 (plus 3.10 on Windows and
  macOS), lints with ruff (`ruff.toml`), compiles every Python module instead
  of a hand-maintained list, and drops a leftover "no tests yet" guard.
- Actor fields that are present but `null` (abilities, attributes, skills,
  spells, currency, items) no longer crash derivation; they are treated like
  missing fields. Output for valid exports is byte-identical (verified over all
  theme x mode x paper x footer combinations).
- The web UI's shared upload state is now lock-protected and rendered from
  atomic snapshots, so two browser tabs can no longer mix one actor's context
  with another's during concurrent preview/generate requests.
- Unexpected web UI failures now return a generic message with the traceback on
  the server console, instead of echoing raw exception text (which could contain
  absolute paths) to the browser. Download filenames are defensively sanitized
  for the `Content-Disposition` header.

### Fixed

- Formulas glued to a reference (e.g. `@abilities.int.mod-1`, `@prof-1`) no longer
  swallow the trailing `-N` as part of the reference name, which made resource
  pip counts silently evaluate to zero. Spaced formulas and hyphenated
  references (`@scale.bard.inspiration`) behave exactly as before.
- Malformed numeric formulas such as `--5` in an export's `uses.max` no longer
  crash the generator; they now resolve to `0` like other unparseable formulas.
- Characters whose primary class has no dedicated theme (e.g. homebrew classes)
  render with the neutral `ledger` layout instead of crashing with a traceback.
  An explicit `--theme not-a-theme` remains a loud error.

### Removed

- Three superseded page renderers and their helpers, left behind by earlier layout
  rewrites with no remaining callers: `render_sheet_v2` (and
  `ensure_official_sheet_assets`, the only code that shelled out to `pdftoppm`),
  `render_cards`, and `render_sheet` (and the `_SHEET_STYLE_*` stylesheets it selected
  between), plus the unused `normalize_hex_color`. This removes 1,783 lines from
  `generate_character_sheet.py` with no change to generated output. (#13)

## [0.4.0] - 2026-07-20

Fight Club 5e XML support in both directions, and the groundwork for game systems
beyond D&D 5e.

### Added

- **Fight Club 5e / Game Master 5 XML import** (`fightclub.py`). Lion's Den's mobile
  apps export a `<pc version="5">` XML document; the new standard-library-only
  importer converts it into the Foundry-shaped `dnd5e` actor dict the renderer already
  consumes, so every theme, color mode, paper profile, PDF export, and the web UI work
  unchanged. Detected automatically by `.xml` extension or `<pc>` content in both the
  CLI and the web UI. (#11)
- **Fight Club 5e XML export** via `--to-fightclub`, which writes `<name>.xml` to the
  output directory instead of rendering a sheet. Confirmed to import into the real
  Fight Club app. (#11)
- **A game-system adapter boundary** (`systems.py`): system detection from Foundry's
  `_stats.systemId` with a fallback to schema sniffing, a `SystemAdapter` protocol
  (`matches` / `build_context` / `default_theme` / `render`), and a registry. `dnd5e`
  is the first adapter. Unsupported exports now raise `UnsupportedSystemError` naming
  the detected system, instead of failing obscurely. Adds `--system` to force a
  system. (#9)
- **Five curated palettes** leaning toward daylight use: `gruvbox-light`, `ayu-light`,
  `ayu-mirage`, `material`, and `everforest-light`. Brings the theme count from 29 to 34. (#10)
- **A Windows executable build**: `char2pdf_desktop.py`, `char2pdf.spec`, a build-only
  `requirements-build.txt`, and a `Windows EXE` GitHub Actions workflow that uploads
  `char2pdf.exe`. It starts the same web UI as `--serve`.
- Sheet and web UI screenshots in the README.

### Changed

- **Print-browser detection covers more browsers and platforms.** `detect_print_browser()`
  now finds Brave, Vivaldi, Helium, and Arc alongside Chrome, Edge, and Chromium, and
  checks the per-user `~/Applications` directory on macOS in addition to the system-wide
  `/Applications`. Adds Brave's Windows install paths. This fixes PDF export failing out
  of the box on macOS machines whose only Chromium-compatible browser is one of the
  above. (#12)

### Known limitations

- Fight Club XML does not carry weapon damage dice, armor/weapon/language proficiency
  chips, or subclass, so those are blank or unfilled on an imported sheet. Ability
  scores are reconstructed from the base array plus the export's modifiers; untyped
  ASI bumps are applied to the class's spellcasting ability.
- Exporting to Fight Club XML is lossy in the same places: ability scores are written
  as base scores with no modifiers, weapon damage is omitted, items are not marked
  equipped, and features become plain-text entries.

## [0.3.0] - 2026-05-24

A way to use the generator without touching a terminal, and nine more palettes.

### Added

- **A local web UI**, launched with `--serve`. `webui.py` is a standard-library
  `http.server` bound to `127.0.0.1` that opens in your browser. Drop or browse to a
  Foundry actor JSON, preview every theme live as real sheets in lazy-loaded iframes,
  choose color mode / paper / footer, and download the HTML — plus a PDF when a
  Chromium-compatible browser is detected. The actor JSON is read client-side and
  POSTed as raw JSON, so the server needs no multipart parsing and character data
  never leaves the machine. Adds `--port` and `--no-browser`; the `actor_json`
  argument is now optional. (#8)
- **Nine curated palettes**: `solarized`, `everforest`, `gruvbox`, `tokyo-night`,
  `one-dark`, `catppuccin-latte`, `rose-pine`, `rose-pine-dawn`, and `kanagawa`. Each
  adds an accent quartet plus a decoration block with its own font pairing and
  background gradient. Brings the theme count from 20 to 29. (#8)

### Fixed

- **Web UI previews ignored the chosen color mode.** The preview URL passed the theme
  name as `?theme=`, but a generated sheet's own script reads `?theme=` as the
  authoritative color-mode override — so it saw a value like `kanagawa` and fell back
  to light. The palette name now rides `?palette=` and the color mode rides `?theme=`. (#8)
- **Web UI previews collapsed to one column.** The preview iframe was pinned to 820px,
  below the sheet's 960px breakpoint. Previews now render at a 1080px logical width and
  are CSS-scaled to fit the pane, so the two-column layout matches the CLI output. (#8)

## [0.2.0] - 2026-05-17

Usage trackers that reflect the actual rules, plus print and PDF fixes.

### Added

- `--paper a4|letter`, so print and PDF output can target US Letter as well as the
  default A4 profile. (#4)
- `--print-browser PATH` for pointing PDF export at a specific browser, alongside
  improved autodetection. `--chromium` is kept as a legacy alias. (#5)
- `--no-footer`, and the attribution/disclaimer footer it omits.
- A smoke test suite (`tests/test_smoke.py`) and a GitHub Actions CI workflow that
  compiles the modules and runs the tests against the minimum supported Python, 3.10. (#1, #2)

### Changed

- **Class-feature usage trackers are now semantic.** Foundry sets `uses.max` on many
  features that are not spendable resources — Spellcasting, domain spell lists, Magic
  Initiate, racial traits like Trance — which produced misleading "uses 1" suffixes
  next to passive entries. Clickable diamond pips are now limited to a whitelist of
  genuinely spendable resources (Channel Divinity, Wild Shape, Bardic Inspiration,
  Rage, Second Wind, Action Surge, Ki/Focus, Lay on Hands, Divine Sense, Sorcery
  Points, Mystic Arcanum, Arcane Recovery, and others); everything else loses the
  suffix. (#7)
- **Pool-style resources render as a number, not a row of pips.** Lay on Hands is a
  25-point pool at level 5 and Healing Light is 6d6 — a row of 25 diamonds was the
  wrong shape. Those now render as a compact `current / max` numeric input that
  persists in `localStorage`. (#7)
- Ability cards were redesigned: the short-code badge is gone, the full name is
  centered, and the signed modifier is large and bold above a small labelled score box.
  The accent rail was later thinned from 3px to 1px to match the separators used
  elsewhere. (#3, #7)
- The Spellcasting section is hidden for non-spellcasters, and Spellcasting and
  Equipment & Notes are forced onto fresh pages.
- Print density in feature list panels was compacted so feature-heavy characters fit
  on the overview page.

### Fixed

- **`uses.max` formulas were rendered raw or dropped.** Values like
  `max(1, @abilities.cha.mod)` and `@scale.<class>.<feature>` now resolve through a
  safe AST evaluator supporting `@prof`, ability modifiers, class scale values,
  arithmetic, and `max`/`min`/`floor`/`ceil`/`round`/`abs`. Action Surge resolves
  through its class ScaleValue advancement and Bardic Inspiration (d8) through the
  Charisma modifier, so both get the right pip count. (#7)
- **Scaling-die features appeared twice.** Foundry exports a separate feat per die
  tier (`bardic-inspiration`, `bardic-inspiration-d8`, …). Only the tier matching the
  character's level is shown now, emitted at the base entry's position so it stays
  above the panel truncation cap. (#7)
- Chromium 147 ignores `--print-to-pdf-no-header`, so exported PDFs carried a
  browser-injected header and footer. Switched to `--no-pdf-header-footer`.
- The HTML page title sat well inside its decorative corner bracket while the PDF
  rendered it correctly; screen padding now matches print.
- Corner brackets no longer overlap content in print, the Armor pill number is
  vertically centered, and the full "Passive Perception" label is restored.
- A compile error on Python 3.10, the minimum supported version.

## [0.1.0] - 2026-04-26

Initial release.

- Converts a Foundry VTT `dnd5e` actor export, including D&D 2024-style data, into an
  interactive two-column HTML sheet and a printable PDF. Character-agnostic within the
  system.
- 20 themes: three layouts (`ledger`, `gazette`, `grimoire`), four curated palettes
  (`dracula`, `catppuccin`, `nord`, `hearth`), and a class accent for each of the 13
  D&D classes. A theme is picked from the actor's primary class unless `--theme` gives
  a name or a `#RRGGBB` accent.
- Three color modes via `--mode`: `light`, `dark`, and `mono` for grayscale printing.
  Generated sheets carry an in-browser toggle that cycles between them.
- `--all-themes` renders one HTML file per registered theme.
- PDF export through a local Chromium-family browser, autodetected or given with
  `--chromium`.
- Editable trackers and notes in the HTML, persisted in browser `localStorage`.
- Derived values the export does not always carry — proficiency bonus, skill bonuses,
  AC, initiative, spell save DC — are computed from the actor data.
- Python 3.10+, standard library only.

[Unreleased]: https://github.com/Str4vinci/foundryvtt-char2pdf/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Str4vinci/foundryvtt-char2pdf/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Str4vinci/foundryvtt-char2pdf/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Str4vinci/foundryvtt-char2pdf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Str4vinci/foundryvtt-char2pdf/releases/tag/v0.1.0
