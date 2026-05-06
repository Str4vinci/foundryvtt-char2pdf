import json
import tempfile
import unittest
from pathlib import Path

import generate_character_sheet as sheet


MINIMAL_ACTOR = {
    "name": "CI Cleric",
    "type": "character",
    "system": {
        "abilities": {
            "str": {"value": 10},
            "dex": {"value": 14},
            "con": {"value": 12},
            "int": {"value": 10},
            "wis": {"value": 16},
            "cha": {"value": 8},
        },
        "attributes": {
            "ac": {"value": 13},
            "hp": {"value": 20, "max": 20, "temp": 0},
            "init": {"bonus": 0},
            "inspiration": False,
        },
        "details": {
            "xp": {"value": 900},
            "trait": "Curious",
            "ideal": "",
            "bond": "",
            "flaw": "",
            "biography": {"value": ""},
        },
        "skills": {},
        "tools": {},
        "traits": {
            "size": "med",
            "armorProf": {"value": ["lgt", "med", "shl"]},
            "weaponProf": {"value": ["sim"]},
            "languages": {"value": ["common"]},
        },
        "spells": {"spell1": {"max": 2, "value": 2}},
        "currency": {"gp": 5},
    },
    "items": [
        {"name": "Cleric", "type": "class", "system": {"levels": 3, "hd": {"denomination": "d8", "spent": 0}}},
        {"name": "Acolyte", "type": "background", "system": {}},
        {"name": "Human", "type": "race", "system": {"movement": {"walk": 30}, "senses": {"ranges": {}}}},
        {"name": "Mace", "type": "weapon", "system": {"equipped": True, "damage": {"base": {"number": 1, "denomination": 6, "types": ["bludgeoning"]}}, "range": {"value": 5, "units": "ft"}}},
        {"name": "Bless", "type": "spell", "system": {"level": 1, "preparation": {"mode": "prepared", "prepared": True}, "activities": {}, "properties": []}},
    ],
}


def write_actor(directory: Path) -> Path:
    actor_path = directory / "minimal-actor.json"
    actor_path.write_text(json.dumps(MINIMAL_ACTOR))
    return actor_path


class GenerationSmokeTests(unittest.TestCase):
    def test_default_sheet_contains_toolbar_footer_and_print_hp_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, theme="ledger")

            self.assertEqual(len(paths), 1)
            html = paths[0].read_text()
            self.assertIn('id="print-sheet"', html)
            self.assertIn('id="theme-sheet"', html)
            self.assertIn('class="sheet-footer"', html)
            self.assertIn("Made by Stravinci @ stravinci.pt", html)
            self.assertIn('data-print-value=""', html)

    def test_footer_can_be_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, theme="ledger", include_footer=False)

            html = paths[0].read_text()
            self.assertNotIn('class="sheet-footer"', html)
            self.assertNotIn("Made by Stravinci @ stravinci.pt", html)

    def test_letter_paper_profile_sets_print_page_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, theme="ledger", paper="letter")

            html = paths[0].read_text()
            self.assertIn("@page { size: Letter; margin: 0.35in; }", html)

    def test_all_themes_render_html_without_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, all_themes=True, mode="mono")

            self.assertEqual(len(paths), len(sheet.THEMES))
            for path in paths:
                html = path.read_text()
                self.assertIn("<!doctype html>", html)
                self.assertIn('data-theme", initial', html)

    def test_print_browser_detection_prefers_path_lookup(self) -> None:
        def fake_which(name: str) -> str | None:
            return "/usr/bin/google-chrome" if name == "google-chrome" else None

        self.assertEqual(sheet.detect_print_browser(which=fake_which), "/usr/bin/google-chrome")

    def test_print_browser_detection_falls_back_to_platform_paths(self) -> None:
        wanted = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

        def fake_exists(path: Path) -> bool:
            return path == wanted

        self.assertEqual(sheet.detect_print_browser(which=lambda _: None, exists=fake_exists), str(wanted))


if __name__ == "__main__":
    unittest.main()
