#!/usr/bin/env python3
"""Recopilación desatendida: examen por URL, metadatos detectados, pausa segura.

No intenta resolver ni esquivar verificaciones. Conserva un ZIP parcial para
reanudar otra ejecución, sin almacenar perfiles ni cookies del navegador.
"""
from __future__ import annotations
import argparse
import functools
import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import zipfile
from pathlib import Path

import extractor as core

CATALOG = json.loads(Path(__file__).with_name("catalogo.json").read_text(encoding="utf-8"))
EXTERNAL = {urllib.parse.urlsplit(f["href"]).hostname.removeprefix("www.") for f in CATALOG["featured"] if f.get("href")}


def exam_from_url(value):
    p = urllib.parse.urlsplit(value.strip())
    if p.scheme != "https" or p.username or p.password or p.port or not p.hostname:
        raise core.ExtractionError("Usa una URL HTTPS del examen sin credenciales ni puertos.")
    host = p.hostname.removeprefix("www.")
    if host == "exambase.com":
        m = re.fullmatch(r"/exams/([\w.-]+)/([\w.-]+)(?:/practice-questions/\d+)?/?", p.path)
        if not m:
            raise core.ExtractionError("Se necesita la URL de un examen concreto, no el índice de proveedores.")
        vendor, slug = m.groups()
        base = f"https://www.exambase.com/exams/{vendor}/{slug}/practice-questions/"
        key = f"{vendor}/{slug}"
    elif host in EXTERNAL and re.fullmatch(r"/(?:practice-questions/\d+/?)?", p.path or "/"):
        vendor, slug, key = host, host.split(".")[0], host
        base = f"https://{p.netloc}/practice-questions/"
    else:
        raise core.ExtractionError("El dominio no figura en ExamBase ni entre los sitios oficiales del catálogo adjunto.")
    return {"key": key, "vendor": vendor, "slug": slug, "name": slug.replace("-", " "), "base": base}


def detect_counts(exam, page):
    r = page["payload"]["result"]
    total, pages = r.get("total"), r.get("total_pages")
    per_page = r.get("per_page") or (len(r.get("items", [])) if r.get("page") == 1 else None)
    if not all(type(n) is int and n > 0 for n in (total, pages, per_page)) or total > 100000 or pages > 20000 or (total + per_page - 1) // per_page != pages:
        raise core.ExtractionError("No se detectaron totales y paginación coherentes en la primera página.")
    return {**exam, "total": total, "pages": pages, "per_page": per_page}


def validate_page(exam, page, number):
    r = page["payload"]["result"]
    expected = list(range((number - 1) * exam["per_page"] + 1, min(number * exam["per_page"], exam["total"]) + 1))
    orders = [q.get("order") for q in r.get("items", [])]
    if r.get("page") != number or sorted(orders) != expected or len(set(orders)) != len(orders):
        raise core.ExtractionError(f"La página {number} no coincide con su numeración esperada.")
    if r.get("total") not in (None, exam["total"]) or r.get("total_pages") not in (None, exam["pages"]):
        raise core.ExtractionError("El sitio cambió los totales durante la extracción; no se mezclarán versiones.")
    url = urllib.parse.urlsplit(page["url"])
    wanted = urllib.parse.urlsplit(exam["base"])
    if url.hostname.removeprefix("www.") != wanted.hostname.removeprefix("www.") or url.path.rstrip("/") != (wanted.path + str(number)).rstrip("/"):
        raise core.ExtractionError("La página corresponde a otro examen o redirigió fuera de la ruta seleccionada.")


