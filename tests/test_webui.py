import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import generate_character_sheet as sheet
import webui


MINIMAL_ACTOR = {
    "name": "Web Cleric",
    "type": "character",
    "system": {
        "abilities": {k: {"value": v} for k, v in
                      {"str": 10, "dex": 14, "con": 12, "int": 10, "wis": 16, "cha": 8}.items()},
        "attributes": {"ac": {"value": 13}, "hp": {"value": 20, "max": 20, "temp": 0},
                       "init": {"bonus": 0}, "inspiration": False},
        "details": {"xp": {"value": 900}, "biography": {"value": ""}},
        "skills": {}, "tools": {},
        "traits": {"size": "med", "armorProf": {"value": ["lgt"]},
                   "weaponProf": {"value": ["sim"]}, "languages": {"value": ["common"]}},
        "spells": {"spell1": {"max": 2, "value": 2}},
        "currency": {"gp": 5},
    },
    "items": [
        {"name": "Cleric", "type": "class", "system": {"levels": 3, "hd": {"denomination": "d8", "spent": 0}}},
    ],
}


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        webui.STATE.context = None

    def test_load_actor_returns_summary_and_sets_state(self) -> None:
        summary = webui.load_actor(MINIMAL_ACTOR)
        self.assertEqual(summary["name"], "Web Cleric")
        self.assertEqual(summary["default_theme"], "cleric")
        self.assertIsNotNone(webui.STATE.context)

    def test_theme_list_covers_all_registered_themes(self) -> None:
        themes = webui.theme_list()
        self.assertEqual(len(themes), len(sheet.THEMES))
        self.assertTrue(all("light_accent" in t for t in themes))

    def test_render_preview_applies_decoration_and_mode(self) -> None:
        webui.load_actor(MINIMAL_ACTOR)
        html = webui.render_preview("nord", "dark")
        self.assertIn("<!doctype html>", html)
        self.assertIn("sheet-palette-nord", html)

    def test_render_preview_without_actor_raises(self) -> None:
        with self.assertRaises(ValueError):
            webui.render_preview("ledger", None)

    def test_generate_files_writes_html(self) -> None:
        webui.load_actor(MINIMAL_ACTOR)
        with tempfile.TemporaryDirectory() as tmp:
            result = webui.generate_files("ledger", None, "a4", True, want_pdf=False, output_dir=Path(tmp))
            self.assertIn("html", result)
            self.assertNotIn("pdf", result)
            self.assertTrue((Path(tmp) / result["html"]).is_file())

    def test_generate_files_pdf_soft_fails_without_browser(self) -> None:
        webui.load_actor(MINIMAL_ACTOR)
        original = sheet.detect_print_browser
        sheet.detect_print_browser = lambda: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = webui.generate_files("ledger", None, "a4", True, want_pdf=True, output_dir=Path(tmp))
            self.assertIn("pdf_error", result)
            self.assertIn("html", result)  # HTML still produced
        finally:
            sheet.detect_print_browser = original


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        webui.OUTPUT_DIR = Path(self.tmp.name)
        webui.STATE.context = None
        self.httpd = webui._make_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def _req(self, method: str, path: str, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        data = resp.read()
        headers = dict(resp.getheaders())
        conn.close()
        return resp.status, headers, data

    def test_index_and_themes(self) -> None:
        status, headers, body = self._req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"char2pdf", body)

        status, _, body = self._req("GET", "/themes")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)), len(sheet.THEMES))

    def test_preview_requires_actor(self) -> None:
        status, _, _ = self._req("GET", "/preview?theme=ledger")
        self.assertEqual(status, 400)

    def test_full_upload_preview_generate_download_flow(self) -> None:
        status, _, body = self._req("POST", "/actor", json.dumps(MINIMAL_ACTOR))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["default_theme"], "cleric")

        status, headers, body = self._req("GET", "/preview?theme=kanagawa&mode=dark")
        self.assertEqual(status, 200)
        self.assertIn(b"sheet-palette-kanagawa", body)

        status, _, body = self._req("POST", "/generate",
                                    json.dumps({"theme": "kanagawa", "paper": "letter",
                                                "footer": False, "pdf": False}))
        self.assertEqual(status, 200)
        name = json.loads(body)["html"]

        status, headers, body = self._req("GET", "/download/" + name)
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertGreater(len(body), 0)

    def test_download_rejects_traversal(self) -> None:
        status, _, _ = self._req("GET", "/download/../webui.py")
        self.assertEqual(status, 404)

    def test_invalid_actor_json_returns_400(self) -> None:
        status, _, _ = self._req("POST", "/actor", b"{not json")
        self.assertEqual(status, 400)

    def test_generate_rejects_bad_mode(self) -> None:
        self._req("POST", "/actor", json.dumps(MINIMAL_ACTOR))
        status, _, _ = self._req("POST", "/generate", json.dumps({"theme": "ledger", "mode": "neon"}))
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
