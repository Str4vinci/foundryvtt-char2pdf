import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_smoke import write_actor

import emblems
import generate_character_sheet as gen

MODE_KEYS = {"paper", "panel", "panel_soft", "ink", "ink_soft", "rule", "rule_soft",
             "shadow", "accent", "accent_strong"}


class ThemeContrastTests(unittest.TestCase):
    """Every theme must stay readable in both color modes."""

    def test_every_theme_defines_both_modes(self) -> None:
        for name, entry in gen.THEMES.items():
            for mode in ("light", "dark"):
                with self.subTest(theme=name, mode=mode):
                    self.assertEqual(set(entry[mode]), MODE_KEYS)

    def test_text_and_accents_meet_wcag_on_every_surface(self) -> None:
        for name, entry in gen.THEMES.items():
            palette = gen.build_theme_palette(entry)
            for mode in ("light", "dark"):
                resolved = palette[mode]
                surfaces = gen._mode_backgrounds(resolved, dark=mode == "dark")
                for surface in surfaces:
                    with self.subTest(theme=name, mode=mode, surface=surface):
                        for key in ("ink", "ink_soft", "accent"):
                            self.assertGreaterEqual(
                                gen.contrast_ratio(resolved[key], surface), gen.TEXT_CONTRAST, key)
                        self.assertGreaterEqual(
                            gen.contrast_ratio(resolved["accent_strong"], surface), gen.GRAPHIC_CONTRAST)
                with self.subTest(theme=name, mode=mode, check="on_accent"):
                    self.assertGreaterEqual(
                        gen.contrast_ratio(resolved["on_accent"], resolved["accent"]), gen.TEXT_CONTRAST)

    def test_custom_hex_themes_are_guarded_too(self) -> None:
        for color in ("#ffff00", "#000080", "#808080", "#00ffff"):
            _, entry = gen.resolve_theme_entry(color)
            palette = gen.build_theme_palette(entry)
            for mode in ("light", "dark"):
                resolved = palette[mode]
                for surface in gen._mode_backgrounds(resolved, dark=mode == "dark"):
                    with self.subTest(color=color, mode=mode, surface=surface):
                        self.assertGreaterEqual(
                            gen.contrast_ratio(resolved["accent"], surface), gen.TEXT_CONTRAST)

    def test_passing_colors_are_left_unchanged(self) -> None:
        self.assertEqual(gen.ensure_contrast("#7a1518", ("#ffffff",), gen.TEXT_CONTRAST), "#7a1518")
        adjusted = gen.ensure_contrast("#91a1b2", ("#ffffff",), gen.TEXT_CONTRAST)
        self.assertNotEqual(adjusted, "#91a1b2")
        self.assertGreaterEqual(gen.contrast_ratio(adjusted, "#ffffff"), gen.TEXT_CONTRAST)

    def test_flatten_color_composites_rgba(self) -> None:
        self.assertEqual(gen.flatten_color("#123456", "#ffffff"), "#123456")
        self.assertEqual(gen.flatten_color("rgba(0, 0, 0, 0.5)", "#ffffff"), "#808080")

    def test_decorations_are_registered(self) -> None:
        for name, entry in gen.THEMES.items():
            decoration = entry["decoration"]
            if decoration is not None:
                with self.subTest(theme=name):
                    self.assertIn(decoration, gen.PALETTE_DECORATIONS)
                    self.assertIn(f"palette-{decoration}", gen._sheet_palette_css(decoration))


class ThemeAliasTests(unittest.TestCase):
    def test_aliases_point_at_registered_themes(self) -> None:
        for alias, (target, mode) in gen.THEME_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertNotIn(alias, gen.THEMES)
                self.assertIn(target, gen.THEMES)
                self.assertIn(mode, gen.MODE_CHOICES)
                label, entry = gen.resolve_theme_entry(alias)
                self.assertEqual(label, alias)
                self.assertEqual(entry["default_mode"], mode)
                self.assertEqual(gen.parse_theme_arg(alias), alias)

    def test_alias_sets_initial_mode_unless_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actor = write_actor(tmp_path)
            [path] = gen.write_output(actor, tmp_path, theme="ayu-mirage")
            self.assertIn('const initialTheme = "dark";', path.read_text(encoding="utf-8"))
            [path] = gen.write_output(actor, tmp_path, theme="ayu-mirage", mode="light")
            self.assertIn('const initialTheme = "light";', path.read_text(encoding="utf-8"))


class EmblemTests(unittest.TestCase):
    def test_every_class_has_an_emblem(self) -> None:
        self.assertEqual(set(emblems.EMBLEMS), set(gen.CLASS_THEME_COLORS))

    def test_unknown_class_falls_back_to_d20(self) -> None:
        self.assertIn(emblems.FALLBACK_EMBLEM, emblems.emblem_svg("homebrew-blood-hunter"))
        self.assertIn(emblems.FALLBACK_EMBLEM, emblems.emblem_svg(None))

    def test_sheet_shows_the_class_emblem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            [path] = gen.write_output(write_actor(tmp_path), tmp_path, theme="nord")
            html = path.read_text(encoding="utf-8")
            self.assertIn('class="sheet-emblem"', html)
            self.assertIn(emblems.EMBLEMS["cleric"], html)


class EmbeddedFontTests(unittest.TestCase):
    def test_manifest_files_exist_and_are_woff2(self) -> None:
        manifest = gen._font_manifest()
        self.assertTrue(manifest)
        for family, info in manifest.items():
            with self.subTest(family=family):
                self.assertIn(info["license"], {"OFL-1.1", "Apache-2.0"})
                slug = family.lower().replace(" ", "-")
                self.assertTrue((gen.FONTS_DIR / "licenses" / f"{slug}.txt").is_file())
                for face in info["faces"]:
                    self.assertEqual((gen.FONTS_DIR / face["file"]).read_bytes()[:4], b"wOF2")

    def test_every_theme_bundles_a_font_for_each_role(self) -> None:
        for name, entry in gen.THEMES.items():
            with self.subTest(theme=name):
                families = gen.theme_font_families(entry["base"], entry["decoration"])
                # serif, display, sans and mono may share families, but none is left to system fallbacks.
                self.assertGreaterEqual(len(families), 2)
                css = gen.embedded_font_css(entry["base"], entry["decoration"])
                for family in families:
                    self.assertIn(f'font-family: "{family}"', css)

    def test_theme_fonts_follow_the_palette(self) -> None:
        self.assertIn("Literata", gen.theme_font_families("ledger", "dracula"))
        self.assertNotIn("Literata", gen.theme_font_families("ledger", None))
        self.assertIn("Cinzel", gen.theme_font_families("grimoire", None))

    def test_sheet_embeds_fonts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            [path] = gen.write_output(write_actor(tmp_path), tmp_path, theme="dracula")
            html = path.read_text(encoding="utf-8")
            self.assertIn('font-family: "Literata"', html)
            self.assertIn("data:font/woff2;base64,", html)

    def test_missing_font_bundle_renders_without_fonts(self) -> None:
        gen._font_manifest.cache_clear()
        try:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gen, "FONTS_DIR", Path(tmp)):
                self.assertEqual(gen.embedded_font_css("ledger", "dracula"), "")
        finally:
            gen._font_manifest.cache_clear()


if __name__ == "__main__":
    unittest.main()
