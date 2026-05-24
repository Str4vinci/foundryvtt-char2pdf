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

## Open
- [ ] Package the web UI as a double-click desktop app (frozen binary via PyInstaller, built per-OS in GitHub Actions) so users without Python installed can run it. Build-time tooling only — the generator runtime stays standard-library-only.
- [ ] Validate PDF export on real macOS and Windows machines.
