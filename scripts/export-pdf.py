#!/usr/bin/env python3
"""Exportiert ein Doku-Repo (Markdown + Mermaid) als PDF.

Voraussetzungen (alles temporär, ändert das System nicht):

    python3 -m venv /tmp/bp-pdf-venv
    /tmp/bp-pdf-venv/bin/pip install markdown weasyprint pillow pymupdf==1.28.2
    curl -sL -o /tmp/bp-pdf-venv/mermaid.min.js \
        https://cdn.jsdelivr.net/npm/mermaid@12.2.0/dist/mermaid.min.js

Außerdem wird `firefox` (headless) zum Rendern der Mermaid-Diagramme benötigt.

Aufruf:

    /tmp/bp-pdf-venv/bin/python scripts/export-pdf.py \
        --repo . --out ../pdf/bp-server-doku-public.pdf \
        --title "phpBB-Server – Dokumentation" --subtitle "Öffentliche Fassung"

Reihenfolge: README.md, docs/*.md, docs/adr/*.md, config|templates/README.md,
danach als Anhang alle Dateien aus config/ bzw. templates/.
Das PDF enthält Lesezeichen, Inhaltsverzeichnis mit Seitenzahlen und die Diagramme als Bilder.
Optik: Doppelrahmen auf jeder Seite (nachträglich mit PyMuPDF gezeichnet; fehlt PyMuPDF, entsteht das PDF
ohne Rahmen), Cover mit Farbband, Tabellen mit Kopfzeile und Zebra-Zeilen, Code-Blöcke mit Akzentkante.
Kapitel laufen fortlaufend (kompakt); mit --page-per-doc beginnt jedes Dokument auf einer neuen Seite.
"""
import argparse
import base64
import datetime
import html
import http.server
import io
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import markdown
from PIL import Image, ImageChops
from weasyprint import HTML

VENV = Path(os.environ.get("BP_PDF_VENV", "/tmp/bp-pdf-venv"))
MERMAID_JS = VENV / "mermaid.min.js"
HOLD_SECONDS = 3.0  # so lange hält der Testserver das Laden an, bis Mermaid fertig gerendert hat

