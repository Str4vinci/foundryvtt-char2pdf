# Sheet Todo

## Done

- [x] Generate both light and dark theme. Light remains the print-first mode.
- [x] Generate more styles. `ledger`, `gazette`, `codex`, `dracula`, `catppuccin`, and `nord` now render with distinct palettes/tracker silhouettes.
- [x] Proficient armors in dark mode use readable light text.
- [x] Spell slots are clickable and persist.
- [x] Spell slot numbers update as slots are checked off.
- [x] Spells now take their own page; equipment and notes moved to a following page.
- [x] Coin purse moved to the main page near the ability/training area.
- [x] Hit points stack vertically as `Current`, `Temp`, `Max`.
- [x] Armor value is vertically centered.
- [x] Level badge is square instead of hexagonal.
- [x] Clicked diamonds now have a stronger visual filled state, including death saves.
- [x] Removed the extra top reference rectangle/source strip.
- [x] Inspiration marker is smaller.
- [x] Languages stay in `Training & Senses`; no duplicate languages section on later pages.
- [x] Removed `Wisdom casting · inventory ... carry weight ...` and `Reference page` from the spellcasting page.
- [x] Prepared spells now use the full page width instead of sharing with equipment.
- [x] A4 print layout was reworked and validated through Chromium PDF output.
- [x] Removed top-right page labels such as `Character Overview` and `Field Journal`.
- [x] Ability skill rows align with the saving throw row.
- [x] Fixed the codex decorative bottom rail so it no longer sticks while scrolling.
- [x] Removed the old `vx` naming from the active generated sheet output; the current renderer now emits neutral `sheet-*` classes/IDs.
- [x] Removed leftover internal `v3` naming from the page-generation code; the internal renderer/CSS/IDs now use a neutral `dnd-layout-*` namespace.
- [x] Made a theme for each D&D Class: Artificer, Barbarian, Bard, Cleric, Druid, Fighter, Monk, Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard.
- [x] Class features with uses show clickable diamond trackers (same as spell slots / death saves).
- [x] Shield value is centered.
- [x] Speed displays with "ft" suffix.
- [x] Added `@stravinci.pt` attribution at the top-left corner of the character name rectangle.
- [x] Temp HP and spent hit dice render blank when their exported value is zero, while current HP stays available in HTML and blanks for print/PDF.
- [x] Added a footer with Stravinci attribution and an unofficial fan-made sheet disclaimer, plus `--no-footer` to omit it.
- [x] Reworked the generated HTML toolbar buttons so they wrap instead of cutting off.
- [x] Expanded browser detection with common macOS/Windows Chrome and Edge paths.
- [x] Added smoke tests for HTML generation, footer toggling, and all-theme rendering.
- [x] Added `--paper a4|letter` so PDF/print output can target US Letter in addition to the default A4 profile.
- [x] Added a clearer `--print-browser` PDF export option and smoke coverage for browser autodetection fallbacks.
- [x] Gave ability stats more visual emphasis with boxed ability abbreviations/scores and an accent rail.
- [x] Thinned the vertical accent rail on each ability card so it matches the 1px separators used elsewhere on the sheet.
- [x] Bolded the written-out ability names (Strength, Dexterity, Constitution, Intelligence, Wisdom, Charisma).
- [x] Made class-feature usage trackers semantic. Clickable diamond pips now render only for whitelisted spendable D&D resources (Channel Divinity, Wild Shape, Bardic Inspiration, Rage, Second Wind, Action Surge, Ki/Focus, Lay on Hands, Divine Sense, Sorcery Points, Mystic Arcanum, Lucky, Healing Light, Tomb of Levistus, Arcane Recovery, Breath Weapon, Relentless Endurance, etc.). Misleading "uses N" text on passive/source-granted features (Spellcasting, domain spell lists, Magic Initiate, racial traits like Trance / Elven Lineage) is suppressed.
- [x] Tightened the HTML page-title padding so the title hugs the decorative corner bracket the way the PDF already does.
- [x] Resolved Foundry formula `uses.max` values (`@prof`, `@abilities.X.mod`, `@scale.<class>.<feature>`, plus arithmetic and `max`/`min`/`floor`/`ceil`/`round`/`abs`) via a small safe AST evaluator. Action Surge now resolves through the class ScaleValue advancement and Bardic Inspiration (d8) resolves through the Cha modifier, so both get the right pip counts.
- [x] Collapsed scaling-die feat variants (e.g. `bardic-inspiration` + `bardic-inspiration-d8`) so the sheet only shows the variant matching the character's current level. The kept variant takes the position of the base entry to avoid being pushed past the panel's truncation cap.
- [x] Added a per-resource render override (`POOL_RESOURCE_IDS`) so pool-style resources like Lay on Hands (hp pool) and Healing Light (d6 pool) render as a small `current / max` numeric input instead of a long row of pips. New resources can be added to the set as they come up.

