import copy
import json
import tempfile
import unittest
from pathlib import Path

import generate_character_sheet as gen
import systems
from test_smoke import MINIMAL_ACTOR


# A deliberately non-dnd5e actor: a plausible Pathfinder 2e-shaped export whose
# ability block does not carry the dnd5e str/dex/con/int/wis/cha fingerprint.
PF2E_ACTOR = {
    "name": "Someone Else",
    "type": "character",
    "system": {
        "abilities": {
            "strength": {"mod": 2},
            "dexterity": {"mod": 3},
        },
        "attributes": {"hp": {"value": 18, "max": 18}},
    },
    "items": [],
}


class DetectionTests(unittest.TestCase):
    def test_dnd5e_adapter_is_registered(self) -> None:
        self.assertIs(systems.get("dnd5e"), gen.DND5E_ADAPTER)
        self.assertIn("dnd5e", systems.known_ids())

    def test_detects_dnd5e_by_schema_when_no_hint(self) -> None:
        # MINIMAL_ACTOR carries no _stats.systemId, so detection must sniff shape.
        self.assertNotIn("_stats", MINIMAL_ACTOR)
        adapter = systems.detect_adapter(MINIMAL_ACTOR)
        self.assertEqual(adapter.system_id, "dnd5e")

    def test_detects_dnd5e_by_stats_hint(self) -> None:
        actor = copy.deepcopy(MINIMAL_ACTOR)
        actor["_stats"] = {"systemId": "dnd5e", "systemVersion": "4.0.0"}
        self.assertEqual(systems.foundry_system_hint(actor), "dnd5e")
        self.assertEqual(systems.detect_adapter(actor).system_id, "dnd5e")

    def test_detects_dnd5e_by_flags_hint(self) -> None:
        # A registered system id appearing as a flags namespace is a valid hint,
        # even if the schema would not otherwise be recognized.
        actor = copy.deepcopy(PF2E_ACTOR)
        actor["flags"] = {"dnd5e": {"something": True}}
        self.assertEqual(systems.foundry_system_hint(actor), "dnd5e")
        self.assertEqual(systems.detect_adapter(actor).system_id, "dnd5e")

    def test_unsupported_system_named_by_stats_hint(self) -> None:
        actor = copy.deepcopy(PF2E_ACTOR)
        actor["_stats"] = {"systemId": "pf2e"}
        with self.assertRaises(systems.UnsupportedSystemError) as ctx:
            systems.detect_adapter(actor)
        self.assertEqual(ctx.exception.system_id, "pf2e")
        self.assertIn("pf2e", str(ctx.exception))
        self.assertIn("dnd5e", str(ctx.exception))  # lists what IS supported

    def test_unrecognized_schema_without_hint(self) -> None:
        with self.assertRaises(systems.UnsupportedSystemError) as ctx:
            systems.detect_adapter(PF2E_ACTOR)
        self.assertIsNone(ctx.exception.system_id)

    def test_forced_system_valid(self) -> None:
        # Forcing bypasses detection entirely, even for a non-matching schema.
        adapter = systems.detect_adapter(PF2E_ACTOR, forced="dnd5e")
        self.assertEqual(adapter.system_id, "dnd5e")

    def test_forced_system_unknown(self) -> None:
        with self.assertRaises(systems.UnsupportedSystemError) as ctx:
            systems.detect_adapter(MINIMAL_ACTOR, forced="pf2e")
        self.assertEqual(ctx.exception.system_id, "pf2e")
        self.assertIn("pf2e", str(ctx.exception))

    def test_no_hint_for_unknown_flags(self) -> None:
        actor = copy.deepcopy(PF2E_ACTOR)
        actor["flags"] = {"exportSource": {}, "pf2e": {}}
        self.assertIsNone(systems.foundry_system_hint(actor))


class WriteOutputDetectionTests(unittest.TestCase):
    def _write(self, actor: dict, directory: Path) -> Path:
        path = directory / "actor.json"
        path.write_text(json.dumps(actor))
        return path

    def test_write_output_rejects_unsupported_actor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actor_path = self._write(PF2E_ACTOR, tmp_path)
            with self.assertRaises(systems.UnsupportedSystemError):
                gen.write_output(actor_path, tmp_path, theme="ledger")

    def test_write_output_force_unknown_system(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actor_path = self._write(MINIMAL_ACTOR, tmp_path)
            with self.assertRaises(systems.UnsupportedSystemError):
                gen.write_output(actor_path, tmp_path, theme="ledger", system="pf2e")

    def test_write_output_force_supported_system(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actor_path = self._write(MINIMAL_ACTOR, tmp_path)
            paths = gen.write_output(actor_path, tmp_path, theme="ledger", system="dnd5e")
            self.assertEqual(len(paths), 1)
            self.assertIn("<!doctype html>", paths[0].read_text(encoding="utf-8"))


class AdapterContractTests(unittest.TestCase):
    """Lock in the adapter boundary's shape so future systems have a target."""

    def test_dnd5e_adapter_satisfies_protocol(self) -> None:
        self.assertIsInstance(gen.DND5E_ADAPTER, systems.SystemAdapter)

    def test_adapter_exposes_required_surface(self) -> None:
        adapter = gen.DND5E_ADAPTER
        self.assertIsInstance(adapter.system_id, str)
        self.assertTrue(adapter.system_id)
        self.assertIsInstance(adapter.display_name, str)
        for name in ("matches", "build_context", "default_theme", "render"):
            self.assertTrue(callable(getattr(adapter, name)), name)

    def test_build_context_and_default_theme(self) -> None:
        adapter = gen.DND5E_ADAPTER
        context = adapter.build_context(MINIMAL_ACTOR)
        self.assertIsInstance(context, dict)
        self.assertIn("class_line", context)
        # MINIMAL_ACTOR is a level 3 Cleric, so its class theme is "cleric".
        self.assertEqual(adapter.default_theme(MINIMAL_ACTOR), "cleric")

    def test_render_matches_shared_renderer(self) -> None:
        # The adapter must not alter output versus the shared render path.
        adapter = gen.DND5E_ADAPTER
        context = adapter.build_context(MINIMAL_ACTOR)
        entry = gen.THEMES["ledger"]
        palette = {k: entry[k] for k in
                   ("light_accent", "light_accent_strong", "dark_accent", "dark_accent_strong")}
        via_adapter = adapter.render(
            context, "sheet", style=entry["base"], initial_theme=None,
            theme_palette=palette, palette_decoration=entry.get("decoration"),
            include_footer=True, paper="a4",
        )
        via_shared = gen.render_character_sheet(
            context, "sheet", style=entry["base"], initial_theme=None,
            theme_palette=palette, palette_decoration=entry.get("decoration"),
            include_footer=True, paper="a4",
        )
        self.assertEqual(via_adapter, via_shared)


if __name__ == "__main__":
    unittest.main()
