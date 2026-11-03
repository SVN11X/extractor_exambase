import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {parseExamUrl, DEFAULT_EXAM, pageForExam, bankPrefix, outputName} from "../extension_navegador/exam.mjs";
import {discoverExam, selectPage, buildArchive, readableOutputs} from "../extension_navegador/core.mjs";
import {storedData} from "../extension_navegador/engine.mjs";
import {captureVendorCatalog} from "../extension_navegador/catalog-browser.mjs";
import {CATALOG} from "../extension_navegador/catalog-data.mjs";
import {exportState} from "../extension_navegador/export.mjs";

test("catálogo aportado: 192 proveedores, no 1657 exámenes precargados", () => {
  assert.equal(CATALOG.vendors.length, 192); assert.equal(CATALOG.total_exams, 1657);
  assert(CATALOG.vendors.some(v => v.slug === "google-cloud"));
});
test("normaliza portada y páginas de cualquier examen de ExamBase", () => {
  const a = parseExamUrl("https://www.exambase.com/exams/cisco/200-301");
  const b = parseExamUrl("https://exambase.com/exams/cisco/200-301/practice-questions/12?x=1");
  assert.equal(a.key, "cisco/200-301"); assert.equal(a.base, b.base); assert.equal(a.total, null);
  assert.equal(pageForExam(b.base + "12", a), 12); assert.equal(pageForExam(DEFAULT_EXAM.base + "1", a), null);
});
test("rechaza índices, dominios ajenos, credenciales, puertos y protocolos", () => {
  for (const url of ["https://www.exambase.com/exams/cisco", "https://evil.test/exams/cisco/a", "https://www.exambase.com.evil.test/exams/cisco/a", "http://exambase.com/exams/cisco/a", "https://a:b@exambase.com/exams/cisco/a", "https://exambase.com:8443/exams/cisco/a"]) assert.throws(() => parseExamUrl(url));
});
test("admite sitios oficiales presentes en el catálogo, con permiso separado", () => {
  const a = parseExamUrl("https://az-104.com/practice-questions/2");
  assert.equal(a.key, "az-104.com"); assert.equal(pageForExam(a.base + "2", a), 2);
});
test("detecta 12 preguntas en tres páginas y genera título del examen elegido", () => {
  const selected = parseExamUrl("https://www.exambase.com/exams/cisco/demo");
  const result = {kind: "questions", page: 1, total: 12, total_pages: 3, per_page: 5, items: Array.from({length: 5}, (_, i) => ({order: i + 1, question_text: "Prueba", choices: [{letter: "A", text: "A", is_correct: true}], solution_text: "Explicación"}))};
  const snap = {url: selected.base + "1", title: "Cisco Demo Practice Questions | ExamBase", scripts: ["let x={result:" + JSON.stringify(result) + "}"], dom: result};
  const exam = discoverExam(snap, selected), page = selectPage(snap, 1, exam);
  const data = buildArchive([{number: 1, extracted: page}], [], exam);
  assert.equal(exam.total, 12); assert.equal(exam.pages, 3); assert.equal(data.report.expected_questions, 12);
  assert(readableOutputs(data).html.includes("Cisco Demo")); assert(!readableOutputs(data).html.includes("Professional Data Engineer"));
  assert.throws(() => selectPage(snap, 1, DEFAULT_EXAM));
});
test("conserva claves antiguas de PDE y separa preguntas e imágenes por examen", () => {
  const cisco = parseExamUrl("https://www.exambase.com/exams/cisco/demo");
  const saved = {"page:1": {number: 1, marker: "pde"}, "image:abc": {marker: "pde"}, [bankPrefix(cisco) + "page:1"]: {number: 1, marker: "cisco"}, [bankPrefix(cisco) + "image:abc"]: {marker: "cisco"}};
  assert.equal(storedData(saved, DEFAULT_EXAM).captures[0].marker, "pde");
  assert.equal(storedData(saved, cisco).captures[0].marker, "cisco");
  assert.equal(storedData(saved, cisco).images.length, 1); assert.notEqual(outputName(cisco), outputName(DEFAULT_EXAM));
  const scoped = exportState({...saved, selectedExam: cisco});
  assert.equal(scoped["page:1"], undefined); assert.equal(scoped[bankPrefix(cisco) + "page:1"].marker, "cisco");
});
test("el proveedor Google Cloud conserva enlaces canónicos /google/", () => {
  const oldDoc = globalThis.document, oldLoc = globalThis.location;
  const links = [{href: DEFAULT_EXAM.base.replace("/practice-questions/", ""), innerText: "Professional Data Engineer Google Cloud 349 questions chevron_right", querySelector: selector => ({textContent:selector.includes('code')?'Professional Data Engineer':'Google Cloud'})}, {href: "https://www.exambase.com/exams/google", innerText: "Google 8 exams"}];
  globalThis.document = {querySelectorAll: selector => selector.includes("a[") ? links : []};
  globalThis.location = {href: "https://www.exambase.com/exams/google-cloud"};
  try { const data = captureVendorCatalog("google-cloud", []); assert.equal(data.exams.length, 1); assert.equal(parseExamUrl(data.exams[0].url).key, DEFAULT_EXAM.key); assert.equal(data.exams[0].name,'Professional Data Engineer'); }
  finally { globalThis.document = oldDoc; globalThis.location = oldLoc; }
});
