"""Sesión Scrapling con captura DOM y API; sin rotación ni cambio de motor."""
import json
import time
import urllib.parse
from importlib.metadata import version
from pathlib import Path
import extractor as core
from access_diagnostics import annotate_access,classify_access,observe_document,transport_exception
from browser_support import choose_page, current_question_page, decode_network_response, network_payloads
from capture_support import capture_script
from reference_support import attach_contexts,context_collections,key as context_key
import base64


class ScraplingAssets:
    """Sólo recursos capturados en la misma sesión; no abre otro cliente HTTP."""
    def __init__(self, source):
        self.source, self.cached, self.failed = source, {}, {}
    def update(self, solution, images):
        for image in images:
            if isinstance(image.get('url'), str) and isinstance(image.get('data'), str):
                self.cached[image['url']] = image['data']
                self.failed.pop(image['url'], None)
            elif isinstance(image.get('url'), str) and isinstance(image.get('status'), int):
                self.failed[image['url']] = image['status']
    def get(self, url):
        parsed, expected = urllib.parse.urlsplit(url), urllib.parse.urlsplit(self.source.exam['base'])
        if parsed.scheme != 'https' or parsed.hostname != expected.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise core.ExtractionError('Imagen externa al origen del examen; se conserva su referencia.')
        status = self.failed.get(url)
        if status in (401, 403, 429):
            raise core.AccessStopped(f'La imagen devolvió HTTP {status}.', kind='image_access_rejected', code=str(status))
        if url not in self.cached:
            raise core.ExtractionError('El recurso no se capturó dentro de la sesión Scrapling; queda pendiente.')
        header, encoded = self.cached[url].split(',', 1)
        if not header.startswith('data:image/') or ';base64' not in header:
            raise core.ExtractionError('La captura no contiene una imagen válida.')
        body = base64.b64decode(encoded, validate=True)
        if len(body) > 20*1024**2:
            raise core.ExtractionError('La imagen supera 20 MiB.')
        return body, header[5:].split(';')[0], 'utf-8'


