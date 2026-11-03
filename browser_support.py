"""Navegador visible con verificación humana manual. Sin técnicas de evasión."""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path


def expand_flat_data(values):
    """Decodifica las referencias de datos JSON de Svelte; no ejecuta código.

    Se conserva por separado el JSON original. Tipos especiales quedan como
    datos etiquetados; no se convierten en objetos ejecutables.
    """
    if not isinstance(values, list) or not values:
        return values
    cache, active = {}, set()

    def resolve(index):
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Referencia inválida")
        if index in {-1, -2}:
            return None
        if index == -3:
            return float("nan")
        if index == -4:
            return float("inf")
        if index == -5:
            return float("-inf")
        if index == -6:
            return 0
        if not 0 <= index < len(values) or index in active:
            raise ValueError("Referencia circular o fuera de rango")
        if index in cache:
            return cache[index]
        active.add(index)
        raw = values[index]
        if isinstance(raw, dict):
            obj = {key: resolve(value) for key, value in raw.items()}
        elif isinstance(raw, list):
            if raw and isinstance(raw[0], str):
                obj = {"_type": raw[0], "values": raw[1:]}
            else:
                obj = [resolve(value) for value in raw]
        else:
            obj = raw
        active.remove(index)
        cache[index] = obj
        return obj

    return resolve(0)


def network_payloads(value):
    """Encuentra sólo los datos de preguntas entregados a la pestaña."""
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            result = obj.get("result")
            if isinstance(result, dict) and result.get("kind") == "questions" and isinstance(result.get("items"), list):
                found.append({k: v for k, v in obj.items() if k in {"result", "page", "discussions", "topicId"}})
                return
            if obj.get("kind") == "questions" and isinstance(obj.get("items"), list):
                found.append({"result": obj})
                return
            if obj.get("type") == "data" and isinstance(obj.get("data"), list):
                try:
                    walk(expand_flat_data(obj["data"]))
                except (ValueError, IndexError, TypeError, RecursionError):
                    pass
            for child in obj.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(obj, list):
            for child in obj:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(value)
    return found


def choose_page(candidates, number, source):
    # Más reciente primero: no mezclar los datos de otra página de la sesión.
    for payload in reversed(candidates):
        if payload.get("result", {}).get("page") == number:
            return {"url": source, "parser": "browser-network", "payload": payload, "warnings": []}
    return None


def verification_error(source, core):
    """Detectar un fallo ya mostrado; no tocar el widget ni reintentarlo."""
    root = core.TreeReader(source).root
    headings = [n.text().strip().lower().replace("’", "'") for n in root.walk() if n.tag in {"h1", "h2", "h3", "h4", "h5"}]
    if not any("verification didn't go through" in h or "verification failed" in h for h in headings):
        return None
    visible = core.readable(source)
    match = re.search(r"\berror\s*[:(]?\s*(\d{6})\b", visible, re.I)
    return match.group(1) if match else "sin código visible"


class BrowserAssets:
    def __init__(self, context, core, delay):
        self.context, self.core, self.delay = context, core, delay
        self.last = 0.0

    def get(self, url):
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        response = self.context.request.get(url, timeout=45000)
        try:
            if response.status in {401, 403, 429}:
                raise self.core.AccessStopped(f"La imagen devolvió HTTP {response.status}; la descarga se detiene.")
            if not response.ok:
                raise self.core.ExtractionError(f"Imagen HTTP {response.status}")
            return response.body(), response.headers.get("content-type", ""), "utf-8"
        finally:
            response.dispose()


