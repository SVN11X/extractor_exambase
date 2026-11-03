import {DEFAULT_EXAM, pageForExam, normalizeCounts} from "./exam.mjs";
// Sin eval, bibliotecas remotas, cambios de identidad ni acceso a cookies.
export const BASE = "https://www.exambase.com/exams/google/professional-data-engineer/practice-questions/";
export const EXPECTED = 349;
export const PAGES = 70;

export function pageNumber(url, exam = DEFAULT_EXAM) { return pageForExam(url, exam); }

// Lector de datos JS literales de Svelte. No ejecuta el código del sitio.
export class LiteralReader {
  constructor(text, position = 0) { this.text = text; this.position = position; this.nodes = 0; }
  ws() { while (/\s/.test(this.text[this.position] || "") && this.position < this.text.length) this.position++; }
  string() {
    const quote = this.text[this.position++];
    let result = "";
    while (this.position < this.text.length) {
      const c = this.text[this.position++];
      if (c === quote) return result;
      if (c !== "\\") { result += c; continue; }
      const escaped = this.text[this.position++];
      const codes = {n: "\n", r: "\r", t: "\t", b: "\b", f: "\f", v: "\v", "0": "\0"};
      if (escaped === "u" || escaped === "x") {
        const size = escaped === "u" ? 4 : 2;
        const digits = this.text.slice(this.position, this.position + size);
        if (!new RegExp(`^[0-9a-f]{${size}}$`, "i").test(digits)) throw Error("Escape inválido");
        result += String.fromCharCode(parseInt(digits, 16)); this.position += size;
      } else if (["\\", "\"", "'", "/"].includes(escaped)) result += escaped;
      else if (Object.hasOwn(codes, escaped)) result += codes[escaped];
      else throw Error("Escape no admitido");
    }
    throw Error("Literal incompleto");
  }
  value(depth = 0) {
    if (depth > 100 || ++this.nodes > 250000) throw Error("Datos demasiado grandes");
    this.ws(); const c = this.text[this.position];
    if (c === "\"" || c === "'") return this.string();
    if (c === "{" || c === "[") {
      const object = c === "{"; const end = object ? "}" : "]";
      const result = object ? Object.create(null) : []; this.position++;
      while (true) {
        this.ws(); if (this.text[this.position] === end) { this.position++; return result; }
        if (object) {
          let key;
          if (["\"", "'"].includes(this.text[this.position])) key = this.string();
          else {
            const m = this.text.slice(this.position).match(/^[A-Za-z_$][\w$]*/);
            if (!m) throw Error("Clave no admitida"); key = m[0]; this.position += key.length;
          }
          this.ws(); if (this.text[this.position++] !== ":" || Object.hasOwn(result, key)) throw Error("Objeto inválido");
          result[key] = this.value(depth + 1);
        } else result.push(this.value(depth + 1));
        this.ws(); const separator = this.text[this.position++];
        if (separator === end) return result;
        if (separator !== ",") throw Error("Separador no admitido");
      }
    }
    for (const [word, value] of [["true", true], ["false", false], ["null", null], ["undefined", null], ["void 0", null]]) {
      if (this.text.startsWith(word, this.position) && !/[\w$]/.test(this.text[this.position + word.length] || "")) {
        this.position += word.length; return value;
      }
    }
    const match = this.text.slice(this.position).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!match) throw Error("Expresión ejecutable no admitida");
    this.position += match[0].length; return Number(match[0]);
  }
}