def restore(source, output, exam):
    if source.is_dir():
        files = list(source.rglob("*.zip"))
        if len(files) != 1:
            raise core.ExtractionError("El respaldo debe contener exactamente un ZIP de resultado.")
        source = files[0]
    with zipfile.ZipFile(source) as z:
        manifests = [i for i in z.infolist() if i.filename.endswith("/manifest_examen.json")]
        if len(manifests) != 1:
            raise core.ExtractionError("El ZIP no tiene un manifiesto único de esta herramienta.")
        info = manifests[0]
        meta = json.loads(z.read(info))
        if meta.get("key") != exam["key"] or meta.get("base") != exam["base"]:
            raise core.ExtractionError("El respaldo pertenece a otro examen; no se mezclará con el seleccionado.")
        detect_counts(meta, {"payload": {"result": {"page": 1, "total": meta.get("total"), "total_pages": meta.get("pages"), "per_page": meta.get("per_page"), "items": []}}})
        root = info.filename.rsplit("/", 1)[0] + "/"
        if sum(i.file_size for i in z.infolist()) > 1024**3 or len(z.infolist()) > 50000:
            raise core.ExtractionError("El respaldo supera los límites de importación.")
        for item in z.infolist():
            if item.is_dir():
                continue
            if not item.filename.startswith(root) or "\\" in item.filename:
                raise core.ExtractionError("Ruta inválida en el respaldo.")
            relative = Path(item.filename[len(root):])
            destination = (output / relative).resolve()
            if not relative.parts or ".." in relative.parts or not destination.is_relative_to(output.resolve()) or item.file_size > 30 * 1024**2 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise core.ExtractionError("Archivo o ruta no admitidos en el respaldo.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(z.read(item))
        return meta


class HttpSource:
    def __init__(self, exam, output, delay):
        self.exam, self.output = exam, output
        self.assets = core.Downloader(delay=delay, retries=1)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def page(self, number):
        url = self.exam["base"] + str(number)
        body, _, encoding = self.assets.get(url)
        text = body.decode(encoding, "replace")
        core.write_json(self.output / "ultima_peticion.json", {"url": url, "page": number})
        target = self.output / "paginas_originales" / f"pagina_{number:05}.html"
        target.parent.mkdir(exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return core.parse_page(text, url)


class BrowserSource:
    def __init__(self, exam, output, delay, *, headed=False, patched=False):
        self.exam, self.output, self.delay, self.headed, self.patched = exam, output, delay, headed, patched
    def __enter__(self):
        try:
            if self.patched:
                from rebrowser_playwright.sync_api import sync_playwright
            else:
                from playwright.sync_api import sync_playwright
        except ImportError as exc:
            instructions = 'Instala requirements_rebrowser.txt y Google Chrome estable.' if self.patched else 'Instala requirements_actions.txt y ejecuta python -m playwright install chromium.'
            raise core.ExtractionError(instructions) from exc
        from browser_support import BrowserAssets, choose_page, network_payloads, verification_error
        self.choose_page, self.network_payloads, self.verification_error = choose_page, network_payloads, verification_error
        self.pw = sync_playwright().start()
        try:
            options={'channel':'chrome','args':['--window-size=1366,900']} if self.patched else {}
            self.browser = self.pw.chromium.launch(headless=not self.headed, **options)
            self.context = self.browser.new_context(no_viewport=True) if self.patched else self.browser.new_context()
            self.tab = self.context.new_page()
            self.received = []
            self.last_navigation = 0.0
            self.assets = BrowserAssets(self.context, core, self.delay)
            self.tab.on("response", self.on_response)
            return self
        except Exception:
            self.pw.stop()
            raise
    def __exit__(self, *_):
        try:
            self.browser.close()
        finally:
            self.pw.stop()
    def on_response(self, response):
        if urllib.parse.urlsplit(response.url).hostname != urllib.parse.urlsplit(self.exam["base"]).hostname:
            return
        try:
            if response.ok and "json" in response.headers.get("content-type", ""):
                self.received.extend(self.network_payloads(response.json()))
        except Exception:
            pass
    def page(self, number):
        from browser_support import current_question_page
        url = self.exam["base"] + str(number)
        self.received.clear()
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_navigation)))
        self.last_navigation = time.monotonic()
        followed=False
        if number>1 and self.tab.url.startswith(self.exam['base']):
            for link in self.tab.locator('a[href]').all():
                if urllib.parse.urljoin(self.tab.url,link.get_attribute('href') or '')==url and link.is_visible():
                    link.click();followed=True;break
        if not followed:self.tab.goto(url, wait_until="domcontentloaded", timeout=60000)
        deadline = time.monotonic() + 60
        last = "La página no entregó preguntas."
        while time.monotonic() < deadline:
            text = self.tab.content()
            target = self.output / "paginas_originales" / f"pagina_{number:05}.html"
            target.parent.mkdir(exist_ok=True)
            target.write_text(text, encoding="utf-8")
            current_url = self.tab.url
            preferred = self.choose_page(self.received, number, current_url)
            try:
                page = current_question_page(text, current_url, number, self.exam, preferred)
            except core.ExtractionError as exc:
                last = str(exc)
                page = None
            if page:
                if page["parser"] == "dom":
                    for button in self.tab.get_by_role("button", name="Reveal Answer", exact=True).all():
                        if button.is_visible():
                            button.click()
                    self.tab.wait_for_timeout(600)
                    text = self.tab.content()
                    target.write_text(text, encoding="utf-8")
                    page = current_question_page(text, self.tab.url, number, self.exam, self.choose_page(self.received, number, self.tab.url))
                return page
            failure = self.verification_error(text, core)
            if failure:
                raise core.AccessStopped(f"Cloudflare rechazó la verificación en la página {number} (código {failure}).", kind='verification_rejected', code=failure, page=number, url=current_url)
            self.tab.wait_for_timeout(1000)
        raise core.AccessStopped("La página requiere acceso o verificación que no se completó en 60 segundos. " + last, kind='access_timeout', page=number, url=self.tab.url)