def collect(args, archive, core):
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError as exc:
        raise core.ExtractionError("Falta Playwright. Ejecuta DESCARGAR_70_PAGINAS.cmd para instalarlo, o: py -3 -m pip install playwright") from exc

    print("Modo navegador: completa personalmente cualquier verificación que aparezca. No se resolverá automáticamente.", flush=True)
    profile = args.browser_profile.resolve()
    if profile.is_relative_to(args.output.resolve()):
        raise core.ExtractionError("El perfil del navegador debe quedar fuera de la carpeta del resultado.")
    allowed_host = urllib.parse.urlsplit(args.url).hostname or ""
    channel = None if args.browser_channel == "chromium" else args.browser_channel
    received, context, page = [], None, None

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(str(profile), channel=channel, headless=False, chromium_sandbox=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            archive.assets.downloader = BrowserAssets(context, core, args.delay)

            def on_response(response):
                host = urllib.parse.urlsplit(response.url).hostname or ""
                if host.removeprefix("www.") != allowed_host.removeprefix("www."):
                    return
                try:
                    if "json" not in response.headers.get("content-type", "") or not response.ok:
                        return
                    received.extend(network_payloads(response.json()))
                except Exception:
                    # Puede haber JSON de analítica o respuestas descartadas al navegar.
                    return

            page.on("response", on_response)
            for number in range(1, args.pages + 1):
                url = args.url.format(page=number)
                cached = args.output / "datos_navegador" / f"pagina_{number:03}.json"
                cached_html = args.output / "paginas_originales" / f"pagina_{number:03}.html"
                extracted = None
                if not args.refresh:
                    if cached.is_file():
                        try:
                            stored = json.loads(cached.read_text(encoding="utf-8"))
                            if stored["payload"]["result"]["kind"] == "questions" and stored["payload"]["result"]["page"] == number:
                                extracted = stored
                        except (ValueError, KeyError, TypeError):
                            pass
                    elif cached_html.is_file():
                        try:
                            candidate = core.parse_page(cached_html.read_text(encoding="utf-8"), url)
                            if candidate["payload"]["result"].get("page") == number and candidate["parser"] == "structured":
                                extracted = candidate
                        except core.ExtractionError:
                            pass
                if extracted is None:
                    received.clear()
                    print(f"Abriendo página {number}/{args.pages}...", flush=True)
                    # Navegación ordinaria: no se imitan tokens ni se modifica el
                    # funcionamiento del widget de verificación del sitio.
                    page.goto(url, wait_until="domcontentloaded", timeout=max(45000, args.timeout * 1000))

                    def current():
                        got = choose_page(received, number, url)
                        if got:
                            return got
                        source = page.content()
                        failed = verification_error(source, core)
                        if failed:
                            diagnostic = args.output / "diagnostico" / f"pagina_{number:03}.html"
                            diagnostic.parent.mkdir(exist_ok=True)
                            diagnostic.write_text(source, encoding="utf-8")
                            raise core.AccessStopped(f"Cloudflare rechazó la verificación en la página {number} (error {failed}). Se detiene el proceso. Prueba esa URL en tu navegador habitual; si funciona allí, solicita al dueño una exportación o un acceso que admita automatización.")
                        try:
                            got = core.parse_page(source, url)
                            return got if got["payload"]["result"].get("page") == number else None
                        except core.ExtractionError:
                            return None

                    # Dejar que la aplicación cargue los datos visibles.
                    for _ in range(8):
                        page.wait_for_timeout(400)
                        extracted = current()
                        if extracted:
                            break
                    if not extracted:
                        diagnostic = args.output / "diagnostico" / f"pagina_{number:03}.html"
                        diagnostic.parent.mkdir(exist_ok=True)
                        diagnostic.write_text(page.content(), encoding="utf-8")
                        print("\nLa página no ha entregado todavía las preguntas.", flush=True)
                        print("Mira la ventana del navegador y completa tú la verificación de Cloudflare, si aparece.", flush=True)
                        print("Cuando veas las preguntas, vuelve a esta ventana. Si no cargan, escribe salir.", flush=True)
                        for attempt in range(2):
                            try:
                                answer = input("Pulsa ENTER cuando las preguntas estén visibles, o escribe salir: ").strip().lower()
                            except EOFError as exc:
                                raise core.AccessStopped("La consola no permite intervención manual. Ejecuta el lanzador CMD en una ventana visible.") from exc
                            if answer in {"salir", "exit", "q"}:
                                raise core.AccessStopped(f"Verificación pendiente en la página {number}. Se conserva lo recuperado.")
                            for _ in range(20):
                                page.wait_for_timeout(300)
                                extracted = current()
                                if extracted:
                                    break
                            if extracted:
                                break
                            print("Aún no se detectan preguntas de esta página. Revisa el navegador antes de continuar.", flush=True)
                        if not extracted:
                            raise core.AccessStopped(f"La página {number} sigue sin entregar preguntas después de la intervención manual. Solicita una exportación al dueño.")
                    # Si sólo queda el DOM, mostrar las claves mediante los
                    # controles normales de la página antes de extraerlo.
                    if extracted["parser"] == "dom":
                        for button in page.get_by_role("button", name="Reveal Answer", exact=True).all():
                            if button.is_visible():
                                button.click()
                        for button in page.get_by_role("button", name=re.compile(r"case study|scenario|context", re.I)).all():
                            if button.is_visible() and button.get_attribute("aria-expanded") == "false":
                                button.click()
                        page.wait_for_timeout(400)
                        extracted = current() or extracted
                    cached_html.parent.mkdir(exist_ok=True)
                    cached_html.write_text(page.content(), encoding="utf-8")
                    core.write_json(cached, extracted)
                    page.wait_for_timeout(args.delay * 1000)
                archive.add_page(extracted, f"datos_navegador/pagina_{number:03}.json")
                print(f"Página {number}/{args.pages}: {len(extracted['payload']['result']['items'])} preguntas; acumuladas {len(archive.questions)}", flush=True)
        except PlaywrightError as exc:
            raise core.ExtractionError("El navegador no pudo continuar: " + str(exc)[:900] + "\nPara usar Chromium: py -3 -m playwright install chromium; después ejecuta con --browser-channel chromium.") from exc
        finally:
            if context:
                context.close()
