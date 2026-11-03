"""API v1 local y fixtures sintéticas; no contacta ExamBase ni resuelve desafíos."""
import argparse
import base64
import contextlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import descargar
import diagnosticar_navegador as diagnostic
import extractor as core
import solver_service
from solver_support import SolverClient, SolverSource, solver_endpoint
from test_access import BLOCK, dom

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
BASE = 'https://www.exambase.com/exams/cisco/demo'


class FakeClient:
    version = 'fixture-1'
    def __init__(self, solution):
        self.solution, self.calls = solution, []
    def call(self, command, **parameters):
        self.calls.append((command, parameters))
        if command == 'sessions.create': return {'session': parameters['session']}
        if command == 'sessions.destroy': return {}
        return {'solution':self.solution}


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exam = {**descargar.exam_from_url(BASE), 'total':7, 'pages':2, 'per_page':5}
    def tearDown(self):
        self.temp.cleanup()
    def solution(self, number=1, **changes):
        value = {'url':self.exam['base']+str(number), 'status':200, 'response':dom(self.exam,number,7), 'userAgent':'Fixture UA', 'cookies':[]}
        value.update(changes)
        return value
    def next_solution(self, number=1, **changes):
        return self.solution(number, executeJsResult=json.dumps({'url':self.exam['base']+str(number),'html':dom(self.exam,number,7),'images':[],**changes}))

    def test_solver_endpoint_is_local_and_never_accepts_credentials_or_redirect_target(self):
        for value in ['https://127.0.0.1:8191/v1','http://public.example/v1','http://u:p@localhost/v1','http://localhost/v1?x=1','http://localhost:abc/v1','http://localhost:0/v1']:
            with self.subTest(value=value), self.assertRaises(core.ExtractionError): solver_endpoint(value)
        self.assertEqual(solver_endpoint('http://[::1]:8191/v1/'),'http://[::1]:8191/v1')

    def test_next_uses_post_javascript_html_instead_of_stale_initial_html(self):
        value = self.next_solution(2)
        value['response'] = BLOCK + dom(self.exam,1,7)
        client = FakeClient(value)
        with SolverSource(self.exam,self.root,0,client=client) as source:
            page = source.page(2)
        self.assertEqual([q['order'] for q in page['payload']['result']['items']],[6,7])
        self.assertEqual(page['transport'],{'engine':'flaresolverr-next','solver_version':'fixture-1'})
        request = client.calls[1][1]
        self.assertIn('executeJs',request)
        self.assertFalse(request['disableMedia'])
        self.assertEqual(client.calls[-1][0],'sessions.destroy')
        self.assertEqual(client.calls[0][1]['session'],client.calls[-1][1]['session'])

    def test_status_ok_and_http_200_do_not_turn_a_challenge_into_questions(self):
        client=FakeClient(self.next_solution(2,html=BLOCK))
        with SolverSource(self.exam,self.root,0,client=client) as source:
            with self.assertRaises(core.AccessStopped) as caught: source.page(2)
        self.assertEqual(caught.exception.detail['code'],'600010')
        self.assertEqual(caught.exception.detail['page'],2)
        self.assertFalse(caught.exception.detail['automatic_retry'])
        self.assertEqual([c for c,_ in client.calls],['sessions.create','request.get','sessions.destroy'])
        self.assertEqual((self.root/'paginas_originales/pagina_00002.html').read_text(),BLOCK)

    def test_classic_keeps_html_protocol_without_sending_next_parameters(self):
        client=FakeClient(self.solution())
        with SolverSource(self.exam,self.root,0,engine='flaresolverr',client=client) as source:
            self.assertEqual(source.page(1)['payload']['result']['page'],1)
        self.assertNotIn('executeJs',client.calls[1][1])

    def test_missing_execute_js_is_rejected_with_actionable_fork_message(self):
        with SolverSource(self.exam,self.root,0,client=FakeClient(self.solution())) as source:
            with self.assertRaisesRegex(core.ExtractionError,'rix1337'): source.page(1)

    def test_rejection_without_execute_js_preserves_actual_cloudflare_code(self):
        with SolverSource(self.exam,self.root,0,client=FakeClient(self.solution(response=BLOCK))) as source:
            with self.assertRaises(core.AccessStopped) as caught: source.page(1)
        self.assertEqual(caught.exception.detail['code'],'600010')

    def test_wrong_page_and_malformed_image_list_never_pass_validation(self):
        for changes in [{'html':dom(self.exam,1,7)},{'images':[None]}]:
            with self.subTest(changes=changes):
                with SolverSource(self.exam,self.root,0,client=FakeClient(self.next_solution(2,**changes))) as source:
                    with self.assertRaises(core.ExtractionError): source.page(2)

    def test_next_images_use_browser_cache_and_never_make_another_request(self):
        url='https://www.exambase.com/media/fixture.png'
        data='data:image/png;base64,'+base64.b64encode(PNG).decode()
        with SolverSource(self.exam,self.root,0,client=FakeClient(self.next_solution(images=[{'url':url,'data':data}]))) as source:
            source.page(1)
            with patch('urllib.request.build_opener',side_effect=AssertionError('No se debe descargar de nuevo')):
                self.assertEqual(source.assets.get(url)[:2],(PNG,'image/png'))
                with self.assertRaises(core.ExtractionError):source.assets.get('https://external.example/media/x.png')

    def test_rejected_image_in_browser_is_not_requested_again(self):
        url='https://www.exambase.com/media/denied.png'
        with SolverSource(self.exam,self.root,0,client=FakeClient(self.next_solution(images=[{'url':url,'status':403}]))) as source:
            source.page(1)
            with patch('urllib.request.build_opener',side_effect=AssertionError('No reintentar')):
                with self.assertRaises(core.AccessStopped):source.assets.get(url)

    def test_cloudproxy_uses_legacy_binary_download_protocol(self):
        client=FakeClient(self.solution(response=base64.b64encode(PNG).decode(),headers={'Content-Type':'image/png'}))
        with SolverSource(self.exam,self.root,0,engine='cloudproxy',client=client) as source:
            self.assertEqual(source.assets.get('https://www.exambase.com/media/test.png')[:2],(PNG,'image/png'))
        self.assertTrue(client.calls[1][1]['download'])

    def test_real_local_http_api_builds_human_and_ai_package_without_exporting_cookies(self):
        # Se prueba urllib + API v1 + recopilador + imágenes + ZIP, con servidor local.
        calls=[]
        exam=self.exam
        image_url='https://www.exambase.com/media/fixture.png'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(request)
                value={'status':'ok','version':'fixture-api'}
                if request['cmd']=='sessions.create': value['session']=request['session']
                elif request['cmd']=='request.get':
                    number=int(request['url'].rsplit('/',1)[1])
                    html=dom(exam,number,7)
                    if number==1:html=html.replace('Pregunta','Pregunta <img src="/media/fixture.png">',1)
                    captured={'url':request['url'],'html':html,'images':[{'url':image_url,'data':'data:image/png;base64,'+base64.b64encode(PNG).decode()}]}
                    value['solution']={'status':200,'url':request['url'],'response':BLOCK,'executeJsResult':json.dumps(captured),'cookies':[{'name':'cf_clearance','value':'PRIVATE_TEST_COOKIE','domain':'.exambase.com'}],'userAgent':'Fixture UA'}
                body=json.dumps(value).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        args=argparse.Namespace(exam_url=BASE,output=self.root/'api',resume_from=None,mode='flaresolverr-next',solver_url=f'http://127.0.0.1:{server.server_port}/v1',delay=5,max_minutes=300,page_limit=0)
        try:
            output=io.StringIO()
            with patch('solver_support.time.sleep'),contextlib.redirect_stdout(output):self.assertEqual(descargar.run(args),2)
        finally:
            server.shutdown();server.server_close();worker.join()
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual((state['questions'],state['coverage_complete']),(7,True))
        self.assertFalse(state['references_complete'])
        with zipfile.ZipFile(args.output/state['zip']) as archive:
            names=archive.namelist()
            self.assertTrue(any(n.endswith('/preguntas.html') for n in names))
            self.assertTrue(any(n.endswith('/para_ia/preguntas.jsonl') for n in names))
            self.assertEqual(sum('/imagenes/' in n for n in names),1)
            self.assertTrue(all(b'PRIVATE_TEST_COOKIE' not in archive.read(n) for n in names))
        self.assertNotIn('PRIVATE_TEST_COOKIE',output.getvalue())
        self.assertEqual([r['cmd'] for r in calls],['sessions.create','request.get','request.get','sessions.destroy'])
        self.assertEqual(len({r['session'] for r in calls}),1)

    def test_api_error_preserves_code_without_logging_response_or_cookies(self):
        client=SolverClient()
        response=MagicMock()
        response.__enter__.return_value.read.return_value=json.dumps({'status':'error','message':'Error 600010 PRIVATE_COOKIE'}).encode()
        client.opener=MagicMock();client.opener.open.return_value=response
        with self.assertRaises(core.AccessStopped) as caught:client.call('request.get',url=self.exam['base']+'1')
        self.assertEqual(caught.exception.detail['code'],'600010')
        self.assertNotIn('PRIVATE_COOKIE',str(caught.exception))

    def test_patched_browser_imports_rebrowser_and_uses_installed_chrome(self):
        with patch('rebrowser_playwright.sync_api.sync_playwright') as make:
            with descargar.BrowserSource(self.exam,self.root,0,headed=True,patched=True):pass
        pw=make.return_value.start.return_value
        self.assertEqual(pw.chromium.launch.call_args.kwargs['channel'],'chrome')
        self.assertFalse(pw.chromium.launch.call_args.kwargs['headless'])
        pw.chromium.launch.return_value.new_context.assert_called_once_with(no_viewport=True)
        pw.stop.assert_called_once()

    def test_browser_follows_exact_pagination_link_before_falling_back_to_goto(self):
        source=descargar.BrowserSource(self.exam,self.root,0)
        source.tab=MagicMock();source.tab.url=self.exam['base']+'1'
        source.tab.content.return_value=dom(self.exam,2,7)
        source.tab.get_by_role.return_value.all.return_value=[]
        link=MagicMock();link.get_attribute.return_value=self.exam['base']+'2';link.is_visible.return_value=True
        link.click.side_effect=lambda:setattr(source.tab,'url',self.exam['base']+'2')
        source.tab.locator.return_value.all.return_value=[link]
        source.received=[];source.last_navigation=0
        from browser_support import choose_page,verification_error
        source.choose_page,source.verification_error=choose_page,verification_error
        self.assertEqual(source.page(2)['payload']['result']['page'],2)
        link.click.assert_called_once();source.tab.goto.assert_not_called()


