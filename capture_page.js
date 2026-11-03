(async (options) => {
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const text = element => (element?.textContent || '').replace(/\s+/g, ' ').trim();
  const cards = () => [...new Set([...document.querySelectorAll('h3,h4,h5')]
    .filter(h => /^Question\s+\d+$/i.test(text(h))).map(h => h.closest('.card')).filter(Boolean))];
  const number = card => Number([...card.querySelectorAll('h3,h4,h5')].map(text).find(t=>/^Question\s+\d+$/i.test(t))?.match(/Question\s+(\d+)/i)?.[1]);
  const answer = card => !!card && ([...card.querySelectorAll('.list-group-item small,.list-group-item span')]
    .some(n => !n.closest?.('.exambase-question__rich-text') && /^correct(?: answer)?$/i.test(text(n))) ||
    !!card.querySelector('.list-group-item[data-correct="true"],.list-group-item[data-is-correct="true"],img[data-answer],.answer-image img'));
  const active = card => [...card.querySelectorAll('button')].find(b => /^Reveal Answer$/i.test(text(b)) && b.getClientRects().length && !b.disabled);
  const started = Date.now();
  let expected = options.expectedCount;
  // Espera hidratación y tarjetas completas; no actúa sobre controles de verificación.
  while (Date.now() - started < options.waitMs) {
    const current = cards();
    if (!expected) {
      const range = text(document.body).match(/Showing\s+(?:(\d+)\s*[-–]\s*)?(\d+)\s+of\s+(\d+)/i);
      if (range && options.page === 1) expected = range[1] ? Number(range[2])-Number(range[1])+1 : Number(range[2]);
    }
    if (current.length && (!expected || current.length === expected) && current.every(c => c.querySelector('.exambase-question__rich-text'))) break;
    const title = text(document.querySelector('h1,h2,h3,title'));
    if (/verification (failed|didn.t go through)|access denied|sorry, you have been blocked/i.test(title)) break;
    await pause(250);
  }
  const deadline = Date.now() + options.revealMs;
  const attempts = [];
  // Busca de nuevo la tarjeta tras cada clic: una SPA puede reemplazar todo el DOM.
  for (const id of cards().map(number)) {
    if (Date.now() > deadline) break;
    let card = cards().find(c => number(c) === id);
    const button = card && active(card);
    if (!button) continue;
    button.click();
    const until = Math.min(deadline, Date.now()+5000);
    let found = false;
    while (Date.now() < until) {
      card = cards().find(c => number(c) === id);
      if (answer(card)) {found = true; break;}
      // El botón desaparecido no demuestra que se haya recibido una respuesta.
      await pause(100);
    }
    attempts.push({question:id, answerVisible:found});
    await pause(200);
  }
  await pause(400);
  const images = [], imageDeadline = Date.now() + options.imageMs;
  let bytes = 0;
  const imageNodes = [...(document.images || [])];
  const urls = [...new Set(imageNodes.flatMap(i => [i.src,i.currentSrc].filter(Boolean)))];
  if (options.images) for (const url of urls.slice(0,128)) {
    if (Date.now() > imageDeadline) break;
    if (new URL(url,location.href).origin !== location.origin) continue;
    try {
      const response = await fetch(url,{credentials:'same-origin',signal:AbortSignal.timeout(Math.max(1,Math.min(3000,imageDeadline-Date.now())))});
      if (!response.ok) {images.push({url,status:response.status});continue;}
      const blob = await response.blob();
      if (blob.size>20*1024*1024 || bytes+blob.size>20*1024*1024) continue;
      bytes+=blob.size;
      const data = await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(blob);});
      images.push({url,data});
    } catch {images.push({url,status:0});}
  }
  return JSON.stringify({url:location.href,html:document.documentElement.outerHTML,images,
    capture:{version:2,expectedCount:expected || null,questions:cards().map(number),attempts,
      unanswered:cards().filter(c=>!answer(c)).map(number)}});
})(__EXAMBASE_CAPTURE_OPTIONS__)
