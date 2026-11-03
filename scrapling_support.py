"""Sesión Scrapling con captura DOM y API; sin rotación ni cambio de motor."""
import json
import time
import urllib.parse
from importlib.metadata import version
from pathlib import Path
import extractor as core
from access_diagnostics import annotate_access,classify_access
from browser_support import current_question_page,choose_page,network_payloads
from capture_support import capture_script
from reference_support import attach_contexts,context_collections,key as context_key
from solver_support import SolverAssets


class ScraplingAssets(SolverAssets):
    def get(self,url):
        if url not in self.cached and url not in self.failed:
            raise core.ExtractionError('El recurso no se capturó dentro de la sesión Scrapling; queda pendiente.')
        return super().get(url)


class ScraplingSource:
    def __init__(self,exam,output,delay,*,headed=False):
        self.exam,self.output,self.delay,self.headed=exam,Path(output),delay,headed
        self.engine='scrapling';self.last=0;self.last_url=exam['base']+'1'
        self.assets=ScraplingAssets(self);self.received=[];self.objects={k:{} for k in ('topics','series','case_studies','objects')}
    def __enter__(self):
        try:from scrapling.fetchers import StealthySession
        except ImportError as exc:raise core.ExtractionError('Instala requirements_scrapling.txt y ejecuta python -m patchright install chromium.') from exc
        self.manager=StealthySession(headless=not self.headed,solve_cloudflare=True,google_search=False,
            disable_resources=False,record_requests=True,max_recorded_requests=200,retries=1,timeout=120000)
        self.session=self.manager.__enter__()
        return self
    def __exit__(self,*args):return self.manager.__exit__(*args)
    def page(self,number):
        time.sleep(max(0,self.delay-(time.monotonic()-self.last)));self.last=time.monotonic()
        url=self.exam['base']+str(number);captured={};self.received=[]
        self.session.network.clear()
        def action(tab):
            try:
                captured.update(json.loads(tab.evaluate(capture_script(number,self.exam,images=True))))
                tab.wait_for_timeout(300)
            except Exception:captured['capture']={'error':'No se completó la captura dinámica; revisar el contenido conservado.'}
        try:response=self.session.fetch(url,page_action=action,google_search=False)
        except Exception as exc:raise core.ExtractionError(f'Scrapling no completó la petición de la página {number} ({type(exc).__name__}).') from exc
        text=captured.get('html') or str(response.html_content)
        actual=captured.get('url') or response.url
        self.last_url=actual
        original=self.output/'paginas_originales'/f'pagina_{number:05}.html'
        original.parent.mkdir(parents=True,exist_ok=True);original.write_text(text,encoding='utf-8')
        incomplete=[]
        for item in self.session.network.search(limit=None):
            if urllib.parse.urlsplit(item.url).hostname!=urllib.parse.urlsplit(self.exam['base']).hostname:continue
            if item.meta.get('body_note') and item.meta.get('resource_type') in {'xhr','fetch'}:incomplete.append({'url':item.url,'issue':'El registro no conserva el cuerpo completo.'})
            headers={k.lower():v for k,v in item.headers.items()}
            if 'json' not in (headers.get('content-type','') or '').lower():continue
            try:value=item.json()
            except (ValueError,TypeError):continue
            self.received.extend(network_payloads(value))
            collections=context_collections(value)
            for kind,items in collections.items():
                for obj in items:self.objects[kind][obj.get('_object_key') or context_key(kind,obj.get('id'))]=obj
        try:page=current_question_page(text,actual,number,self.exam,choose_page(self.received,number,actual))
        except core.ExtractionError:
            detail=classify_access(text,response.status)
            if detail:
                stopped=core.AccessStopped(f'Scrapling no entregó acceso en la página {number}: {detail["kind"]}.',kind=detail['kind'],code=detail.get('code'),page=number,url=actual)
                stopped.detail.update(detail);raise stopped
            raise
        page=attach_contexts(page,[{k:list(v.values()) for k,v in self.objects.items()},*self.received])
        self.assets.update({},captured.get('images',[]))
        page['capture']=captured.get('capture',{})
        page['transport']={'engine':'scrapling','version':version('scrapling'),'network_incomplete':incomplete}
        return annotate_access(page,text)
