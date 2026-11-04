import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import descargar
import extractor as core
import recuperar_respaldo as backups
from browser_support import current_question_page
from selenium_support import SeleniumSource
from test_actions import page

BLOCK = '<h2>Verification failed</h2><p>Error: 600010</p>'
EXAM_URL = 'https://www.exambase.com/exams/google/associate-data-practitioner'


def dom(exam, number, total=103):
    data = page(exam, number, total)['payload']['result']
    cards = ''.join(f'<div class="card"><h4 class="card-title">Question {q["order"]}</h4><div class="exambase-question__rich-text">Pregunta</div><div class="list-group-item"><span>A</span><div class="exambase-question__rich-text">Opción</div><small>Correct</small></div></div>' for q in data['items'])
    return cards + f'Showing {data["items"][0]["order"]}-{data["items"][-1]["order"]} of {total} · page {number} of {data["total_pages"]}'


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exam = {**descargar.exam_from_url(EXAM_URL), 'total':103, 'pages':21, 'per_page':5}
    def tearDown(self):
        self.temp.cleanup()

    def test_valid_questions_take_priority_over_old_verification_notice(self):
        html = '<section hidden>'+BLOCK+'</section>'+dom(self.exam, 2)
        value = current_question_page(html, self.exam['base']+'2', 2, self.exam)
        self.assertEqual([q['order'] for q in value['payload']['result']['items']], list(range(6,11)))

    def test_old_script_does_not_hide_current_dom(self):
        old = json.dumps(page(self.exam, 1, 103)['payload'])
        html = '<script>const initial={data:'+old+'};</script>'+dom(self.exam, 2)
        value = current_question_page(html, self.exam['base']+'2', 2, self.exam)
        self.assertEqual(value['parser'], 'dom')
        self.assertEqual(value['payload']['result']['page'], 2)
        self.assertEqual(value['payload']['result']['items'][0]['order'], 6)

    def test_old_script_does_not_hide_current_structured_data(self):
        scripts = ''.join('<script>const initial={data:'+json.dumps(page(self.exam,n,103)['payload'])+'};</script>' for n in (1,2))
        value = current_question_page(scripts+dom(self.exam,2),self.exam['base']+'2',2,self.exam)
        self.assertEqual(value['parser'],'structured')
        self.assertEqual(value['payload']['result']['items'][0]['id'],6)

    def test_page_one_is_never_accepted_as_page_two(self):
        with self.assertRaises(core.ExtractionError):
            current_question_page(dom(self.exam, 1), self.exam['base']+'2', 2, self.exam)

    def test_selenium_rejection_is_structured_and_not_retried(self):
        with patch('selenium.webdriver.Chrome') as make:
            driver=make.return_value
            driver.current_url=self.exam['base']+'2'
            driver.page_source=BLOCK
            with SeleniumSource(self.exam, self.root, 5) as source:
                with self.assertRaises(core.AccessStopped) as caught:
                    source.page(2)
            self.assertEqual(caught.exception.detail['code'], '600010')
            self.assertEqual(caught.exception.detail['page'], 2)
            self.assertFalse(caught.exception.detail['automatic_retry'])
            driver.get.assert_called_once()
            driver.quit.assert_called_once()

    def test_headed_selenium_can_read_questions_with_stale_notice(self):
        with patch('selenium.webdriver.Chrome') as make, patch('selenium_support.time.sleep'):
            driver=make.return_value
            driver.current_url=self.exam['base']+'2'
            driver.page_source=BLOCK+dom(self.exam, 2)
            driver.find_elements.return_value=[]
            with SeleniumSource(self.exam, self.root, 5, headed=True) as source:
                result=source.page(2)
            self.assertEqual(result['payload']['result']['page'], 2)
            self.assertNotIn('--headless=new', make.call_args.kwargs['options'].arguments)

    def test_playwright_also_prefers_current_questions(self):
        source=descargar.BrowserSource(self.exam, self.root, 5)
        source.received=[]
        source.last_navigation=0
        source.tab=MagicMock()
        source.tab.url=self.exam['base']+'2'
        source.tab.content.return_value=BLOCK+dom(self.exam, 2)
        source.tab.get_by_role.return_value.all.return_value=[]
        from browser_support import choose_page, verification_error
        source.choose_page,source.verification_error=choose_page,verification_error
        result=source.page(2)
        self.assertEqual(result['payload']['result']['items'][0]['order'], 6)
        source.tab.goto.assert_called_once()

    def test_actual_log_scenario_preserves_five_and_resumes_to_103(self):
        calls=[]
        class Source:
            assets=None
            blocked=True
            def __init__(self, exam, output, delay): self.exam=exam
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def page(self, number):
                calls.append(number)
                if number==2 and self.blocked:
                    raise core.AccessStopped('Cloudflare rechazó la verificación (600010).',kind='verification_rejected',code='600010',page=2)
                return page(self.exam, number, 103)
        args=argparse.Namespace(exam_url=EXAM_URL,output=self.root/'primera',resume_from=None,mode='selenium',delay=5,max_minutes=300,page_limit=0)
        output=io.StringIO()
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'true'}), contextlib.redirect_stdout(output):
            self.assertEqual(descargar.run(args,Source),2)
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual((state['questions'],state['status'],state['next_page']),(5,'blocked',2))
        self.assertEqual(state['failure']['code'],'600010')
        self.assertIn('::error title=Acceso rechazado', output.getvalue())
        self.assertEqual(calls,[1,2])
        result_zip=args.output/state['zip']
        with zipfile.ZipFile(result_zip) as archive:
            hashes=json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/integridad_sha256.json'))))['files']
            root=next(n for n in archive.namelist() if n.endswith('/preguntas.json')).rsplit('/',1)[0]+'/'
            for name,digest in hashes.items():self.assertEqual(hashlib.sha256(archive.read(root+name)).hexdigest(),digest,name)
            self.assertIn('diagnostico_acceso.json',hashes)
        Source.blocked=False
        calls.clear()
        resumed=argparse.Namespace(**{**vars(args),'output':self.root/'segunda','resume_from':result_zip})
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(descargar.run(resumed,Source),0)
        state=json.loads((resumed.output/'estado_ejecucion.json').read_text())
        self.assertEqual((state['questions'],state['status'],state['next_page']),(103,'complete',None))
        self.assertEqual(calls,list(range(2,22)))
        class BlockedImage:
            def get(self, url): raise core.AccessStopped('Imagen HTTP 403',code='403')
        class ImageSource(Source):
            assets=BlockedImage()
            def page(self, number):
                value=super().page(number)
                if number==2:value['payload']['result']['items'][0]['question_text']+='<img src="/media/missing.png">'
                return value
        image_args=argparse.Namespace(**{**vars(args),'output':self.root/'imagen'})
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(descargar.run(image_args,ImageSource),2)
        state=json.loads((image_args.output/'estado_ejecucion.json').read_text())
        self.assertEqual((state['questions'],state['pages_saved'],state['next_page']),(5,[1],2))

    def test_actions_summary_handles_zero_question_block(self):
        # Ejecuta el Python real del resumen, no una copia de su lógica.
        import subprocess,sys,yaml
        workflow=yaml.safe_load((Path(__file__).parents[1]/'.github/workflows/descargar-examen.yml').read_text())
        code=next(s['run'] for s in workflow['jobs']['descargar']['steps'] if s.get('name')=='Resumen').split("<<'PY'",1)[1].split('\n',1)[1].rsplit('\n          PY',1)[0]
        # YAML ya ha retirado la indentación común.
        code=code.rsplit('\nPY',1)[0]
        (self.root/'salida').mkdir()
        state={'questions':0,'exam':{},'status':'blocked','coverage_complete':False,'review_pending':True,'stopped_reason':'600010','failure':{'code':'600010','page':1},'resume_supported':False}
        (self.root/'salida/estado_ejecucion.json').write_text(json.dumps(state))
        result=subprocess.run([sys.executable,'-c',code],cwd=self.root,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('600010',result.stdout)

        state.update(questions=349, status='complete', coverage_complete=True, execution_complete=True,
                     stopped_reason=None, failure=None, resume_supported=True, next_page=None,
                     images_found=8, images_downloaded=8, images_failed=[],
                     images_requiring_review=list(range(8)), missing_explanations=list(range(1,28)))
        (self.root/'salida/estado_ejecucion.json').write_text(json.dumps(state))
        result=subprocess.run([sys.executable,'-c',code],cwd=self.root,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Imágenes guardadas **8/8**',result.stdout)
        self.assertIn('conservado **27**',result.stdout)
        self.assertIn('Recopilación completa',result.stdout)
        self.assertNotIn('revisar imágenes',result.stdout)
        self.assertNotIn('Para reanudar',result.stdout)

        state.update(status='partial', execution_complete=False, images_downloaded=7, images_failed=['pending'])
        (self.root/'salida/estado_ejecucion.json').write_text(json.dumps(state))
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'123'}):
            result=subprocess.run([sys.executable,'-c',code],cwd=self.root,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Imágenes guardadas **7/8**',result.stdout)
        self.assertIn('resume_run_id = 123',result.stdout)
        self.assertIn('informe_validacion.json',result.stdout)
        self.assertNotIn('revisar imágenes',result.stdout)

    def test_resumed_bank_only_marks_incomplete_pages_with_shared_context(self):
        incomplete=[2,5,8,11,14,17,20]
        calls=[]
        class Source:
            assets=None
            blocked=False
            def __init__(self,exam,*_): self.exam=exam
            def __enter__(self): return self
            def __exit__(self,*_): pass
            def page(self,number):
                calls.append(number)
                if self.blocked:
                    raise core.AccessStopped('Comprobación pendiente',kind='challenge_pending',page=number)
                value=page(self.exam,number,103)
                result=value['payload']['result']
                result['case_studies']=[{'id':8,'text':'Contexto común'}]
                for question in result['items']:
                    question['case_study_id']=8
                    if number in incomplete:
                        question['_dom_card_html']='<div></div>'
                        question['choices'][0]['is_correct']=None
                return value
        args=argparse.Namespace(exam_url=EXAM_URL,output=self.root/'original',resume_from=None,mode='scrapling',delay=5,max_minutes=300,page_limit=0)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(descargar.run(args,Source),2)
        initial=json.loads((args.output/'estado_ejecucion.json').read_text())
        Source.blocked=True
        calls.clear()
        args.resume_from=args.output/initial['zip']
        args.output=self.root/'reanudado'
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(descargar.run(args,Source),2)
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual(calls,[2])
        self.assertEqual(state['status'],'blocked')
        self.assertEqual((state['questions'],state['answers_present'],state['objects_preserved']),(103,68,1))
        self.assertEqual(state['pages_pending_answers'],incomplete)
        self.assertEqual(state['pages_pending_references'],incomplete)
        self.assertEqual(state['unresolved_references'],[])
        self.assertEqual(state['next_page'],2)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def container(self,name='resultado.zip'):
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w') as archive:
            archive.writestr(name,b'inner-result');archive.writestr('estado_ejecucion.json','{}')
        return body.getvalue()
    def test_actions_container_is_unwrapped_without_gh(self):
        target=backups.extract_result(self.container(),self.root/'respaldo')
        self.assertEqual(target.read_bytes(),b'inner-result')
    def test_actions_container_rejects_path_traversal(self):
        with self.assertRaises(ValueError):backups.extract_result(self.container('../escape.zip'),self.root/'respaldo')
        self.assertFalse((self.root/'escape.zip').exists())
    def test_saved_backup_is_used_when_artifact_has_expired(self):
        folder=self.root/'bancos/demo/99';folder.mkdir(parents=True)
        (folder/'resultado.zip').write_bytes(b'original')
        (self.root/'bancos/index.json').write_text(json.dumps({'runs':[{'run_id':'99','zip_path':'bancos/demo/99/resultado.zip','sha256':hashlib.sha256(b'original').hexdigest()}]}))
        target,kind=backups.recover('owner/repo','99',self.root/'restored','',self.root)
        self.assertEqual(kind,'repository');self.assertEqual(target.read_bytes(),b'original')
    def test_signed_download_never_receives_github_authorization(self):
        import urllib.error
        redirect=urllib.error.HTTPError('https://api.github.com/repos/o/r/actions/artifacts/1/zip',302,'Found',{'Location':'https://storage.example/archive?signature=temporary'},None)
        response=MagicMock();response.__enter__.return_value.read.return_value=b'zip'
        with patch.object(backups,'github_request',side_effect=redirect),patch('urllib.request.urlopen',return_value=response) as get:
            self.assertEqual(backups.artifact_bytes('/repos/o/r/actions/artifacts/1/zip','SECRET'),'zip'.encode())
        self.assertIsNone(get.call_args.args[0].get_header('Authorization'))


if __name__=='__main__':unittest.main()
