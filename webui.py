"""Local web UI for foundryvtt-char2pdf.

Stdlib-only. Binds to 127.0.0.1, opens the browser, and lets a user pick a
Foundry actor JSON, preview themes live (one large, readable sheet at a time),
and generate an HTML sheet (and a PDF if a Chromium-compatible browser is
present) — no terminal needed after the app is launched.

Launch with `python3 generate_character_sheet.py --serve` or `python3 webui.py`.
The actor JSON is read in the browser and POSTed as raw JSON, so the server
never needs multipart parsing, and the data never leaves the local machine.
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fightclub
import generate_character_sheet as gen
import systems

# Where generated files are written. Configured by run(); used by the HTTP path.
OUTPUT_DIR = Path("output")

# Themes that are layouts in their own right (no curated decoration, not a class).
_LAYOUT_THEMES = {"ledger", "gazette", "grimoire"}


# --------------------------------------------------------------------------- #
# In-memory state — this is a single-user local server, so one "current actor"
# is enough. The browser uploads once; previews and generation reuse it.
# --------------------------------------------------------------------------- #
class _State:
    def __init__(self) -> None:
        self.context: dict | None = None
        self.adapter: systems.SystemAdapter = gen.DND5E_ADAPTER
        self.sheet_id: str = "sheet"
        self.name: str = ""
        self.default_theme: str = "ledger"


STATE = _State()


def load_actor(actor: dict) -> dict:
    """Parse an uploaded actor dict into a render context and store it.

    Detects the actor's game system first; an unsupported export raises
    :class:`systems.UnsupportedSystemError`, which the HTTP layer surfaces to the
    user. Returns a small summary for the UI (name, class line, detected theme).
    """
    adapter = systems.detect_adapter(actor)
    context = adapter.build_context(actor)
    default = adapter.default_theme(actor) or "ledger"
    STATE.adapter = adapter
    STATE.context = context
    STATE.sheet_id = gen.slugify(actor.get("name", "sheet"))
    STATE.name = actor.get("name") or "Unnamed Character"
    STATE.default_theme = default if default in gen.THEMES else "ledger"
    return {
        "name": STATE.name,
        "sheet_id": STATE.sheet_id,
        "default_theme": STATE.default_theme,
        "class_line": context.get("class_line", ""),
    }


def theme_list() -> list[dict]:
    """Theme names + accent swatches + group for the sidebar list."""
    out = []
    for name, entry in gen.THEMES.items():
        if name in _LAYOUT_THEMES:
            group = "Layouts"
        elif entry.get("decoration"):
            group = "Curated palettes"
        else:
            group = "Class themes"
        out.append({
            "name": name,
            "light_accent": entry["light_accent"],
            "dark_accent": entry["dark_accent"],
            "group": group,
        })
    return out


def _palette(entry: dict) -> dict:
    return {k: entry[k] for k in
            ("light_accent", "light_accent_strong", "dark_accent", "dark_accent_strong")}


def _resolve(theme: str) -> tuple[str, dict]:
    resolved = gen.resolve_theme_entry(theme)
    if resolved is None:
        return "ledger", dict(gen.THEMES["ledger"])
    return resolved


def render_preview(theme: str, mode: str | None, paper: str = "a4") -> str:
    """Full sheet HTML for the current actor in `theme` (for the preview iframe).

    The in-sheet toolbar is hidden so the preview shows just the sheet. The
    color mode is applied two ways: baked in here as the initial theme, and
    (authoritatively) via the iframe's `?theme=<mode>` query, which the sheet's
    own script honors as an override.
    """
    if STATE.context is None:
        raise ValueError("No actor loaded.")
    _, entry = _resolve(theme)
    html = STATE.adapter.render(
        STATE.context,
        STATE.sheet_id,
        style=entry["base"],
        initial_theme=mode,
        theme_palette=_palette(entry),
        palette_decoration=entry.get("decoration"),
        include_footer=True,
        paper=paper,
    )
    return html.replace(
        "</head>",
        "<style>.sheet-toolbar{display:none !important;}</style></head>",
        1,
    )


def generate_files(theme: str, mode: str | None, paper: str, footer: bool,
                   want_pdf: bool, output_dir: Path) -> dict:
    """Write the HTML sheet (and optionally a PDF) to `output_dir`.

    HTML always succeeds when an actor is loaded; PDF failures are reported
    softly so the HTML download still works.
    """
    if STATE.context is None:
        raise ValueError("No actor loaded.")
    output_dir.mkdir(parents=True, exist_ok=True)
    label, entry = _resolve(theme)
    html_path = gen._render_one_theme(
        STATE.context, STATE.sheet_id, output_dir, label, dict(entry), mode,
        include_footer=footer, paper=paper, adapter=STATE.adapter,
    )
    result: dict = {"html": html_path.name, "theme": label}
    if want_pdf:
        browser = gen.detect_print_browser()
        if not browser:
            result["pdf_error"] = ("No Chrome/Chromium/Edge found. Download the HTML, "
                                   "open it, and use Print → Save as PDF.")
        else:
            try:
                pdf_path = html_path.with_suffix(".pdf")
                gen.render_pdf(html_path, pdf_path, browser, mode=mode)
                result["pdf"] = pdf_path.name
            except Exception as exc:  # subprocess/browser failure — keep the HTML
                result["pdf_error"] = f"PDF export failed: {exc}"
    return result


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = f"char2pdf-webui/{gen.APP_VERSION}"

    # -- helpers ----------------------------------------------------------- #
    def _send(self, status: int, body: bytes,
              content_type: str = "application/json; charset=utf-8",
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"))

    def _err(self, status: int, message: str) -> None:
        self._json({"error": message}, status=status)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def log_message(self, *args) -> None:  # keep the console quiet
        return

    # -- routes ------------------------------------------------------------ #
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/":
            self._send(HTTPStatus.OK, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/themes":
            self._json(theme_list())
        elif route == "/preview":
            self._handle_preview(parse_qs(parsed.query))
        elif route.startswith("/download/"):
            self._handle_download(route[len("/download/"):])
        else:
            self._err(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route == "/actor":
            self._handle_actor()
        elif route == "/generate":
            self._handle_generate()
        else:
            self._err(HTTPStatus.NOT_FOUND, "Not found.")

    def _handle_preview(self, query: dict) -> None:
        if STATE.context is None:
            self._err(HTTPStatus.BAD_REQUEST, "Upload an actor first.")
            return
        # `palette` = which theme to render; `theme` = color mode (so the sheet's
        # own ?theme override applies it). They are deliberately separate params.
        theme = (query.get("palette") or ["ledger"])[0]
        mode = (query.get("theme") or ["light"])[0]
        paper = (query.get("paper") or ["a4"])[0]
        if paper not in gen.PAPER_PROFILES:
            paper = "a4"
        if mode not in gen.MODE_CHOICES:
            mode = None
        try:
            html = render_preview(theme, mode, paper)
        except Exception as exc:
            self._err(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _handle_actor(self) -> None:
        raw = (self._body() or b"").decode("utf-8", errors="replace")
        if fightclub.looks_like_fightclub(raw):
            try:
                actor = fightclub.parse_actor(raw)
            except fightclub.FightClubParseError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
        else:
            try:
                actor = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                self._err(HTTPStatus.BAD_REQUEST, f"That file is not valid JSON or Fight Club XML: {exc}")
                return
            if not isinstance(actor, dict):
                self._err(HTTPStatus.BAD_REQUEST, "Expected a Foundry actor JSON object or Fight Club XML.")
                return
        try:
            summary = load_actor(actor)
        except systems.UnsupportedSystemError as exc:
            self._err(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self._err(HTTPStatus.BAD_REQUEST, f"Could not read that actor: {exc}")
            return
        self._json(summary)

    def _handle_generate(self) -> None:
        if STATE.context is None:
            self._err(HTTPStatus.BAD_REQUEST, "Upload an actor first.")
            return
        try:
            opts = json.loads(self._body() or b"{}")
        except json.JSONDecodeError as exc:
            self._err(HTTPStatus.BAD_REQUEST, f"Invalid request: {exc}")
            return
        theme = opts.get("theme") or STATE.default_theme
        mode = opts.get("mode") or None
        paper = opts.get("paper") or "a4"
        footer = bool(opts.get("footer", True))
        want_pdf = bool(opts.get("pdf", False))
        if paper not in gen.PAPER_PROFILES:
            self._err(HTTPStatus.BAD_REQUEST, f"Unknown paper {paper!r}.")
            return
        if mode is not None and mode not in gen.MODE_CHOICES:
            self._err(HTTPStatus.BAD_REQUEST, f"Unknown mode {mode!r}.")
            return
        try:
            result = generate_files(theme, mode, paper, footer, want_pdf, OUTPUT_DIR)
        except Exception as exc:
            self._err(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self._json(result)

    def _handle_download(self, raw_name: str) -> None:
        # Sanitise: strip any directory components, only serve from OUTPUT_DIR.
        safe = Path(raw_name).name
        target = (OUTPUT_DIR / safe).resolve()
        if target.parent != OUTPUT_DIR.resolve() or not target.is_file():
            self._err(HTTPStatus.NOT_FOUND, "File not found.")
            return
        ctype = "application/pdf" if safe.lower().endswith(".pdf") else "text/html; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), ctype,
                   {"Content-Disposition": f'attachment; filename="{safe}"'})


# --------------------------------------------------------------------------- #
# Server bootstrap
# --------------------------------------------------------------------------- #
def _make_server(host: str, port: int) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, port), Handler)
    except OSError:
        # Requested port busy — let the OS pick a free one.
        return ThreadingHTTPServer((host, 0), Handler)


def run(port: int = 8765, output_dir: Path = Path("output"),
        open_browser: bool = True, host: str = "127.0.0.1") -> int:
    global OUTPUT_DIR
    OUTPUT_DIR = output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    httpd = _make_server(host, port)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"char2pdf web UI running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Port to serve on (default: 8765)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"),
                        help="Where generated files are written (default: output)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run(port=args.port, output_dir=args.output_dir,
               open_browser=not args.no_browser, host=args.host)


# --------------------------------------------------------------------------- #
# The single-page UI (embedded so there are no static-file assets to bundle).
# --------------------------------------------------------------------------- #
_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>char2pdf · character sheet generator</title>
<style>
  :root {
    --ink: #1b1d22; --ink-soft: #5c616b; --line: #e3e0d8; --bg: #ece9e2;
    --panel: #f7f5f0; --card: #fff; --accent: #7a1518; --radius: 10px;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--ink);
    font: 14px/1.5 "Inter", "Segoe UI", system-ui, sans-serif;
  }
  .app { display: flex; height: 100vh; }

  /* ---- sidebar ---- */
  .sidebar {
    flex: 0 0 312px; width: 312px; background: var(--panel);
    border-right: 1px solid var(--line); display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar > * { padding: 0 16px; }
  .brand { padding-top: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
  .brand h1 { margin: 0; font-size: 17px; letter-spacing: 0.02em; }
  .brand .sub { color: var(--ink-soft); font-size: 11.5px; }
  .brand .ver { color: var(--ink-soft); font-size: 11px; float: right; }

  .banner { display: none; margin: 12px 16px 0; padding: 9px 11px; border-radius: 8px;
            background: #fdecea; color: #8a1c12; border: 1px solid #f3c9c4; font-size: 12.5px; }
  .banner.show { display: block; }

  #drop {
    margin: 14px 16px 0; padding: 16px; text-align: center; cursor: pointer;
    border: 2px dashed #cbc7bd; border-radius: var(--radius); background: var(--card);
    transition: border-color .15s, background .15s; font-size: 12.5px;
  }
  #drop:hover, #drop.hover { border-color: var(--accent); background: #fffdfb; }
  #drop .big { font-weight: 600; font-size: 13px; }
  #drop .small { color: var(--ink-soft); margin-top: 3px; }

  .actor { display: none; margin-top: 12px; }
  .actor.show { display: block; }
  .actor .who { font-weight: 600; font-size: 14px; }
  .actor .cls { color: var(--ink-soft); font-size: 12px; }
  .actor .change { margin-top: 4px; background: none; border: 0; color: var(--accent);
                   font-size: 12px; cursor: pointer; padding: 0; text-decoration: underline; }

  .opts { margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 9px 12px; }
  .opts .full { grid-column: 1 / -1; }
  .field label { display: block; font-size: 10.5px; color: var(--ink-soft);
                 text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3px; }
  select { width: 100%; padding: 6px 8px; border: 1px solid #cbc7bd; border-radius: 7px;
           background: #fff; font: inherit; }
  .check { display: flex; align-items: center; gap: 7px; }
  .check input { width: 15px; height: 15px; }
  .check label { font-size: 12.5px; color: var(--ink); }

  .list-head { margin-top: 14px; padding-bottom: 6px; font-size: 10.5px; color: var(--ink-soft);
               text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid var(--line); }
  .theme-list { flex: 1; overflow-y: auto; padding: 4px 10px 12px; }
  .theme-list .group { font-size: 10px; color: var(--ink-soft); text-transform: uppercase;
                       letter-spacing: 0.07em; margin: 12px 6px 4px; }
  .theme-row {
    display: flex; align-items: center; gap: 9px; width: 100%; padding: 7px 8px;
    border: 1px solid transparent; border-radius: 7px; background: none; cursor: pointer;
    font: inherit; color: var(--ink); text-align: left;
  }
  .theme-row:hover { background: #fff; }
  .theme-row.selected { background: #fff; border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
  .theme-row .sw { width: 14px; height: 14px; border-radius: 4px; flex: 0 0 auto;
                   border: 1px solid rgba(0,0,0,.15); }
  .theme-row .nm { font-size: 13px; }

  .actions { padding: 12px 16px; border-top: 1px solid var(--line); background: var(--panel); }
  .gen-row { display: flex; gap: 8px; }
  .btn { flex: 1; padding: 9px 10px; border: 1px solid var(--accent); border-radius: 8px;
         background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
  .btn.ghost { background: #fff; color: var(--accent); }
  .btn:disabled { opacity: .55; cursor: default; }
  #result { margin-top: 9px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  #result .dl { padding: 6px 10px; border-radius: 7px; border: 1px solid #cbc7bd; background: #fff;
                color: var(--ink); text-decoration: none; font-size: 12px; font-weight: 600; }
  #result .dl:hover { border-color: var(--accent); color: var(--accent); }
  #result .warn { color: #8a5a12; font-size: 11.5px; margin: 0; flex-basis: 100%; }

  /* ---- preview ---- */
  .preview-pane { flex: 1; overflow: auto; display: flex; justify-content: center;
                  align-items: flex-start; padding: 24px; }
  .empty { color: var(--ink-soft); margin: auto; text-align: center; font-size: 14px; }
  /* The sheet keeps its two-column layout above 960px (it collapses to one
     column below that), so the preview is rendered wide and scaled to fit. */
  .preview-stage { position: relative; }
  .preview-stage[hidden] { display: none; }
  .preview-frame { transform-origin: top left; border: 0; background: #fff;
                   box-shadow: 0 10px 40px rgba(0,0,0,.14); border-radius: 6px; }
  .loading { position: fixed; top: 14px; right: 18px; background: var(--ink); color: #fff;
             padding: 6px 12px; border-radius: 20px; font-size: 12px; opacity: 0; transition: opacity .15s; }
  .loading.show { opacity: .9; }
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <span class="ver">v__VERSION__</span>
      <h1>char2pdf</h1>
      <div class="sub">Foundry VTT actor &rarr; character sheet</div>
    </div>

    <div id="banner" class="banner"></div>

    <div id="drop">
      <div class="big">Drop actor JSON or XML here</div>
      <div class="small">Foundry VTT JSON or Fight Club 5e XML &mdash; stays on your computer</div>
      <input id="file" type="file" accept=".json,application/json,.xml,text/xml,application/xml" hidden>
    </div>

    <div class="actor" id="actor">
      <div class="who" id="actor-name">&mdash;</div>
      <div class="cls" id="actor-class"></div>
      <button class="change" id="btn-change">Choose a different file</button>
    </div>

    <div class="opts">
      <div class="field">
        <label for="opt-mode">Color mode</label>
        <select id="opt-mode">
          <option value="">Light</option>
          <option value="dark">Dark</option>
          <option value="mono">Mono</option>
        </select>
      </div>
      <div class="field">
        <label for="opt-paper">Paper</label>
        <select id="opt-paper">
          <option value="a4">A4</option>
          <option value="letter">US Letter</option>
        </select>
      </div>
      <div class="field full check">
        <input type="checkbox" id="opt-footer" checked>
        <label for="opt-footer">Include attribution footer</label>
      </div>
    </div>

    <div class="list-head">Themes &mdash; click to preview</div>
    <div class="theme-list" id="themes"></div>

    <div class="actions">
      <div class="gen-row">
        <button class="btn ghost" id="btn-html" disabled>HTML</button>
        <button class="btn" id="btn-pdf" disabled>PDF</button>
      </div>
      <div id="result"></div>
    </div>
  </aside>

  <main class="preview-pane">
    <div class="empty" id="empty">Upload a Foundry actor JSON to preview themes.</div>
    <div class="preview-stage" id="stage" hidden>
      <iframe class="preview-frame" id="preview" title="Sheet preview"></iframe>
    </div>
  </main>
</div>
<div class="loading" id="loading">Rendering…</div>

<script>
const state = { themes: [], theme: null, mode: "", paper: "a4", footer: true, ready: false };
const $ = (id) => document.getElementById(id);

function showError(msg) { const b = $("banner"); b.textContent = msg; b.classList.add("show"); }
function clearError() { $("banner").classList.remove("show"); }
function setLoading(on) { $("loading").classList.toggle("show", on); }

async function uploadActor(file) {
  clearError();
  let text;
  try { text = await file.text(); } catch (e) { return showError("Could not read that file."); }
  let res, data;
  try { res = await fetch("/actor", { method: "POST", body: text }); data = await res.json(); }
  catch (e) { return showError("Could not reach the server."); }
  if (!res.ok) { return showError(data.error || "Upload failed."); }
  state.ready = true;
  $("actor-name").textContent = data.name;
  $("actor-class").textContent = data.class_line || "";
  $("actor").classList.add("show");
  $("drop").style.display = "none";
  $("btn-html").disabled = false;
  $("btn-pdf").disabled = false;
  if (!state.themes.length) {
    try { state.themes = await (await fetch("/themes")).json(); }
    catch (e) { return showError("Could not load themes."); }
    buildThemeList();
  }
  selectTheme(data.default_theme);
}

function buildThemeList() {
  const list = $("themes");
  list.innerHTML = "";
  let lastGroup = null;
  for (const t of state.themes) {
    if (t.group !== lastGroup) {
      const h = document.createElement("div");
      h.className = "group";
      h.textContent = t.group;
      list.appendChild(h);
      lastGroup = t.group;
    }
    const row = document.createElement("button");
    row.className = "theme-row";
    row.dataset.theme = t.name;
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = t.light_accent;
    const nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = t.name;
    row.append(sw, nm);
    row.onclick = () => selectTheme(t.name);
    list.appendChild(row);
  }
}

function previewSrc(name) {
  return "/preview?palette=" + encodeURIComponent(name)
       + "&theme=" + encodeURIComponent(state.mode || "light")
       + "&paper=" + state.paper;
}

function selectTheme(name) {
  state.theme = name;
  document.querySelectorAll(".theme-row").forEach((r) => {
    const on = r.dataset.theme === name;
    r.classList.toggle("selected", on);
    if (on) r.scrollIntoView({ block: "nearest" });
  });
  showPreview();
}

// Render the sheet at a width that keeps its two-column layout (breakpoint is
// 960px), then scale the same-origin iframe down to fit the pane — readable and
// matching the CLI HTML, without horizontal scrolling.
const PREVIEW_WIDTH = 1080;

function fitPreview() {
  const stage = $("stage");
  if (stage.hidden) return;
  const frame = $("preview");
  const avail = document.querySelector(".preview-pane").clientWidth - 48;
  const scale = Math.min(1, avail / PREVIEW_WIDTH);
  let h = 1400;
  try { h = frame.contentWindow.document.documentElement.scrollHeight; } catch (e) {}
  frame.style.width = PREVIEW_WIDTH + "px";
  frame.style.height = h + "px";
  frame.style.transform = "scale(" + scale + ")";
  stage.style.width = (PREVIEW_WIDTH * scale) + "px";
  stage.style.height = (h * scale) + "px";
}

function showPreview() {
  if (!state.theme) return;
  const frame = $("preview");
  setLoading(true);
  frame.onload = () => { setLoading(false); fitPreview(); };
  frame.src = previewSrc(state.theme);
  $("stage").hidden = false;
  $("empty").hidden = true;
}

async function generate(wantPdf) {
  clearError();
  const btn = wantPdf ? $("btn-pdf") : $("btn-html");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "…";
  let res, data;
  try {
    res = await fetch("/generate", {
      method: "POST",
      body: JSON.stringify({ theme: state.theme, mode: state.mode || null,
                             paper: state.paper, footer: state.footer, pdf: wantPdf }),
    });
    data = await res.json();
  } catch (e) {
    btn.disabled = false; btn.textContent = original;
    return showError("Could not reach the server.");
  }
  btn.disabled = false;
  btn.textContent = original;
  const out = $("result");
  out.innerHTML = "";
  if (!res.ok) { return showError(data.error || "Generation failed."); }
  addLink(out, data.html, "Download HTML");
  if (data.pdf) addLink(out, data.pdf, "Download PDF");
  if (data.pdf_error) {
    const p = document.createElement("p");
    p.className = "warn";
    p.textContent = data.pdf_error;
    out.appendChild(p);
  }
}

function addLink(out, name, text) {
  const a = document.createElement("a");
  a.className = "dl";
  a.href = "/download/" + encodeURIComponent(name);
  a.setAttribute("download", "");
  a.textContent = text;
  out.appendChild(a);
}

// Wiring
const drop = $("drop"), input = $("file");
drop.onclick = () => input.click();
$("btn-change").onclick = (e) => { e.stopPropagation(); input.click(); };
input.onchange = () => { if (input.files[0]) uploadActor(input.files[0]); };
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("hover"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("hover"); }));
drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) uploadActor(f); });

$("opt-mode").onchange = (e) => { state.mode = e.target.value; if (state.ready) showPreview(); };
$("opt-paper").onchange = (e) => { state.paper = e.target.value; if (state.ready) showPreview(); };
$("opt-footer").onchange = (e) => { state.footer = e.target.checked; };
$("btn-html").onclick = () => generate(false);
$("btn-pdf").onclick = () => generate(true);
window.addEventListener("resize", fitPreview);
</script>
</body>
</html>
"""

INDEX_HTML = _PAGE.replace("__VERSION__", gen.APP_VERSION)


if __name__ == "__main__":
    raise SystemExit(main())