CSS = """
@page { size: A4; margin: 20mm 18mm 22mm 18mm;
  @top-right { content: string(doctitle); font-size: 8pt; color: #1f3f73; }
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 8pt; color: #1f3f73; } }
@page :first { @top-right { content: none; } @bottom-center { content: none; } }
html { font-family: 'Liberation Sans', 'Noto Sans', sans-serif; font-size: 10pt; line-height: 1.45; color: #1b1b1b; }
/* Der Seitenrahmen entsteht nach dem Schreiben des PDFs (add_frame, PyMuPDF). */

h1 { font-size: 20pt; color: #1f3f73; margin-top: 0; padding: 0 0 5pt 0; border-bottom: 1.5pt solid #2b5797;
     line-height: 1.2; break-after: avoid; string-set: doctitle content(); }
/* Akzentbalken als Inline-Element, damit er an Seitenumbruechen nicht abreisst */
h1::before { content: ""; display: inline-block; width: 5pt; height: 0.95em; margin-right: 9pt;
             background: #2b5797; vertical-align: -0.12em; }
h2 { font-size: 14pt; margin-top: 18pt; color: #2b5797; padding-bottom: 2pt; border-bottom: 0.6pt solid #c5d3ea; break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 14pt; color: #1f3f73; break-after: avoid; }
h4 { font-size: 10.5pt; break-after: avoid; }
h1 code { font-size: inherit; background: none; color: inherit; padding: 0; }
p, li { orphans: 3; widows: 3; }
a { color: #1a5fb4; text-decoration: none; }
code { font-family: 'DejaVu Sans Mono', 'Liberation Mono', monospace; font-size: 8.6pt; background: #eef2f9; color: #1f3f73; padding: 0 2pt; border-radius: 2pt; overflow-wrap: anywhere; }
pre { background: #f5f7fb; border: 0.6pt solid #cfd9ea; border-left: 3.5pt solid #2b5797; border-radius: 3pt; padding: 6pt 9pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid-page; }
pre code { background: none; color: #1b1b1b; padding: 0; font-size: 8pt; }

table { border-collapse: separate; border-spacing: 0; width: 100%; margin: 9pt 0; font-size: 8.8pt;
        border: 0.8pt solid #9db4d8; border-radius: 4pt; }
th, td { padding: 3.5pt 6pt; vertical-align: top; text-align: left; overflow-wrap: break-word;
         border-right: 0.5pt solid #dbe4f3; border-bottom: 0.5pt solid #dbe4f3; }
th:last-child, td:last-child { border-right: none; }
tbody tr:last-child td { border-bottom: none; }
th { background: #2b5797; color: #fff; font-weight: 600; border-right-color: #4a76b8; border-bottom: none; }
th:first-child { border-top-left-radius: 3pt; }
th:last-child { border-top-right-radius: 3pt; }
tbody tr:nth-child(even) td { background: #f3f6fb; }
tbody tr:last-child td:first-child { border-bottom-left-radius: 3pt; }
tbody tr:last-child td:last-child { border-bottom-right-radius: 3pt; }
tr { break-inside: avoid; }

blockquote { margin: 8pt 0; padding: 5pt 10pt; border: 0.6pt solid #e4d28a; border-left: 4pt solid #c9a227; border-radius: 3pt; background: #fbf7e6; }
hr { border: none; border-top: 0.8pt solid #c5d3ea; margin: 12pt 0; }
img.diagram { display: block; margin: 8pt auto; max-width: 100%; max-height: 190mm; break-inside: avoid; }

/* Kapitel laufen standardmaessig fortlaufend; der erste Abschnitt und der Anhang beginnen auf neuer Seite */
.toc + section.doc, section.appendix { break-before: page; }
section.doc + section.doc { margin-top: 30pt; }

.cover { text-align: center; box-sizing: border-box; height: 250mm; padding-top: 38mm; overflow: hidden; break-after: page; }
.cover .band { height: 7mm; margin: 0; background: linear-gradient(90deg, #1f3f73, #2b5797 60%, #6f9ad6); }
.cover .band.bottom { margin-top: 24mm; }
.cover h1 { font-size: 30pt; margin: 22mm 0 4mm; padding: 0; border: none; color: #1f3f73; string-set: none; }
.cover h1::before { display: none; }
.cover .sub { font-size: 14pt; color: #555; }
.cover .rule { width: 40mm; height: 0; margin: 10mm auto 0; border-top: 2pt solid #c9a227; }
.cover .meta { display: inline-block; margin-top: 26mm; padding: 6pt 22pt; color: #444; font-size: 10pt;
               border: 0.8pt solid #9db4d8; border-radius: 4pt; background: #f5f7fb; line-height: 1.7; }

.toc { break-before: page; }
.toc h1 { string-set: doctitle "Inhaltsverzeichnis"; }
.toc ol { list-style: none; padding: 0; counter-reset: t; }
.toc li { counter-increment: t; margin: 5pt 0; padding: 5pt 10pt; border: 0.6pt solid #cfd9ea;
          border-left: 3.5pt solid #2b5797; border-radius: 3pt; background: #f9fbfe; break-inside: avoid; }
.toc li::before { content: counter(t) "."; display: inline-block; width: 18pt; color: #2b5797; font-weight: 600; }
.toc a::after { content: leader('.') target-counter(attr(href), page); }
.appendix h3 { font-family: 'DejaVu Sans Mono', monospace; font-size: 9.5pt; }
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Liefert Dateien aus dem Arbeitsordner; /hold.js verzögert das Laden künstlich."""

    def do_GET(self):
        if self.path.startswith("/hold.js"):
            time.sleep(HOLD_SECONDS)
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(b"/* hold */")
            return
        super().do_GET()

    def log_message(self, *a):
        pass


