import unittest
from pathlib import Path

import fightclub
import generate_character_sheet as sheet
import systems

FIXTURE = Path(__file__).parent / "fixtures" / "fightclub_sample.xml"


class FightClubImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.xml = FIXTURE.read_text(encoding="utf-8")
        cls.actor = fightclub.parse_actor(cls.xml)

    def test_looks_like_fightclub(self) -> None:
        self.assertTrue(fightclub.looks_like_fightclub(self.xml))
        self.assertTrue(fightclub.looks_like_fightclub("  \n<?xml version='1.0'?><pc><character/></pc>"))
        self.assertFalse(fightclub.looks_like_fightclub('{"name": "Foundry actor"}'))

    def test_rejects_non_fightclub_xml(self) -> None:
        with self.assertRaises(fightclub.FightClubParseError):
            fightclub.parse_actor("<html><body>not a character</body></html>")

    def test_identity(self) -> None:
        self.assertEqual(self.actor["name"], "Test Cleric")
        self.assertEqual(self.actor["type"], "character")

    def test_ability_scores_apply_typed_mods(self) -> None:
        scores = {code: v["value"] for code, v in self.actor["system"]["abilities"].items()}
        self.assertEqual(scores, {"str": 10, "dex": 12, "con": 15, "int": 13, "wis": 18, "cha": 8})

    def test_untyped_asi_goes_to_spellcasting_ability(self) -> None:
        # Two untyped +1 ability mods should land on the class's casting stat.
        xml = self.xml.replace(
            "<spell><name>Sacred Flame</name>",
            '<mod><category>1</category><value>1</value></mod>'
            '<mod><category>1</category><value>1</value></mod>'
            "<spell><name>Sacred Flame</name>",
        )
        actor = fightclub.parse_actor(xml)
        # Casting ability is WIS (spellAbility=4): 18 + 2 = 20.
        self.assertEqual(actor["system"]["abilities"]["wis"]["value"], 20)

    def test_saving_throw_proficiencies(self) -> None:
        profs = {c for c, v in self.actor["system"]["abilities"].items() if v["proficient"]}
        self.assertEqual(profs, {"wis", "cha"})

    def test_skill_proficiencies(self) -> None:
        profs = {c for c, v in self.actor["system"]["skills"].items() if v["value"]}
        self.assertEqual(profs, {"ins", "rel", "med", "per"})

    def test_class_and_spellcasting(self) -> None:
        cls = next(i for i in self.actor["items"] if i["type"] == "class")
        self.assertEqual(cls["name"], "Cleric")
        self.assertEqual(cls["system"]["levels"], 3)
        self.assertEqual(cls["system"]["spellcasting"]["ability"], "wis")
        self.assertEqual(self.actor["system"]["attributes"]["spellcasting"], "wis")

    def test_spell_slots(self) -> None:
        spells = self.actor["system"]["spells"]
        self.assertEqual(spells["spell1"]["value"], 4)
        self.assertEqual(spells["spell2"]["value"], 2)
        self.assertEqual(spells["spell3"]["value"], 0)

    def test_spell_items_and_schools(self) -> None:
        spell_items = [i for i in self.actor["items"] if i["type"] == "spell"]
        self.assertEqual(len(spell_items), 5)
        by_name = {i["name"]: i["system"] for i in spell_items}
        self.assertEqual(by_name["Sacred Flame"]["level"], 0)
        self.assertEqual(by_name["Sacred Flame"]["school"], "evo")  # school 5
        self.assertEqual(by_name["Bless"]["school"], "enc")  # school 4
        self.assertEqual(by_name["Cure Wounds"]["prepared"], 1)

    def test_tracker_becomes_feature_uses(self) -> None:
        feats = {i["name"]: i["system"] for i in self.actor["items"] if i["type"] == "feat"}
        self.assertIn("Channel Divinity", feats)
        self.assertEqual(feats["Channel Divinity"]["uses"]["max"], 2)

    def test_equipment_armor_and_currency(self) -> None:
        equip = [i for i in self.actor["items"] if i["type"] == "equipment"]
        names = {i["name"] for i in equip}
        self.assertIn("Chain Shirt", names)
        self.assertIn("Shield", names)
        self.assertEqual(self.actor["system"]["currency"], {"gp": 15})

    def test_hp(self) -> None:
        hp = self.actor["system"]["attributes"]["hp"]
        self.assertEqual((hp["value"], hp["max"]), (18, 21))

    def test_routes_to_dnd5e_adapter(self) -> None:
        adapter = systems.detect_adapter(self.actor)
        self.assertEqual(adapter.system_id, "dnd5e")
        self.assertEqual(adapter.default_theme(self.actor), "cleric")

    def test_end_to_end_render(self) -> None:
        adapter = systems.detect_adapter(self.actor)
        context = adapter.build_context(self.actor)
        self.assertEqual(context["class_line"], "Cleric 3")
        self.assertEqual(context["ac"], 16)  # Chain Shirt 13 (+1 Dex, cap 2) + Shield 2
        html = adapter.render(
            context, "test-cleric", style="ledger", initial_theme=None,
            theme_palette=None, palette_decoration=None, include_footer=True, paper="a4",
        )
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("Test Cleric", html)
        self.assertIn("Cleric 3", html)


