import {DEFAULT_EXAM, parseExamUrl, bankPrefix, pageKey, imageKey, metadataKey} from "./exam.mjs";
import {BASE, PAGES, pageNumber, selectPage, discoverExam, imageReferences, imageUrl, decodeImageData, buildArchive} from "./core.mjs";
import {captureExamPage, fetchImageInPage} from "./capture.mjs";

export const ALARM = "exambase-worker";
export function isTabBusy(error) { return /Tabs cannot be edited right now|user may be dragging a tab/i.test(error?.message || String(error)); }
export function captureReady(snapshot, number, exam = DEFAULT_EXAM) {
  if (!exam.total || !exam.perPage) return Boolean(snapshot.dom?.items?.length) && snapshot.dom.page === number;
  const first = (number - 1) * exam.perPage + 1, count = Math.min(exam.perPage, exam.total + 1 - first), numbers = snapshot.dom?.items?.map(q => q.order) || [];
  return numbers.length === count && Array.from({length: count}, (_, i) => first + i).every(n => numbers.includes(n));
}
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const suffix = mime => ({"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg", "image/avif": ".avif", "image/tiff": ".tiff", "image/bmp": ".bmp"})[mime] || ".img";
const bytes64 = bytes => { let text = ""; for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(text); };
export function storedData(saved, exam = saved.collectorJob?.exam || saved.selectedExam || DEFAULT_EXAM) {
  const prefix = bankPrefix(exam);
  return {captures: Object.entries(saved).filter(([k]) => k.startsWith(prefix + "page:")).map(([, v]) => v), images: Object.entries(saved).filter(([k]) => k.startsWith(prefix + "image:")).map(([, v]) => v)};
}