class MermaidRenderer:
    def __init__(self, workdir: Path):
        self.work = workdir
        (self.work / "mermaid.min.js").write_bytes(MERMAID_JS.read_bytes())
        handler = lambda *a, **k: _Handler(*a, directory=str(self.work), **k)  # noqa: E731
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.profile = self.work / "ffprofile"
        self.profile.mkdir()
        (self.profile / "user.js").write_text(
            'user_pref("layout.css.devPixelsPerPx", "2.0");\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
        )

    def render(self, code: str, idx: int) -> bytes:
        page = self.work / f"d{idx}.html"
        page.write_text(
            "<!doctype html><html><head><meta charset='utf-8'><style>"
            "body{margin:0;padding:12px;background:#fff;width:820px;font-family:'Liberation Sans',sans-serif}"
            "</style></head><body><pre class='mermaid'>" + html.escape(code) + "</pre>"
            "<script src='mermaid.min.js'></script>"
            "<script>mermaid.initialize({startOnLoad:false,theme:'default',securityLevel:'loose',"
            "flowchart:{htmlLabels:true,useMaxWidth:true},sequence:{useMaxWidth:true}});"
            "mermaid.run({querySelector:'.mermaid'});</script>"
            "<script src='/hold.js'></script></body></html>",
            encoding="utf-8",
        )
        shot = self.work / f"d{idx}.png"
        subprocess.run(
            ["firefox", "--headless", "--no-remote", "--profile", str(self.profile),
             "--screenshot", str(shot), "--window-size=860,2200",
             f"http://127.0.0.1:{self.port}/d{idx}.html"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
        )
        img = Image.open(shot).convert("RGB")
        bbox = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255))).getbbox()
        if not bbox or (bbox[2] - bbox[0]) < 60:
            raise RuntimeError(f"Diagramm {idx} wurde nicht gerendert (leeres Bild)")
        pad = 16
        box = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
               min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height))
        if bbox[3] >= img.height - 2:
            raise RuntimeError(f"Diagramm {idx} ist höher als das Renderfenster")
        out = io.BytesIO()
        img.crop(box).save(out, "PNG", optimize=True)
        return out.getvalue()

    def close(self):
        self.server.shutdown()


def collect_files(repo: Path):
    files = []
    if (repo / "README.md").exists():
        files.append("README.md")
    files += sorted(str(p.relative_to(repo)) for p in (repo / "docs").glob("*.md"))
    files += sorted(str(p.relative_to(repo)) for p in (repo / "docs").glob("adr/*.md"))
    for d in ("config", "templates"):
        if (repo / d / "README.md").exists():
            files.append(f"{d}/README.md")
    return files


def doc_id(rel: str) -> str:
    return "doc-" + re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-")


def git_info(repo: Path) -> str:
    try:
        h = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        return f"Commit {h}" + (" (mit uncommitteten Änderungen)" if dirty else "")
    except Exception:
        return "ohne Git-Stand"


PAGE_PER_DOC_CSS = "section.doc { break-before: page; } section.doc + section.doc { margin-top: 0; }"


