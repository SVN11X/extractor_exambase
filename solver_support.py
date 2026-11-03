"""Clientes locales de FlareSolverr/Next y compatibilidad CloudProxy v1."""
from __future__ import annotations
import base64
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import extractor as core
from browser_support import current_question_page, verification_error

MAX_RESPONSE = 40 * 1024**2
MAX_ASSET = 20 * 1024**2

# Sólo controles de contenido del examen. No pulsa widgets de verificación.
CAPTURE_JS = r'''return (async () => {
  for (const button of document.querySelectorAll('button')) {
    if (button.textContent.trim() === 'Reveal Answer' && button.getClientRects().length) button.click();
  }
  await new Promise(resolve => setTimeout(resolve, 1000));
  const images = [];
  const deadline = Date.now() + 14000;
  let bytes = 0;
  const urls = [...new Set([...document.images].map(i => i.currentSrc || i.src))];
  for (const url of urls.slice(0, 128)) {
    if (Date.now() > deadline) break;
    if (new URL(url, location.href).origin !== location.origin) continue;
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal:AbortSignal.timeout(3000)});
      if (!response.ok) {images.push({url, status:response.status}); continue;}
      const blob = await response.blob(); if (blob.size > 20*1024*1024) continue;
      if (bytes + blob.size > 20*1024*1024) continue;
      bytes += blob.size;
      const data = await new Promise((resolve,reject) => {const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob);});
      images.push({url, data});
    } catch { images.push({url, status:0}); }
  }
  return JSON.stringify({url:location.href, html:document.documentElement.outerHTML, images});
})();'''


def solver_endpoint(value):
    try:
        p = urllib.parse.urlsplit(value)
        port = p.port
    except ValueError as exc:
        raise core.ExtractionError('URL del solver inválida.') from exc
    if p.scheme != 'http' or p.hostname not in {'127.0.0.1', 'localhost', '::1'} or p.username or p.password or p.query or p.fragment or p.path.rstrip('/') != '/v1':
        raise core.ExtractionError('El solver debe estar en una URL HTTP local, por ejemplo http://127.0.0.1:8191/v1.')
    if port is not None and not 1 <= port <= 65535:
        raise core.ExtractionError('Puerto del solver inválido.')
    return value.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class SolverClient:
    def __init__(self, endpoint='http://127.0.0.1:8191/v1'):
        self.endpoint = solver_endpoint(endpoint)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.version = None

    def call(self, command, **parameters):
        body = json.dumps({'cmd': command, **parameters}).encode('utf-8')
        request = urllib.request.Request(self.endpoint, data=body, headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=parameters.get('maxTimeout', 120000)/1000 + 30) as response:
                payload = response.read(MAX_RESPONSE + 1)
        except (urllib.error.URLError, OSError) as exc:
            raise core.ExtractionError('No se pudo consultar el solver local. Comprueba que el servicio está iniciado y accesible.') from exc
        if len(payload) > MAX_RESPONSE:
            raise core.ExtractionError('La respuesta del solver supera 40 MiB.')
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeError) as exc:
            raise core.ExtractionError('El servicio local no devolvió JSON de la API v1.') from exc
        if not isinstance(result, dict):
            raise core.ExtractionError('Respuesta del solver inválida.')
        self.version = result.get('version')
        if result.get('status') != 'ok':
            code = re.search(r'\b([36]\d{5})\b', str(result.get('message', '')))
            raise core.AccessStopped('El solver no consiguió entregar el contenido solicitado.', kind='solver_rejected', code=code[1] if code else None)
        return result


class SolverAssets:
    def __init__(self, source):
        self.source = source
        self.cached = {}
        self.failed = {}
        self.user_agent = ''
        self.jar = http.cookiejar.CookieJar()
        self.last = 0.0

    def update(self, solution, images):
        if isinstance(solution.get('userAgent'), str):
            self.user_agent = solution['userAgent']
        for cookie in solution.get('cookies') or []:
            if not isinstance(cookie, dict) or not all(isinstance(cookie.get(k), str) for k in ('name', 'value', 'domain')):
                continue
            domain = cookie['domain']
            path = cookie.get('path') if isinstance(cookie.get('path'), str) else '/'
            self.jar.set_cookie(http.cookiejar.Cookie(0, cookie['name'], cookie['value'], None, False, domain, domain.startswith('.'), domain.startswith('.'), path or '/', True, bool(cookie.get('secure')), None, True, None, None, {}, False))
        for image in images:
            if isinstance(image.get('data'), str) and isinstance(image.get('url'), str):
                self.cached[image['url']] = image['data']
                self.failed.pop(image['url'], None)
            elif isinstance(image.get('url'), str) and isinstance(image.get('status'), int):
                self.failed[image['url']] = image['status']

    def get(self, url):
        parsed, expected = urllib.parse.urlsplit(url), urllib.parse.urlsplit(self.source.exam['base'])
        if parsed.scheme != 'https' or parsed.hostname != expected.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
            raise core.ExtractionError('Imagen externa al origen del examen; se conserva la referencia para revisión.')
        if url in self.failed:
            status = self.failed[url]
            if status in {401,403,429}:
                raise core.AccessStopped(f'La imagen devolvió HTTP {status} dentro de la sesión.', kind='image_access_rejected', code=str(status))
            raise core.ExtractionError(f'No se pudo recuperar la imagen dentro de la sesión (estado {status}).')
        if url in self.cached:
            header, encoded = self.cached[url].split(',', 1)
            if ';base64' not in header or not header.startswith('data:image/'):
                raise core.ExtractionError('El solver no devolvió una imagen válida.')
            body = base64.b64decode(encoded, validate=True)
            if len(body) > MAX_ASSET:
                raise core.ExtractionError('La imagen supera 20 MiB.')
            return body, header[5:].split(';')[0], 'utf-8'
        time.sleep(max(0, self.source.delay - (time.monotonic()-self.last)))
        self.last = time.monotonic()
        if self.source.engine == 'cloudproxy':
            solution = self.source.request(url, download=True)
            body = base64.b64decode(solution.get('response', ''), validate=True)
            if len(body) > MAX_ASSET:
                raise core.ExtractionError('La imagen supera 20 MiB.')
            headers = {k.lower():v for k,v in (solution.get('headers') or {}).items()}
            content_type = headers.get('content-type', '')
            if not isinstance(content_type, str) or not content_type.lower().startswith('image/'):
                raise core.ExtractionError('CloudProxy no entregó una respuesta de tipo imagen.')
            return body, content_type, 'utf-8'
        # El solver clásico no implementa download: conserva UA y cookies en memoria.
        if not self.user_agent:
            raise core.ExtractionError('El solver no conservó su User-Agent para descargar imágenes.')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())
        req = urllib.request.Request(url, headers={'User-Agent': self.user_agent, 'Accept': 'image/*', 'Referer': self.source.last_url})
        try:
            with opener.open(req, timeout=45) as response:
                body = response.read(MAX_ASSET+1)
                content_type = response.headers.get('Content-Type', '')
        except urllib.error.HTTPError as exc:
            if exc.code in {401,403,429}:
                raise core.AccessStopped(f'La imagen devolvió HTTP {exc.code}.', kind='image_access_rejected', code=str(exc.code)) from exc
            raise core.ExtractionError(f'La imagen devolvió HTTP {exc.code}.') from exc
        except (urllib.error.URLError, OSError) as exc:
            raise core.ExtractionError('No se pudo recuperar una imagen del examen.') from exc
        if len(body) > MAX_ASSET or not content_type.lower().startswith('image/'):
            raise core.ExtractionError('La URL de imagen no entregó una imagen de tamaño admitido.')
        return body, content_type, 'utf-8'


