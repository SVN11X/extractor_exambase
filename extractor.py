#!/usr/bin/env python3
"""Exportador de preguntas ExamBase. Python 3.10+, sin paquetes adicionales.

Lee los datos que la página entrega públicamente en su HTML; no ejecuta el
JavaScript recibido. Conserva los originales y no deduce respuestas ausentes.
"""
from __future__ import annotations

import argparse
import copy
import base64
import copy
import hashlib
import html
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://www.exambase.com/exams/google/professional-data-engineer/practice-questions/{page}"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".avif"}
HTML_TAGS = set('a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol optgroup option output p param picture pre progress q rp rt ruby s samp script search section select slot small source span strong style sub summary sup table tbody td template textarea tfoot th thead time title tr track u ul var video wbr svg path g circle rect ellipse line polyline polygon defs text tspan use symbol foreignobject mask clippath lineargradient radialgradient stop filter'.split())


def literal_markers(fragment):
    return sorted({m.group(1) for m in re.finditer(r'<([A-Za-z][\w:-]*)\s*>', str(fragment or '')) if m.group(1).lower() not in HTML_TAGS})


class ExtractionError(Exception):
    pass


class AccessStopped(ExtractionError):
    def __init__(self, message, *, kind="access_blocked", code=None, page=None, url=None):
        super().__init__(message)
        self.detail = {"kind": kind, "code": code, "page": page, "url": url,
                       "message": str(message), "automatic_retry": False}


class ChallengeRequired(AccessStopped):
    pass