// Cada paso se confirma en storage. Las alarmas restauran el trabajo después
// de que Chrome termine el service worker; el panel no ejecuta el recorrido.
export class CollectorEngine {
  constructor(api, {now = () => Date.now(), sleep = ms => new Promise(r => setTimeout(r, ms)), exportZip = async () => { throw Error("Exportación no disponible"); }, closeExport = async () => {}, setTimer = setTimeout, clearTimer = clearTimeout} = {}) {
    this.api = api; this.now = now; this.sleep = sleep; this.exportZip = exportZip; this.closeExport = closeExport;
    this.queue = Promise.resolve(); this.timer = null; this.setTimer = setTimer; this.clearTimer = clearTimer;
  }
  serial(fn) { const work = this.queue.then(fn); this.queue = work.catch(() => {}); return work; }
  async job() { return (await this.api.storage.local.get("collectorJob")).collectorJob; }
  async save(job) { await this.api.storage.local.set({collectorJob: {...job, updatedAt: this.now()}}); }
  async resolveExam(value) {
    const parsed = parseExamUrl(value), key = metadataKey(parsed), stored = (await this.api.storage.local.get(key))[key];
    const fallback = parsed.key === DEFAULT_EXAM.key ? DEFAULT_EXAM : parsed;
    return {...fallback, ...(stored?.key === parsed.key ? stored : {}), origin: parsed.origin, base: parsed.base};
  }
  selectExam(value) { return this.serial(async () => {
    const current = await this.job(); if (current?.running) throw Error("Pausa el recorrido antes de elegir otro examen.");
    const exam = await this.resolveExam(value);
    await this.api.storage.local.set({selectedExam: exam, collectorJob: null}); return exam;
  }); }
  async log(message) {
    const old = (await this.api.storage.local.get("runLog")).runLog || [];
    await this.api.storage.local.set({runLog: [...old, `${new Date(this.now()).toLocaleString("es-CL")}  ${message}`].slice(-500)});
  }
  async status(job, message) { job.message = message; await this.save(job); await this.log(message); }
  async tabUpdate(id, change) {
    for (let n = 0; n < 6; n++) {
      try { return await this.api.tabs.update(id, change); }
      catch (error) { if (!isTabBusy(error) || n === 5) throw error; await this.sleep(Math.min(2000, 250 * 2 ** n)); }
    }
  }
  async resources(job) {
    if (job.running && job.settings.keepAwake) this.api.power.requestKeepAwake("display");
    else this.api.power.releaseKeepAwake();
  }
  async release(job) {
    this.api.power.releaseKeepAwake();
    if (job.protectedTab != null) {
      try { await this.tabUpdate(job.protectedTab, {autoDiscardable: job.wasAutoDiscardable !== false}); } catch { /* La pestaña puede haberse cerrado. */ }
      job.protectedTab = null; await this.save(job);
    }
    this.clearTimer(this.timer); this.timer = null;
    await this.api.alarms.clear(ALARM);
  }
  async schedule(job) {
    this.clearTimer(this.timer); this.timer = null;
    if (!job?.running) return;
    // La alarma durable es el respaldo de los temporizadores cortos.
    await this.api.alarms.create(ALARM, {when: Math.max(this.now() + 30000, job.due || this.now()), periodInMinutes: 0.5});
    const wait = Math.max(0, (job.due || this.now()) - this.now());
    if (wait < 25000) { this.timer = this.setTimer(() => this.wake().catch(() => {}), Math.max(50, wait)); this.timer?.unref?.(); }
  }
  async pickTarget(job) {
    let tab;
    if (job.targetTab != null) {
      try { const got = await this.api.tabs.get(job.targetTab); if (pageNumber(got.url, job.exam)) tab = got; }
      catch (error) { if (!/No tab|not found|Invalid tab/i.test(error.message)) throw error; }
    }
    if (!tab) tab = (await this.api.tabs.query({url: [job.exam.origin + "/*"]})).find(t => pageNumber(t.url, job.exam));
    if (!tab) tab = await this.api.tabs.create({url: job.exam.base + (job.page || 1), active: job.settings.foreground});
    job.targetTab = tab.id;
    if (job.protectedTab !== tab.id) {
      job.protectedTab = tab.id; job.wasAutoDiscardable = tab.autoDiscardable !== false;
      await this.save(job); await this.tabUpdate(tab.id, {autoDiscardable: false});
    }
    return tab;
  }
  start(settings = {}) { return this.serial(async () => {
    const prior = await this.job();
    if (prior?.running) return prior;
    const old = (await this.api.storage.local.get("settings")).settings || {};
    const config = {delay: Math.max(5, Math.min(120, Number(settings.delay ?? old.delay) || 10)), foreground: settings.foreground ?? old.foreground ?? true, keepAwake: settings.keepAwake ?? old.keepAwake ?? true, automatic: settings.automatic ?? old.automatic ?? true};
    const savedExam = (await this.api.storage.local.get("selectedExam")).selectedExam || DEFAULT_EXAM;
    const exam = await this.resolveExam(settings.examUrl || savedExam.base + "1");
    const job = {running: true, exam, phase: exam.pages ? "choose" : "navigate", mode: "collect", page: exam.pages ? null : 1, targetTab: prior?.targetTab ?? old.targetTab ?? null, due: this.now(), settings: config, transientRetries: 0, message: "Recorrido automático iniciado en segundo plano."};
    await this.api.storage.local.set({settings: {...old, ...config}, selectedExam: exam, runLease: null});
    await this.save(job); await this.log(job.message); await this.resources(job); await this.schedule(job); return job;
  }); }
  pause() { return this.serial(async () => {
    const job = await this.job(); if (!job) return null;
    job.running = false; job.phase = "paused";
    await this.status(job, "Recorrido pausado. Se conserva el avance."); await this.release(job); return job;
  }); }
  repair() { return this.serial(async () => {
    if ((await this.job())?.running) throw Error("Pausa el recorrido antes de recuperar imágenes.");
    const saved = await this.api.storage.local.get(null), exam = saved.selectedExam || DEFAULT_EXAM, all = storedData(saved, exam), data = buildArchive(all.captures, all.images, exam);
    const prior = saved.collectorJob || {}, settings = {...saved.settings, keepAwake: true};
    const job = {running: true, exam, mode: "images", phase: "assets", assetCursor: 0, pendingAssets: Object.values(data.assets).filter(a => a.download_status !== "downloaded").map(a => ({source: a.source_url, alt: a.alt})), targetTab: prior.targetTab, settings, due: this.now(), message: "Recuperando imágenes pendientes."};
    await this.save(job); await this.resources(job); await this.schedule(job); return job;
  }); }
  async inject(tabId, func, args) {
    const entries = await this.api.scripting.executeScript({target: {tabId}, func, args});
    if (!entries[0]?.result) throw Error("La pestaña no entregó una captura."); return entries[0].result;
  }
  async asset(address, alt, tabId, exam = DEFAULT_EXAM) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(address));
    const id = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 20);
    let reply;
    if (address.startsWith("data:image/")) reply = {data_url: address};
    else if (await this.api.permissions.contains({origins: [new URL(address).origin + "/*"]})) {
      try {
        const response = await fetch(address, {credentials: "include", cache: "force-cache", signal: AbortSignal.timeout(20000)});
        const mime = (response.headers.get("content-type") || "").split(";")[0];
        if (!response.ok) reply = {error: `HTTP ${response.status}`, status: response.status};
        else if (!mime.startsWith("image/") || Number(response.headers.get("content-length")) > MAX_IMAGE_BYTES) reply = {error: "Recurso de imagen inválido o demasiado grande"};
        else { const bytes = new Uint8Array(await response.arrayBuffer()); reply = bytes.length <= MAX_IMAGE_BYTES ? {data_url: `data:${mime};base64,${bytes64(bytes)}`} : {error: "Imagen demasiado grande"}; }
      } catch (error) { reply = {error: error.message}; }
    } else {
      try { reply = await this.inject(tabId, fetchImageInPage, [address, MAX_IMAGE_BYTES]); }
      catch (error) { reply = {error: error.message}; }
    }
    const record = {id, source_url: address, alt: alt || "", download_status: "failed", ocr_status: "not_run", review_required: true};
    if (reply.data_url) {
      const {bytes, mime} = decodeImageData(reply.data_url);
      if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) throw Error("Tamaño de imagen no admitido");
      Object.assign(record, {download_status: "downloaded", data_url: reply.data_url, bytes: bytes.length, content_type: mime, local_path: `imagenes/${id}${suffix(mime)}`});
    } else Object.assign(record, {error: reply.error || "Descarga pendiente", http_status: reply.status || null});
    await this.api.storage.local.set({[imageKey(exam, id)]: record});
    if (reply.status === 429) throw Error("HTTP 429: el sitio ha limitado la descarga de imágenes. Se ha pausado para respetar ese límite.");
  }
  async step(job) {
    if (job.phase === "choose") {
      const {captures} = storedData(await this.api.storage.local.get(null), job.exam), present = new Set(captures.map(c => c.number));
      const missing = Array.from({length: job.exam.pages}, (_, i) => i + 1).filter(n => !present.has(n));
      if (!missing.length) { job.phase = job.settings.automatic ? "export" : "finished"; job.due = this.now(); await this.save(job); return; }
      job.page = missing[0]; const tab = await this.pickTarget(job);
      if (present.size === 0 && missing.includes(pageNumber(tab.url, job.exam))) job.page = pageNumber(tab.url, job.exam);
      job.phase = "navigate"; job.due = this.now(); await this.save(job); return;
    }
    if (job.phase === "navigate") {
      const tab = await this.pickTarget(job), changes = {autoDiscardable: false};
      if (pageNumber(tab.url, job.exam) !== job.page) changes.url = job.exam.base + job.page;
      if (job.settings.foreground) changes.active = true;
      await this.tabUpdate(tab.id, changes);
      if (job.settings.foreground) await this.api.windows.update(tab.windowId, {focused: true});
      job.phase = "waiting"; job.waitStarted = this.now(); job.waitNotified = false; job.due = this.now();
      await this.status(job, `Abriendo página ${job.page} de ${job.exam.pages || "total por detectar"}…`); return;
    }
    if (job.phase === "waiting") {
      // Recupera un commit que pudo ocurrir justo antes de terminar el worker.
      if ((await this.api.storage.local.get(pageKey(job.exam, job.page)))[pageKey(job.exam, job.page)]) { job.phase = "assets"; job.assetCursor = 0; job.due = this.now(); await this.save(job); return; }
      let tab;
      try { tab = await this.api.tabs.get(job.targetTab); }
      catch (error) { if (!/No tab|not found|Invalid tab/i.test(error.message)) throw error; job.phase = "navigate"; job.targetTab = null; job.due = this.now(); await this.save(job); return; }
      if (pageNumber(tab.url, job.exam) !== job.page && tab.status === "complete") throw Error("La pestaña fue movida a otra página. Revisa ExamBase y reanuda.");
      if (tab.status === "complete") {
        let snapshot = await this.inject(tab.id, captureExamPage, [job.page, false]);
        if (snapshot.verification?.failed || snapshot.verification?.code) throw Error(`Fallo explícito de verificación en página ${job.page}${snapshot.verification.code ? " (" + snapshot.verification.code + ")" : ""}. Requiere revisión personal.`);
        if (captureReady(snapshot, job.page, job.exam)) {
          if (!job.exam.total || !job.exam.pages) {
            job.exam = discoverExam(snapshot, job.exam);
            await this.api.storage.local.set({selectedExam: job.exam, [metadataKey(job.exam)]: job.exam}); await this.save(job);
          }
          snapshot = await this.inject(tab.id, captureExamPage, [job.page, true]);
          if (!snapshot.verification && captureReady(snapshot, job.page, job.exam)) {
            const extracted = selectPage(snapshot, job.page, job.exam);
            await this.api.storage.local.set({[pageKey(job.exam, job.page)]: {number: job.page, captured_at: snapshot.captured_at, html: snapshot.html, currentImages: snapshot.currentImages, extracted}, lastAttempt: {page: job.page, phase: "questions_ready", parser: extracted.parser, at: new Date(this.now()).toISOString(), collector_version: "4.0.0"}});
            if (job.waitNotified) await this.log(`Página ${job.page}: preguntas disponibles; se continúa automáticamente.`);
            job.phase = "assets"; job.assetCursor = 0; job.due = this.now(); await this.status(job, `Página ${job.page} guardada. Recuperando imágenes…`); return;
          }
        }
        if (snapshot.verification && !job.waitNotified) {
          job.waitNotified = true; await this.status(job, `Esperando las preguntas de la página ${job.page}. Si la web pide interacción, complétala allí; continuaremos cuando aparezcan las preguntas.`);
        }
      }
      if (this.now() - job.waitStarted >= 180000) throw Error(`La página ${job.page} no entregó preguntas en tres minutos. Se conserva el avance y se requiere revisar la página.`);
      job.due = this.now() + 2000; await this.save(job); return;
    }
    if (job.phase === "assets") {
      const saved = await this.api.storage.local.get(null), all = storedData(saved, job.exam), capture = saved[pageKey(job.exam, job.page)];
      const refs = job.mode === "images" ? job.pendingAssets : [...imageReferences(capture.extracted.payload), ...(capture.currentImages || [])];
      let cursor = job.assetCursor || 0;
      while (cursor < refs.length) {
        const ref = refs[cursor++]; let address;
        try { address = imageUrl(ref.source, capture?.extracted.url || job.exam.base + "1"); } catch { continue; }
        if (all.images.some(a => a.source_url === address && (job.mode !== "images" || a.download_status === "downloaded"))) continue;
        await this.asset(address, ref.alt, job.targetTab, job.exam); job.assetCursor = cursor; job.due = this.now(); await this.save(job); return;
      }
      if (job.mode === "images") { job.phase = job.settings.automatic ? "export" : "finished"; job.due = this.now(); await this.save(job); return; }
      if (all.captures.length >= job.exam.pages) { job.phase = "choose"; job.due = this.now(); await this.save(job); return; }
      job.phase = "delay"; job.due = this.now() + job.settings.delay * 1000;
      await this.status(job, `Página ${job.page} guardada. Próxima página dentro de ${job.settings.delay} segundos.`); return;
    }
    if (job.phase === "delay") { job.phase = "choose"; job.due = this.now(); await this.save(job); return; }
    if (job.phase === "export") {
      job.downloadId = await this.exportZip(); job.phase = "download"; job.due = this.now() + 30000;
      await this.status(job, "ZIP preparado; comprobando que la descarga termine."); return;
    }
    if (job.phase === "download") {
      const item = (await this.api.downloads.search({id: job.downloadId}))[0];
      if (item?.state === "complete") { await this.closeExport(); job.phase = "finished"; job.due = this.now(); await this.save(job); return; }
      if (!item || item.state === "interrupted") {
        if ((job.exportRetries || 0) >= 2) throw Error("La descarga del ZIP fue interrumpida. El contenido sigue guardado; puedes volver a descargarlo.");
        job.exportRetries = (job.exportRetries || 0) + 1; job.phase = "export"; job.due = this.now() + 30000;
      } else job.due = this.now() + 30000;
      await this.save(job); return;
    }
    if (job.phase === "finished") {
      const all = storedData(await this.api.storage.local.get(null), job.exam), data = buildArchive(all.captures, all.images, job.exam);
      job.running = false;
      await this.status(job, `${data.report.questions_extracted}/${job.exam.total} preguntas guardadas. ${data.report.collection_complete ? "Conservación completa." : "Consulta el informe: hay contenido o revisiones pendientes."}${job.downloadId ? " Descarga del ZIP completada." : " Puedes descargar el ZIP."}`);
      await this.release(job);
    }
  }
  wake(force = false) { return this.serial(async () => {
    let job = await this.job(); if (!job?.running) return;
    job.exam ||= DEFAULT_EXAM;
    if (force && job.phase === "download") job.due = this.now();
    await this.resources(job);
    try {
      const started = this.now();
      if ((job.due || 0) && started - job.due > 60000) await this.log("Se recuperó una espera prolongada del navegador. Se continúa desde el último paso guardado.");
      for (let n = 0; n < 10 && job.running && (job.due || 0) <= this.now(); n++) {
        await this.step(job); job.transientRetries = 0;
        if (this.now() - started > 22000) break;
      }
    } catch (error) {
      if (/No tab with id|Invalid tab ID/i.test(error.message)) {
        job.targetTab = null; job.protectedTab = null; job.phase = "navigate"; job.due = this.now() + 2000;
        await this.status(job, "La pestaña se cerró durante una operación. Se abrirá otra para continuar desde el avance guardado.");
      } else if (/frame.*(?:removed|detached)|execution context.*destroyed/i.test(error.message) && job.phase === "waiting" && this.now() - job.waitStarted < 180000) {
        job.due = this.now() + 2000; await this.status(job, "La página está cambiando su contenido. Se esperará sin reiniciar el recorrido.");
      } else if (isTabBusy(error) && (job.transientRetries || 0) < 20) {
        job.transientRetries = (job.transientRetries || 0) + 1; job.due = this.now() + 30000;
        await this.status(job, `El navegador tiene las pestañas temporalmente ocupadas. Se reintentará automáticamente; avance conservado (${job.transientRetries}/20).`);
      } else {
        job.running = false; job.phase = "blocked"; job.error = error.message;
        await this.status(job, error.message); await this.release(job);
      }
    }
    await this.schedule(job);
  }); }
}
