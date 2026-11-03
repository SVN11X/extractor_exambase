import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync, writeFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {BASE, LiteralReader, selectPage, buildArchive, pageNumber, imageReferences, decodeImageData, readableOutputs, zipBytes, crc32} from "../extension_navegador/core.mjs";

const source = readFileSync(new URL("../entrada_muestra/pagina1_fuente.txt", import.meta.url), "utf8");
const realScripts = [...source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const real = selectPage({url: BASE + "1", scripts: realScripts}, 1);
function synthetic(number) {
  const start = (number - 1) * 5 + 1;
  return {kind: "questions", page: number, per_page: 5, total: 349, total_pages: 70, topics: [], series: [], case_studies: [],
    items: Array.from({length: Math.min(5, 350 - start)}, (_, i) => ({id: `synthetic-${start + i}`, order: start + i, question_text: `<p>Pregunta de prueba ${start + i}</p>`, solution_text: "Explicación de prueba", choices: [{letter: "A", text: "Alternativa de prueba", is_correct: true}], type_data: {}}))};
}
const capture = number => ({number, html: "<!doctype html><title>Prueba sintética</title>", extracted: {url: BASE + number, parser: "structured", payload: {result: synthetic(number)}, warnings: []}});

test("muestra real aportada: 5 preguntas y claves C B C A D; cobertura parcial", () => {
  const data = buildArchive([{number: 1, extracted: real}]);
  assert.equal(data.questions.length, 5);
  assert.deepEqual(data.questions.map(q => q.correct_choices.join("")), ["C", "B", "C", "A", "D"]);
  assert.equal(data.report.collection_complete, false);
  assert.equal(data.report.missing_pages.length, 69);
});
test("un script de la página 1 nunca se acepta como página 2", () => {
  assert.throws(() => selectPage({url: BASE + "2", scripts: realScripts}, 2), /esperadas/);
  const page = selectPage({url: BASE + "2", scripts: realScripts, dom: synthetic(2)}, 2);
  assert.equal(page.parser, "dom"); assert.equal(page.payload.result.items[0].order, 6);
});
test("sólo admite el examen, el dominio HTTPS y páginas 1–70", () => {
  assert.equal(pageNumber(BASE + "2"), 2);
  for (const bad of ["http://www.exambase.com/exams/google/professional-data-engineer/practice-questions/2", "https://www.exambase.com.evil.test/exams/google/professional-data-engineer/practice-questions/2", BASE + "0", BASE + "71", BASE + "2/otra"]) assert.equal(pageNumber(bad), null);
});
test("lector de literales rechaza expresiones ejecutables y no contamina prototipos", () => {
  const value = new LiteralReader('{"__proto__":{"exam":"safe"},active:true,nothing:void 0,rows:[1,"x\\u00f1"]}').value();
  assert.equal(value.rows[1], "xñ"); assert.equal({}.exam, undefined); assert.equal(value.nothing, null);
  for (const bad of ["alert(1)", "(()=>1)()", "new Function()", "{a:window.cookie}"]) assert.throws(() => new LiteralReader(bad).value());
});
test("no acepta numeración incompleta, repetida ni una página distinta", () => {
  const partial = synthetic(2); partial.items.pop();
  assert.throws(() => selectPage({url: BASE + "2", dom: partial}, 2), /todas sus preguntas/);
  const duplicate = synthetic(2); duplicate.items[1].order = 6;
  assert.throws(() => selectPage({url: BASE + "2", dom: duplicate}, 2), /repetida/);
  assert.throws(() => selectPage({url: BASE + "3", dom: synthetic(2)}, 2), /cambió/);
});
test("simulación de 70 páginas: 349 preguntas, sin duplicados y última página de cuatro", () => {
  const data = buildArchive(Array.from({length: 70}, (_, i) => capture(i + 1)));
  assert.equal(data.questions.length, 349); assert.equal(data.pages.at(-1).question_count, 4);
  assert.equal(data.report.collection_complete, true); assert.equal(data.report.duplicate_observations, 0);
});
test("claves y contextos ausentes impiden declarar cobertura completa", () => {
  const all = Array.from({length: 70}, (_, i) => capture(i + 1));
  all[1].extracted.payload.result.items[0].choices[0].is_correct = null;
  all[1].extracted.payload.result.items[1].case_study_id = 23;
  const data = buildArchive(all);
  assert.equal(data.report.collection_complete, false); assert.deepEqual(data.report.missing_or_special_answers, [6]);
  assert.deepEqual(data.report.unresolved_contexts, [{question: 7, context: "case_studies:23"}]);
});
test("preserva vínculos de contexto, imágenes de alternativas, explicación y formatos especiales", () => {
  const page = capture(1), raw = page.extracted.payload.result;
  raw.case_studies = [{id: 23, text: '<p>Contexto de prueba<img src="/contexto.png"></p>'}];
  raw.items[0].case_study_id = 23; raw.items[0].choices[0].text += '<img src="/choice.png" alt="Opción">';
  raw.items[0].solution_text += '<svg xmlns="http://www.w3.org/2000/svg"><text>Diagrama</text></svg>';
  raw.items[0].type_data = {image_url: "https://www.exambase.com/formato.png"};
  const data = buildArchive([page]);
  assert.deepEqual(data.questions[0].context_refs, ["case_studies:23"]);
  assert.equal(data.questions[0].image_refs.length, 3); assert.equal(data.contexts["case_studies:23"].image_refs.length, 1);
  assert.equal(data.report.images_found, 4); assert.equal(data.report.images_failed.length, 4);
  assert.equal(imageReferences({text: '<img data-src="/x.png?a=1&amp;b=2">'})[0].source, "/x.png?a=1&b=2");
});
test("imágenes binarias conservadas y transcripción pendiente", () => {
  const dataUrl = "data:image/png;base64,iVBORw0KGgo=";
  const page = capture(1); page.extracted.payload.result.items[0].question_text += `<img src="${dataUrl}">`;
  const data = buildArchive([page], [{id: "sample", source_url: dataUrl, download_status: "downloaded", local_path: "imagenes/sample.png", data_url: dataUrl, ocr_status: "not_run"}]);
  assert.equal(data.report.images_failed.length, 0); assert.equal(data.report.image_transcription_review_complete, false);
  assert.equal(data.assets.sample.data_url, undefined); assert.equal(decodeImageData(dataUrl).bytes[0], 137);
});
test("salidas legibles escapan contenido remoto activo", () => {
  const page = capture(1); page.extracted.payload.result.items[0].question_text = '<p>Pregunta segura</p><script>alert(1)</script>';
  const output = readableOutputs(buildArchive([page]));
  assert(!output.html.includes("<script>")); assert(output.html.includes("Pregunta segura"));
});
test("ZIP con CRC y UTF-8 verificable por un lector independiente", async () => {
  assert.equal(crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
  const blob = zipBytes([{name: "prueba/explicación.txt", data: "áéíóú\n"}, {name: "prueba/imagen.bin", data: Uint8Array.from([0, 255, 1, 128])}]);
  const file = fileURLToPath(new URL("./extension_zip_verificacion.zip", import.meta.url));
  writeFileSync(file, new Uint8Array(await blob.arrayBuffer()));
  assert.equal(new DataView(await blob.arrayBuffer()).getUint32(0, true), 0x04034b50);
});

export {synthetic, capture, realScripts};
