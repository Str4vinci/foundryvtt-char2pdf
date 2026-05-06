import tempfile
import unittest
from pathlib import Path

import generate_character_sheet as sheet


ROOT = Path(__file__).resolve().parents[1]
ACTOR = ROOT / "fvtt-Actor-xano-miJSPjh0oyGzrgSD.json"


class GenerationSmokeTests(unittest.TestCase):
    def test_default_sheet_contains_toolbar_footer_and_print_hp_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = sheet.write_output(ACTOR, Path(tmp), theme="ledger")

            self.assertEqual(len(paths), 1)
            html = paths[0].read_text()
            self.assertIn('id="print-sheet"', html)
            self.assertIn('id="theme-sheet"', html)
            self.assertIn('class="sheet-footer"', html)
            self.assertIn("Made by Stravinci @ stravinci.pt", html)
            self.assertIn('data-print-value=""', html)

    def test_footer_can_be_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = sheet.write_output(ACTOR, Path(tmp), theme="ledger", include_footer=False)

            html = paths[0].read_text()
            self.assertNotIn('class="sheet-footer"', html)
            self.assertNotIn("Made by Stravinci @ stravinci.pt", html)

    def test_all_themes_render_html_without_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = sheet.write_output(ACTOR, Path(tmp), all_themes=True, mode="mono")

            self.assertEqual(len(paths), len(sheet.THEMES))
            for path in paths:
                html = path.read_text()
                self.assertIn("<!doctype html>", html)
                self.assertIn('data-theme", initial', html)


if __name__ == "__main__":
    unittest.main()
