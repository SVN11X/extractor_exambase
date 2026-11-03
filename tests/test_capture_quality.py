import argparse
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
import descargar
import extractor as core
from access_diagnostics import classify_access,annotate_access
from browser_support import current_question_page
from capture_quality import page_quality,merge_page
from test_actions import page


def html_page(value):
    result=value['payload']['result'];cards=[]
    for q in result['items']:
        choices=''.join('<div class="list-group-item"><span>'+c['letter']+'</span><div class="exambase-question__rich-text">'+c['text']+'</div>'+('<small>Correct</small>' if c.get('is_correct') is True else '')+'</div>' for c in q['choices'])
        explanation='<div class="card"><div class="card-header">Explanation</div><div class="exambase-question__rich-text">'+q.get('solution_text','')+'</div></div>'
        cards.append(f'<div class="card"><h4 class="card-title">Question {q["order"]}</h4><div class="exambase-question__rich-text">{q["question_text"]}</div>{choices}{explanation}</div>')
    return ''.join(cards)+f'Showing {len(result["items"])} of {result["total"]} · page {result["page"]} of {result["total_pages"]}'


class CaptureQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.exam={**descargar.exam_from_url('https://www.exambase.com/exams/cisco/demo'),'total':7,'per_page':5,'pages':2}
    def tearDown(self):self.temp.cleanup()

    def test_structured_metadata_is_enriched_from_revealed_matching_dom(self):
        old=page(self.exam,1);old['payload']['result']['items'][0]['case_study_id']=99
        complete=copy.deepcopy(old)
        for q in old['payload']['result']['items']:
            q['choices'][0]['is_correct']=None;q['solution_text']=''
        html='<script>const initial={data:'+json.dumps(old['payload'])+'};</script>'+html_page(complete)
        actual=current_question_page(html,self.exam['base']+'1',1,self.exam,old)
        first=actual['payload']['result']['items'][0]
        self.assertEqual(first['id'],1);self.assertEqual(first['case_study_id'],99)
        self.assertTrue(first['choices'][0]['is_correct']);self.assertTrue(first['solution_text'])
        self.assertFalse(page_quality(actual)['missing_answers'])
        self.assertTrue(actual['enrichment'])

    def test_conflicting_explicit_answers_are_never_silently_combined(self):
        first=page(self.exam,1)
        for q in first['payload']['result']['items']:q['choices'].append({'letter':'B','text':'Otra','is_correct':False})
        other=copy.deepcopy(first)
        other['payload']['result']['items'][0]['choices'][0]['is_correct']=False
        other['payload']['result']['items'][0]['choices'][1]['is_correct']=True
        with self.assertRaisesRegex(core.ExtractionError,'contradictorias'):merge_page(first,other)

    def test_different_question_images_cannot_cross_enrich_answers(self):
        first=page(self.exam,1);other=copy.deepcopy(first)
        first['payload']['result']['items'][0]['question_text']='<img src="/a.png">'
        other['payload']['result']['items'][0]['question_text']='<img src="/b.png">'
        first['payload']['result']['items'][0]['choices'][0]['is_correct']=None
        self.assertIn(1,page_quality(merge_page(first,other))['missing_answers'])

    def test_access_diagnostics_distinguish_challenge_http_rate_limit_and_login(self):
        self.assertEqual(classify_access('<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x"></script> Cloudflare')['kind'],'challenge_pending')
        self.assertEqual(classify_access('<h2>Verification failed</h2> Error: 600010')['code'],'600010')
        self.assertEqual(classify_access('<title>Forbidden</title>',403)['kind'],'http_access_rejected')
        self.assertIsNone(classify_access('<title>Forbidden</title>',403)['provider'])
        self.assertEqual(classify_access('<h1>Rate limit</h1>',429)['kind'],'rate_limited')
        self.assertEqual(classify_access('<h1>Sign in</h1>')['kind'],'authentication_required')
        self.assertIsNone(classify_access('<section hidden><h2>Verification failed</h2>600010</section>'))
        self.assertIsNone(classify_access('<iframe hidden src="https://challenges.cloudflare.com/x"></iframe>'))

    def test_questions_can_be_preserved_with_a_challenge_blocking_answers(self):
        value=page(self.exam,1)
        for q in value['payload']['result']['items']:q['choices'][0]['is_correct']=None
        value=annotate_access(value,'<iframe src="https://challenges.cloudflare.com/x"></iframe>')
        self.assertEqual(value['access_failure']['kind'],'challenge_pending')
        self.assertEqual(len(value['payload']['result']['items']),5)

    def test_explicit_correct_badges_and_data_attributes_exclude_words_in_choice_text(self):
        self.assertTrue(core.dom_choice_is_correct('<div class="list-group-item"><small>Correct Answer</small></div>'))
        self.assertTrue(core.dom_choice_is_correct('<div class="list-group-item" data-correct="true">A</div>'))
        self.assertFalse(core.dom_choice_is_correct('<div class="list-group-item"><div class="exambase-question__rich-text"><span>Correct</span></div></div>'))

    def test_empty_question_and_choices_are_detected_without_rejecting_media_content(self):
        from capture_quality import answers_report
        data={'questions':[{'number':1,'question_text':'','question_html':'','choices':[{'letter':'A','text':'','html':''}],'correct_choices':['A']}]}
        self.assertEqual(answers_report(data)['empty_questions'],[1]);self.assertEqual(answers_report(data)['empty_choices'],[{'question':1,'letter':'A'}])
        data['questions'][0]['question_html']='<img src="/question.png">'
        data['questions'][0]['choices'][0]['html']='<img src="/choice.png">'
        self.assertFalse(answers_report(data)['empty_questions']);self.assertFalse(answers_report(data)['empty_choices'])

    def args(self,folder,resume=None):
        return argparse.Namespace(exam_url=self.exam['base']+'1',output=self.root/folder,resume_from=resume,mode='http',delay=5,max_minutes=300,page_limit=0)

    def test_full_count_with_missing_answers_fails_and_resume_only_repairs_pending_page(self):
        calls=[]
        class Source:
            assets=None;behavior='missing'
            def __init__(self,exam,*_):self.exam=exam
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def page(self,n):
                calls.append(n)
                if n==1 and self.behavior=='blocked':raise core.AccessStopped('Verificación rechazada',code='600010',page=1)
                value=page(self.exam,n)
                if n==1 and self.behavior=='missing':
                    value['payload']['result']['items'][0]['choices'][0]['is_correct']=None
                return value
        first=self.args('first')
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(first,Source),2)
        state=json.loads((first.output/'estado_ejecucion.json').read_text())
        self.assertEqual(state['questions'],7);self.assertTrue(state['coverage_complete'])
        self.assertFalse(state['execution_complete']);self.assertEqual(state['answers_missing'],[1])
        self.assertEqual(state['pages_pending_answers'],[1]);self.assertEqual(state['next_page'],1)
        Source.behavior='blocked';calls.clear();second=self.args('second',first.output/state['zip'])
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(second,Source),2)
        state=json.loads((second.output/'estado_ejecucion.json').read_text())
        self.assertEqual(calls,[1]);self.assertEqual(state['questions'],7)
        self.assertEqual(state['pages_saved'],[1,2]);self.assertEqual(state['status'],'blocked')
        Source.behavior='complete';calls.clear();third=self.args('third',second.output/state['zip'])
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(descargar.run(third,Source),0)
        state=json.loads((third.output/'estado_ejecucion.json').read_text())
        self.assertEqual(calls,[1]);self.assertTrue(state['answers_complete'])
        self.assertEqual(state['answers_present'],7);self.assertEqual(state['status'],'complete')
        data=json.loads(next(third.output.glob('resultado_*/preguntas.json')).read_text())
        self.assertEqual(data['questions'][0]['correct_choices'],['A'])
        self.assertEqual(data['questions'][0]['id'],1)


if __name__=='__main__':unittest.main()
