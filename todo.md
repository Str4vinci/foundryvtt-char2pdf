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

## Open

- [ ] Check whether a separate Letter print profile is worth supporting in addition to the current A4-first layout.
- [ ] Add a small plug-and-play interface so users can pick the actor JSON file, style/theme, and output mode, then run generation without using the CLI.
- [ ] In that interface, show a visual preview for each style/theme so users can see what `ledger`, `codex`, `mono`, etc. look like before generating.
- [ ] Validate browser detection and PDF export setup on real macOS and Windows machines.
- [ ] The stats (wis, con, etc) should have a bit more emphasis. Not sure how. Maybe also center to the middle as well. Or a box like level has (but smaller to not change the layout size too much).