class ServiceTests(unittest.TestCase):
    def test_managed_container_is_loopback_only_and_cleanup_checks_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'runtime.json'
            def fake(*args):
                if args[0]=='run': return 'owned-container'
                if args[0]=='inspect': return json.loads(state.read_text())['owner']
                return ''
            with patch('solver_service.shutil.which',return_value='/bin/docker'),patch('solver_service.ready'),patch('solver_service.docker',side_effect=fake) as docker:
                data=solver_service.start('flaresolverr-next',state)
                run=next(c.args for c in docker.call_args_list if c.args[0]=='run')
                self.assertIn('127.0.0.1:8191:8191',run)
                self.assertEqual(data['image'],'ghcr.io/rix1337/flaresolverr-next:latest')
                solver_service.stop(state);solver_service.stop(state)
                self.assertEqual(sum(c.args[0]=='rm' for c in docker.call_args_list),1)
                self.assertTrue(json.loads(state.read_text())['stopped'])

    def test_cleanup_never_removes_an_unowned_container_or_external_service(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'runtime.json'
            state.write_text(json.dumps({'managed':True,'container':'other','owner':'expected'}))
            with patch('solver_service.docker',return_value='different') as docker:
                with self.assertRaises(RuntimeError):solver_service.stop(state)
                self.assertEqual(docker.call_count,1)
            state.unlink()
            with patch('solver_service.ready') as ready,patch('solver_service.docker') as docker:
                self.assertFalse(solver_service.start('cloudproxy',state)['managed'])
                solver_service.stop(state)
                ready.assert_called_once();docker.assert_not_called()

    def test_failed_service_start_cleans_its_container_and_does_not_retry_exam(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'runtime.json'
            def fake(*args):
                if args[0]=='run':return 'mine'
                if args[0]=='inspect':return json.loads(state.read_text())['owner']
                return ''
            with patch('solver_service.shutil.which',return_value='docker'),patch('solver_service.docker',side_effect=fake) as docker,patch('solver_service.ready',side_effect=RuntimeError('unavailable')):
                with self.assertRaisesRegex(RuntimeError,'unavailable'):solver_service.start('flaresolverr-next',state)
                self.assertIn(('rm','-f','mine'),[c.args for c in docker.call_args_list])

    def test_docker_port_failure_removes_only_its_partially_created_container(self):
        with tempfile.TemporaryDirectory() as folder:
            owner=MagicMock(hex='test-owned-uuid')
            def fake(*args):
                if args[0]=='run':raise RuntimeError('Puerto ocupado')
                if args[0]=='inspect':return owner.hex
                return ''
            with patch('solver_service.uuid.uuid4',return_value=owner),patch('solver_service.shutil.which',return_value='docker'),patch('solver_service.docker',side_effect=fake) as docker:
                with self.assertRaisesRegex(RuntimeError,'Puerto ocupado'):solver_service.start('flaresolverr-next',Path(folder)/'runtime.json')
                self.assertIn(('rm','-f','exambase-solver-'+owner.hex[:12]),[c.args for c in docker.call_args_list])


class DiagnosticTests(unittest.TestCase):
    def test_detector_preserves_raw_ratings_and_does_not_claim_exambase_access(self):
        result={'url':diagnostic.DETECTOR,'detections':[{'type':'fixture','rating':1,'note':'Detected'}]}
        with tempfile.TemporaryDirectory() as folder,patch('diagnosticar_navegador.SolverSource') as factory:
            source=factory.return_value.__enter__.return_value
            source.request.return_value={'executeJsResult':json.dumps(result)}
            saved=json.loads(diagnostic.diagnose('flaresolverr-next',folder).read_text())
            self.assertEqual(saved['detections'],result['detections'])
            self.assertIn('no valida acceso a ExamBase',saved['scope'])
            source.request.assert_called_once()
            self.assertEqual(source.request.call_args.args[0],diagnostic.DETECTOR)

    def test_empty_detector_is_saved_as_missing_and_fails_instead_of_passing(self):
        with tempfile.TemporaryDirectory() as folder,patch('diagnosticar_navegador.BrowserSource') as factory:
            source=factory.return_value.__enter__.return_value
            source.tab.evaluate.return_value=json.dumps({'url':diagnostic.DETECTOR,'detections':None})
            with self.assertRaisesRegex(ValueError,'no entregó resultados'):diagnostic.diagnose('rebrowser',folder)
            self.assertIsNone(json.loads((Path(folder)/'diagnostico_rebrowser.json').read_text())['detections'])
            self.assertTrue(factory.call_args.kwargs['patched'])


if __name__=='__main__':unittest.main()