class ScraplingSource:
    def __init__(self,exam,output,delay,*,headed=False,verification_wait=None):
        self.exam,self.output,self.delay,self.headed=exam,Path(output),delay,headed
        self.verification_wait=verification_wait
        self.engine='scrapling';self.last=0;self.last_url=exam['base']+'1'
        self.assets=ScraplingAssets(self);self.received=[];self.objects={k:{} for k in ('topics','series','case_studies','objects')}
    def __enter__(self):
        try:from scrapling.fetchers import StealthySession
        except ImportError as exc:raise core.ExtractionError('Instala requirements_scrapling.txt y ejecuta python -m patchright install chromium.') from exc
        self.manager=StealthySession(headless=not self.headed,solve_cloudflare=False,google_search=False,
            disable_resources=False,record_requests=True,max_recorded_requests=200,retries=1,timeout=120000)
        self.session=self.manager.__enter__()
        return self
    def __exit__(self,*args):return self.manager.__exit__(*args)
    def page(self,number):
        from patchright.sync_api import Error as BrowserError

        time.sleep(max(0,self.delay-(time.monotonic()-self.last)));self.last=time.monotonic()
        url=self.exam['base']+str(number);captured={};self.received=[]
        self.session.network.clear()
        def action(tab):
            deadline=time.monotonic()+(self.verification_wait or 20)
            announced=False
            while True:
                try:
                    html=tab.content()
                    detail=classify_access(html)
                    if not detail:
                        captured.update(json.loads(tab.evaluate(capture_script(number,self.exam,images=True))))
                        tab.wait_for_timeout(300)
                        return
                    if detail['kind']!='challenge_pending' or time.monotonic()>=deadline:
                        captured.update(html=html,url=tab.url)
                        return
                    if not announced:
                        message=f'Página {number}: esperando que termine la comprobación de acceso.'
                        if self.verification_wait:
                            message+=' Si el sitio solicita una acción, complétala en el navegador.'
                        print(message,flush=True)
                        announced=True
                except BrowserError as exc:
                    # La comprobación puede navegar en la misma pestaña mientras leemos el DOM.
                    navigating=any(marker in str(exc).lower() for marker in (
                        'execution context was destroyed','frame was detached','page is navigating',
                    ))
                    if not navigating or time.monotonic()>=deadline:
                        captured['capture']={'error':'El navegador interrumpió la captura dinámica.'}
                        return
                except (ValueError,TypeError):
                    captured['capture']={'error':'No se pudo leer el resultado de la captura dinámica.'}
                    return
                tab.wait_for_timeout(500)
        evidence = {}
        try:response=self.session.fetch(url,page_action=action,page_setup=observe_document(url,evidence),google_search=False)
        except Exception as exc:raise transport_exception(exc,url,number,evidence) from exc
        text=captured.get('html') or str(response.html_content)
        actual=captured.get('url') or response.url
        self.last_url=actual
        original=self.output/'paginas_originales'/f'pagina_{number:05}.html'
        original.parent.mkdir(parents=True,exist_ok=True);original.write_text(text,encoding='utf-8')
        incomplete = []
        response_types = {}
        expected = urllib.parse.urlsplit(url)
        for item in self.session.network.search(limit=None):
            address = urllib.parse.urlsplit(item.url)
            if address.scheme != expected.scheme or address.netloc != expected.netloc:
                continue
            if not 200 <= item.status < 300:
                continue
            data_route = address.path.endswith('/__data.json')
            if data_route and address.path != expected.path.rstrip('/') + '/__data.json':
                continue
            resource_type = item.meta.get('resource_type')
            headers = {k.lower(): v for k, v in item.headers.items()}
            media_type = (headers.get('content-type') or '').partition(';')[0].strip().lower()
            if resource_type == 'document' and media_type == 'text/html' and address.path.rstrip('/') == expected.path.rstrip('/'):
                if item.meta.get('body_note'):
                    continue
                try:
                    original_page = core.parse_page(item.body.decode('utf-8'), item.url, expected_page=number)
                except (core.ExtractionError, ValueError):
                    continue
                if original_page['parser'] == 'structured':
                    self.received.append(original_page['payload'])
                continue
            if resource_type not in {'xhr', 'fetch'}:
                continue
            if media_type != 'text/sveltekit-data' and 'json' not in media_type:
                continue
            response_types[media_type] = response_types.get(media_type, 0) + 1
            if item.meta.get('body_note'):
                incomplete.append({'path': address.path, 'issue': 'El registro no conserva el cuerpo completo.'})
                continue
            try:
                value = decode_network_response(item.body, media_type)
            except (ValueError, TypeError, RecursionError):
                incomplete.append({'path': address.path, 'issue': 'No se pudieron decodificar los datos recibidos.'})
                continue
            self.received.extend(network_payloads(value))
            collections=context_collections(value)
            for kind,items in collections.items():
                for obj in items:self.objects[kind][obj.get('_object_key') or context_key(kind,obj.get('id'))]=obj
        preferred = choose_page(self.received, number, actual, exam=self.exam)
        try:page=current_question_page(text,actual,number,self.exam,preferred,candidates=self.received)
        except core.ExtractionError:
            detail=classify_access(text,response.status)
            if detail:
                stopped=core.AccessStopped(f'Scrapling no entregó acceso en la página {number}: {detail["kind"]}.',kind=detail['kind'],code=detail.get('code'),page=number,url=actual)
                stopped.detail.update(detail);raise stopped
            raise
        page=attach_contexts(page,[{k:list(v.values()) for k,v in self.objects.items()},*self.received])
        self.assets.update({},captured.get('images',[]))
        page['capture']=captured.get('capture',{})
        page['transport']={'engine':'scrapling','version':version('scrapling'),'network_incomplete':incomplete,
                           'network_response_types':response_types,'validated_network_page':page.get('parser') == 'browser-network'}
        return annotate_access(page,text)
