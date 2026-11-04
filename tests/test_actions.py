import argparse
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import descargar
import extractor as core

URL = "https://www.exambase.com/exams/cisco/demo"


def page(exam, number, total=7):
    first = (number - 1) * 5 + 1
    result = {"kind": "questions", "page": number, "total": total, "total_pages": (total + 4) // 5, "per_page": 5, "topics": [], "series": [], "case_studies": [], "items": [
        {"id": i, "order": i, "question_text": f"Pregunta sintética {i}", "solution_text": "Explicación sintética", "choices": [{"letter": "A", "text": "Opción sintética", "is_correct": True}], "type_data": {}} for i in range(first, min(total + 1, first + 5))]}
    return {"url": exam["base"] + str(number), "parser": "structured", "payload": {"result": result}, "warnings": []}


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, **changes):
        values = dict(exam_url=URL, output=self.root / "salida", resume_from=None, mode="scrapling", delay=5, max_minutes=300, page_limit=0)
        values.update(changes)
        return argparse.Namespace(**values)

    def factory(self, blocked=None, modify=None):
        calls = self.calls
        class Source:
            assets = None
            def __init__(self, exam, output, delay):
                self.exam = exam
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def page(self, number):
                calls.append(number)
                if number == blocked:
                    raise core.ChallengeRequired("Verificación pendiente; no se resolverá en CI.")
                value = page(self.exam, number)
                return modify(value) if modify else value
        return Source

    def state(self, args):
        return json.loads((args.output / "estado_ejecucion.json").read_text())

    def test_normalization_and_domain_restrictions(self):
        a = descargar.exam_from_url(URL)
        b = descargar.exam_from_url(URL + "/practice-questions/2")
        self.assertEqual(a, b)
        self.assertEqual(descargar.exam_from_url("https://az-104.com")['key'], "az-104.com")
        for bad in ["https://evil.test/exams/cisco/demo", "http://www.exambase.com/exams/cisco/demo", "https://a:b@exambase.com/exams/cisco/demo", "https://exambase.com/exams/cisco"]:
            with self.assertRaises(core.ExtractionError):
                descargar.exam_from_url(bad)

    def test_complete_dynamic_exam(self):
        args = self.args()
        self.assertEqual(descargar.run(args, self.factory()), 0)
        state = self.state(args)
        self.assertEqual(state['questions'], 7)
        self.assertTrue(state['coverage_complete'])
        self.assertEqual(state['exam']['pages'], 2)
        with zipfile.ZipFile(args.output / state['zip']) as z:
            self.assertIsNone(z.testzip())
            names = z.namelist()
            manifest = next(n for n in names if n.endswith('/manifest_examen.json'))
            self.assertEqual(json.loads(z.read(manifest))['key'], 'cisco/demo')
            rendered = z.read(next(n for n in names if n.endswith('/preguntas.html'))).decode()
            self.assertIn('<h1>demo</h1>', rendered)
            self.assertNotIn('Professional Data Engineer', rendered)

    def test_partial_then_resume_uses_cache(self):
        first = self.args(page_limit=1)
        self.assertEqual(descargar.run(first, self.factory()), 2)
        zip_path = first.output / self.state(first)['zip']
        second = self.args(output=self.root / 'segunda', resume_from=zip_path)
        self.calls.clear()
        self.assertEqual(descargar.run(second, self.factory()), 0)
        self.assertEqual(self.calls, [2])
        self.assertEqual(self.state(second)['questions'], 7)

    def test_challenge_saves_partial_without_input_or_loop(self):
        args = self.args()
        self.assertEqual(descargar.run(args, self.factory(blocked=2)), 2)
        state = self.state(args)
        self.assertEqual(self.calls, [1, 2])
        self.assertEqual(state['questions'], 5)
        self.assertIn('Verificación', state['stopped_reason'])
        self.assertTrue((args.output / state['zip']).exists())

    def test_unknown_counts_remain_unknown(self):
        def missing(value):
            value['payload']['result']['total'] = None
            return value
        args = self.args()
        self.assertEqual(descargar.run(args, self.factory(modify=missing)), 2)
        state = self.state(args)
        with zipfile.ZipFile(args.output / state['zip']) as z:
            report = json.loads(z.read(next(n for n in z.namelist() if n.endswith('/informe_validacion.json'))))
            self.assertIsNone(report['expected_questions'])
            self.assertFalse(report['coverage_complete'])

    def test_resume_rejects_other_exam(self):
        args = self.args(page_limit=1)
        descargar.run(args, self.factory())
        path = args.output / self.state(args)['zip']
        with self.assertRaisesRegex(core.ExtractionError, 'otro examen'):
            descargar.restore(path, self.root / 'otro', descargar.exam_from_url('https://www.exambase.com/exams/cisco/otro'))

    def test_restore_rejects_path_escape(self):
        path = self.root / 'malicioso.zip'
        exam = {**descargar.exam_from_url(URL), 'total': 7, 'pages': 2, 'per_page': 5}
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('bank/manifest_examen.json', json.dumps(exam))
            z.writestr('bank/../escape.txt', 'no')
        with self.assertRaises(core.ExtractionError):
            descargar.restore(path, self.root / 'destino', exam)
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_duplicate_number_is_not_accepted(self):
        exam = descargar.exam_from_url(URL)
        one = page(exam, 1)
        exam.update(descargar.detect_counts(exam, one))
        one['payload']['result']['items'][1]['order'] = 1
        with self.assertRaises(core.ExtractionError):
            descargar.validate_page(exam, one, 1)

    def test_workflow_inputs_are_env_not_shell_substitution(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        workflow = yaml.load((root/'.github/workflows/descargar-examen.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(list(workflow['on']['workflow_dispatch']['inputs']), ['exam_url'])
        action = (root/'.github/actions/ejecutar/action.yml').read_text()
        self.assertIn('if: always()', action)
        self.assertIn('actions/upload-artifact@v6', action)
        self.assertIn('EXAM_URL: ${{ inputs.exam_url }}', action)
        self.assertIn('--exam-url "$EXAM_URL"', action)
        self.assertNotIn('python acciones.py examen --exam-url "${{', action)
        self.assertFalse((root/'.github/workflows/publicar-pages.yml').exists())

    def test_interrupt_keeps_partial_result(self):
        def interrupt(value):
            if value['payload']['result']['page'] == 2:
                raise KeyboardInterrupt
            return value
        args = self.args()
        self.assertEqual(descargar.run(args, self.factory(modify=interrupt)), 2)
        self.assertEqual(self.state(args)['questions'], 5)
        self.assertIn('interrumpida', self.state(args)['stopped_reason'])

    def test_restore_rejects_unbounded_metadata(self):
        path = self.root / 'metadata.zip'
        exam = descargar.exam_from_url(URL)
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('bank/manifest_examen.json', json.dumps({**exam, 'total': 10**15, 'pages': 10**10, 'per_page': 5}))
        with self.assertRaises(core.ExtractionError):
            descargar.restore(path, self.root / 'destino', exam)

    def test_cli_rejects_non_finite_delays(self):
        with self.assertRaises(SystemExit) as caught:
            descargar.main(['--exam-url', URL, '--delay', 'nan'])
        self.assertEqual(caught.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
