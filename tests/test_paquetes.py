import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import descargar
import paquetes
from persistir_banco import persist
from actualizar_catalogo import parse_vendor, update
from html_support import soup_page
from test_actions import page


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def collect(self, name='demo'):
        args = argparse.Namespace(exam_url=f'https://www.exambase.com/exams/cisco/{name}', output=self.root / name, resume_from=None, mode='scrapling', delay=5, max_minutes=300, page_limit=0)
        class Source:
            assets = None
            def __init__(self, exam, output, delay): self.exam = exam
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def page(self, n): return page(self.exam, n)
        self.assertEqual(descargar.run(args, Source), 0)
        return args.output, args.output / f'resultado_cisco_{name}'
    def test_ai_and_hashes_are_complete(self):
        self.assertEqual(descargar.core.readable('<p>actor=<actorname> o <timestamp>#<sensorid></sensorid></timestamp></actorname></p>'), 'actor=<actorname> o <timestamp>#<sensorid>')
        _, result = self.collect()
        rows = [json.loads(s) for s in (result / 'para_ia/preguntas.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows), 7)
        self.assertEqual(len({r['stable_id'] for r in rows}), 7)
        hashes = json.loads((result / 'integridad_sha256.json').read_text())['files']
        self.assertIn('para_ia/preguntas.jsonl', hashes)
        for path, digest in hashes.items(): self.assertEqual(hashlib.sha256((result / path).read_bytes()).hexdigest(), digest)
    def test_two_exams_persist_as_separate_versions(self):
        first, _ = self.collect('uno')
        second, _ = self.collect('dos')
        a = persist(first, self.root / 'repo', '101')
        b = persist(second, self.root / 'repo', '102')
        self.assertNotEqual(a['zip_path'], b['zip_path'])
        index = json.loads((self.root / 'repo/bancos/index.json').read_text())
        self.assertEqual(sorted(v['run_id'] for v in index['exams']), ['101', '102'])
        self.assertTrue((self.root / 'repo' / a['zip_path']).is_file())
        persist(first, self.root / 'repo', '101')
        self.assertEqual(len(json.loads((self.root / 'repo/bancos/index.json').read_text())['exams']), 2)
    def test_missing_explanations_and_images_do_not_claim_review_complete(self):
        _, result = self.collect()
        data = json.loads((result / 'preguntas.json').read_text())
        data['questions'][0]['explanation_text'] = ''
        data['questions'][0]['explanation_html'] = ''
        data['assets']['x'] = {'id': 'x', 'local_path': 'imagenes/missing.png'}
        (result / 'preguntas.json').write_text(json.dumps(data))
        changed = paquetes.enrich(result)
        self.assertTrue(changed['report']['coverage_complete'])
        self.assertFalse(changed['report']['content_review_complete'])
        self.assertEqual(changed['report']['images_failed'], ['x'])
        self.assertEqual(changed['report']['images_found'], 1)
        self.assertEqual(changed['report']['images_downloaded'], 0)
        self.assertEqual(changed['report']['missing_explanations'], [1])
    def test_asset_path_escape_is_rejected(self):
        with self.assertRaises(ValueError): paquetes.safe_asset(self.root, '../escape.png')
    def test_reader_places_choice_image_before_next_choice(self):
        _, result = self.collect()
        data = json.loads((result / 'preguntas.json').read_text())
        q = data['questions'][0]
        q['choices'] = [{'letter':'A','text':'Primera'}, {'letter':'B','text':'Segunda'}]
        q['image_refs'] = [{'asset_id':'image','field':'choices[0].text'}]
        data['assets']['image'] = {'id':'image','local_path':'imagenes/image.png','ocr_status':'not_run'}
        rendered, _ = paquetes.reader(data)
        self.assertLess(rendered.index('imagenes/image.png'), rendered.index('B. Segunda'))
    def test_vendor_parser_accepts_alias_and_ignores_navigation(self):
        source = '<main><a href="/exams/google/demo"><h3>Demo</h3>42 questions</a><a href="/exams/cisco">Cisco</a></main>'
        exams = parse_vendor(source, {'vendor':'Google Cloud','slug':'google-cloud'})
        self.assertEqual(exams[0]['id'], 'google/demo')
        self.assertEqual(exams[0]['vendor_slug'], 'google-cloud')
        self.assertEqual(exams[0]['questions'], 42)
        actual = '<main><a class="ebo-idx__row" href="https://www.exambase.com/exams/google/professional-data-engineer"><span class="ebo-idx__code">Professional Data Engineer</span><span class="ebo-idx__info"><span class="ebo-idx__name">Google Cloud</span><span class="ebo-idx__blurb">Descripción separada</span></span><span class="ebo-idx__count">349 questions</span></a></main>'
        self.assertEqual(parse_vendor(actual, {'vendor':'Google Cloud','slug':'google-cloud'})[0]['name'], 'Professional Data Engineer')
    def test_catalog_failure_preserves_entries(self):
        path=self.root/'catalog.json'
        original={'vendors':[{'vendor':'Cisco','slug':'cisco'}], 'exams':[{'id':'cisco/old','vendor':'Cisco','name':'Old','vendor_slug':'cisco'}]}
        path.write_text(json.dumps(original))
        source=MagicMock();source.get.side_effect=descargar.core.AccessStopped('HTTP 403')
        result=update(path,'cisco',5,source)
        self.assertTrue(result['errors'])
        self.assertEqual(json.loads(path.read_text())['exams'], original['exams'])
    def test_soup_reads_answers_and_keeps_missing_keys_missing(self):
        source='<h4 class="card-title">Not a card</h4><div class="card"><h4 class="card-title">Question 1</h4><div class="exambase-question__rich-text">Pregunta</div><div class="list-group-item"><span>A</span><div class="exambase-question__rich-text">Opción</div><small>Correct</small></div></div>Showing 1 of 1 · page 1 of 1'
        data=soup_page(source,'https://www.exambase.com/exams/cisco/demo/practice-questions/1')
        self.assertEqual(data['payload']['result']['total'], 1)
        self.assertTrue(data['payload']['result']['items'][0]['choices'][0]['is_correct'])
        data=soup_page(source.replace('<small>Correct</small>',''),data['url'])
        self.assertIsNone(data['payload']['result']['items'][0]['choices'][0]['is_correct'])


if __name__ == '__main__': unittest.main()