def add_frame(pdf: Path) -> bool:
    """Zeichnet auf jede Seite einen Doppelrahmen (aussen kraeftig, innen fein).

    Kopf- und Fusszeile (WeasyPrint-Randboxen) liegen innerhalb des Rahmens. Fehlt PyMuPDF,
    bleibt das PDF ohne Rahmen (sonst unveraendert).
    """
    try:
        import pymupdf
    except ImportError:
        print("Hinweis: pymupdf fehlt, PDF entsteht ohne Seitenrahmen (pip install pymupdf)")
        return False
    doc = pymupdf.open(str(pdf))
    for page in doc:
        r = page.rect
        outer = pymupdf.Rect(r.x0 + 20, r.y0 + 20, r.x1 - 20, r.y1 - 20)
        inner = pymupdf.Rect(outer.x0 + 4, outer.y0 + 4, outer.x1 - 4, outer.y1 - 4)
        page.draw_rect(outer, color=(0.122, 0.247, 0.451), width=1.4, radius=0.012)
        page.draw_rect(inner, color=(0.616, 0.706, 0.847), width=0.4, radius=0.01)
    tmp = pdf.with_suffix(".tmp.pdf")
    doc.save(str(tmp), garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--page-per-doc", action="store_true",
                    help="jedes Dokument beginnt auf einer neuen Seite (Standard: fortlaufend, kompakter)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    files = collect_files(repo)
    ids = {f: doc_id(f) for f in files}

    with tempfile.TemporaryDirectory(prefix="bp-pdf-") as tmp:
        renderer = MermaidRenderer(Path(tmp))
        sections, toc = [], []
        n = 0
        try:
            for rel in files:
                text = (repo / rel).read_text(encoding="utf-8")
                md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"])
                body = md.convert(text)

                def fit_scale(png_bytes):
                    # Faktor, mit dem das Bild in den Satzspiegel (174 x 190 mm bei 192 dpi) passt
                    w, h = Image.open(io.BytesIO(png_bytes)).size
                    return min(1315 / w, 1437 / h)

                def diagram(m):
                    nonlocal n
                    n += 1
                    code = html.unescape(m.group(1))
                    png = renderer.render(code, n)
                    # Breite "flowchart LR"-Diagramme zusätzlich hochkant rendern, größere Variante nehmen
                    if re.match(r"\s*flowchart LR", code):
                        alt = renderer.render(re.sub(r"flowchart LR", "flowchart TB", code, count=1), 1000 + n)
                        if fit_scale(alt) > fit_scale(png) * 1.15:
                            png = alt
                    b64 = base64.b64encode(png).decode()
                    return f'<img class="diagram" alt="Diagramm {n}" src="data:image/png;base64,{b64}">'

                body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>', diagram, body, flags=re.S)

                def link(m):
                    href, label = m.group(1), m.group(2)
                    if re.match(r"^(https?:|mailto:)", href):
                        return m.group(0)
                    target = os.path.normpath(os.path.join(os.path.dirname(rel), href.split("#")[0]))
                    if target in ids:
                        return f'<a href="#{ids[target]}">{label}</a>'
                    return label

                body = re.sub(r'<a href="([^"]*)">(.*?)</a>', link, body, flags=re.S)
                title_m = re.search(r"<h1>(.*?)</h1>", body, flags=re.S)
                title = re.sub(r"<[^>]+>", "", title_m.group(1)) if title_m else rel
                toc.append((ids[rel], title, rel))
                sections.append(f'<section class="doc" id="{ids[rel]}">{body}</section>')
        finally:
            renderer.close()

        appendix = ""
        for d in ("config", "templates"):
            base = repo / d
            if base.is_dir():
                items = []
                for p in sorted(base.rglob("*")):
                    if p.is_file() and p.name != "README.md":
                        items.append(f"<h3>{html.escape(str(p.relative_to(repo)))}</h3>"
                                     f"<pre><code>{html.escape(p.read_text(encoding='utf-8'))}</code></pre>")
                if items:
                    appendix = ('<section class="doc appendix" id="anhang"><h1>Anhang: Konfigurationsdateien</h1>'
                                + "".join(items) + "</section>")
                    toc.append(("anhang", "Anhang: Konfigurationsdateien", d + "/"))

        toc_html = ('<section class="toc"><h1>Inhaltsverzeichnis</h1><ol>'
                    + "".join(f'<li><a href="#{i}">{html.escape(t)}</a></li>' for i, t, _ in toc)
                    + "</ol></section>")
        cover = (f'<section class="cover"><div class="band"></div><h1>{html.escape(args.title)}</h1>'
                 f'<div class="sub">{html.escape(args.subtitle)}</div><div class="rule"></div>'
                 f'<div class="meta">Stand: {datetime.date.today():%d.%m.%Y}<br>{html.escape(git_info(repo))}</div>'
                 f'<div class="band bottom"></div></section>')
        extra_css = PAGE_PER_DOC_CSS if args.page_per_doc else ""
        doc = (f'<!doctype html><html lang="de"><head><meta charset="utf-8"><title>{html.escape(args.title)}</title>'
               f"<style>{CSS}{extra_css}</style></head><body>{cover}{toc_html}{''.join(sections)}{appendix}</body></html>")
        HTML(string=doc, base_url=str(repo)).write_pdf(str(out))
        add_frame(out)
    print(f"PDF: {out} ({out.stat().st_size // 1024} KB), {len(files)} Dokumente, {n} Diagramme")


if __name__ == "__main__":
    main()
