"""Local web UI for foundryvtt-char2pdf.

Stdlib-only. Binds to 127.0.0.1, opens the browser, and lets a user pick a
Foundry actor JSON, preview every theme live, and generate an HTML sheet (and a
PDF if a Chromium-compatible browser is present) — no terminal needed after the
app is launched.

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

import generate_character_sheet as gen

# Where generated files are written. Configured by run(); used by the HTTP path.
OUTPUT_DIR = Path("output")


# --------------------------------------------------------------------------- #
# In-memory state — this is a single-user local server, so one "current actor"
# is enough. The browser uploads once; previews and generation reuse it.
# --------------------------------------------------------------------------- #
class _State:
    def __init__(self) -> None:
        self.context: dict | None = None
        self.sheet_id: str = "sheet"
        self.name: str = ""
        self.default_theme: str = "ledger"


STATE = _State()


def load_actor(actor: dict) -> dict:
    """Parse an uploaded actor dict into a render context and store it.

    Returns a small summary for the UI (name, class line, detected theme).
    """
    context = gen.sheet_context(actor)
    default = gen.primary_class_slug(actor) or "ledger"
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
    """Theme names + accent swatches for building the gallery cards."""
    return [
        {
            "name": name,
            "light_accent": entry["light_accent"],
            "dark_accent": entry["dark_accent"],
            "base": entry["base"],
        }
        for name, entry in gen.THEMES.items()
    ]


def _palette(entry: dict) -> dict:
    return {k: entry[k] for k in
            ("light_accent", "light_accent_strong", "dark_accent", "dark_accent_strong")}


def _resolve(theme: str) -> tuple[str, dict]:
    resolved = gen.resolve_theme_entry(theme)
    if resolved is None:
        return "ledger", dict(gen.THEMES["ledger"])
    return resolved


def render_preview(theme: str, mode: str | None, paper: str = "a4") -> str:
    """Full sheet HTML for the current actor in `theme` (for an iframe)."""
    if STATE.context is None:
        raise ValueError("No actor loaded.")
    _, entry = _resolve(theme)
    return gen.render_character_sheet(
        STATE.context,
        STATE.sheet_id,
        style=entry["base"],
        initial_theme=mode,
        theme_palette=_palette(entry),
        palette_decoration=entry.get("decoration"),
        paper=paper,
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
        include_footer=footer, paper=paper,
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
        theme = (query.get("theme") or ["ledger"])[0]
        mode = (query.get("mode") or [None])[0]
        paper = (query.get("paper") or ["a4"])[0]
        if paper not in gen.PAPER_PROFILES:
            paper = "a4"
        if mode is not None and mode not in gen.MODE_CHOICES:
            mode = None
        try:
            html = render_preview(theme, mode, paper)
        except Exception as exc:
            self._err(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _handle_actor(self) -> None:
        try:
            actor = json.loads(self._body() or b"{}")
        except json.JSONDecodeError as exc:
            self._err(HTTPStatus.BAD_REQUEST, f"That file is not valid JSON: {exc}")
            return
        if not isinstance(actor, dict):
            self._err(HTTPStatus.BAD_REQUEST, "Expected a Foundry actor JSON object.")
            return
        try:
            summary = load_actor(actor)
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
    --ink: #1b1d22; --ink-soft: #5c616b; --line: #e3e0d8; --paper: #f7f5f0;
    --card: #ffffff; --accent: #7a1518; --radius: 12px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font: 15px/1.5 "Inter", "Segoe UI", system-ui, sans-serif;
  }
  header.top {
    padding: 22px 28px; border-bottom: 1px solid var(--line);
    display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  }
  header.top h1 { margin: 0; font-size: 20px; letter-spacing: 0.02em; }
  header.top .sub { color: var(--ink-soft); font-size: 13px; }
  header.top .ver { margin-left: auto; color: var(--ink-soft); font-size: 12px; }
  main { max-width: 1180px; margin: 0 auto; padding: 26px 28px 60px; }

  .banner { display: none; margin: 0 0 18px; padding: 11px 14px; border-radius: 8px;
            background: #fdecea; color: #8a1c12; border: 1px solid #f3c9c4; }
  .banner.show { display: block; }

  #drop {
    border: 2px dashed #cbc7bd; border-radius: var(--radius); background: var(--card);
    padding: 40px 24px; text-align: center; cursor: pointer; transition: border-color .15s, background .15s;
  }
  #drop:hover, #drop.hover { border-color: var(--accent); background: #fffdfb; }
  #drop .big { font-size: 16px; font-weight: 600; }
  #drop .small { color: var(--ink-soft); font-size: 13px; margin-top: 6px; }

  #workspace[hidden] { display: none; }
  .actor-bar {
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    padding: 14px 16px; margin: 18px 0; background: var(--card);
    border: 1px solid var(--line); border-radius: var(--radius);
  }
  .actor-bar .who { font-weight: 600; }
  .actor-bar .cls { color: var(--ink-soft); font-size: 13px; }
  .actor-bar .change { margin-left: auto; }

  .options { display: flex; gap: 18px 22px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 18px; }
  .field { display: flex; flex-direction: column; gap: 5px; }
  .field label { font-size: 12px; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.06em; }
  select, button { font: inherit; }
  select { padding: 7px 10px; border: 1px solid #cbc7bd; border-radius: 8px; background: #fff; }
  .check { flex-direction: row; align-items: center; gap: 8px; }
  .check input { width: 16px; height: 16px; }

  .gallery {
    display: grid; grid-template-columns: repeat(auto-fill, 300px);
    gap: 18px; justify-content: center;
  }
  .card {
    padding: 0; border: 1px solid var(--line); border-radius: var(--radius);
    background: var(--card); cursor: pointer; overflow: hidden; text-align: left;
    transition: border-color .12s, box-shadow .12s, transform .12s;
  }
  .card:hover { box-shadow: 0 6px 20px rgba(0,0,0,.08); transform: translateY(-2px); }
  .card.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
  .frame-wrap { width: 300px; height: 424px; overflow: hidden; background: #fff; }
  .frame { width: 820px; height: 1160px; border: 0; transform: scale(.3658); transform-origin: top left; pointer-events: none; background: #fff; }
  .frame.empty { display: flex; }
  .card-label { display: flex; align-items: center; gap: 9px; padding: 10px 12px; border-top: 1px solid var(--line); }
  .swatch { width: 14px; height: 14px; border-radius: 4px; border: 1px solid rgba(0,0,0,.15); flex: 0 0 auto; }
  .card-label .nm { font-size: 13.5px; font-weight: 600; }

  .generate-bar {
    position: sticky; bottom: 0; margin-top: 26px; padding: 14px 16px;
    background: rgba(247,245,240,.94); backdrop-filter: blur(6px);
    border: 1px solid var(--line); border-radius: var(--radius);
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  }
  .generate-bar .chosen { font-size: 14px; }
  .generate-bar .chosen b { color: var(--accent); }
  .spacer { margin-left: auto; }
  .btn {
    padding: 9px 16px; border: 1px solid var(--accent); border-radius: 8px;
    background: var(--accent); color: #fff; font-weight: 600; cursor: pointer;
  }
  .btn.ghost { background: #fff; color: var(--accent); }
  .btn:disabled { opacity: .55; cursor: default; }
  #result { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  #result .dl { padding: 7px 12px; border-radius: 7px; border: 1px solid #cbc7bd; background: #fff;
                color: var(--ink); text-decoration: none; font-size: 13px; font-weight: 600; }
  #result .dl:hover { border-color: var(--accent); color: var(--accent); }
  #result .warn { color: #8a5a12; font-size: 13px; margin: 0; }
  .hint { color: var(--ink-soft); font-size: 13px; }
</style>
</head>
<body>
<header class="top">
  <h1>char2pdf</h1>
  <span class="sub">Foundry VTT actor &rarr; printable character sheet</span>
  <span class="ver">v__VERSION__</span>
</header>
<main>
  <div id="banner" class="banner"></div>

  <div id="drop">
    <div class="big">Drop your Foundry actor JSON here</div>
    <div class="small">&hellip; or click to choose a file. Everything stays on your computer.</div>
    <input id="file" type="file" accept=".json,application/json" hidden>
  </div>

  <section id="workspace" hidden>
    <div class="actor-bar">
      <span class="who" id="actor-name">&mdash;</span>
      <span class="cls" id="actor-class"></span>
      <button class="btn ghost change" id="btn-change">Choose a different file</button>
    </div>

    <div class="options">
      <div class="field">
        <label for="opt-mode">Color mode</label>
        <select id="opt-mode">
          <option value="">Light (default)</option>
          <option value="dark">Dark</option>
          <option value="mono">Mono (grayscale print)</option>
        </select>
      </div>
      <div class="field">
        <label for="opt-paper">Paper</label>
        <select id="opt-paper">
          <option value="a4">A4</option>
          <option value="letter">US Letter</option>
        </select>
      </div>
      <div class="field check">
        <input type="checkbox" id="opt-footer" checked>
        <label for="opt-footer" style="text-transform:none;letter-spacing:0">Include attribution footer</label>
      </div>
      <span class="hint">Click a theme below to pick it &mdash; previews are live.</span>
    </div>

    <div class="gallery" id="gallery"></div>

    <div class="generate-bar">
      <span class="chosen">Theme: <b id="chosen-theme">&mdash;</b></span>
      <span class="spacer"></span>
      <div id="result"></div>
      <button class="btn ghost" id="btn-html">Generate HTML</button>
      <button class="btn" id="btn-pdf">Generate PDF</button>
    </div>
  </section>
</main>

<script>
const state = { themes: [], theme: null, mode: "", paper: "a4", footer: true, ready: false };
const $ = (id) => document.getElementById(id);

function showError(msg) { const b = $("banner"); b.textContent = msg; b.classList.add("show"); }
function clearError() { $("banner").classList.remove("show"); }

async function uploadActor(file) {
  clearError();
  let text;
  try { text = await file.text(); } catch (e) { return showError("Could not read that file."); }
  let res, data;
  try { res = await fetch("/actor", { method: "POST", body: text }); data = await res.json(); }
  catch (e) { return showError("Could not reach the server."); }
  if (!res.ok) { return showError(data.error || "Upload failed."); }
  state.theme = data.default_theme;
  state.ready = true;
  $("actor-name").textContent = data.name;
  $("actor-class").textContent = data.class_line || "";
  $("workspace").hidden = false;
  if (!state.themes.length) {
    try { state.themes = await (await fetch("/themes")).json(); }
    catch (e) { return showError("Could not load themes."); }
  }
  buildGallery();
  updateChosen();
}

function previewSrc(name) {
  const m = state.mode ? "&mode=" + encodeURIComponent(state.mode) : "";
  return "/preview?theme=" + encodeURIComponent(name) + m + "&paper=" + state.paper;
}

const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (e.isIntersecting && !e.target.src) { e.target.src = e.target.dataset.src; io.unobserve(e.target); }
  }
}, { rootMargin: "300px" });

function buildGallery() {
  const g = $("gallery");
  g.innerHTML = "";
  for (const t of state.themes) {
    const card = document.createElement("button");
    card.className = "card" + (t.name === state.theme ? " selected" : "");
    card.dataset.theme = t.name;
    card.onclick = () => {
      state.theme = t.name;
      document.querySelectorAll(".card").forEach((c) => c.classList.toggle("selected", c.dataset.theme === t.name));
      updateChosen();
    };
    const wrap = document.createElement("div");
    wrap.className = "frame-wrap";
    const f = document.createElement("iframe");
    f.className = "frame";
    f.title = t.name + " preview";
    f.dataset.src = previewSrc(t.name);
    io.observe(f);
    wrap.appendChild(f);
    const label = document.createElement("div");
    label.className = "card-label";
    const sw = document.createElement("span");
    sw.className = "swatch";
    sw.style.background = t.light_accent;
    const nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = t.name;
    label.append(sw, nm);
    card.append(wrap, label);
    g.appendChild(card);
  }
}

function refreshPreviews() {
  document.querySelectorAll(".frame").forEach((f) => {
    const name = f.closest(".card").dataset.theme;
    f.removeAttribute("src");
    f.dataset.src = previewSrc(name);
    io.observe(f);
  });
}

function updateChosen() { $("chosen-theme").textContent = state.theme || "—"; }

async function generate(wantPdf) {
  clearError();
  const btn = wantPdf ? $("btn-pdf") : $("btn-html");
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Working…";
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

$("opt-mode").onchange = (e) => { state.mode = e.target.value; if (state.ready) refreshPreviews(); };
$("opt-paper").onchange = (e) => { state.paper = e.target.value; };
$("opt-footer").onchange = (e) => { state.footer = e.target.checked; };
$("btn-html").onclick = () => generate(false);
$("btn-pdf").onclick = () => generate(true);
</script>
</body>
</html>
"""

INDEX_HTML = _PAGE.replace("__VERSION__", gen.APP_VERSION)


if __name__ == "__main__":
    raise SystemExit(main())
