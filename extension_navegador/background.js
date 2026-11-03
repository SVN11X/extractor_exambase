import {CollectorEngine, ALARM} from "./engine.mjs";
import {DEFAULT_EXAM, outputName} from "./exam.mjs";
import {loadVendorCatalog} from "./catalog-browser.mjs";
import {exportState} from "./export.mjs";

async function closeExport() {
  const found = await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"], documentUrls: [chrome.runtime.getURL("offscreen.html")]});
  if (found.length) await chrome.offscreen.closeDocument();
}
async function exportZip() {
  const found = await chrome.runtime.getContexts({contextTypes: ["OFFSCREEN_DOCUMENT"], documentUrls: [chrome.runtime.getURL("offscreen.html")]});
  if (!found.length) await chrome.offscreen.createDocument({url: "offscreen.html", reasons: ["BLOBS"], justification: "Preparar el ZIP de preguntas e imágenes y descargarlo sin requerir que el panel esté abierto."});
  let reply;
  for (let attempt = 0; attempt < 5; attempt++) {
    try { reply = await chrome.runtime.sendMessage({target: "offscreen", action: "build"}); break; }
    catch (error) { if (!/Receiving end does not exist|Could not establish connection/i.test(error.message) || attempt === 4) throw error; await new Promise(r => setTimeout(r, 300)); }
  }
  if (!reply?.url) throw Error(reply?.error || "No se pudo preparar el ZIP.");
  const exam = (await chrome.storage.local.get("selectedExam")).selectedExam || DEFAULT_EXAM;
  return chrome.downloads.download({url: reply.url, filename: outputName(exam), saveAs: false, conflictAction: "uniquify"});
}
const engine = new CollectorEngine(chrome, {exportZip, closeExport});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== "worker" || sender.id !== chrome.runtime.id) return;
  (async () => {
    if (message.action === "export-data") return {saved: exportState(await chrome.storage.local.get(null))};
    if (message.action === "select") return {exam: await engine.selectExam(message.url)};
    if (message.action === "catalog") return loadVendorCatalog(chrome, message.vendor);
    if (message.action === "start") { const job = await engine.start(message.settings); engine.wake().catch(console.error); return {job}; }
    if (message.action === "pause") return {job: await engine.pause()};
    if (message.action === "images") { const job = await engine.repair(); engine.wake().catch(console.error); return {job}; }
    if (message.action === "export") {
      if ((await engine.job())?.running) throw Error("Pausa el recorrido antes de descargar un ZIP parcial.");
      const id = await exportZip(); await chrome.storage.local.set({manualDownloadId: id}); return {downloadId: id};
    }
    throw Error("Acción desconocida.");
  })().then(respond).catch(error => respond({error: error.message}));
  return true;
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) engine.wake().catch(console.error); });
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.status === "complete") engine.job().then(job => { if (job?.running && job.targetTab === id) return engine.wake(); }).catch(console.error);
});
chrome.downloads.onChanged.addListener(delta => {
  if (!delta.state) return;
  // La descarga local puede terminar antes de guardar downloadId. Esperar a
  // que termine el paso actual evita perder ese evento de finalización.
  engine.queue.then(() => engine.job()).then(async job => {
    if (job?.running && job.downloadId === delta.id) await engine.wake(true);
    else if (job?.downloadId === delta.id && ["complete", "interrupted"].includes(delta.state.current)) await closeExport();
    const manual = (await chrome.storage.local.get("manualDownloadId")).manualDownloadId;
    if (manual === delta.id && ["complete", "interrupted"].includes(delta.state.current)) await closeExport();
  }).catch(console.error);
});
chrome.runtime.onStartup.addListener(() => engine.wake().catch(console.error));
chrome.runtime.onInstalled.addListener(() => engine.wake().catch(console.error));
// Recrear la alarma y restaurar el checkpoint cuando Chrome reinicie el worker.
engine.job().then(async job => { if (job?.running) { await engine.schedule(job); await engine.wake(); } }).catch(console.error);

chrome.action.onClicked.addListener(async () => {
  const url = chrome.runtime.getURL("panel.html");
  const existing = (await chrome.tabs.query({})).find(tab => tab.url === url);
  if (existing) {
    await chrome.tabs.update(existing.id, {active: true});
    await chrome.windows.update(existing.windowId, {focused: true});
  } else {
    await chrome.tabs.create({url});
  }
});
