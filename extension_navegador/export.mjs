import {DEFAULT_EXAM, bankPrefix} from "./exam.mjs";
import {buildArchive, readableOutputs, zipBytes, decodeImageData} from "./core.mjs";
import {storedData} from "./engine.mjs";
import {aiOutputs} from "./ai.mjs";
export function exportState(saved) {
  const exam = saved.collectorJob?.exam || saved.selectedExam || DEFAULT_EXAM, prefix = bankPrefix(exam);
  const state = {selectedExam: exam, collectorJob: saved.collectorJob, runLog: saved.runLog, lastAttempt: saved.lastAttempt};
  for (const [key, value] of Object.entries(saved)) if (key.startsWith(prefix + "page:") || key.startsWith(prefix + "image:")) state[key] = value;
  return state;
}
export function exportBlob(saved) {
  const exam = saved.collectorJob?.exam || saved.selectedExam || DEFAULT_EXAM, {captures, images} = storedData(saved, exam), data = buildArchive(captures, images, exam), readable = readableOutputs(data), root = "resultado_exambase/";
  if (!captures.length) throw Error("Aún no hay preguntas guardadas.");
  const ai = aiOutputs(data);
  const entries = [
    {name: root + "preguntas.json", data: JSON.stringify(data, null, 2)}, {name: root + "informe_validacion.json", data: JSON.stringify(data.report, null, 2)},
    {name: root + "preguntas.md", data: readable.markdown}, {name: root + "preguntas.html", data: readable.html},
    {name: root + "registro.txt", data: (saved.runLog || []).join("\n")},
    {name: root + "diagnostico_navegacion.json", data: JSON.stringify({job: saved.collectorJob, lastAttempt: saved.lastAttempt}, null, 2)},
    {name: root + "manifest_examen.json", data: JSON.stringify(exam, null, 2)},
    {name: root + "para_ia/preguntas.jsonl", data: ai.jsonl},
    {name: root + "para_ia/LEEME_IA.md", data: ai.guide},
    {name: root + "para_ia/contextos.json", data: JSON.stringify(data.contexts, null, 2)},
    {name: root + "para_ia/imagenes.json", data: JSON.stringify(data.assets, null, 2)},
    {name: root + "para_ia/informe_validacion.json", data: JSON.stringify(data.report, null, 2)}
  ];
  for (const capture of captures.sort((a, b) => a.number - b.number)) {
    const tag = String(capture.number).padStart(3, "0");
    entries.push({name: root + `paginas_originales/pagina_${tag}.html`, data: capture.html});
    entries.push({name: root + `datos_originales/pagina_${tag}.json`, data: JSON.stringify(capture.extracted.payload, null, 2)});
  }
  for (const image of images) if (image.download_status === "downloaded" && data.assets[image.id]) entries.push({name: root + image.local_path, data: decodeImageData(image.data_url).bytes});
  return zipBytes(entries);
}
