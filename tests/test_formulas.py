import json
import tempfile
import unittest
from pathlib import Path

import generate_character_sheet as sheet


class ResolveFormulaTests(unittest.TestCase):
    def test_glued_subtraction_after_reference(self) -> None:
        # Foundry writes "@abilities.int.mod-1" without spaces; the "-1" is
        # arithmetic, not part of the reference name.
        self.assertEqual(sheet.resolve_formula("@abilities.int.mod-1", {"@abilities.int.mod": 3}), 2)
        self.assertEqual(sheet.resolve_formula("@prof-1", {"@prof": 2}), 1)

    def test_spaced_subtraction_still_works(self) -> None:
        self.assertEqual(sheet.resolve_formula("@abilities.int.mod - 1", {"@abilities.int.mod": 3}), 2)

    def test_hyphenated_references_are_not_split(self) -> None:
        self.assertEqual(
            sheet.resolve_formula("@scale.bard.inspiration", {"@scale.bard.inspiration": 5}),
            5,
        )
        self.assertEqual(
            sheet.resolve_formula("@scale.x.my-feature-1", {"@scale.x.my-feature-1": 4}),
            4,
        )
        self.assertEqual(
            sheet.resolve_formula("@scale.x.my-feature-1", {"@scale.x.my-feature": 4}),
            3,
        )

    def test_unknown_reference_resolves_to_zero(self) -> None:
        self.assertEqual(sheet.resolve_formula("@nope.mod-1", {}), 0)

    def test_malformed_numbers_do_not_crash(self) -> None:
        for bad in ("--5", "-x", "1e400"):
            with self.subTest(formula=bad):
                self.assertEqual(sheet.resolve_formula(bad, {}), 0)

    def test_negative_and_large_integers_are_preserved(self) -> None:
        self.assertEqual(sheet.resolve_formula("-5", {}), -5)
        big = "9" * 40
        self.assertEqual(sheet.resolve_formula(big, {}), int(big))


HOMEBREW_ACTOR = {
    "name": "Blood Hunter",
    "type": "character",
    "_stats": {"systemId": "dnd5e"},
    "items": [
        {"name": "Blood Hunter", "type": "class", "system": {"levels": 3, "identifier": "blood-hunter"}}
    ],
}


def write_actor(directory: Path, actor: dict) -> Path:
    actor_path = directory / "actor.json"
    actor_path.write_text(json.dumps(actor))
    return actor_path


class UnknownClassThemeTests(unittest.TestCase):
    def test_homebrew_class_falls_back_to_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path, HOMEBREW_ACTOR), tmp_path)

            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].name, "blood-hunter-character-sheet-ledger.html")
            html = paths[0].read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", html)

    def test_classless_actor_still_falls_back_to_ledger(self) -> None:
        actor = {"name": "Mystery", "type": "character", "_stats": {"systemId": "dnd5e"}}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            paths = sheet.write_output(write_actor(tmp_path, actor), tmp_path)

            self.assertEqual(paths[0].name, "mystery-character-sheet-ledger.html")

    def test_explicit_bad_theme_is_still_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(ValueError):
                sheet.write_output(write_actor(tmp_path, HOMEBREW_ACTOR), tmp_path, theme="not-a-theme")


if __name__ == "__main__":
    unittest.main()