export function selectPage(snapshot, expectedPage, exam = DEFAULT_EXAM) {
  if (pageNumber(snapshot.url, exam) !== expectedPage) throw Error("La pestaña cambió de página durante la captura.");
  for (const script of snapshot.scripts || []) {
    for (const [level, pattern] of [
      [0, /(?:\bdata|"data")\s*:\s*(\{\s*(?:result|"result")\s*:)/g],
      [1, /(?:\bresult|"result")\s*:\s*(\{)/g]
    ]) {
      for (const match of script.matchAll(pattern)) {
        try {
          const index = match.index + match[0].length - match[1].length;
          const value = new LiteralReader(script, index).value();
          const payload = level === 0 ? value : {result: value};
          if (payload.result?.kind !== "questions" || payload.result.page !== expectedPage || !payload.result.items?.length) continue;
          validateItems(payload.result, expectedPage, exam);
          return {url: snapshot.url, parser: "structured", payload, warnings: []};
        } catch { /* Un script viejo u otro objeto no es la página actual. */ }
      }
    }
  }
  if (!snapshot.dom?.items?.length || snapshot.dom.page !== expectedPage) throw Error("La página aún no entregó las preguntas esperadas.");
  validateItems(snapshot.dom, expectedPage, exam);
  return {url: snapshot.url, parser: "dom", payload: {result: snapshot.dom}, warnings: [
    "Se conserva el contenido visible y los contextos desplegados. Revisar los contextos de esta página: no se encontró el objeto estructurado actual."
  ]};
}

export function discoverExam(snapshot, selected) {
  const number = pageNumber(snapshot.url, selected);
  if (number !== 1) throw Error("La detección del examen debe comenzar en la página 1.");
  const name = String(snapshot.title || selected.name).replace(/\s*(?:Practice Questions.*|\|.*)$/i, "").trim() || selected.name;
  for (const script of snapshot.scripts || []) {
    for (const m of script.matchAll(/(?:\bresult|"result")\s*:\s*(\{)/g)) {
      try {
        const result = new LiteralReader(script, m.index + m[0].length - 1).value();
        if (result.kind === "questions" && result.page === 1) return normalizeCounts({...selected, name}, result);
      } catch { /* El DOM puede contener el resultado de una carga posterior. */ }
    }
  }
  if (snapshot.dom?.page === 1) return normalizeCounts({...selected, name}, snapshot.dom);
  throw Error("La página aún no entregó los totales del examen seleccionado.");
}

export function validateItems(result, page, exam = DEFAULT_EXAM) {
  const EXPECTED = exam.total, PAGES = exam.pages;
  if (!EXPECTED || !PAGES || !exam.perPage) throw Error("Falta detectar la paginación de este examen.");
  const numbers = result.items.map(q => q.order);
  if (numbers.some(n => !Number.isInteger(n) || n < 1 || n > EXPECTED) || new Set(numbers).size !== numbers.length) throw Error("Numeración inválida o repetida dentro de una página.");
  const perPage = result.per_page || exam.perPage;
  const expected = Array.from({length: Math.min(perPage, EXPECTED - (page - 1) * perPage)}, (_, i) => (page - 1) * perPage + i + 1);
  if (numbers.length !== expected.length || expected.some(n => !numbers.includes(n))) throw Error(`La página ${page} no conserva todas sus preguntas. Se espera ${expected.join(", ")}.`);
  if (result.total && result.total !== EXPECTED) throw Error(`El sitio indica ${result.total} preguntas; el total esperado es ${EXPECTED}.`);
  if (result.total_pages && result.total_pages !== PAGES) throw Error("Cambió el número total de páginas del sitio.");
}

export function textFromHtml(source = "") {
  const tags = new Set('a abbr address area article aside audio b base bdi bdo blockquote body br button canvas caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol optgroup option output p param picture pre progress q rp rt ruby s samp script search section select slot small source span strong style sub summary sup table tbody td template textarea tfoot th thead time title tr track u ul var video wbr svg path g circle rect ellipse line polyline polygon defs text tspan use symbol foreignobject mask clippath lineargradient radialgradient stop filter'.split(' '));
  source = String(source).replace(/<([A-Za-z][\w:-]*)\s*>/g, (whole, tag) => tags.has(tag.toLowerCase()) ? whole : '&lt;'+tag+'&gt;');
  if (typeof DOMParser !== "undefined") {
    const doc = new DOMParser().parseFromString(String(source).replace(/<(br|\/p|\/div|\/li|\/tr|\/h[1-6])\b[^>]*>/gi, "$&\n"), "text/html");
    doc.querySelectorAll("script,style").forEach(n => n.remove());
    return doc.body.textContent.replace(/\u00a0/g, " ").replace(/\n[ \t]+/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  const entities = {amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " "};
  return String(source).replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, "").replace(/<(?:br\b[^>]*|\/(?:p|div|li|tr|h[1-6]))>/gi, "\n").replace(/<[^>]+>/g, "").replace(/&(#x[\da-f]+|#\d+|\w+);/gi, (whole, code) => {
    if (code.startsWith("#")) { const n = code[1].toLowerCase() === "x" ? parseInt(code.slice(2), 16) : Number(code.slice(1)); return n >= 0 && n <= 0x10ffff ? String.fromCodePoint(n) : whole; }
    return entities[code] ?? whole;
  }).trim();
}

export function utf8Base64(value) {
  let binary = ""; for (const byte of new TextEncoder().encode(value)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function imageReferences(value, field = "") {
  const found = [];
  if (Array.isArray(value)) value.forEach((child, i) => found.push(...imageReferences(child, `${field}[${i}]`)));
  else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) if (!key.startsWith("_dom_card")) found.push(...imageReferences(child, field ? `${field}.${key}` : key));
  } else if (typeof value === "string") {
    for (const m of value.matchAll(/<(img|image|source)\b[^>]*>/gi)) {
      const attrs = Object.create(null);
      for (const a of m[0].matchAll(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g)) attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4];
      const source = attrs["data-original"] || attrs["data-src"] || attrs.src || attrs.href || attrs["xlink:href"];
      if (source) found.push({source: source.replace(/&amp;/g, "&"), field, alt: attrs.alt || ""});
      if (attrs.srcset && !source) {
        const last = attrs.srcset.split(",").at(-1).trim().split(/\s+/)[0];
        if (last) found.push({source: last, field, alt: attrs.alt || ""});
      }
    }
    for (const svg of value.matchAll(/<svg\b[\s\S]*?<\/svg>/gi)) found.push({source: `data:image/svg+xml;base64,${utf8Base64(svg[0])}`, field, alt: "Diagrama SVG original"});
    const last = field.split(".").at(-1)?.toLowerCase() || "";
    if (/^data:image\//i.test(value) || (/^(https?:\/\/|\/|\.\.?\/)/i.test(value) && (/\.(png|jpe?g|gif|webp|svg|bmp|tiff?|avif)([?#]|$)/i.test(value) || /image_url|imageurl|image_src/.test(last) || ["image", "images", "img", "src", "answer_image", "question_image"].includes(last)))) found.push({source: value, field, alt: ""});
  }
  return found;
}

export function imageUrl(source, base) {
  const url = new URL(source, base);
  if (!["https:", "data:"].includes(url.protocol) || (url.protocol === "data:" && !/^data:image\//i.test(source))) throw Error("Referencia de imagen no admitida");
  return url.href;
}

function contextRefs(raw) {
  return [["topics", "topic_id"], ["series", "series_id"], ["case_studies", "case_study_id"]].filter(([, field]) => raw[field] != null).map(([kind, field]) => `${kind}:${raw[field]}`);
}

// El orden de las propiedades JSON no cambia el contenido de un contexto.
export function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(k => [k, stableValue(value[k])]));
  return value;
}

export function buildArchive(captures, imageRecords = [], exam = DEFAULT_EXAM) {
  const EXPECTED = exam.total, PAGES = exam.pages;
  const questions = new Map(), contexts = Object.create(null), assets = Object.create(null), pages = [], conflicts = [], errors = [];
  const byUrl = new Map(imageRecords.map(a => [a.source_url, a]));
  let duplicateObservations = 0;
  function references(value, base) {
    return imageReferences(value).map(ref => {
      let address; try { address = imageUrl(ref.source, base); } catch { address = ref.source; }
      let item = byUrl.get(address);
      if (!item) {
        item = {id: `pending_${byUrl.size}`, source_url: address, download_status: "pending", ocr_status: "not_run", review_required: true};
        byUrl.set(address, item);
      }
      const {data_url, ...publicItem} = item; // Los bytes van en imagenes/, no duplicados en preguntas.json.
      assets[item.id] = publicItem;
      return {...ref, asset_id: item.id};
    });
  }
  for (const capture of [...captures].sort((a, b) => a.number - b.number)) {
    const page = capture.extracted, result = page.payload.result;
    try { validateItems(result, capture.number, exam); } catch (e) { errors.push({page: capture.number, issue: e.message}); continue; }
    pages.push({page: capture.number, url: page.url, parser: page.parser, question_count: result.items.length, warnings: page.warnings});
    for (const kind of ["topics", "series", "case_studies"]) {
      for (const raw of Object.values(result[kind] || {})) {
        if (!raw || typeof raw !== "object" || raw.id == null) continue;
        const key = `${kind}:${raw.id}`;
        if (contexts[key] && JSON.stringify(stableValue(contexts[key].raw)) !== JSON.stringify(stableValue(raw))) conflicts.push({context: key, issue: "Contenido distinto para el mismo contexto"});
        else contexts[key] = {key, raw, image_refs: references(raw, page.url)};
      }
    }
    for (const raw of result.items) {
      const choices = (raw.choices || []).map(c => ({id: c.id, letter: c.letter, html: c.text || "", text: textFromHtml(c.text || ""), is_correct: c.is_correct ?? null}));
      const correct = choices.filter(c => c.is_correct === true).map(c => c.letter);
      const q = {id: raw.id ?? null, number: raw.order, question_type: raw.question_type, question_html: raw.question_text || "", question_text: textFromHtml(raw.question_text), choices, correct_choices: correct,
        answer_status: correct.length ? "explicit_choices" : raw.answer_image_url ? "answer_image" : "missing_or_special_format",
        explanation_html: raw.solution_text || "", explanation_text: textFromHtml(raw.solution_text), answer_image_url: raw.answer_image_url,
        type_data: raw.type_data || {}, context_refs: contextRefs(raw), image_refs: references(raw, page.url), sources: [{page: capture.number, url: page.url, parser: page.parser, file: `paginas_originales/pagina_${String(capture.number).padStart(3, "0")}.html`}], raw};
      if (questions.has(q.number)) { duplicateObservations++; conflicts.push({question: q.number, issue: "Pregunta repetida entre páginas"}); }
      else questions.set(q.number, q);
    }
  }
  const items = [...questions.values()].sort((a, b) => a.number - b.number), present = pages.map(p => p.page);
  const report = {expected_questions: EXPECTED, questions_extracted: items.length, expected_pages: PAGES, pages_present: present,
    missing_pages: Array.from({length: PAGES}, (_, i) => i + 1).filter(n => !present.includes(n)),
    missing_question_numbers: Array.from({length: EXPECTED}, (_, i) => i + 1).filter(n => !questions.has(n)),
    duplicate_observations: duplicateObservations, conflicts, errors,
    missing_or_special_answers: items.filter(q => q.answer_status === "missing_or_special_format").map(q => q.number),
    missing_explanations: items.filter(q => !q.explanation_text && !q.raw.solution_text).map(q => q.number),
    unresolved_contexts: items.flatMap(q => q.context_refs.filter(k => !contexts[k]).map(k => ({question: q.number, context: k}))),
    dom_questions_requiring_context_review: items.filter(q => q.sources[0].parser === "dom").map(q => q.number),
    images_found: Object.keys(assets).length, images_failed: Object.values(assets).filter(a => a.download_status !== "downloaded").map(a => a.id),
    images_requiring_review: Object.keys(assets), image_transcription_review_complete: Object.keys(assets).length === 0,
    notes: ["Las claves son las indicadas por la fuente; no se ha validado su corrección técnica.", "Las imágenes originales se conservan si se pudieron descargar. Su transcripción y la interpretación de diagramas requieren revisión.", "Un CAPTCHA o bloqueo pausa el recorrido y exige intervención del usuario."]};
  report.collection_complete = items.length === EXPECTED && ["missing_pages", "missing_question_numbers", "conflicts", "errors", "missing_or_special_answers", "missing_explanations", "unresolved_contexts", "dom_questions_requiring_context_review", "images_failed"].every(k => report[k].length === 0);
  report.coverage_complete = pages.length === PAGES && items.length === EXPECTED && !report.missing_pages.length && !report.missing_question_numbers.length && !duplicateObservations;
  return {schema_version: "1.2", collector_version: "5.0.0", exam, generated_at: new Date().toISOString(), report, questions: items, contexts, assets, pages};
}

export function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
function contextText(raw) { return Object.entries(raw).map(([key, value]) => `${key}:\n${typeof value === "string" ? textFromHtml(value) : JSON.stringify(value, null, 2)}`).join("\n\n"); }
export function readableOutputs(data) {
  const r = data.report, EXPECTED = r.expected_questions, title = data.exam?.name || DEFAULT_EXAM.name, md = [`# ${title}`, "", `${r.questions_extracted}/${EXPECTED} preguntas. Cobertura ${r.coverage_complete ? "completa" : "parcial"}.`, "", "Respuestas originales de la fuente; imágenes y transcripciones requieren revisión.", ""];
  const body = [`<h1>${escapeHtml(title)}</h1><p>${r.questions_extracted}/${EXPECTED} preguntas · Cobertura ${r.coverage_complete ? "completa" : "parcial"}</p>`];
  function pictures(refs) {
    const unique = [...new Set(refs.map(ref => ref.asset_id))];
    return unique.map(id => {
      const a = data.assets[id];
      if (!a.local_path) { md.push(`Imagen pendiente: ${a.source_url}`, ""); return `<p>Imagen pendiente: ${escapeHtml(a.source_url)}</p>`; }
      md.push(`![Imagen original](${a.local_path})`, "", "Transcripción e interpretación pendientes de revisión.", "");
      return `<figure><img loading="lazy" src="${escapeHtml(a.local_path)}" alt="Imagen original"><figcaption>Imagen original · transcripción y revisión pendientes</figcaption></figure>`;
    }).join("");
  }
  for (const [key, context] of Object.entries(data.contexts)) {
    const text = contextText(context.raw);
    md.push(`## Contexto ${key}`, "", text, "");
    body.push(`<section id="${escapeHtml(key)}"><h2>Contexto ${escapeHtml(key)}</h2><div class="rich">${escapeHtml(text)}</div>${pictures(context.image_refs)}</section>`);
  }
  for (const q of data.questions) {
    const used = new Set(), group = pattern => q.image_refs.filter((ref, index) => { if (!pattern.test(ref.field || "")) return false; used.add(index); return true; });
    md.push(`## Pregunta ${q.number}`, "", q.context_refs.length ? `Contextos: ${q.context_refs.join(", ")}` : "", q.question_text, "");
    body.push(`<article><h2>Pregunta ${q.number}</h2>${q.context_refs.map(k => `<p><a href="#${escapeHtml(k)}">Contexto: ${escapeHtml(k)}</a></p>`).join("")}<div class="rich">${escapeHtml(q.question_text)}</div>`);
    body.push(pictures(group(/^question/)));
    for (const [index, c] of q.choices.entries()) { md.push(`**${c.letter}.** ${c.text}`, ""); body.push(`<div class="rich">${escapeHtml(`${c.letter}. ${c.text}`)}</div>`, pictures(group(new RegExp(`^choices\\[${index}\\]`)))); }
    const answer = q.correct_choices.join(", ") || q.answer_status;
    md.push(`**Respuesta indicada por la fuente:** ${answer}`, "", "**Explicación:**", "", q.explanation_text || "No incluida en la fuente.", "");
    body.push(`<h3>Respuesta de la fuente: ${escapeHtml(answer)}</h3><h3>Explicación</h3><div class="rich">${escapeHtml(q.explanation_text || "No incluida en la fuente.")}</div>`);
    if (q.raw.visible_context_html) { const text = textFromHtml(q.raw.visible_context_html); md.push("**Contexto visible:**", "", text, ""); body.push(`<h3>Contexto visible</h3><div class="rich">${escapeHtml(text)}</div>`); }
    body.push(pictures(q.image_refs.filter((ref, index) => !used.has(index))), "</article>");
  }
  const html = `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"><title>Archivo de estudio</title><style>body{max-width:960px;margin:36px auto;padding:0 20px;background:#f3f6fa;color:#163047;font:17px/1.6 system-ui}article,section{background:white;border:1px solid #d5dee6;border-radius:12px;padding:26px;margin:24px 0}.rich{white-space:pre-wrap;margin:12px 0;overflow-wrap:anywhere}img{max-width:100%}figcaption{font-size:13px}a{color:#175cb3}@media print{body{margin:0;background:white;font-size:11pt}article,section{border:0;border-top:1px solid #bbb;padding:12px 0}h2,h3{break-after:avoid}figure{break-inside:avoid}}</style><body>${body.join("")}</body></html>`;
  return {markdown: md.join("\n"), html};
}

const CRC_TABLE = Array.from({length: 256}, (_, n) => { for (let j = 0; j < 8; j++) n = (n & 1) ? 0xedb88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
export function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 255] ^ (crc >>> 8); return (crc ^ 0xffffffff) >>> 0; }
export function zipBytes(entries) {
  const encoder = new TextEncoder(), local = [], central = []; let offset = 0, centralSize = 0;
  for (const entry of entries) {
    const name = encoder.encode(entry.name), bytes = typeof entry.data === "string" ? encoder.encode(entry.data) : entry.data;
    if (bytes.length > 0xffffffff || offset + bytes.length > 0xffffffff) throw Error("El archivo supera el límite del ZIP.");
    const crc = crc32(bytes), header = new Uint8Array(30 + name.length), h = new DataView(header.buffer);
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x800, true); h.setUint16(12, 33, true);
    h.setUint32(14, crc, true); h.setUint32(18, bytes.length, true); h.setUint32(22, bytes.length, true); h.setUint16(26, name.length, true); header.set(name, 30);
    const record = new Uint8Array(46 + name.length), c = new DataView(record.buffer);
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x800, true); c.setUint16(14, 33, true);
    c.setUint32(16, crc, true); c.setUint32(20, bytes.length, true); c.setUint32(24, bytes.length, true); c.setUint16(28, name.length, true); c.setUint32(42, offset, true); record.set(name, 46);
    local.push(header, bytes); central.push(record); offset += header.length + bytes.length; centralSize += record.length;
  }
  if (entries.length > 65535) throw Error("Demasiados archivos para este ZIP.");
  const end = new Uint8Array(22), e = new DataView(end.buffer);
  e.setUint32(0, 0x06054b50, true); e.setUint16(8, entries.length, true); e.setUint16(10, entries.length, true); e.setUint32(12, centralSize, true); e.setUint32(16, offset, true);
  return new Blob([...local, ...central, end], {type: "application/zip"});
}

export function decodeImageData(url) {
  const match = url.match(/^data:(image\/[\w.+-]+)(;base64)?,([\s\S]*)$/i);
  if (!match) throw Error("Imagen embebida inválida");
  const bytes = match[2] ? Uint8Array.from(atob(match[3]), c => c.charCodeAt(0)) : new TextEncoder().encode(decodeURIComponent(match[3]));
  return {bytes, mime: match[1]};
}