class SolverSource:
    def __init__(self, exam, output, delay, *, engine='flaresolverr-next', endpoint='http://127.0.0.1:8191/v1', client=None):
        self.exam, self.output, self.delay, self.engine = exam, Path(output), delay, engine
        self.client = client or SolverClient(endpoint)
        self.session = None
        self.last = 0.0
        self.last_url = exam['base']+'1'
        self.assets = SolverAssets(self)

    def __enter__(self):
        result = self.client.call('sessions.create', session='exambase-'+uuid.uuid4().hex)
        session = result.get('session')
        if not isinstance(session, str) or not session:
            raise core.ExtractionError('El solver no creó una sesión válida.')
        self.session = session
        return self

    def __exit__(self, *_):
        if self.session:
            try:
                self.client.call('sessions.destroy', session=self.session)
            except core.ExtractionError:
                # El error de cierre no reemplaza el motivo original de la parada.
                pass
            self.session = None

    def request(self, url, **extra):
        result = self.client.call('request.get', url=url, session=self.session, maxTimeout=120000, **extra)
        solution = result.get('solution')
        if not isinstance(solution, dict):
            raise core.ExtractionError('El solver devolvió status=ok sin una solución utilizable.')
        if solution.get('status') in {401,403,429}:
            raise core.AccessStopped(f'El solver recibió HTTP {solution["status"]}.', kind='solver_rejected', code=str(solution['status']))
        return solution

    def page(self, number):
        url = self.exam['base']+str(number)
        time.sleep(max(0, self.delay - (time.monotonic()-self.last)))
        self.last = time.monotonic()
        extra = {'waitInSeconds': 2}
        if self.engine == 'flaresolverr-next':
            extra.update(executeJs=CAPTURE_JS, disableMedia=False)
        try:
            solution = self.request(url, **extra)
        except core.AccessStopped as exc:
            exc.detail.update(page=number, url=url)
            raise
        text, actual_url, images = solution.get('response'), solution.get('url'), []
        if self.engine == 'flaresolverr-next':
            try:
                captured = json.loads(solution.get('executeJsResult', ''))
            except (ValueError, TypeError) as exc:
                code = verification_error(text, core) if isinstance(text, str) else None
                if code:
                    raise core.AccessStopped(f'La página {number} sigue mostrando un rechazo de acceso ({code}).', kind='verification_rejected', code=code, page=number, url=actual_url) from exc
                raise core.ExtractionError('FlareSolverr-next no devolvió executeJsResult válido. Comprueba que usas la imagen del fork rix1337.') from exc
            if not isinstance(captured, dict):
                raise core.ExtractionError('El resultado executeJs no contiene una captura válida.')
            text, actual_url, images = captured.get('html'), captured.get('url'), captured.get('images', [])
        if not isinstance(images, list) or len(images)>128 or not all(isinstance(item, dict) for item in images):
            raise core.ExtractionError('El solver devolvió una lista de imágenes inválida.')
        if not isinstance(text, str) or not isinstance(actual_url, str):
            raise core.ExtractionError('El solver no devolvió HTML y URL de la página.')
        target = self.output/'paginas_originales'/f'pagina_{number:05}.html'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        self.last_url = actual_url
        try:
            page = current_question_page(text, actual_url, number, self.exam)
        except core.ExtractionError:
            code = verification_error(text, core)
            if code:
                raise core.AccessStopped(f'La página {number} sigue mostrando un rechazo de acceso ({code}).', kind='verification_rejected', code=code, page=number, url=actual_url)
            raise
        self.assets.update(solution, images)
        page['transport'] = {'engine':self.engine, 'solver_version':self.client.version}
        return page
