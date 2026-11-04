import argparse
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import descargar
import extractor as core
from access_diagnostics import observe_document, transport_exception
from browser_support import current_question_page
from capture_quality import answers_report
from scrapling_support import ScraplingSource
from test_actions import page
from test_capture_quality import html_page


class MetadataRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.exam={**descargar.exam_from_url('https://www.exambase.com/exams/cisco/demo'),'total':7,'pages':2,'per_page':5}
    def tearDown(self):self.temp.cleanup()
    def pair(self):
        visible=page(self.exam,2)
        structured=copy.deepcopy(visible)
        for i,q in enumerate(structured['payload']['result']['items'],1):
            q['order']=i;q['topic_id']=90
        structured['payload']['result']['topics']=[{'id':90,'title':'Tema'}]
        return visible,structured
    def parse(self,visible,structured,**kw):
        html='<script>const initial={data:'+json.dumps(structured['payload'])+'};</script>'+html_page(visible)
        return current_question_page(html,self.exam['base']+'2',2,self.exam,**kw)

    def test_topic_local_order_keeps_source_ids_and_original_order(self):
        visible,structured=self.pair()
        result=self.parse(visible,structured)
        items=result['payload']['result']['items']
        self.assertNotEqual(result['parser'],'dom')
        self.assertEqual([q['order'] for q in items],[6,7])
        self.assertEqual([q['source_order'] for q in items],[1,2])
        self.assertEqual([q['id'] for q in items],[6,7])
        self.assertEqual([q['topic_id'] for q in items],[90,90])
        self.assertEqual(result['numbering_alignment']['method'],'identical_visible_content')
        self.assertEqual(structured['payload']['result']['items'][0]['order'],1)

    def test_skipped_internal_number_is_aligned_using_visible_content(self):
        visible,structured=self.pair();structured['payload']['result']['items'][0]['order']=5
        result=self.parse(visible,structured)
        self.assertEqual(result['payload']['result']['items'][0]['source_order'],5)
        self.assertEqual(result['payload']['result']['items'][0]['order'],6)

    def test_network_metadata_survives_a_stale_captcha_bootstrap(self):
        visible,structured=self.pair()
        html='<script>const initial={result:{kind:"captcha_required"}};</script>'+html_page(visible)
        result=current_question_page(html,self.exam['base']+'2',2,self.exam,candidates=[structured['payload']])
        self.assertEqual(result['parser'],'browser-network')
        self.assertEqual(result['payload']['result']['items'][0]['topic_id'],90)

    def test_changed_text_or_other_page_does_not_supply_metadata(self):
        for field in ('text','page'):
            visible,structured=self.pair()
            if field=='text':structured['payload']['result']['items'][0]['question_text']='Otra pregunta'
            else:structured['payload']['result']['page']=1
            result=self.parse(visible,structured)
            self.assertEqual(result['parser'],'dom')
            self.assertIsNone(result['payload']['result']['items'][0]['id'])

    def test_matching_global_numbers_do_not_hide_changed_question_content(self):
        visible=page(self.exam,2);structured=copy.deepcopy(visible)
        structured['payload']['result']['items'][0]['question_text']='Contenido antiguo de otra versión'
        result=self.parse(visible,structured)
        self.assertEqual(result['parser'],'dom')
        self.assertEqual(result['payload']['result']['items'][0]['question_text'],visible['payload']['result']['items'][0]['question_text'])

    def test_ambiguous_duplicate_content_is_not_assigned_ids(self):
        visible,structured=self.pair()
        for group in (visible,structured):
            group['payload']['result']['items'][1]['question_text']=group['payload']['result']['items'][0]['question_text']
        self.assertEqual(self.parse(visible,structured)['parser'],'dom')

    def test_a_changed_dataset_count_still_requires_restart(self):
        visible,structured=self.pair()
        visible['payload']['result']['total']=structured['payload']['result']['total']=8
        with self.assertRaises(descargar.DatasetChanged):self.parse(visible,structured)

    def test_saved_html_recovers_metadata_without_opening_a_browser(self):
        exam=self.exam
        class Source:
            assets=None
            def __init__(self,exam,output,*_):self.exam,self.output=exam,output
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def page(self,n):
                value=page(self.exam,n);data=copy.deepcopy(value)
                for i,q in enumerate(data['payload']['result']['items'],1):q['order']=i
                html='<script>const initial={data:'+json.dumps(data['payload'])+'};</script>'+html_page(value)
                path=self.output/'paginas_originales'/f'pagina_{n:05}.html';path.parent.mkdir(exist_ok=True);path.write_text(html)
                for q in value['payload']['result']['items']:
                    q['id']=None;q['_dom_card_html']='<div>Captura visible</div>'
                return {'url':value['url'],'parser':'dom','payload':value['payload'],'warnings':[]}
        args=argparse.Namespace(exam_url=exam['base']+'1',output=self.root/'first',resume_from=None,mode='scrapling',delay=0,max_minutes=5,page_limit=0)
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(args,Source),2)
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        args.resume_from=args.output/state['zip'];args.output=self.root/'resumed'
        forbidden=Mock(side_effect=AssertionError('No se debe abrir otra sesión.'))
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(args,forbidden),0)
        forbidden.assert_not_called()
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual(state['pages_recovered_offline'],[1,2])
        self.assertFalse(state['metadata_unverified_questions'])

    def test_modified_snapshot_hash_is_not_trusted(self):
        visible,structured=self.pair()
        html='<script>const initial={data:'+json.dumps(structured['payload'])+'};</script>'+html_page(visible)
        path=self.root/'paginas_originales/pagina_00002.json';path.parent.mkdir()
        path.write_text(json.dumps({'format':'captured_html_as_data','html':html,'sha256_original':'incorrecto'}))
        visible['parser']='dom'
        self.assertIs(descargar.recover_saved_metadata(self.root,self.exam,2,visible),visible)

    def test_all_false_source_marks_remain_missing_despite_explanation(self):
        raw={'choices':[{'letter':'A','is_correct':False},{'letter':'B','is_correct':False}]}
        data={'questions':[{'number':288,'question_text':'Pregunta','choices':[{'letter':'A','text':'A'},{'letter':'B','text':'B'}],
                            'correct_choices':[],'raw':raw,'explanation_text':'La opción B sería correcta.'}]}
        report=answers_report(data)
        self.assertEqual(report['answers_unmarked_in_source'],[288])
        self.assertEqual(report['answers_missing'],[288])
        self.assertFalse(report['answers_complete'])

    def test_unknown_http_response_failure_is_not_labeled_cloudflare(self):
        error=transport_exception(Exception('Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE'),self.exam['base']+'2',2)
        self.assertIsInstance(error,core.TransportError)
        self.assertEqual(error.detail['code'],'ERR_HTTP_RESPONSE_CODE_FAILURE')
        self.assertIsNone(error.detail['http_status'])
        self.assertNotIn('cloudflare',str(error).lower())

    def test_observed_http_rejection_is_preserved_without_retry(self):
        tab=Mock();evidence={};setup=observe_document(self.exam['base']+'2',evidence);setup(tab)
        callback=tab.on.call_args.args[1]
        response=Mock(status=403,url=self.exam['base']+'2');response.request.resource_type='document'
        callback(response)
        error=transport_exception(Exception('net::ERR_HTTP_RESPONSE_CODE_FAILURE'),self.exam['base']+'2',2,evidence)
        self.assertIsInstance(error,core.AccessStopped)
        self.assertEqual(error.detail['code'],'403')
        self.assertFalse(error.detail['automatic_retry'])

    def test_transport_failure_keeps_checkpoint_and_exact_browser_code(self):
        exam=self.exam
        class Source:
            assets=None
            def __init__(self,*_):pass
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def page(self,n):
                if n==2:raise transport_exception(Exception('net::ERR_HTTP_RESPONSE_CODE_FAILURE'),exam['base']+'2',2)
                return page(exam,n)
        args=argparse.Namespace(exam_url=exam['base']+'1',output=self.root/'transport',resume_from=None,mode='scrapling',delay=0,max_minutes=5,page_limit=0)
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(args,Source),2)
        state=json.loads((args.output/'estado_ejecucion.json').read_text())
        self.assertEqual(state['questions'],5);self.assertEqual(state['next_page'],2)
        self.assertIsNone(state['failure'])
        self.assertEqual(state['transport_failure']['code'],'ERR_HTTP_RESPONSE_CODE_FAILURE')


if __name__=='__main__':unittest.main()
