import {CATALOG} from "./catalog-data.mjs";
export const DEFAULT_EXAM = Object.freeze({key: "google/professional-data-engineer", vendor: "google", slug: "professional-data-engineer", name: "Professional Data Engineer", origin: "https://www.exambase.com", base: "https://www.exambase.com/exams/google/professional-data-engineer/practice-questions/", total: 349, pages: 70, perPage: 5});
const external = new Set(CATALOG.featured.filter(f => f.href).map(f => new URL(f.href).hostname.replace(/^www\./, "")));
export function parseExamUrl(value) {
  const url = new URL(String(value).trim());
  if (url.protocol !== "https:" || url.username || url.password || url.port) throw Error("Usa una URL HTTPS del examen, sin credenciales ni puertos.");
  const host = url.hostname.replace(/^www\./, ""); let vendor, slug, root;
  if (host === "exambase.com") {
    const m = url.pathname.match(/^\/exams\/([\w.-]+)\/([\w.-]+)(?:\/practice-questions\/\d+)?\/?$/);
    if (!m) throw Error("Pega el enlace de un examen concreto o de una página de sus preguntas.");
    [, vendor, slug] = m; root = `/exams/${vendor}/${slug}`;
  } else if (external.has(host)) {
    if (!/^\/(?:practice-questions\/\d+\/?)?$/.test(url.pathname)) throw Error("Para este sitio, pega la URL de su página de preguntas.");
    vendor = host; slug = host.split(".")[0]; root = "";
  } else throw Error("El sitio no figura en ExamBase ni en los sitios oficiales del catálogo adjunto.");
  const origin = host === "exambase.com" ? "https://www.exambase.com" : url.origin;
  const key = host === "exambase.com" ? `${vendor}/${slug}` : host;
  return {key, vendor, slug, name: slug.replace(/-/g, " "), origin, base: origin + root + "/practice-questions/", total: null, pages: null, perPage: null};
}
export function pageForExam(url, exam = DEFAULT_EXAM) {
  try {
    const parsed = new URL(url), wanted = new URL(exam.base);
    if (parsed.protocol !== "https:" || parsed.hostname.replace(/^www\./, "") !== wanted.hostname.replace(/^www\./, "") || parsed.port || parsed.username || parsed.password) return null;
    if (!parsed.pathname.startsWith(wanted.pathname)) return null;
    const rest = parsed.pathname.slice(wanted.pathname.length), m = rest.match(/^(\d+)\/?$/), n = m ? Number(m[1]) : 0;
    return n >= 1 && n <= (exam.pages || 100000) ? n : null;
  } catch { return null; }
}
export function bankPrefix(exam = DEFAULT_EXAM) { return exam.key === DEFAULT_EXAM.key ? "" : `exam:${exam.key}:`; }
export function pageKey(exam, number) { return bankPrefix(exam) + `page:${number}`; }
export function imageKey(exam, id) { return bankPrefix(exam) + `image:${id}`; }
export function metadataKey(exam) { return `exam:${exam.key}:meta`; }
export function outputName(exam = DEFAULT_EXAM) { return exam.key === DEFAULT_EXAM.key ? "resultado_exambase.zip" : `resultado_${exam.key.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 100)}.zip`; }
export function normalizeCounts(exam, result) {
  const total = Number(result.total), pages = Number(result.total_pages), perPage = Number(result.per_page) || (result.page === 1 && result.items?.length ? result.items.length : 0);
  if (![total, pages, perPage].every(n => Number.isSafeInteger(n) && n > 0) || total > 100000 || pages > 20000 || Math.ceil(total / perPage) !== pages) throw Error("No se pudieron detectar de forma coherente el total de preguntas y la paginación del examen.");
  return {...exam, total, pages, perPage};
}