class LiteralReader:
    """Lector acotado de literales JS, sin eval, exec ni navegador.

    Acepta objetos, listas, strings, números, booleanos, null y void 0.
    Rechaza llamadas, referencias, funciones y cualquier expresión ejecutable.
    """

    def __init__(self, text: str, pos: int = 0):
        self.text, self.pos = text, pos

    def ws(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def string(self):
        quote, start = self.text[self.pos], self.pos
        self.pos += 1
        escaped = False
        while self.pos < len(self.text):
            c = self.text[self.pos]
            self.pos += 1
            if c == quote and not escaped:
                raw = self.text[start:self.pos]
                if quote == '"':
                    return json.loads(raw)
                # Las exportaciones Svelte usan comillas dobles. Se aceptan
                # simples sin introducir un intérprete de expresiones.
                body = raw[1:-1]
                body = body.replace('"', '\\"').replace("\\'", "'")
                return json.loads('"' + body + '"')
            if c == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        raise ExtractionError("String sin cierre en los datos de la página")

    def value(self, depth=0):
        if depth > 100:
            raise ExtractionError("Datos anidados en exceso")
        self.ws()
        if self.pos >= len(self.text):
            raise ExtractionError("Literal incompleto")
        c = self.text[self.pos]
        if c in '\"\'':
            return self.string()
        if c == "{":
            self.pos += 1
            result = {}
            while True:
                self.ws()
                if self.pos < len(self.text) and self.text[self.pos] == "}":
                    self.pos += 1
                    return result
                if self.pos < len(self.text) and self.text[self.pos] in '\"\'':
                    key = self.string()
                else:
                    m = re.match(r"[A-Za-z_$][\w$]*", self.text[self.pos:])
                    if not m:
                        raise ExtractionError("Clave de objeto no admitida")
                    key = m.group(0)
                    self.pos += len(key)
                self.ws()
                if self.text[self.pos:self.pos + 1] != ":":
                    raise ExtractionError("Falta ':' en un objeto")
                self.pos += 1
                if key in result:
                    raise ExtractionError("Clave repetida en un objeto")
                result[key] = self.value(depth + 1)
                self.ws()
                sep = self.text[self.pos:self.pos + 1]
                if sep == "}":
                    self.pos += 1
                    return result
                if sep != ",":
                    raise ExtractionError("Separador no admitido en objeto")
                self.pos += 1
        if c == "[":
            self.pos += 1
            result = []
            while True:
                self.ws()
                if self.text[self.pos:self.pos + 1] == "]":
                    self.pos += 1
                    return result
                result.append(self.value(depth + 1))
                self.ws()
                sep = self.text[self.pos:self.pos + 1]
                if sep == "]":
                    self.pos += 1
                    return result
                if sep != ",":
                    raise ExtractionError("Separador no admitido en lista")
                self.pos += 1
        for word, value in (("true", True), ("false", False), ("null", None), ("undefined", None)):
            m = re.match(re.escape(word) + r"\b", self.text[self.pos:])
            if m:
                self.pos += len(word)
                return value
        m = re.match(r"void\s+0\b", self.text[self.pos:])
        if m:
            self.pos += len(m.group(0))
            return None
        m = re.match(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?", self.text[self.pos:])
        if m:
            self.pos += len(m.group(0))
            return json.loads(m.group(0))
        raise ExtractionError("Se encontró una expresión JS; no se ejecutará")


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Any = None

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def outer(self):
        if self.tag == "root":
            return self.inner()
        attrs = "".join(f' {k}="{html.escape(v or "", quote=True)}"' for k, v in self.attrs.items())
        if self.tag in VOID_TAGS:
            return f"<{self.tag}{attrs}>"
        return f"<{self.tag}{attrs}>{self.inner()}</{self.tag}>"

    def inner(self):
        return "".join(c.outer() if isinstance(c, Node) else html.escape(c) for c in self.children)


class TreeReader(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def readable(fragment):
    # Un marcador como <sensorid> no es una etiqueta HTML de presentación.
    # Conserva su forma capturada, sin inventar valores ni restaurar mayúsculas.
    fragment = re.sub(r'<([A-Za-z][\w:-]*)\s*>', lambda m: html.escape(m.group(0)) if m.group(1).lower() not in HTML_TAGS else m.group(0), str(fragment or ''))
    root = TreeReader(str(fragment or "")).root

    def render(node):
        if isinstance(node, str):
            return node
        if node.tag in {"script", "style"}:
            return ""
        if node.tag == "br":
            return "\n"
        if node.tag == "img":
            return " [Imagen: " + (node.attrs.get("alt") or "sin descripción") + "] "
        content = "".join(render(c) for c in node.children)
        if node.tag == "a" and node.attrs.get("href"):
            return content + " (" + node.attrs["href"] + ")"
        if node.tag in {"td", "th"}:
            return content.strip() + "\t"
        if node.tag == "li":
            return "\n• " + content.strip() + "\n"
        if node.tag in {"p", "div", "tr", "table", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}:
            return "\n" + content.strip() + "\n"
        return content

    text = render(root).replace("\xa0", " ")
    text = "\n".join(re.sub(r"[ \r\f\v]+", " ", line).strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def canonical_url(root, fallback):
    for n in root.walk():
        if n.tag == "link" and n.attrs.get("rel") == "canonical":
            return urllib.parse.urljoin(fallback, n.attrs.get("href", ""))
    return fallback


def dom_choice_is_correct(value):
    node=TreeReader(value).root if isinstance(value,str) else value
    for item in node.walk():
        if item.has_class('list-group-item'):
            if item.attrs.get('data-correct')=='true' or item.attrs.get('data-is-correct')=='true' or item.attrs.get('aria-label','').strip().lower() in {'correct','correct answer'}:return True
        if item.tag not in {'span','small'}:continue
        parent=item.parent
        in_content=False
        while parent and parent is not node:
            if parent.has_class('exambase-question__rich-text'):in_content=True;break
            parent=parent.parent
        if not in_content and item.text().strip().lower() in {'correct','correct answer'}:return True
    return False


def parse_page(source, fallback_url=DEFAULT_URL.format(page=1)):
    tree = TreeReader(source).root
    url = canonical_url(tree, fallback_url)
    errors = []
    has_cards = any(n.has_class("card-title") and re.fullmatch(r"Question\s+\d+", n.text().strip(), re.I) for n in tree.walk())
    # Preferir el objeto 'data' completo: incluye discusiones y todos los
    # contextos, además de alternativas y marcas explícitas de respuesta.
    for script in (n for n in tree.walk() if n.tag == "script"):
        text = script.text()
        patterns = [
            r'(?:\bdata|"data")\s*:\s*(\{\s*(?:result|"result")\s*:)',
            r'(?:\bresult|"result")\s*:\s*(\{)',
        ]
        for level, pattern in enumerate(patterns):
            for m in re.finditer(pattern, text):
                try:
                    obj = LiteralReader(text, m.start(1)).value()
                    payload = obj if level == 0 else {"result": obj}
                    result = payload.get("result", {})
                    if result.get("kind") == "captcha_required" and not has_cards:
                        raise ChallengeRequired("La página requiere verificación humana de Cloudflare Turnstile. Usa DESCARGAR_70_PAGINAS.cmd (modo navegador), completa la verificación y continúa.")
                    if result.get("kind") == "questions" and isinstance(result.get("items"), list):
                        return {"url": url, "parser": "structured", "payload": payload, "warnings": []}
                except ChallengeRequired:
                    raise
                except (ExtractionError, ValueError, RecursionError, IndexError) as e:
                    errors.append(str(e))
    # El archivo guardado por el navegador puede contener sólo el DOM y un
    # script inicial de otra ruta. Recuperar el texto, pero no inventar claves.
    items = []
    for title in tree.walk():
        if title.tag not in {"h3", "h4", "h5"}:
            continue
        m = re.fullmatch(r"Question\s+(\d+)", title.text().strip(), re.I)
        if not m:
            continue
        card = title.parent
        while card is not None and not card.has_class("card"):
            card = card.parent
        if card is None:
            continue
        rich = [n for n in card.walk() if n.has_class("exambase-question__rich-text")]
        if not rich:
            continue
        choices = []
        for li in card.walk():
            if not li.has_class("list-group-item"):
                continue
            label = next((n.text().strip() for n in li.walk() if n.tag == "span" and re.fullmatch("[A-Z]", n.text().strip())), None)
            body = next((n for n in li.walk() if n.has_class("exambase-question__rich-text")), None)
            if label and body:
                correct = dom_choice_is_correct(li)
                choices.append({"letter": label, "text": body.inner(), "is_correct": True if correct else None})
        explanation = ""
        for header in card.walk():
            if header.has_class("card-header") and header.text().strip() == "Explanation":
                block = next((n for n in header.parent.walk() if n.has_class("exambase-question__rich-text")), None)
                if block:
                    explanation = block.inner()
        topic = next((n.text().strip() for n in card.walk() if n.has_class("card-subtitle")), "")
        items.append({"id": None, "order": int(m.group(1)), "question_text": rich[0].inner(), "solution_text": explanation, "choices": choices, "type_data": {}, "topic_label": topic, "_dom_card_html": card.outer()})
    if not items:
        headings = [n.text().strip().lower() for n in tree.walk() if n.tag in {"h1", "h2", "h3", "h4", "h5", "title"}]
        if any("checking that you're human" in h or "verify you are human" in h or "just a moment" in h for h in headings):
            raise ChallengeRequired("Cloudflare está mostrando una verificación humana. Usa el modo navegador para completarla manualmente.")
        raise ExtractionError("No se encontraron preguntas. Puede ser un bloqueo, una página distinta o un cambio de estructura. " + "; ".join(errors[:2]))
    page_num = re.search(r"/practice-questions/(\d+)", url)
    text = readable(source)
    counts = re.search(r"Showing\s+(?:\d+\s*(?:[-–]|to)\s*)?\d+\s+of\s+(\d+)\s*[·•]\s*page\s+(\d+)\s+of\s+(\d+)", text)
    return {"url": url, "parser": "dom", "warnings": ["El HTML guardado no conserva el objeto de respuestas. Las claves ausentes quedan pendientes; no se deducen de la explicación."], "payload": {"result": {"kind": "questions", "page": int(counts.group(2)) if counts else int(page_num.group(1)) if page_num else None, "total": int(counts.group(1)) if counts else None, "total_pages": int(counts.group(3)) if counts else None, "items": items, "topics": [], "series": [], "case_studies": []}}}


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Downloader:
    def __init__(self, delay=2.0, timeout=45.0, retries=3):
        self.delay, self.timeout, self.retries = delay, timeout, retries
        self.last_request = 0.0
        self.opener = urllib.request.build_opener()

    def get(self, url):
        for attempt in range(self.retries + 1):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            req = urllib.request.Request(url, headers={"User-Agent": "AuthorizedStudyArchive/1.0", "Accept": "text/html,application/json,image/*;q=0.9,*/*;q=0.5"})
            self.last_request = time.monotonic()
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    return response.read(), response.headers.get("Content-Type", ""), response.headers.get_content_charset() or "utf-8"
            except urllib.error.HTTPError as e:
                if e.code in {401, 403}:
                    raise AccessStopped(f"HTTP {e.code}: se detuvo la descarga; solicita una exportación al dueño o usa archivos guardados.") from e
                if e.code == 429:
                    if attempt == self.retries:
                        raise AccessStopped("HTTP 429 persistente: descarga detenida para respetar el límite del servidor.") from e
                    wait = e.headers.get("Retry-After", "")
                    time.sleep(min(60, max(self.delay, float(wait) if wait.isdigit() else 5 * 2 ** attempt)))
                elif 500 <= e.code < 600 and attempt < self.retries:
                    time.sleep(min(20, 2 ** attempt))
                else:
                    raise ExtractionError(f"HTTP {e.code} al descargar {url}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt == self.retries:
                    raise ExtractionError(f"No se pudo descargar {url}: {e}") from e
                time.sleep(min(20, 2 ** attempt))
        raise ExtractionError("Se agotaron los intentos")


def scan_images(value, field_path=""):
    """Incluye enunciados, alternativas, solución, type_data y contextos."""
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith("_dom_card"):
                continue
            found.extend(scan_images(v, f"{field_path}.{k}".strip(".")))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(scan_images(v, f"{field_path}[{i}]"))
    elif isinstance(value, str):
        if "<" in value:
            for node in TreeReader(value).root.walk():
                if node.tag in {"img", "image", "source"}:
                    src = node.attrs.get("data-original") or node.attrs.get("data-src") or node.attrs.get("src") or node.attrs.get("href") or node.attrs.get("xlink:href")
                    if not src and node.attrs.get("srcset"):
                        src = node.attrs["srcset"].split(",")[-1].strip().split()[0]
                    if src:
                        found.append({"source": html.unescape(src), "field": field_path, "alt": node.attrs.get("alt", "")})
                if node.tag == "svg":
                    # Mantener también el diagrama vectorial original.
                    svg = node.outer()
                    found.append({"source": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(), "field": field_path, "alt": "SVG incluido en el contenido"})
        last = field_path.split(".")[-1].lower()
        if value.startswith("data:image/") or (re.match(r"^(?:https?://|/|\.\.?/)", value) and (Path(urllib.parse.urlsplit(value).path).suffix.lower() in IMAGE_EXTS or any(k in last for k in ("image_url", "imageurl", "image_src")) or last in {"image", "images", "img", "src", "answer_image", "question_image"})):
            found.append({"source": value, "field": field_path, "alt": ""})
    return found


def image_address(source, base_url, local_source=None):
    if source.startswith("data:image/"):
        return source
    if local_source and not urllib.parse.urlsplit(source).scheme and not source.startswith("/"):
        parent = Path(local_source).resolve().parent
        candidate = (parent / urllib.parse.unquote(source.split("?")[0])).resolve()
        if candidate.is_relative_to(parent) and candidate.is_file():
            return candidate.as_uri()
    url = urllib.parse.urljoin(base_url, source)
    if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
        raise ExtractionError("Referencia de imagen no admitida")
    return url


class AssetStore:
    def __init__(self, output, downloader=None, ocr="auto", tesseract=None, ocr_language="eng"):
        self.output, self.downloader = Path(output), downloader
        self.assets = {}
        self.ocr_language = ocr_language
        self.tesseract = tesseract or shutil.which("tesseract")
        if not self.tesseract:
            for base in (Path("C:/Program Files/Tesseract-OCR"), Path("C:/Program Files (x86)/Tesseract-OCR")):
                if (base / "tesseract.exe").is_file():
                    self.tesseract = str(base / "tesseract.exe")
                    break
        self.ocr_enabled = ocr != "off" and bool(self.tesseract)
        self.explicit_ocr_missing = ocr == "on" and not self.tesseract

    def add(self, ref, base_url, local_source=None):
        try:
            address = image_address(ref["source"], base_url, local_source)
        except ExtractionError as e:
            address = ref["source"]
            failed = str(e)
        else:
            failed = None
        key = hashlib.sha256(address.encode()).hexdigest()[:20]
        if key in self.assets:
            return key
        item = {"id": key, "source_url": address, "alt": ref.get("alt", ""), "download_status": "pending", "ocr_status": "pending", "review_required": True}
        self.assets[key] = item
        try:
            if failed:
                raise ExtractionError(failed)
            content_type = ""
            if address.startswith("data:image/"):
                header, data = address.split(",", 1)
                content_type = header[5:].split(";")[0]
                body = base64.b64decode(data, validate=True) if ";base64" in header else urllib.parse.unquote_to_bytes(data)
            elif address.startswith("file:"):
                path = Path(urllib.request.url2pathname(urllib.parse.urlsplit(address).path))
                body = path.read_bytes()
                content_type = mimetypes.guess_type(path.name)[0] or ""
            elif self.downloader:
                body, content_type, _ = self.downloader.get(address)
            else:
                raise ExtractionError("Imagen remota pendiente: usa --fetch-images o el modo de descarga")
            suffix = Path(urllib.parse.urlsplit(address).path).suffix.lower()
            mime = content_type.split(";")[0].lower()
            if suffix not in IMAGE_EXTS:
                suffix = mimetypes.guess_extension(mime) or ".bin"
            if suffix == ".jpe":
                suffix = ".jpg"
            if mime.startswith("text/") and mime != "image/svg+xml":
                raise ExtractionError("La URL de la imagen devolvió texto en lugar de una imagen")
            if not body:
                raise ExtractionError("La imagen está vacía")
            relative = f"imagenes/{key}{suffix}"
            path = self.output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            item.update(local_path=relative, download_status="downloaded", sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), content_type=content_type)
            self.run_ocr(path, item)
        except AccessStopped:
            item.update(download_status="failed", error="El servidor requiere detener la descarga")
            raise
        except (ExtractionError, ValueError, OSError) as e:
            item.update(download_status="failed", error=str(e), ocr_status="not_run")
        return key

    def run_ocr(self, path, item):
        if not self.ocr_enabled:
            item["ocr_status"] = "not_installed" if not self.tesseract else "disabled"
            return
        if path.suffix.lower() in {".svg", ".avif", ".webp", ".bin"}:
            item["ocr_status"] = "format_needs_review"
            return
        try:
            run = subprocess.run([self.tesseract, str(path), "stdout", "-l", self.ocr_language], capture_output=True, timeout=120, check=False)
            if run.returncode:
                item.update(ocr_status="failed", ocr_error=run.stderr.decode("utf-8", "replace")[-1000:])
                return
            text = run.stdout.decode("utf-8", "replace").strip()
            item.update(ocr_status="extracted_unverified" if text else "no_text_detected", ocr_text=text)
            target = self.output / f"ocr/{item['id']}.txt"
            target.parent.mkdir(exist_ok=True)
            target.write_text(text + "\n", encoding="utf-8")
            item["ocr_path"] = target.relative_to(self.output).as_posix()
        except (OSError, subprocess.TimeoutExpired) as e:
            item.update(ocr_status="failed", ocr_error=str(e))


def normalized_question(raw, page, source_label):
    choices = []
    for c in raw.get("choices") or []:
        choices.append({"id": c.get("id"), "letter": c.get("letter"), "html": c.get("text", ""), "text": readable(c.get("text", "")), "is_correct": c.get("is_correct")})
    correct = [c["letter"] for c in choices if c["is_correct"] is True]
    from reference_support import question_refs
    contexts = question_refs(raw)
    return {"id": raw.get("id"), "number": raw.get("order"), "question_type": raw.get("question_type"), "question_html": raw.get("question_text", ""), "question_text": readable(raw.get("question_text", "")), "choices": choices, "correct_choices": correct, "answer_status": "explicit_choices" if correct else "answer_image" if raw.get("answer_image_url") else "missing_or_special_format", "explanation_html": raw.get("solution_text", ""), "explanation_text": readable(raw.get("solution_text", "")), "answer_image_url": raw.get("answer_image_url"), "type_data": raw.get("type_data", {}), "context_refs": contexts, "image_refs": [], "sources": [{"page": page["payload"]["result"].get("page"), "url": page["url"], "parser": page["parser"], "file": source_label}], "raw": raw}


def content_identity(q):
    return (q.get("question_text", ""), tuple((c.get("letter"), c.get("text")) for c in q["choices"]))


class Archive:
    def __init__(self, output, assets, exam=None):
        self.output, self.assets = Path(output), assets
        self.exam = exam or {"name": "Professional Data Engineer"}
        self.questions = {}
        self.contexts = {}
        self.pages = []
        self.conflicts = []
        self.errors = []
        self.duplicates = 0
        self.observed_totals = set()
        self.observed_page_totals = set()

    def add_page(self, page, label, local_source=None):
        from reference_support import attach_contexts
        page=attach_contexts(page,page['payload'])
        result = page["payload"]["result"]
        for key, dest in (("total", self.observed_totals), ("total_pages", self.observed_page_totals)):
            if isinstance(result.get(key), int):
                dest.add(result[key])
        self.pages.append({"page": result.get("page"), "url": page["url"], "file": label, "parser": page["parser"], "question_count": len(result.get("items", [])), "warnings": page.get("warnings", [])})
        tag = f"pagina_{result.get('page') or 'desconocida'}_{len(self.pages):03}"
        write_json(self.output / "datos_originales" / f"{tag}.json", page["payload"])
        for kind in ("topics", "series", "case_studies", "objects"):
            group = result.get(kind) or []
            if isinstance(group, dict):
                group = list(group.values())
            for context in group:
                if not isinstance(context, dict):
                    continue
                key = context.get('_object_key') or f"{kind}:{context.get('id')}"
                context={k:v for k,v in context.items() if k not in {'_object_key','_object_kind'}}
                old = self.contexts.get(key)
                if old and old["raw"] != context:
                    self.conflicts.append({"context": key, "issue": "Distinto contenido para el mismo contexto", "page": result.get("page")})
                if not old:
                    refs = []
                    for ref in scan_images(context):
                        refs.append({**ref, "asset_id": self.assets.add(ref, page["url"], local_source)})
                    self.contexts[key] = {"key": key, "raw": context, "image_refs": refs}
        for raw in result.get("items", []):
            q = normalized_question(raw, page, label)
            if not isinstance(q["number"], int) or q["number"] < 1:
                self.errors.append({"source": label, "issue": "Pregunta sin número válido", "raw_id": raw.get("id")})
                continue
            for ref in scan_images(raw):
                q["image_refs"].append({**ref, "asset_id": self.assets.add(ref, page["url"], local_source)})
            previous = self.questions.get(q["number"])
            if not previous:
                self.questions[q["number"]] = q
                continue
            self.duplicates += 1
            if content_identity(previous) != content_identity(q) or (previous["id"] is not None and q["id"] is not None and previous["id"] != q["id"]):
                self.conflicts.append({"question": q["number"], "issue": "Contenido o identificador distintos para el mismo número", "sources": previous["sources"] + q["sources"]})
            if previous["correct_choices"] and q["correct_choices"] and previous["correct_choices"] != q["correct_choices"]:
                self.conflicts.append({"question": q["number"], "issue": "Respuestas explícitas distintas"})
            sources = previous["sources"] + q["sources"]
            prefer_new=q['sources'][0]['parser'] in {'structured','browser-network'} and previous['sources'][0]['parser'] not in {'structured','browser-network'}
            chosen=copy.deepcopy(q if prefer_new else previous)
            other=previous if prefer_new else q
            if content_identity(previous)==content_identity(q):
                if not chosen['correct_choices'] and other['correct_choices']:
                    chosen['correct_choices']=other['correct_choices'][:]
                    chosen['answer_status']=other['answer_status']
                    for group in (chosen['choices'],chosen['raw'].get('choices') or []):
                        for choice in group:
                            if choice.get('letter') in chosen['correct_choices']:choice['is_correct']=True
                for field in ('explanation_text','explanation_html','answer_image_url'):
                    if not chosen.get(field) and other.get(field):chosen[field]=other[field]
                if not chosen['raw'].get('solution_text') and other['raw'].get('solution_text'):chosen['raw']['solution_text']=other['raw']['solution_text']
                if not chosen['raw'].get('answer_image_url') and other['raw'].get('answer_image_url'):chosen['raw']['answer_image_url']=other['raw']['answer_image_url']
                for ref in other['image_refs']:
                    if ref not in chosen['image_refs']:chosen['image_refs'].append(ref)
            chosen['sources']=sources
            self.questions[q['number']]=chosen

    def report(self, expected=349, expected_pages=70):
        questions = sorted(self.questions.values(), key=lambda q: q["number"])
        numbers = set(self.questions)
        present_pages = {p["page"] for p in self.pages if isinstance(p["page"], int)}
        missing_contexts = [{"question": q["number"], "context": key} for q in questions for key in q["context_refs"] if key not in self.contexts]
        missing_answers = [q["number"] for q in questions if q["answer_status"] == "missing_or_special_format"]
        failed_images = [a["id"] for a in self.assets.assets.values() if a["download_status"] != "downloaded"]
        report = {"expected_questions": expected, "questions_extracted": len(questions), "expected_pages": expected_pages, "pages_present": sorted(present_pages), "missing_pages": sorted(set(range(1, expected_pages + 1)) - present_pages), "missing_question_numbers": sorted(set(range(1, expected + 1)) - numbers), "unexpected_question_numbers": sorted(numbers - set(range(1, expected + 1))), "observed_question_totals": sorted(self.observed_totals), "observed_page_totals": sorted(self.observed_page_totals), "duplicate_observations": self.duplicates, "conflicts": self.conflicts, "errors": self.errors, "missing_or_special_answers": missing_answers, "missing_explanations": [q["number"] for q in questions if not q["explanation_text"] and not q["raw"].get("solution_text")], "unresolved_contexts": missing_contexts, "images_found": len(self.assets.assets), "images_failed": failed_images, "images_requiring_review": list(self.assets.assets), "ocr_requested_but_not_installed": self.assets.explicit_ocr_missing}
        report["dom_questions_requiring_context_review"] = [q["number"] for q in questions if "_dom_card_html" in q["raw"]]
        report["collection_complete"] = not any((len(questions) != expected, report["missing_pages"], report["missing_question_numbers"], report["unexpected_question_numbers"], report["conflicts"], report["errors"], missing_answers, report["missing_explanations"], missing_contexts, failed_images, report["dom_questions_requiring_context_review"], self.observed_totals and self.observed_totals != {expected}, self.observed_page_totals and self.observed_page_totals != {expected_pages}))
        # OCR automático no equivale a validar diagramas, código o tablas.
        report["image_transcription_review_complete"] = not bool(self.assets.assets)
        report["notes"] = ["collection_complete comprueba cobertura y conservación; no valida la corrección técnica de las respuestas de ExamBase.", "Se conservan los originales y todas las imágenes detectadas. Cada imagen requiere revisión visual aunque se haya extraído texto mediante OCR.", "Las preguntas de formatos especiales sin clave explícita quedan pendientes; sus datos originales se conservan en raw/type_data."]
        return report

    def save(self, expected=349, expected_pages=70):
        report = self.report(expected, expected_pages)
        data = {"schema_version": "1.0", "exam": self.exam, "generated_at": datetime.now(timezone.utc).isoformat(), "report": report, "questions": sorted(self.questions.values(), key=lambda q: q["number"]), "contexts": self.contexts, "assets": self.assets.assets, "pages": self.pages}
        write_json(self.output / "preguntas.json", data)
        write_json(self.output / "informe_validacion.json", report)
        (self.output / "preguntas.md").write_text(make_markdown(data), encoding="utf-8")
        (self.output / "preguntas.html").write_text(make_html(data), encoding="utf-8")
        return data


def context_text(context):
    parts = []
    for key, value in context["raw"].items():
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}:\n{readable(value)}")
        elif isinstance(value, (dict, list)) and value:
            parts.append(f"{key}:\n{json.dumps(value, ensure_ascii=False, indent=2)}")
    return "\n\n".join(parts)


def image_lines(refs, assets):
    lines, seen = [], set()
    for ref in refs:
        aid = ref["asset_id"]
        if aid in seen:
            continue
        seen.add(aid)
        a = assets[aid]
        lines.append(f"Imagen · {ref.get('field', '')} · {ref.get('alt') or 'sin descripción'}")
        if a.get("local_path"):
            lines.append(f"![Imagen original]({a['local_path']})")
        else:
            lines.append("Descarga pendiente: " + a.get("error", ""))
        lines.append("OCR: " + a["ocr_status"] + " · Revisión visual pendiente.")
        if a.get("ocr_text"):
            lines.append("```text\n" + a["ocr_text"].replace("```", "''' ") + "\n```")
    return lines


def make_markdown(data):
    r = data["report"]
    lines = ["# " + data.get("exam", {}).get("name", "Professional Data Engineer") + " · Archivo de estudio", "", f"Preguntas extraídas: **{r['questions_extracted']} de {r['expected_questions'] if r['expected_questions'] is not None else 'por detectar'}**. Cobertura completa: **{'sí' if r['collection_complete'] else 'no'}**.", "", "Contenido original de los archivos/páginas; las respuestas no se han corregido ni validado técnicamente.", ""]
    if data["contexts"]:
        lines.extend(["## Contextos compartidos", ""])
    for key, context in data["contexts"].items():
        lines.extend([f'<a id="{key.replace(":", "-")}"></a>', f"### {key}", "", context_text(context), ""])
        lines.extend(image_lines(context["image_refs"], data["assets"]))
    for q in data["questions"]:
        lines.extend(["", f"## Pregunta {q['number']}", ""])
        if q["context_refs"]:
            lines.extend(["Contextos: " + ", ".join(f'[{key}](#{key.replace(":", "-")})' for key in q["context_refs"]), ""])
        lines.extend([q["question_text"], ""])
        for c in q["choices"]:
            lines.extend([f"**{c['letter']}.** {c['text']}", ""])
        lines.extend(["**Respuesta indicada por la fuente:** " + (", ".join(q["correct_choices"]) or q["answer_status"]), "", "**Explicación:**", "", q["explanation_text"] or "No incluida en la fuente.", ""])
        lines.extend(image_lines(q["image_refs"], data["assets"]))
    lines.extend(["", "## Validación", "", "Consulta informe_validacion.json para ver omisiones, conflictos y OCR pendiente.", ""])
    return "\n".join(lines)


def make_html(data):
    # No se inserta HTML remoto activo: se muestra texto escapado y recursos
    # locales. El JSON y los datos originales conservan los fragmentos íntegros.
    def paragraph(text):
        return '<div class="rich">' + html.escape(text) + '</div>'

    def pictures(refs):
        pieces, seen = [], set()
        for ref in refs:
            aid = ref["asset_id"]
            if aid in seen:
                continue
            seen.add(aid)
            a = data["assets"][aid]
            if a.get("local_path"):
                pieces.append(f'<figure><img loading="lazy" src="{html.escape(a["local_path"], quote=True)}" alt="{html.escape(ref.get("alt", "Imagen"), quote=True)}"><figcaption>{html.escape(ref["field"])} · OCR: {a["ocr_status"]} · revisión pendiente</figcaption></figure>')
            else:
                pieces.append(paragraph("Imagen pendiente: " + a.get("error", "")))
            if a.get("ocr_text"):
                pieces.append(paragraph("Transcripción automática sin verificar:\n" + a["ocr_text"]))
        return "".join(pieces)

    r = data["report"]
    body = ["<h1>" + html.escape(data.get("exam", {}).get("name", "Professional Data Engineer")) + "</h1>", f"<p class=summary>{r['questions_extracted']} de {r['expected_questions'] if r['expected_questions'] is not None else 'por detectar'} preguntas · Cobertura {'completa' if r['collection_complete'] else 'parcial'}</p>", "<p>Respuestas de la fuente original. No se ha validado su corrección técnica.</p>"]
    for key, context in data["contexts"].items():
        body.append(f'<section id="{html.escape(key.replace(":", "-"), quote=True)}"><h2>Contexto: {html.escape(key)}</h2>{paragraph(context_text(context))}{pictures(context["image_refs"])}</section>')
    for q in data["questions"]:
        part = [f'<article><h2>Pregunta {q["number"]}</h2>']
        for key in q["context_refs"]:
            part.append(f'<p><a href="#{html.escape(key.replace(":", "-"), quote=True)}">Contexto: {html.escape(key)}</a></p>')
        part.append(paragraph(q["question_text"]))
        for c in q["choices"]:
            part.append(paragraph(f"{c['letter']}. {c['text']}"))
        part.extend(["<h3>Respuesta de la fuente</h3>", paragraph(", ".join(q["correct_choices"]) or q["answer_status"]), "<h3>Explicación</h3>", paragraph(q["explanation_text"] or "No incluida."), pictures(q["image_refs"]), "</article>"])
        body.extend(part)
    return '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'unsafe-inline\'"><title>Preguntas · Archivo de estudio</title><style>body{max-width:960px;margin:40px auto;padding:0 24px;color:#172a3a;font:17px/1.65 system-ui,sans-serif;background:#f4f6f9}h1{font-size:34px}h2{font-size:25px}h3{font-size:18px}.summary{font-weight:700}article,section{background:white;border:1px solid #ced9e4;border-radius:14px;padding:26px;margin:24px 0}.rich{white-space:pre-wrap;margin:12px 0;overflow-wrap:anywhere}img{max-width:100%;height:auto}figcaption{font-size:13px;color:#445d72}a{color:#124e9a}@media print{body{background:white;margin:0;max-width:none;font-size:11pt}article,section{border:0;border-top:1px solid #aaa;border-radius:0;padding:12px 0;break-inside:auto}h2,h3{break-after:avoid}figure{break-inside:avoid}}</style><body>' + "".join(body) + "</body></html>"


def create_zip(output):
    target = output.with_name(output.name + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output.parent))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exporta páginas de ExamBase a JSON, Markdown, HTML e imágenes. Sin dependencias externas.")
    parser.add_argument("--input", type=Path, help="HTML/TXT local o carpeta de páginas ya guardadas; sin este argumento descarga las páginas")
    parser.add_argument("--output", type=Path, default=Path("resultado_exambase"))
    parser.add_argument("--url", default=DEFAULT_URL, help="URL con marcador {page}")
    parser.add_argument("--pages", type=int, default=70)
    parser.add_argument("--expected", type=int, default=349)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--fetch-images", action="store_true", help="Permite descargar imágenes remotas también en modo --input")
    parser.add_argument("--ocr", choices=["auto", "on", "off"], default="auto", help="Usa Tesseract si está instalado. OCR siempre queda sin verificar")
    parser.add_argument("--tesseract", help="Ruta de tesseract.exe si no está en PATH")
    parser.add_argument("--ocr-language", default="eng")
    parser.add_argument("--refresh", action="store_true", help="Vuelve a descargar HTML ya almacenado")
    parser.add_argument("--browser", action="store_true", help="Abre un navegador visible; la verificación humana la completa el usuario")
    parser.add_argument("--browser-channel", default="msedge", choices=["msedge", "chrome", "chromium"])
    parser.add_argument("--browser-profile", type=Path, default=Path("perfil_navegador_exambase"))
    parser.add_argument("--zip", action="store_true", help="Crea también resultado_exambase.zip")
    args = parser.parse_args(argv)
    if args.pages < 1 or args.expected < 1 or args.delay < 0 or args.retries < 0:
        parser.error("pages y expected deben ser positivos; delay y retries no pueden ser negativos")
    if "{page}" not in args.url:
        parser.error("--url debe contener {page}")
    args.output.mkdir(parents=True, exist_ok=True)
    downloader = Downloader(args.delay, args.timeout, args.retries)
    assets = AssetStore(args.output, downloader if not args.input or args.fetch_images else None, args.ocr, args.tesseract, args.ocr_language)
    archive = Archive(args.output, assets)
    interrupted = False
    try:
        if args.input:
            if not args.input.exists():
                raise ExtractionError("La ruta --input no existe")
            files = sorted(p for p in (args.input.rglob("*") if args.input.is_dir() else [args.input]) if p.is_file() and p.suffix.lower() in {".html", ".htm", ".txt"} and not p.resolve().is_relative_to(args.output.resolve()))
            if not files:
                raise ExtractionError("No se encontraron archivos HTML o TXT en --input")
            for path in files:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                if not re.search(r"<(?:!doctype|html|script|main)\b", text, re.I):
                    continue
                try:
                    page = parse_page(text)
                    print(f"Archivo: {path.name} -> {len(page['payload']['result']['items'])} preguntas ({page['parser']})", flush=True)
                    archive.add_page(page, path.name, path)
                except AccessStopped:
                    raise
                except ExtractionError as e:
                    archive.errors.append({"source": path.name, "issue": str(e)})
        elif args.browser:
            import browser_support
            browser_support.collect(args, archive, sys.modules[__name__])
        else:
            consecutive_failures = 0
            for number in range(1, args.pages + 1):
                url = args.url.format(page=number)
                cached = args.output / "paginas_originales" / f"pagina_{number:03}.html"
                try:
                    if cached.exists() and not args.refresh:
                        text = cached.read_text(encoding="utf-8")
                    else:
                        body, _, encoding = downloader.get(url)
                        text = body.decode(encoding, "replace")
                    # Conservar también las respuestas de error HTTP 200:
                    # antes se perdía el HTML de verificación de Cloudflare.
                    diagnostic = args.output / "diagnostico" / f"pagina_{number:03}.html"
                    diagnostic.parent.mkdir(exist_ok=True)
                    diagnostic.write_text(text, encoding="utf-8")
                    page = parse_page(text, url)
                    if page["payload"]["result"].get("page") != number:
                        raise ExtractionError(f"Se pidió la página {number}, pero el contenido indica otra página")
                    cached.parent.mkdir(exist_ok=True)
                    cached.write_text(text, encoding="utf-8")
                    archive.add_page(page, f"paginas_originales/{cached.name}")
                    consecutive_failures = 0
                    print(f"Página {number}/{args.pages}: {len(page['payload']['result']['items'])} preguntas; acumuladas {len(archive.questions)}", flush=True)
                except AccessStopped:
                    raise
                except ExtractionError as e:
                    consecutive_failures += 1
                    archive.errors.append({"page": number, "url": url, "issue": str(e)})
                    print(f"PENDIENTE página {number}: {e}", flush=True)
                    # Si la estructura cambió, detenerse antes de repetir el fallo 70 veces.
                    if (number == 1 and not archive.questions) or consecutive_failures >= 2:
                        print("Se detiene la secuencia para no repetir el mismo fallo en las demás páginas.", flush=True)
                        break
    except (AccessStopped, ExtractionError) as e:
        archive.errors.append({"issue": str(e)})
        print(str(e), file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        interrupted = True
        archive.errors.append({"issue": "Descarga interrumpida. Los HTML conservados permiten reanudar ejecutando el mismo comando."})
    data = archive.save(args.expected, args.pages)
    if args.zip:
        print(f"ZIP creado: {create_zip(args.output)}", flush=True)
    report = data["report"]
    print(f"Resultado: {report['questions_extracted']}/{args.expected} preguntas. Cobertura {'COMPLETA' if report['collection_complete'] else 'PARCIAL; consulta informe_validacion.json'}.", flush=True)
    if report["images_found"]:
        print(f"Imágenes: {report['images_found']}; descargas fallidas: {len(report['images_failed'])}. Revisión visual de transcripciones pendiente.", flush=True)
    return 130 if interrupted else 0 if report["collection_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