class FightClubExportTests(unittest.TestCase):
    """Foundry-shaped actor dict -> Fight Club XML (to_xml)."""

    @classmethod
    def setUpClass(cls) -> None:
        # Start from the parsed fixture so we have a realistic actor dict.
        cls.actor = fightclub.parse_actor(FIXTURE.read_text(encoding="utf-8"))
        cls.xml = fightclub.to_xml(cls.actor)

    def test_produces_recognizable_document(self) -> None:
        self.assertTrue(self.xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertTrue(fightclub.looks_like_fightclub(self.xml))

    def test_round_trip_preserves_core_fields(self) -> None:
        again = fightclub.parse_actor(self.xml)
        orig, rt = self.actor["system"], again["system"]
        self.assertEqual(again["name"], self.actor["name"])
        self.assertEqual(
            {c: v["value"] for c, v in rt["abilities"].items()},
            {c: v["value"] for c, v in orig["abilities"].items()},
        )
        self.assertEqual(
            {c for c, v in rt["abilities"].items() if v["proficient"]},
            {c for c, v in orig["abilities"].items() if v["proficient"]},
        )
        self.assertEqual(
            {c for c, v in rt["skills"].items() if v["value"]},
            {c for c, v in orig["skills"].items() if v["value"]},
        )
        self.assertEqual(rt["attributes"]["spellcasting"], orig["attributes"]["spellcasting"])
        self.assertEqual(rt["spells"]["spell1"]["value"], orig["spells"]["spell1"]["value"])
        self.assertEqual(rt["spells"]["spell2"]["value"], orig["spells"]["spell2"]["value"])

    def test_round_trip_class_and_spells(self) -> None:
        again = fightclub.parse_actor(self.xml)
        cls = next(i for i in again["items"] if i["type"] == "class")
        self.assertEqual(cls["name"], "Cleric")
        self.assertEqual(cls["system"]["levels"], 3)
        self.assertEqual(len([i for i in again["items"] if i["type"] == "spell"]), 5)

    def test_exports_final_scores_without_double_counting(self) -> None:
        # No ability <mod> entries are emitted, so re-parsing yields identical scores.
        self.assertNotIn("<category>1</category>", self.xml)

    def test_round_trip_renders(self) -> None:
        again = fightclub.parse_actor(self.xml)
        adapter = systems.detect_adapter(again)
        context = adapter.build_context(again)
        self.assertEqual(context["class_line"], "Cleric 3")
        html = adapter.render(
            context, "rt-cleric", style="ledger", initial_theme=None,
            theme_palette=None, palette_decoration=None, include_footer=True, paper="a4",
        )
        self.assertIn("Test Cleric", html)


if __name__ == "__main__":
    unittest.main()
