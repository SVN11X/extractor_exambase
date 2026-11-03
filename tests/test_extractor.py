"""Pruebas con los HTML aportados y datos sintéticos. No requieren Internet."""
import base64
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
import zipfile
import types
import sys
from pathlib import Path
from unittest.mock import patch

import extractor as e
import browser_support as browser

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "entrada_muestra" / "pagina1_fuente.txt"
SAVED = ROOT / "entrada_muestra" / "pagina1_guardada.html"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=")
IMAGE = "data:image/png;base64," + base64.b64encode(PNG).decode()
CHALLENGE = '<html><h1>Checking That You\'re Human</h1><script>const app={data:{result:{kind:"captcha_required",type:"turnstile",action:"questions"},page:2}};</script></html>'


def fake_payload(page=1, total=1, pages=1, items=None):
    if items is None:
        items = [{"id": page, "order": page, "question_type": "mc_single", "question_text": f"Pregunta de prueba {page}<br>Contexto", "solution_text": "Explicación de prueba", "choices": [{"letter": "A", "text": "Opción de prueba", "is_correct": True}], "type_data": {}}]
    return {"result": {"kind": "questions", "page": page, "total": total, "total_pages": pages, "items": items, "topics": [], "series": [], "case_studies": []}, "discussions": {"1": {"items": [{"body": "Discusión sintética"}]}}}