- [x] Added a local web UI (`--serve`, `webui.py`): drop or browse an actor JSON, see a live per-theme preview gallery, pick color mode / paper / footer, then download the HTML (and PDF if a browser is present). Bound to `127.0.0.1`; character data stays local. Reuses the generator's render/PDF functions and is covered by `tests/test_webui.py`.
- [x] Added a basic Windows PyInstaller path: `char2pdf_desktop.py`, `char2pdf.spec`, build-only `requirements-build.txt`, and a `Windows EXE` GitHub Actions workflow that uploads `char2pdf.exe`.
- [x] Added a daytime-leaning batch of curated palettes: `gruvbox-light`, `ayu-light`, `ayu-mirage`, `material`, and `everforest-light`. Each follows the existing `light_accent` / `dark_accent` pattern (official scheme hexes) with a bespoke decoration, and is picked up automatically by the CLI `--theme` help, the web UI gallery, and the all-themes render. Latte, Mocha, and Rosé Pine Dawn were already covered by the existing `catppuccin-latte`, `catppuccin`, and `rose-pine-dawn` themes.
- [x] Introduced a system-adapter boundary (`systems.py`): system detection (via Foundry `_stats.systemId`/flags hint, falling back to schema sniffing), a `SystemAdapter` protocol (`matches` / `build_context` / `default_theme` / `render`), and a registry. `dnd5e` is the first adapter (`Dnd5eAdapter`, delegating to the existing schema/layout code); output is byte-identical to before. Unsupported exports raise a clear `UnsupportedSystemError` (named system, exit code 2 in the CLI, banner in the web UI). Added `--system` to force a system, plus `tests/test_systems.py`. No second system implemented yet — the boundary is the deliverable.

## Open
- [ ] Implement a second game system (e.g. Pathfinder 2e) against the new adapter boundary once a sanitized fixture export is available.
- [ ] Polish desktop app packaging beyond the basic Windows executable: validate the artifact on Windows, decide on icon/version metadata, add macOS/Linux builds if wanted, and consider signing/installer packaging.
- [ ] Validate PDF export on a real Windows machine.

## Recently done
- [x] Broadened print-browser detection to cover more Chromium-based browsers (Brave, Vivaldi, Helium, Arc) alongside Chrome/Edge/Chromium, and to also check the per-user `~/Applications` directory on macOS. Validated end-to-end PDF export on real macOS (via Helium) across all 13 real `dnd5e` exports (warlock/cleric/barbarian/bard/rogue/paladin/fighter/monk/artificer/druid). Added detection tests.
- [x] Added a Foundry → Fight Club 5e XML **exporter** (`fightclub.to_xml`, the inverse of `parse_actor`) exposed as `--to-fightclub`, which writes a `<name>.xml` to the output dir instead of rendering a sheet. Confirmed to import into the real Fight Club app. Best-effort/lossy: final ability scores are written as base scores with no mods (so totals stay correct without double-counting), weapon damage is omitted, items are not marked equipped, and features export as plain text. Covered by round-trip tests (`to_xml` → `parse_actor` preserves abilities, saves, skills, class/level, slots, spells, and still renders).
- [x] Added a Fight Club 5e / Game Master 5 XML import path (`fightclub.py`). Lion's Den's mobile apps export a `<pc version="5">` XML document; the new stdlib-only importer converts it into the Foundry-shaped `dnd5e` actor dict the existing renderer already consumes, so every theme, color mode, paper profile, PDF export, and the web UI work unchanged. Decoded the format (ability CSV + `<mod>` bonuses, save/skill proficiency codes, alphabetical skill/school indices, `<slots>` per-level slots, `<tracker>` feature uses) and confirmed it via the export's internal consistency and known D&D 5e rules (e.g. racial ability bonuses and named skill grants land on the expected indices); the decoded values produce a coherent character. Detection is automatic (`.xml` extension or `<pc>` content) in both the CLI (`load_actor_file`) and web UI (`_handle_actor`). Added a sanitized fixture (`tests/fixtures/fightclub_sample.xml`) and `tests/test_fightclub.py`. Known gaps (documented in the README): weapon attack rows, armor/weapon/language proficiency chips, and subclass are not present in the export; untyped ASI ability bumps are applied to the class casting stat.
