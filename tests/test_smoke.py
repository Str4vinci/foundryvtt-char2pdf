import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            html = paths[0].read_text(encoding="utf-8")
            self.assertIn('id="print-sheet"', html)
            self.assertIn('id="theme-sheet"', html)
            self.assertIn('class="sheet-footer"', html)
            self.assertIn("Made by Stravinci @ stravinci.pt", html)
            self.assertIn('data-print-value=""', html)

    def test_footer_can_be_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, theme="ledger", include_footer=False)

            html = paths[0].read_text(encoding="utf-8")
            self.assertNotIn('class="sheet-footer"', html)
            self.assertNotIn("Made by Stravinci @ stravinci.pt", html)

    def test_letter_paper_profile_sets_print_page_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, theme="ledger", paper="letter")

            html = paths[0].read_text(encoding="utf-8")
            self.assertIn("@page { size: Letter; margin: 0.35in; }", html)

    def test_all_themes_render_html_without_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path), tmp_path, all_themes=True, mode="mono")

            self.assertEqual(len(paths), len(sheet.THEMES))
            for path in paths:
                html = path.read_text(encoding="utf-8")
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

    def test_print_browser_detection_finds_other_chromium_browsers(self) -> None:
        wanted = Path("/Applications/Helium.app/Contents/MacOS/Helium")

        def fake_exists(path: Path) -> bool:
            return path == wanted

        self.assertEqual(sheet.detect_print_browser(which=lambda _: None, exists=fake_exists), str(wanted))

    def test_print_browser_detection_checks_user_applications_dir(self) -> None:
        wanted = Path.home() / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

        def fake_exists(path: Path) -> bool:
            return path == wanted

        self.assertEqual(sheet.detect_print_browser(which=lambda _: None, exists=fake_exists), str(wanted))


class NullFieldRobustnessTests(unittest.TestCase):
    """A field present but null must be tolerated like a missing one."""

    NULL_FIELD_ACTOR = {
        "name": "Null Carrier",
        "type": "character",
        "_stats": {"systemId": "dnd5e"},
        "system": {
            "abilities": {"str": None, "dex": {"value": 14}},
            "attributes": None,
            "details": None,
            "skills": None,
            "tools": None,
            "traits": None,
            "spells": {"spell1": None},
            "currency": None,
        },
        "items": None,
    }

    def test_sheet_context_survives_null_fields(self) -> None:
        context = sheet.sheet_context(self.NULL_FIELD_ACTOR)
        self.assertEqual(context["level"], 0)
        # A null ability value coerces to 0 exactly like a missing one.
        self.assertEqual([row["score"] for row in context["ability_rows"]][0], 0)

    def test_null_field_actor_renders_with_ledger_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actor_path = tmp_path / "nulls.json"
            actor_path.write_text(json.dumps(self.NULL_FIELD_ACTOR))
            paths = sheet.write_output(actor_path, tmp_path)
            self.assertEqual(paths[0].name, "null-carrier-character-sheet-ledger.html")
            self.assertIn("<!doctype html>", paths[0].read_text(encoding="utf-8"))


class PdfExportTests(unittest.TestCase):
    def test_export_command_is_locked_down_and_timeout_bounded(self) -> None:
        recorded = {}

        def fake_run(command, **kwargs):
            recorded["command"] = list(command)
            recorded["timeout"] = kwargs.get("timeout")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch.object(sheet.subprocess, "run", fake_run):
            sheet.render_pdf(Path("sheet.html"), Path("sheet.pdf"), "chrome", mode="dark")

        self.assertNotIn("--allow-file-access-from-files", recorded["command"])
        self.assertEqual(recorded["timeout"], sheet.PDF_EXPORT_TIMEOUT_SECONDS)

    def test_browser_failure_raises_with_stderr_tail(self) -> None:
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="ERROR:gpu_init failed\nretrying")

        with mock.patch.object(sheet.subprocess, "run", fake_run):
            with self.assertRaises(sheet.PdfExportError) as ctx:
                sheet.render_pdf(Path("sheet.html"), Path("sheet.pdf"), "chrome")
        self.assertIn("status 1", str(ctx.exception))
        self.assertIn("ERROR:gpu_init failed", str(ctx.exception))

    def test_hung_browser_raises_friendly_timeout_error(self) -> None:
        def fake_run(command, **kwargs):
            raise subprocess.TimeoutExpired(cmd=command, timeout=120)

        with mock.patch.object(sheet.subprocess, "run", fake_run):
            with self.assertRaises(sheet.PdfExportError) as ctx:
                sheet.render_pdf(Path("sheet.html"), Path("sheet.pdf"), "chrome")
        self.assertIn("did not finish printing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