def fake_html(payload):
    page = payload["result"]["page"]
    serialized = json.dumps(payload, ensure_ascii=False).replace("<", r"\u003C")
    return f'<html><link rel="canonical" href="https://example.test/practice-questions/{page}"><script>const kit={{data:{serialized}}};</script></html>'


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "salida"
        self.out.mkdir()

    def archive(self):
        assets = e.AssetStore(self.out, ocr="off")
        return e.Archive(self.out, assets)

    def test_js_literals_unicode_and_nested_values(self):
        obj = e.LiteralReader(r'{field:"Código \u003Cbr/> = 2", correct:true, other:null, n:-1.2e3, nested:[{key:"a,b:{ }"}], optional:void 0}').value()
        self.assertEqual(obj["field"], "Código <br/> = 2")
        self.assertIs(obj["correct"], True)
        self.assertEqual(obj["n"], -1200)
        self.assertIsNone(obj["optional"])

    def test_does_not_execute_expressions(self):
        for source in ["{a:alert(1)}", "{a:(function(){return 1})()}", "{a:process.env}"]:
            with self.subTest(source=source), self.assertRaises(e.ExtractionError):
                e.LiteralReader(source).value()

    def test_user_source_has_exact_answers_and_explanations(self):
        page = e.parse_page(SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(page["parser"], "structured")
        result = page["payload"]["result"]
        self.assertEqual((result["total"], result["total_pages"]), (349, 70))
        correct = [[c["letter"] for c in q["choices"] if c["is_correct"]] for q in result["items"]]
        self.assertEqual(correct, [["C"], ["B"], ["C"], ["A"], ["D"]])
        self.assertTrue(all(q["solution_text"] for q in result["items"]))
        self.assertIn("discussions", page["payload"])

    def test_saved_browser_html_never_infers_missing_answers(self):
        page = e.parse_page(SAVED.read_text(encoding="utf-8"))
        self.assertEqual(page["parser"], "dom")
        archive = self.archive()
        archive.add_page(page, SAVED.name)
        report = archive.report()
        self.assertEqual(report["missing_or_special_answers"], [1, 2, 3, 4, 5])
        self.assertFalse(report["collection_complete"])
        self.assertTrue(all(q["explanation_text"] for q in archive.questions.values()))

    def test_both_sources_merge_in_either_order_without_duplicates(self):
        pages = [e.parse_page(p.read_text(encoding="utf-8")) for p in (SAVED, SOURCE)]
        for order in [pages, list(reversed(pages))]:
            archive = self.archive()
            for p in order:
                archive.add_page(p, "archivo")
            report = archive.report()
            self.assertEqual(report["questions_extracted"], 5)
            self.assertEqual(report["duplicate_observations"], 5)
            self.assertFalse(report["conflicts"])
            self.assertFalse(report["missing_or_special_answers"])
            self.assertEqual(archive.questions[1]["correct_choices"], ["C"])

    def test_conflicting_numbers_are_reported(self):
        archive = self.archive()
        p = fake_payload()
        archive.add_page(e.parse_page(fake_html(p)), "primera")
        p["result"]["items"][0]["question_text"] = "Otro enunciado"
        archive.add_page(e.parse_page(fake_html(p)), "segunda")
        self.assertTrue(archive.report(1, 1)["conflicts"])
        self.assertFalse(archive.report(1, 1)["collection_complete"])

    def test_shared_contexts_and_their_images_are_linked(self):
        payload = fake_payload()
        payload["result"]["case_studies"] = [{"id": 9, "name": "Caso compartido", "case_study_text": '<p>Situación completa</p><img src="' + IMAGE + '">'}]
        payload["result"]["items"][0]["case_study_id"] = 9
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        data = archive.save(1, 1)
        self.assertEqual(data["questions"][0]["context_refs"], ["case_studies:9"])
        self.assertEqual(data["contexts"]["case_studies:9"]["raw"], payload["result"]["case_studies"][0])
        self.assertEqual(data["report"]["images_found"], 1)
        self.assertTrue(data["report"]["collection_complete"])
        self.assertFalse(data["report"]["image_transcription_review_complete"])
        self.assertIn("#case_studies-9", (self.out / "preguntas.md").read_text())

    def test_missing_context_prevents_complete_status(self):
        payload = fake_payload()
        payload["result"]["items"][0]["series_id"] = 22
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        report = archive.report(1, 1)
        self.assertEqual(report["unresolved_contexts"], [{"question": 1, "context": "series:22"}])
        self.assertFalse(report["collection_complete"])

    def test_unknown_answer_format_preserves_data_and_stays_pending(self):
        payload = fake_payload()
        q = payload["result"]["items"][0]
        q["choices"] = []
        q["question_type"] = "drag_drop"
        q["type_data"] = {"targets": [{"id": 5}], "answer": [3, 2, 1], "unknown_future_field": "conservar"}
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        data = archive.save(1, 1)
        self.assertEqual(data["questions"][0]["type_data"], q["type_data"])
        self.assertEqual(data["report"]["missing_or_special_answers"], [1])
        raw_files = list((self.out / "datos_originales").glob("*.json"))
        self.assertEqual(json.loads(raw_files[0].read_text())["discussions"], payload["discussions"])

    def test_missing_explanation_prevents_complete_status(self):
        payload = fake_payload()
        payload["result"]["items"][0]["solution_text"] = ""
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        self.assertFalse(archive.report(1, 1)["collection_complete"])
        self.assertEqual(archive.report(1, 1)["missing_explanations"], [1])

    def test_tables_breaks_and_code_are_readable_without_loss_of_raw(self):
        source = '<p>Encabezado</p><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table><pre>x &lt; 2\ny = 3</pre>'
        text = e.readable(source)
        self.assertIn("A\tB", text)
        self.assertIn("1\t2", text)
        self.assertIn("x < 2\ny = 3", text)

    def test_image_bytes_preserved_and_duplicate_references_share_file(self):
        assets = e.AssetStore(self.out, ocr="off")
        ref = {"source": IMAGE, "field": "question_text", "alt": "Tabla"}
        aid = assets.add(ref, "https://example.test/")
        self.assertEqual(assets.add(ref, "https://example.test/"), aid)
        self.assertEqual(len(assets.assets), 1)
        saved = assets.assets[aid]
        self.assertEqual((self.out / saved["local_path"]).read_bytes(), PNG)
        self.assertTrue(saved["review_required"])

    def test_images_in_choices_solutions_type_data_and_svg_are_detected(self):
        refs = e.scan_images({"choices": [{"text": '<img data-src="/a.png" src="placeholder.png">'}], "answer_image_url": "https://example.test/answer", "type_data": {"image": "https://example.test/no-extension"}, "solution_text": '<svg xmlns="http://www.w3.org/2000/svg"><text>2</text></svg>'})
        self.assertTrue(any(r["source"] == "/a.png" for r in refs))
        self.assertTrue(any(r["source"] == "https://example.test/answer" for r in refs))
        self.assertTrue(any(r["source"].startswith("data:image/svg+xml") for r in refs))
        self.assertTrue(any(r["source"] == "https://example.test/no-extension" for r in refs))

    def test_remote_image_stays_pending_without_network_in_local_mode(self):
        payload = fake_payload()
        payload["result"]["items"][0]["question_text"] += '<img src="https://example.test/table.png">'
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        report = archive.report(1, 1)
        self.assertEqual(len(report["images_failed"]), 1)
        self.assertFalse(report["collection_complete"])

    def test_ocr_output_is_always_marked_unverified(self):
        with patch.object(e.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"Table A 42", b"")):
            assets = e.AssetStore(self.out, ocr="on", tesseract="tesseract")
            aid = assets.add({"source": IMAGE}, "https://example.test/")
        item = assets.assets[aid]
        self.assertEqual(item["ocr_status"], "extracted_unverified")
        self.assertTrue(item["review_required"])
        self.assertEqual(item["ocr_text"], "Table A 42")

    def test_local_asset_resolution_and_path_containment(self):
        input_dir = self.out / "entrada"
        input_dir.mkdir()
        pic = input_dir / "figura.png"
        pic.write_bytes(PNG)
        source = input_dir / "pagina.html"
        source.write_text("<html></html>")
        self.assertEqual(e.image_address("figura.png", "https://example.test/", source), pic.as_uri())
        self.assertEqual(e.image_address("../secreto.png", "https://example.test/folder/", source), "https://example.test/secreto.png")
        with self.assertRaises(e.ExtractionError):
            e.image_address("file:///etc/passwd", "https://example.test/", source)

    def test_unsafe_remote_html_not_executed_in_readable_output(self):
        payload = fake_payload()
        payload["result"]["items"][0]["question_text"] = '<p>Contenido</p><script>alert(1)</script>'
        archive = self.archive()
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        data = archive.save(1, 1)
        self.assertEqual(data["questions"][0]["question_text"], "Contenido")
        self.assertIn("<script>", data["questions"][0]["question_html"])
        self.assertNotIn("<script>", (self.out / "preguntas.html").read_text())

    def test_output_escapes_active_markup(self):
        archive = self.archive()
        payload = fake_payload()
        payload["result"]["items"][0]["question_text"] = '<p>Contenido &lt;script&gt;alert(1)&lt;/script&gt;</p>'
        archive.add_page(e.parse_page(fake_html(payload)), "pagina")
        data = archive.save(1, 1)
        out = (self.out / "preguntas.html").read_text()
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertEqual(data["questions"][0]["question_html"], payload["result"]["items"][0]["question_text"])

    def test_403_stops_without_retry(self):
        d = e.Downloader(delay=0)
        err = urllib.error.HTTPError("https://example.test/", 403, "Forbidden", {}, None)
        with patch.object(d.opener, "open", side_effect=err) as opened, self.assertRaises(e.AccessStopped):
            d.get("https://example.test/")
        self.assertEqual(opened.call_count, 1)

    def test_429_has_bounded_retries(self):
        d = e.Downloader(delay=0, retries=2)
        err = urllib.error.HTTPError("https://example.test/", 429, "Rate limit", {"Retry-After": "2"}, None)
        with patch.object(d.opener, "open", side_effect=err) as opened, patch.object(e.time, "sleep"), self.assertRaises(e.AccessStopped):
            d.get("https://example.test/")
        self.assertEqual(opened.call_count, 3)

    def test_synthetic_70_page_349_question_end_to_end_and_resume(self):
        calls = []

        def get(_self, url):
            page = int(url.rsplit("/", 1)[-1])
            calls.append(page)
            items = []
            for number in range((page - 1) * 5 + 1, min(page * 5, 349) + 1):
                item = fake_payload()["result"]["items"][0]
                item.update(id=10000 + number, order=number, question_text=f"Pregunta sintética {number}")
                items.append(item)
            return fake_html(fake_payload(page, 349, 70, items)).encode(), "text/html", "utf-8"

        args = ["--url", "https://example.test/practice-questions/{page}", "--output", str(self.out), "--delay", "0", "--ocr", "off", "--zip"]
        with patch.object(e.Downloader, "get", get), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.main(args), 0)
        self.assertEqual(calls, list(range(1, 71)))
        report = json.loads((self.out / "informe_validacion.json").read_text())
        self.assertEqual(report["questions_extracted"], 349)
        self.assertTrue(report["collection_complete"])
        data = json.loads((self.out / "preguntas.json").read_text())
        self.assertEqual([q["number"] for q in data["questions"]], list(range(1, 350)))
        with zipfile.ZipFile(self.out.with_suffix(".zip")) as z:
            self.assertIn("salida/preguntas.json", z.namelist())
            self.assertIn("salida/paginas_originales/pagina_070.html", z.namelist())
        # Repetir la descarga con caché no debe volver a pedir los HTML.
        with patch.object(e.Downloader, "get", side_effect=AssertionError("No debería acceder a Internet")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(e.main(args), 0)

    def test_wrong_page_response_is_not_counted(self):
        body = fake_html(fake_payload(page=2, total=1, pages=1)).encode()
        with patch.object(e.Downloader, "get", return_value=(body, "text/html", "utf-8")), contextlib.redirect_stdout(io.StringIO()):
            code = e.main(["--url", "https://example.test/practice-questions/{page}", "--pages", "1", "--expected", "1", "--output", str(self.out), "--ocr", "off"])
        self.assertEqual(code, 2)
        report = json.loads((self.out / "informe_validacion.json").read_text())
        self.assertEqual(report["questions_extracted"], 0)
        self.assertFalse(report["collection_complete"])

    def test_turnstile_http_200_is_detected_explicitly(self):
        with self.assertRaises(e.ChallengeRequired) as caught:
            e.parse_page(CHALLENGE)
        self.assertIn("verificación", str(caught.exception))

    def test_challenge_stops_http_sequence_after_first_blocked_page(self):
        calls = []

        def get(_self, url):
            number = int(url.rsplit("/", 1)[-1])
            calls.append(number)
            content = fake_html(fake_payload(1, 349, 70)) if number == 1 else CHALLENGE
            return content.encode(), "text/html", "utf-8"

        with patch.object(e.Downloader, "get", get), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = e.main(["--output", str(self.out), "--ocr", "off"])
        self.assertEqual(code, 2)
        self.assertEqual(calls, [1, 2])
        self.assertEqual((self.out / "diagnostico/pagina_002.html").read_text(), CHALLENGE)
        report = json.loads((self.out / "informe_validacion.json").read_text())
        self.assertEqual(report["questions_extracted"], 1)
        self.assertIn("Cloudflare", report["errors"][0]["issue"])

    def test_two_unknown_failures_stop_http_sequence(self):
        calls = []

        def get(_self, url):
            number = int(url.rsplit("/", 1)[-1])
            calls.append(number)
            content = fake_html(fake_payload(1, 349, 70)) if number == 1 else "<html><h1>Other response</h1></html>"
            return content.encode(), "text/html", "utf-8"

        with patch.object(e.Downloader, "get", get), contextlib.redirect_stdout(io.StringIO()):
            e.main(["--output", str(self.out), "--ocr", "off"])
        self.assertEqual(calls, [1, 2, 3])

    def test_network_json_and_svelte_references_can_be_read(self):
        payload = fake_payload()
        self.assertEqual(browser.network_payloads({"data": payload})[0], payload)
        flattened = [{"result": 1}, {"kind": 2, "page": 3, "items": 4}, "questions", 2, [5], {"order": 6, "question_text": 7}, 6, "Pregunta sintética"]
        result = browser.network_payloads({"nodes": [{"type": "data", "data": flattened}]})[0]["result"]
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["items"][0]["order"], 6)

    def test_browser_does_not_reuse_data_from_other_page(self):
        payload = fake_payload(page=1)
        self.assertIsNone(browser.choose_page([payload], 2, "https://example.test/2"))
        self.assertEqual(browser.choose_page([payload], 1, "https://example.test/1")["payload"], payload)

    def test_browser_waits_for_user_and_collects_after_manual_verification(self):
        manual = [False]
        state = {}

        class FakePage:
            def set_default_timeout(self, _timeout):
                pass
            def on(self, _event, callback):
                state["callback"] = callback
            def goto(self, url, **kwargs):
                state["url"] = url
            def wait_for_timeout(self, _ms):
                pass
            def content(self):
                return fake_html(fake_payload()) if manual[0] else CHALLENGE

        class FakeContext:
            pages = [FakePage()]
            def close(self):
                state["closed"] = True

        class FakeChromium:
            def launch_persistent_context(self, path, **kwargs):
                state["launch"] = kwargs
                return FakeContext()

        class FakePW:
            chromium = FakeChromium()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        class FakeError(Exception):
            pass

        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = FakePW
        sync_api.Error = FakeError
        pkg = types.ModuleType("playwright")
        pkg.sync_api = sync_api

        def complete(_prompt):
            manual[0] = True
            return ""

        with patch.dict(sys.modules, {"playwright": pkg, "playwright.sync_api": sync_api}), patch("builtins.input", side_effect=complete) as ask, contextlib.redirect_stdout(io.StringIO()):
            code = e.main(["--browser", "--url", "https://example.test/practice-questions/{page}", "--pages", "1", "--expected", "1", "--output", str(self.out), "--ocr", "off"])
        self.assertEqual(code, 0)
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(state["closed"])
        self.assertEqual(state["launch"], {"channel": "msedge", "headless": False, "chromium_sandbox": True})
        self.assertTrue((self.out / "datos_navegador/pagina_001.json").is_file())
        self.assertTrue(json.loads((self.out / "informe_validacion.json").read_text())["collection_complete"])

    def test_visible_verification_failure_is_identified(self):
        failed = '<html><h2>Verification Didn\'t Go Through</h2><p>Turnstile couldn\'t verify you (error 300030).</p><button>Try again</button></html>'
        self.assertEqual(browser.verification_error(failed, e), "300030")
        self.assertIsNone(browser.verification_error(CHALLENGE, e))

    def test_a_question_mentioning_turnstile_is_not_a_failed_verification(self):
        source = '<h4 class="card-title">Question 1</h4><p>What does Turnstile error 300030 mean?</p>'
        self.assertIsNone(browser.verification_error(source, e))


if __name__ == "__main__":
    unittest.main()
