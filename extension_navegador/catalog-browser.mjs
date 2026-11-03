import {CATALOG} from "./catalog-data.mjs";
export function captureVendorCatalog(vendor, externalHosts) {
  const allowed = new Set(externalHosts), found = new Map();
  const links = document.querySelectorAll("main a[href]").length ? document.querySelectorAll("main a[href]") : document.querySelectorAll("a[href]");
  for (const a of links) {
    let url; try { url = new URL(a.href); } catch { continue; }
    const host = url.hostname.replace(/^www\./, ""), parts = url.pathname.split("/").filter(Boolean);
    // El grupo comercial y el slug de la ruta pueden diferir:
    // Google Cloud está agrupado en /google-cloud, pero sus exámenes usan /google.
    const internal = host === "exambase.com" && parts[0] === "exams" && parts.length === 3;
    const external = allowed.has(host) && !url.pathname.replace(/\//g, "");
    if (url.protocol !== "https:" || (!internal && !external)) continue;
    const label = a.innerText.replace(/\s+/g, " ").replace(/chevron_right/g, "").trim();
    if (!label) continue;
    const count = label.match(/([\d,]+)\s+questions/i);
    if (!count) continue;
    const code = a.querySelector('.ebo-idx__code')?.textContent.trim(), title = a.querySelector('.ebo-idx__name')?.textContent.trim(), normalize = text => String(text).toLowerCase().replace(/[^a-z0-9]/g, '');
    const name = title && normalize(title) !== normalize(vendor) ? title : code || label.slice(0, 220);
    found.set(url.href, {url: url.href, name, questions: count ? Number(count[1].replace(/,/g, "")) : null});
  }
  const heading = [...document.querySelectorAll("h1,h2,h3")].map(n => n.textContent.trim()).find(t => /checking.*human|verify.*human|verification failed|just a moment/i.test(t));
  return {exams: [...found.values()], heading: heading || "", url: location.href};
}
export async function loadVendorCatalog(api, vendor) {
  if (!CATALOG.vendors.some(v => v.slug === vendor)) throw Error("Proveedor no reconocido en el catálogo.");
  const job = (await api.storage.local.get("collectorJob")).collectorJob;
  if (job?.running) throw Error("Pausa el recorrido antes de abrir el catálogo de otro proveedor.");
  const tab = await api.tabs.create({url: "https://www.exambase.com/exams/" + vendor, active: true});
  const hosts = CATALOG.featured.filter(f => f.href).map(f => new URL(f.href).hostname.replace(/^www\./, ""));
  for (let n = 0; n < 25; n++) {
    const current = await api.tabs.get(tab.id);
    if (current.status === "complete") {
      const results = await api.scripting.executeScript({target: {tabId: tab.id}, func: captureVendorCatalog, args: [vendor, hosts]});
      const captured = results[0]?.result;
      if (captured?.exams.length) {
        await api.storage.local.set({["catalog:" + vendor]: captured.exams}); return {tabId: tab.id, exams: captured.exams};
      }
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  throw Error("La lista aún no cargó. Revisa la pestaña del proveedor y vuelve a pulsar Ver exámenes; también puedes pegar la URL de un examen.");
}
