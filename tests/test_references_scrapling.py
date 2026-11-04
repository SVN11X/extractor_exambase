import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from patchright.sync_api import Error as BrowserError
import descargar
import extractor as core
from browser_support import decode_network_response, network_payloads
from reference_support import attach_contexts,question_refs,reference_graph
from scrapling_support import ScraplingSource
from test_actions import page
from test_capture_quality import html_page


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.exam={**descargar.exam_from_url('https://www.exambase.com/exams/cisco/demo'),'total':7,'pages':2,'per_page':5}
    def tearDown(self):self.temp.cleanup()

    def collect(self,modifier,folder):
        class Source:
            assets=None
            def __init__(self,exam,*_):self.exam=exam
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def page(self,n):return modifier(page(self.exam,n),n)
        output=self.root/folder
        args=argparse.Namespace(exam_url=self.exam['base']+'1',output=output,resume_from=None,mode='scrapling',delay=5,max_minutes=300,page_limit=0)
        with contextlib.redirect_stdout(io.StringIO()):result=descargar.run(args,Source)
        state=json.loads((output/'estado_ejecucion.json').read_text())
        directory=next(output.glob('resultado_*_demo'))
        return result,state,json.loads((directory/'preguntas.json').read_text()),json.loads((directory/'para_ia/referencias.json').read_text())

    def test_sibling_api_objects_are_not_discarded(self):
        value=page(self.exam,1)['payload']
        value['case_studies']=[{'id':8,'text':'Contexto'}]
        found=network_payloads(value)
        self.assertEqual(found[0]['result']['case_studies'][0]['id'],8)

    def test_embedded_objects_and_reverse_question_links_are_exported_with_ids(self):
        def modify(value,n):
            if n==1:
                value['payload']['result']['items'][0].update(case_study_id=8,scenario={'id':9,'text':'Escenario','question_ids':[1]})
                value['payload']['case_studies']=[{'id':8,'text':'Caso','question_ids':[1]}]
            return value
        result,state,data,graph=self.collect(modify,'good')
        self.assertEqual(result,0);self.assertTrue(state['references_complete'])
        self.assertEqual(state['objects_preserved'],2)
        self.assertEqual(set(data['questions'][0]['context_refs']),{'case_studies:8','objects:scenario:9'})
        self.assertTrue(any(edge['relation']=='question' and edge['to']=='cisco/demo:q:00001' for edge in graph['edges']))
        self.assertTrue(graph['complete']);self.assertFalse(graph['unresolved'])

    def test_missing_object_target_prevents_success_even_with_all_questions_and_answers(self):
        def modify(value,n):
            if n==1:value['payload']['result']['items'][0]['case_study_id']=999
            return value
        result,state,data,graph=self.collect(modify,'missing')
        self.assertEqual(result,2);self.assertEqual(state['questions'],7);self.assertEqual(state['answers_present'],7)
        self.assertFalse(state['references_complete']);self.assertEqual(graph['unresolved'][0]['to'],'case_studies:999')
        self.assertEqual(state['next_page'],1)

    def test_unknown_reference_ids_are_preserved_for_review_instead_of_guessed(self):
        def modify(value,n):
            if n==1:value['payload']['result']['items'][0]['type_data']={'diagram_id':'D9'}
            return value
        result,state,data,graph=self.collect(modify,'unknown')
        self.assertEqual(result,2);self.assertEqual(data['questions'][0]['type_data']['diagram_id'],'D9')
        self.assertEqual(graph['unresolved'][0]['relation'],'unclassified_reference')

    def test_dom_without_metadata_is_explicitly_incomplete(self):
        result,state,data,graph=self.collect(lambda value,n:core.parse_page(html_page(value),self.exam['base']+str(n)),'dom')
        self.assertEqual(result,2);self.assertEqual(state['answers_present'],7)
        self.assertEqual(graph['metadata_unverified_questions'],list(range(1,8)))

    def test_typed_api_object_can_resolve_a_previously_unknown_field(self):
        def modify(value,n):
            if n==1:
                value['payload']['result']['items'][0]['type_data']={'diagram_id':'D9'}
                value['payload']['objects']=[{'kind':'diagram','id':'D9','text':'Diagrama de la fuente'}]
            return value
        result,state,data,graph=self.collect(modify,'typed')
        self.assertEqual(result,0);self.assertTrue(graph['complete'])
        self.assertIn('objects:diagram:D9',data['questions'][0]['context_refs'])
        self.assertIsNone(state['next_page'])

    def test_object_with_missing_reverse_question_reference_is_incomplete(self):
        def modify(value,n):
            if n==2:value['payload']['case_studies']=[{'id':8,'text':'Caso','question_ids':[999]}]
            return value
        result,state,data,graph=self.collect(modify,'reverse')
        self.assertEqual(result,2);self.assertEqual(graph['unresolved'][0]['source_question_id'],999)
        self.assertEqual(state['pages_pending_references'],[2])

    def test_reference_chain_between_objects_is_checked(self):
        for present in (True,False):
            def modify(value,n):
                if n==1:
                    value['payload']['result']['items'][0]['scenario']={'id':9,'diagram_id':'D9','text':'Escenario'}
                    if present:value['payload']['objects']=[{'id':'D9','kind':'diagram','text':'Diagrama'}]
                return value
            result,state,data,graph=self.collect(modify,'chain-'+str(present))
            self.assertEqual(result,0 if present else 2)
            self.assertEqual(graph['complete'],present)

    def test_scrapling_waits_through_same_tab_navigation_and_collects_api_objects(self):
        value=page(self.exam,1);value['payload']['result']['items'][0]['case_study_id']=8
        record=MagicMock(status=200);record.url=self.exam['base']+'1/__data.json';record.headers={'Content-Type':'application/json'}
        record.meta={'resource_type':'fetch'};record.body=json.dumps({**value['payload'],'case_studies':[{'id':8,'text':'Caso API'}]}).encode()
        response=MagicMock();response.url=self.exam['base']+'1';response.status=200;response.html_content=html_page(value)
        browser_page=MagicMock()
        browser_page.content.side_effect=[
            '<iframe src="https://challenges.cloudflare.com/test"></iframe>',
            BrowserError('Frame was detached'),
            response.html_content,
        ]
        browser_page.evaluate.return_value=json.dumps({'url':response.url,'html':response.html_content,'images':[],'capture':{'version':2}})
        with patch('scrapling.fetchers.StealthySession') as factory:
            session=factory.return_value.__enter__.return_value
            session.network.search.return_value=[record]
            def fetch(url,**options):options['page_action'](browser_page);return response
            session.fetch.side_effect=fetch
            with ScraplingSource(self.exam,self.root,0) as source:captured=source.page(1)
            self.assertEqual(captured['payload']['result']['case_studies'][0]['id'],8)
            self.assertEqual(captured['payload']['result']['items'][0]['id'],1)
            self.assertEqual(captured['transport']['engine'],'scrapling')
            self.assertEqual(factory.call_args.kwargs['retries'],1)
            self.assertTrue(factory.call_args.kwargs['record_requests'])
            self.assertFalse(factory.call_args.kwargs['google_search'])
            self.assertFalse(factory.call_args.kwargs['solve_cloudflare'])
            self.assertEqual(browser_page.content.call_count,3)
            browser_page.evaluate.assert_called_once()
            session.fetch.assert_called_once()
            session.network.clear.assert_called_once();factory.return_value.__exit__.assert_called_once()
        self.assertNotIn('request_headers',json.dumps(captured))

    def test_success_action_data_can_contain_flattened_payload(self):
        body=json.dumps({'type':'success','status':200,'data':'[{"case_studies":1},[2],{"id":3},900]'}).encode()
        decoded=decode_network_response(body,'application/json')
        self.assertEqual(decoded['data']['case_studies'],[{'id':900}])

    def test_resume_repairs_metadata_from_stream_without_losing_saved_answers(self):
        def initial(value, number):
            if number == 1:
                return value
            return core.parse_page(html_page(value),value['url'])

        result,old,_,_=self.collect(initial,'pending')
        self.assertEqual((result,old['answers_present'],old['pages_pending_references']),(2,7,[2]))
        current=page(self.exam,2)
        current['payload']['result']['items'][0].update(case_study_id=807)
        for question in current['payload']['result']['items']:
            question['choices'][0]['is_correct']=None

        def flatten(value):
            nodes=[]
            def visit(item):
                index=len(nodes)
                nodes.append(None)
                if isinstance(item,dict): item={k:visit(v) for k,v in item.items()}
                elif isinstance(item,list): item=[visit(v) for v in item]
                nodes[index]=item
                return index
            visit(value)
            return nodes

        data=flatten({**current['payload'],'case_studies':None})
        cases=[{'id':807,'text':'Caso diferido','question_ids':[6]}]
        data[data[0]['case_studies']]=['Promise',len(data)]
        data.append(1)
        stream=[{'type':'data','nodes':[{'type':'data','data':data}]},
                {'type':'chunk','id':1,'data':flatten(cases)}]
        stream_record=MagicMock(status=200,url=current['url']+'/__data.json?x-sveltekit-invalidated=01',
                                headers={'content-type':'text/sveltekit-data; charset=utf-8'},
                                meta={'resource_type':'fetch'},body='\n'.join(map(json.dumps,stream)).encode())
        invalid=MagicMock(status=200,url=current['url']+'/__data.json',headers={'content-type':'application/json'},
                          meta={'resource_type':'fetch'},body=b'{"result":{"kind":"questions","page":2,"items":[]}}')
        other=MagicMock(status=200,url=self.exam['base']+'1/__data.json',headers={'content-type':'application/json'},
                        meta={'resource_type':'fetch'},body=b'{"case_studies":[{"id":999}]}')
        html=html_page(current)
        browser_page=MagicMock(url=current['url'])
        browser_page.content.return_value=html
        browser_page.evaluate.return_value=json.dumps({'url':current['url'],'html':html})
        response=MagicMock(status=200,url=current['url'],html_content=html)
        args=argparse.Namespace(exam_url=self.exam['base']+'1',output=self.root/'repaired',
                                resume_from=self.root/'pending'/old['zip'],mode='scrapling',delay=0,max_minutes=300,page_limit=0)
        with patch('scrapling.fetchers.StealthySession') as factory, contextlib.redirect_stdout(io.StringIO()):
            session=factory.return_value.__enter__.return_value
            session.network.search.return_value=[stream_record,invalid,other]
            def fetch(url,**options):
                options['page_action'](browser_page)
                return response
            session.fetch.side_effect=fetch
            self.assertEqual(descargar.run(args),0)
            self.assertEqual([call.args[0] for call in session.fetch.call_args_list],[current['url']])

        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual((state['status'],state['answers_present'],state['objects_preserved']),('complete',7,1))
        self.assertEqual(state['metadata_unverified_questions'],[])
        captured=json.loads(next(args.output.glob('resultado_*/capturas/pagina_00002.json')).read_text())
        self.assertEqual(captured['payload']['result']['items'][0]['id'],6)
        self.assertEqual(captured['payload']['result']['case_studies'],cases)

    def test_scrapling_reports_persistent_challenge_with_no_extra_navigation(self):
        browser_page=MagicMock()
        browser_page.url=self.exam['base']+'2'
        browser_page.content.return_value='<title>Just a moment...</title>Cloudflare'
        response=MagicMock(status=403)
        with patch('scrapling.fetchers.StealthySession') as factory, patch('scrapling_support.time.monotonic',side_effect=[0,0,0,21]):
            session=factory.return_value.__enter__.return_value
            session.network.search.return_value=[]
            def fetch(url,**options):
                options['page_action'](browser_page)
                return response
            session.fetch.side_effect=fetch
            with ScraplingSource(self.exam,self.root,0) as source, self.assertRaises(core.AccessStopped) as caught:
                source.page(2)
            self.assertEqual(caught.exception.detail['kind'],'challenge_pending')
            self.assertEqual(caught.exception.detail['page'],2)
            self.assertFalse(caught.exception.detail['automatic_retry'])
            browser_page.evaluate.assert_not_called()
            session.fetch.assert_called_once()


if __name__=='__main__':unittest.main()
