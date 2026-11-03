"""Selenium estándar y lectura del DOM con Beautiful Soup."""
from __future__ import annotations
import base64
import re
import time
import urllib.parse
from pathlib import Path
import extractor as core
import json
from capture_support import capture_script
from capture_quality import page_quality
from access_diagnostics import classify_access, annotate_access


def soup_page(source, url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(source, 'html.parser')
    items = []
    for heading in soup.select('h4.card-title'):
        match = re.fullmatch(r'Question\s+(\d+)', heading.get_text(' ', strip=True))
        card = heading.find_parent(class_='card')
        if not match or not card:
            continue
        rich = card.select('.exambase-question__rich-text')
        if not rich:
            continue
        choices = []
        for li in card.select('.list-group-item'):
            letter = next((s.get_text(strip=True) for s in li.select('span') if re.fullmatch('[A-Z]', s.get_text(strip=True))), None)
            body = li.select_one('.exambase-question__rich-text')
            if letter and body:
                correct = core.dom_choice_is_correct(str(li))
                choices.append({'letter': letter, 'text': body.decode_contents(), 'is_correct': True if correct else None})
        explanation = ''
        for header in card.select('.card-header'):
            if header.get_text(' ', strip=True) == 'Explanation':
                body = header.parent.select_one('.exambase-question__rich-text')
                if body:
                    explanation = body.decode_contents()
        items.append({'id': None, 'order': int(match[1]), 'question_text': rich[0].decode_contents(), 'solution_text': explanation, 'choices': choices, 'type_data': {}, '_dom_card_html': str(card)})
    if not items:
        return core.parse_page(source, url)
    counts = re.search(r'Showing\s+(?:\d+\s*(?:[-–]|to)\s*)?\d+\s+of\s+(\d+)\s*[·•]\s*page\s+(\d+)\s+of\s+(\d+)', soup.get_text(' ', strip=True))
    page = re.search(r'/practice-questions/(\d+)', url)
    return {'url': url, 'parser': 'dom', 'warnings': ['Beautiful Soup leyó el DOM visible; metadatos de contexto pendientes de revisión.'], 'payload': {'result': {'kind': 'questions', 'page': int(counts[2]) if counts else int(page[1]) if page else None, 'total': int(counts[1]) if counts else None, 'total_pages': int(counts[3]) if counts else None, 'items': items, 'topics': [], 'series': [], 'case_studies': []}}}


class SeleniumAssets:
    def __init__(self, driver, delay):
        self.driver, self.delay, self.last = driver, delay, 0
    def get(self, url):
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        result = self.driver.execute_async_script('''
          const url=arguments[0],done=arguments[arguments.length-1];
          fetch(url).then(async r=>{
            if(!r.ok) return done({error:'HTTP '+r.status,status:r.status});
            const b=await r.blob(); if(b.size>30*1024*1024)return done({error:'Imagen demasiado grande'});
            const f=new FileReader();f.onload=()=>done({data:f.result,type:b.type});f.onerror=()=>done({error:'Lectura de imagen fallida'});f.readAsDataURL(b);
          }).catch(()=>done({error:'No se pudo recuperar la imagen desde la sesión del navegador.'}));
        ''', url)
        if result.get('status') in (401, 403, 429):
            raise core.AccessStopped('La imagen requiere detener la descarga: '+result['error'])
        if result.get('error'):
            raise core.ExtractionError(result['error'])
        return base64.b64decode(result['data'].split(',', 1)[1], validate=True), result['type'], 'utf-8'


class SeleniumSource:
    def __init__(self, exam, output, delay, *, headed=False):
        self.exam, self.output, self.delay, self.last, self.headed = exam, output, delay, 0, headed
    def __enter__(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            raise core.ExtractionError('Instala requirements_actions.txt para usar Selenium y Beautiful Soup.') from exc
        options = Options()
        options.page_load_strategy = 'eager'
        if not self.headed:
            options.add_argument('--headless=new')
        options.add_argument('--window-size=1365,900')
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(60)
        self.driver.set_script_timeout(80)
        self.assets = SeleniumAssets(self.driver, self.delay)
        return self
    def __exit__(self, *_):
        self.driver.quit()
    def page(self, number):
        from browser_support import verification_error, current_question_page
        from selenium.webdriver.common.by import By
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        url = self.exam['base'] + str(number)
        followed=False
        if number>1 and self.driver.current_url.startswith(self.exam['base']):
            for link in self.driver.find_elements(By.CSS_SELECTOR,'a[href]'):
                if urllib.parse.urljoin(self.driver.current_url,link.get_attribute('href') or '')==url and link.is_displayed():
                    link.click();followed=True;break
        if not followed:self.driver.get(url)
        deadline = time.monotonic() + 60
        target = self.output / 'paginas_originales' / f'pagina_{number:05}.html'
        target.parent.mkdir(exist_ok=True)
        while time.monotonic() < deadline:
            text = self.driver.page_source
            target.write_text(text, encoding='utf-8')
            try:
                page = current_question_page(text, self.driver.current_url, number, self.exam)
            except core.ExtractionError:
                detail=classify_access(text)
                if detail:
                    failure=core.AccessStopped(f'Acceso sin completar en la página {number}: {detail["kind"]}.',kind=detail['kind'],code=detail['code'],page=number,url=self.driver.current_url)
                    failure.detail.update(detail)
                    raise failure
                time.sleep(1)
                continue
            buttons=self.driver.find_elements(By.TAG_NAME,'button')
            if page_quality(page)['missing_answers'] or any(b.text.strip()=='Reveal Answer' and b.is_displayed() for b in buttons):
                expression=capture_script(number,self.exam)
                result=self.driver.execute_async_script('const done=arguments[arguments.length-1];'+expression+'.then(v=>done({value:v})).catch(()=>done({error:true}));')
                if result.get('error'):raise core.ExtractionError('Falló la captura de respuestas en Selenium.')
                captured=json.loads(result['value'])
                text = captured['html']
                target.write_text(text, encoding='utf-8')
                page = current_question_page(text,captured['url'],number,self.exam)
                page['capture']=captured.get('capture',{})
            return annotate_access(page,text)
        raise core.AccessStopped('Las preguntas no aparecieron en 60 segundos. Se conserva el resultado parcial para reanudar.', kind='access_timeout', page=number, url=self.driver.current_url)
