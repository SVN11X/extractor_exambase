import {DEFAULT_EXAM, parseExamUrl} from "./exam.mjs";
import {CATALOG} from "./catalog-data.mjs";
import {buildArchive, pageNumber, BASE} from "./core.mjs";
import {storedData} from "./engine.mjs";
const $ = id => document.getElementById(id);
let current = {}, rendered = false, refreshTimer;
async function send(action, extra = {}) {
  const reply = await chrome.runtime.sendMessage({target: "worker", action, ...extra});
  if (reply?.error) throw Error(reply.error); return reply;
}
async function refresh() {
  current = await chrome.storage.local.get(null);
  const exam = current.selectedExam || DEFAULT_EXAM, all = storedData(current, exam), data = buildArchive(all.captures, all.images, exam), job = current.collectorJob;
  $("page-count").textContent = `${all.captures.length} / ${exam.pages || "por detectar"}`;
  $("question-count").textContent = `${data.questions.length} / ${exam.total || "por detectar"}`;
  $("image-count").textContent = String(data.report.images_failed.length);
  $("progress").max = exam.pages || Math.max(1, all.captures.length); $("progress").value = all.captures.length;
  $("exam-summary").textContent = `${exam.name} · ${exam.total || "total por detectar"} preguntas · ${exam.pages || "páginas por detectar"}. Cada examen conserva su propio avance.`;
  for (const id of ["select-exam", "use-current", "load-catalog", "vendor", "exam-list", "exam-url"]) $(id).disabled = Boolean(job?.running);
  $("start").disabled = Boolean(job?.running); $("pause").disabled = !job?.running;
  $("download").disabled = Boolean(job?.running) || !all.captures.length;
  $("download").textContent = data.report.collection_complete ? "Descargar ZIP" : "Descargar ZIP e informe";
  $("images").hidden = !data.report.images_failed.length; $("images").disabled = Boolean(job?.running);
  $("focus").hidden = job?.targetTab == null;
  $("log").textContent = (current.runLog || []).join("\n");
  $("message").textContent = job?.message || (all.captures.length ? "Avance recuperado. Pulsa Iniciar / reanudar para continuar." : "Preparado. Abre ExamBase para comenzar.");
  if (!rendered) {
    const settings = current.settings || {};
    $("exam-url").value = exam.base + "1";
    $("delay").value = settings.delay ?? 10;
    $("foreground").checked = settings.foreground ?? true;
    $("awake").checked = settings.keepAwake ?? true;
    $("automatic").checked = settings.automatic ?? true;
    rendered = true;
  }
}
function action(id, fn) { $(id).addEventListener("click", async () => { try { await fn(); await refresh(); } catch (error) { $("message").textContent = error.message; } }); }
action("start", async () => { await permitExam(); return send("start", {settings: {examUrl: $("exam-url").value, delay: Number($("delay").value), foreground: $("foreground").checked, keepAwake: $("awake").checked, automatic: $("automatic").checked}}); });
action("pause", () => send("pause"));
action("download", async () => { await send("export"); });
action("open", async () => {
  const exam = parseExamUrl($("exam-url").value); await permitExam();
  const existing = (await chrome.tabs.query({url: [exam.origin + "/*"]})).find(tab => pageNumber(tab.url, exam));
  if (existing) { await chrome.tabs.update(existing.id, {active: true}); await chrome.windows.update(existing.windowId, {focused: true}); }
  else await chrome.tabs.create({url: exam.base + "1"});
});
action("focus", async () => {
  const tab = await chrome.tabs.update(current.collectorJob.targetTab, {active: true}); await chrome.windows.update(tab.windowId, {focused: true});
});
action("images", async () => {
  const exam = current.selectedExam || DEFAULT_EXAM, all = storedData(current, exam), data = buildArchive(all.captures, all.images, exam);
  const origins = [...new Set(Object.values(data.assets).filter(a => a.download_status !== "downloaded" && a.source_url.startsWith("https://")).map(a => new URL(a.source_url).origin + "/*"))];
  if (origins.length && !await chrome.permissions.request({origins})) throw Error("No se autorizaron los dominios de las imágenes pendientes.");
  await send("images");
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  clearTimeout(refreshTimer); refreshTimer = setTimeout(() => refresh().catch(error => { $("message").textContent = error.message; }), 150);
});
await refresh();

async function permitExam() {
  const exam = parseExamUrl($("exam-url").value), origin = new URL(exam.base).origin + "/*";
  if (!origin.includes("exambase.com/") && !await chrome.permissions.request({origins: [origin]})) throw Error("Hace falta permitir el sitio oficial de este examen para recopilarlo.");
  return exam;
}
function showExamList(exams) {
  $("exam-list").replaceChildren(new Option("Selecciona un examen", ""), ...exams.map(item => new Option(item.name, item.url)));
}
$("vendor").replaceChildren(new Option("Elige un proveedor", ""), ...CATALOG.vendors.map(v => new Option(`${v.vendor} (${v.examCount})`, v.slug)));
$("vendor").addEventListener("change", () => showExamList(current["catalog:" + $("vendor").value] || CATALOG.presets.filter(p => p.group === $("vendor").value)));
$("exam-list").addEventListener("change", () => { if ($("exam-list").value) $("exam-url").value = $("exam-list").value; });
action("select-exam", async () => { await permitExam(); await send("select", {url: $("exam-url").value}); rendered = false; });
action("load-catalog", async () => {
  $("message").textContent = "Abriendo el catálogo del proveedor en otra pestaña…";
  const response = await send("catalog", {vendor: $("vendor").value}); current["catalog:" + $("vendor").value] = response.exams; showExamList(response.exams);
});
action("use-current", async () => {
  const tabs = await chrome.tabs.query({});
  const choices = tabs.map(tab => { try { return {tab, exam: parseExamUrl(tab.url)}; } catch { return null; } }).filter(Boolean);
  const selected = choices.find(c => c.tab.active) || choices[0];
  if (!selected) throw Error("Abre primero el examen que quieres descargar.");
  $("exam-url").value = selected.exam.base + "1"; await send("select", {url: $("exam-url").value}); rendered = false;
});

showExamList(CATALOG.presets);