def run(args, source_factory=None):
    exam = exam_from_url(args.exam_url)
    if getattr(args, 'exam_name', None):
        exam['name'] = args.exam_name[:150]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", exam["key"])[:100]
    output = args.output / ("resultado_" + slug)
    output.mkdir(parents=True, exist_ok=True)
    if args.resume_from:
        exam = restore(args.resume_from, output, exam)
    elif (output / "manifest_examen.json").exists():
        meta = json.loads((output / "manifest_examen.json").read_text())
        if meta.get("key") != exam["key"] or meta.get("base") != exam["base"]:
            raise core.ExtractionError("La carpeta de salida pertenece a otro examen.")
        exam = meta
    assets = core.AssetStore(output, ocr="off")
    previous = output / "preguntas.json"
    if previous.exists():
        for key, item in json.loads(previous.read_text(encoding="utf-8")).get("assets", {}).items():
            path = (output / item.get("local_path", "")).resolve()
            if item.get("download_status") == "downloaded" and path.is_relative_to(output.resolve()) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256"):
                assets.assets[key] = item
    archive = core.Archive(output, assets, exam)
    if source_factory:
        factory = source_factory
    elif args.mode in {'flaresolverr-next','flaresolverr','cloudproxy'}:
        from solver_support import SolverSource
        factory=functools.partial(SolverSource,engine=args.mode,endpoint=getattr(args,'solver_url','http://127.0.0.1:8191/v1'))
    elif args.mode == "selenium":
        from selenium_support import SeleniumSource
        factory = functools.partial(SeleniumSource, headed=getattr(args, 'headed', False))
    else:
        factory = functools.partial(BrowserSource, headed=getattr(args, 'headed', False),patched=args.mode=='rebrowser') if args.mode in {'browser','rebrowser'} else HttpSource
    started = time.monotonic()
    stopped = None
    failure = None
    number = 1
    try:
        with factory(exam, output, args.delay) as source:
            assets.downloader = source.assets
            number = 1
            while True:
                if time.monotonic() - started > args.max_minutes * 60:
                    stopped = "Se alcanzó el presupuesto de tiempo; se conserva el progreso para otra ejecución."
                    break
                cache = output / "capturas" / f"pagina_{number:05}.json"
                page = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else source.page(number)
                if number == 1 and "total" not in exam:
                    exam.update(detect_counts(exam, page))
                    archive.exam = exam
                    core.write_json(output / "manifest_examen.json", exam)
                validate_page(exam, page, number)
                core.write_json(cache, page)
                archive.add_page(page, f"capturas/{cache.name}")
                print(f"Página {number}/{exam['pages']}: {len(archive.questions)}/{exam['total']} preguntas", flush=True)
                if number >= exam["pages"] or (args.page_limit and number >= args.page_limit):
                    if number < exam["pages"]:
                        stopped = "Se alcanzó el límite de páginas solicitado; puede reanudarse desde este ZIP."
                    break
                number += 1
    except core.AccessStopped as exc:
        stopped = str(exc)
        failure = {**exc.detail, 'page': exc.detail.get('page') or number, 'url': exc.detail.get('url') or exam['base']+str(number)}
        archive.errors.append({'page': number, 'issue': stopped, 'kind': failure['kind'], 'code': failure['code']})
    except (core.ExtractionError, OSError, ValueError, KeyError, TypeError) as exc:
        stopped = str(exc)
        archive.errors.append({"page": len(archive.pages) + 1, "issue": stopped})
    except KeyboardInterrupt:
        stopped = "Ejecución interrumpida; se conserva lo recuperado en el ZIP parcial."
        archive.errors.append({"issue": stopped})
    except Exception as exc:
        stopped = f"{type(exc).__name__}: {exc}"
        archive.errors.append({"issue": stopped})
    total, pages = exam.get("total", 0), exam.get("pages", 0)
    if "total" not in exam:
        archive.errors.append({"issue": "No se pudo detectar el total del examen. El resultado es parcial."})
    data = archive.save(total, pages)
    report = data["report"]
    if "total" not in exam:
        report["expected_questions"] = None
        report["expected_pages"] = None
    report["coverage_complete"] = bool(exam.get("total")) and len(archive.questions) == total and not report["missing_pages"] and not report["missing_question_numbers"]
    core.write_json(output / "informe_validacion.json", report)
    core.write_json(output / "preguntas.json", data)
    (output / "preguntas.md").write_text(core.make_markdown(data), encoding="utf-8")
    (output / "preguntas.html").write_text(core.make_html(data), encoding="utf-8")
    from paquetes import enrich
    data = enrich(output, ocr=getattr(args, "ocr", False))
    report = data["report"]
    # add_page registra el HTML antes de recuperar imágenes: sólo contar una
    # página cuando se conservaron todas sus preguntas, incluso si falla un recurso.
    saved_pages = [n for n in report['pages_present'] if all(q in archive.questions for q in range((n-1)*exam['per_page']+1, min(n*exam['per_page'], total)+1))]
    next_page = next((p for p in range(1, pages+1) if p not in saved_pages), None) if pages else 1
    success = report["coverage_complete"] and not archive.errors and not report["images_failed"]
    status = 'complete' if success else 'blocked' if failure else 'partial' if saved_pages else 'failed'
    diagnostic = {'status': status, 'failure': failure, 'pages_saved': saved_pages, 'next_page': next_page}
    core.write_json(output / 'diagnostico_acceso.json', diagnostic)
    integrity_path = output / 'integridad_sha256.json'
    integrity = json.loads(integrity_path.read_text(encoding='utf-8'))
    integrity['files']['diagnostico_acceso.json'] = hashlib.sha256((output / 'diagnostico_acceso.json').read_bytes()).hexdigest()
    core.write_json(integrity_path, integrity)
    result_zip = core.create_zip(output)
    state = {"exam": exam, "mode": args.mode, "questions": len(archive.questions), "coverage_complete": report["coverage_complete"], "execution_complete": success, "stopped_reason": stopped, "zip": result_zip.name, "review_pending": not report["collection_complete"], 'status': status, 'failure': failure, 'pages_saved': saved_pages, 'next_page': next_page, 'resume_supported': bool(saved_pages and exam.get('total')), 'runner_environment': os.environ.get('RUNNER_ENVIRONMENT', 'local')}
    core.write_json(args.output / "estado_ejecucion.json", state)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    if failure:
        label = 'Acceso rechazado por el sitio' if failure['kind'] == 'verification_rejected' else 'Acceso sin completar'
        hint = f"{label} en página {failure['page']}; {len(archive.questions)}/{exam.get('total') or '?'} preguntas conservadas. Código: {failure.get('code') or failure['kind']}. El ZIP parcial permite reanudar; repetir con el mismo cliente puede volver a bloquearse."
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            print('::error title='+label+'::'+hint.replace('%','%25').replace('\r','%0D').replace('\n','%0A'), flush=True)
        else:
            print(hint, flush=True)
    return 0 if success else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exam-url", required=True)
    parser.add_argument("--exam-name", help="Nombre para el lector y el historial")
    parser.add_argument("--mode", choices=["http", "browser", "selenium", "rebrowser", "flaresolverr-next", "flaresolverr", "cloudproxy"], default="http")
    parser.add_argument('--solver-url',default=os.environ.get('EXAM_SOLVER_URL','http://127.0.0.1:8191/v1'),help='API v1 del solver local')
    parser.add_argument("--output", type=Path, default=Path("salida"))
    parser.add_argument("--delay", type=float, default=10)
    parser.add_argument("--page-limit", type=int, default=0)
    parser.add_argument("--max-minutes", type=float, default=300)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--ocr", action="store_true", help="Transcribir imágenes con Tesseract, siempre sin verificar")
    parser.add_argument("--headed", action="store_true", help="Navegador visible para browser, rebrowser o selenium; requiere pantalla real o Xvfb")
    args = parser.parse_args(argv)
    if not math.isfinite(args.delay) or not math.isfinite(args.max_minutes) or args.delay < 5 or args.delay > 120 or args.page_limit < 0 or args.max_minutes <= 0:
        parser.error("delay debe estar entre 5 y 120; page-limit no puede ser negativo; max-minutes debe ser positivo")
    try:
        return run(args)
    except (core.ExtractionError, ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
