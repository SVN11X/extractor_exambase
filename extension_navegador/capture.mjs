// Estas funciones se ejecutan únicamente en la pestaña elegida de ExamBase.
// No acceden a iframes ni interactúan con widgets de verificación.
export async function captureExamPage(expectedPage, expand = false) {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const ownPage = () => Number(location.pathname.match(/\/practice-questions\/(\d+)\/?$/)?.[1]);
  if (ownPage() !== expectedPage) return {wrongPage: true, url: location.href};
  const cardTitles = () => [...document.querySelectorAll("h3,h4,h5")].filter(n => /^Question\s+\d+$/i.test(n.textContent.trim()));
  const cards = () => [...new Set(cardTitles().map(n => n.closest(".card")).filter(Boolean))];
  function challenge() {
    const headings = [...document.querySelectorAll("title,h1,h2,h3,h4,h5")].map(n => n.textContent.replace(/’/g, "'").trim());
    const failure = headings.find(t => /verification (didn't go through|failed)|checking that you're human|verify (that )?you are human|just a moment/i.test(t));
    if (failure && !cardTitles().length) return {label: failure, code: document.body?.innerText.match(/\berror\s*[:(]?\s*(\d{6})\b/i)?.[1] || null, failed: /verification (didn't go through|failed)/i.test(failure)};
    return null;
  }
  const initialChallenge = challenge();
  if (initialChallenge) return {url: location.href, verification: initialChallenge};
  if (expand && cardTitles().length) {
    for (const card of cards()) {
      for (const button of card.querySelectorAll("button")) {
        const label = button.textContent.trim();
        const reveal = /^reveal answer$/i.test(label) && button.getAttribute("aria-pressed") !== "true";
        const context = /^(?:(?:view|show|read|open)\s+)?(?:case study|scenario|context)(?:\s*[:—-].*)?$/i.test(label) && button.getAttribute("aria-expanded") === "false";
        if ((reveal || context) && !button.disabled && button.getClientRects().length) {
          button.click(); await wait(250);
          if (ownPage() !== expectedPage) return {wrongPage: true, url: location.href};
        }
      }
      for (const details of card.querySelectorAll("details")) if (/case study|scenario|context/i.test(details.querySelector("summary")?.textContent || "")) details.open = true;
    }
    await wait(500);
  }
  const afterChallenge = challenge();
  if (afterChallenge) return {url: location.href, verification: afterChallenge};
  const items = cards().map(card => {
    const number = Number([...card.querySelectorAll("h3,h4,h5")].find(n => /^Question\s+\d+$/i.test(n.textContent.trim()))?.textContent.trim().match(/\d+/)?.[0]);
    const rich = [...card.querySelectorAll(".exambase-question__rich-text")];
    const explanationHeader = [...card.querySelectorAll(".card-header")].find(n => n.textContent.trim() === "Explanation");
    const explanation = explanationHeader?.parentElement.querySelector(".exambase-question__rich-text");
    const choices = [...card.querySelectorAll(".list-group-item")].map(li => {
      const letter = [...li.querySelectorAll("span")].map(n => n.textContent.trim()).find(t => /^[A-Z]$/.test(t));
      const body = li.querySelector(".exambase-question__rich-text");
      const correct = [...li.querySelectorAll("span,small")].some(n => n.textContent.trim().toLowerCase() === "correct");
      return letter && body ? {letter, text: body.innerHTML, is_correct: correct ? true : null} : null;
    }).filter(Boolean);
    if (choices.some(c => c.is_correct === true)) choices.forEach(c => { c.is_correct = c.is_correct === true; });
    const visibleContexts = [...card.querySelectorAll("details[open],[aria-expanded='true']")].filter(n => /context|scenario|case study/i.test(n.textContent)).map(n => n.tagName === "BUTTON" ? n.parentElement.outerHTML : n.outerHTML);
    return {id: null, order: number, question_text: rich[0]?.innerHTML || "", solution_text: explanation?.innerHTML || "", choices, type_data: {}, visible_context_html: visibleContexts.join("\n"), _dom_card_html: card.outerHTML};
  });
  const showing = document.body?.innerText.match(/Showing\s+(?:\d+\s*(?:[-–]|to)\s*)?\d+\s+of\s+(\d+)\s*[·•]\s*page\s+(\d+)\s+of\s+(\d+)/i);
  const currentImages = cards().flatMap(card => [...card.querySelectorAll("img")].map(img => ({source: img.currentSrc || img.getAttribute("data-src") || img.src, field: "visible_image", alt: img.alt || ""}))).filter(ref => ref.source);
  return {url: location.href, title: document.title, captured_at: new Date().toISOString(), html: "<!doctype html>\n" + document.documentElement.outerHTML,
    scripts: [...document.querySelectorAll("script:not([src])")].map(script => script.textContent),
    currentImages, dom: {kind: "questions", page: showing ? Number(showing[2]) : ownPage(), per_page: expectedPage === 1 ? items.length || 5 : 5, total: showing ? Number(showing[1]) : null, total_pages: showing ? Number(showing[3]) : null, items, topics: [], series: [], case_studies: []}};
}

export async function fetchImageInPage(url, maxBytes) {
  try {
    const response = await fetch(url, {credentials: "include", cache: "force-cache", signal: AbortSignal.timeout(20000)});
    if (!response.ok) return {error: `HTTP ${response.status}`, status: response.status};
    const mime = (response.headers.get("content-type") || "").split(";")[0].toLowerCase();
    if (!mime.startsWith("image/")) return {error: "El recurso no devolvió una imagen"};
    if (Number(response.headers.get("content-length")) > maxBytes) return {error: "Imagen de más de 20 MiB; revisión pendiente"};
    const blob = await response.blob();
    if (!blob.size || blob.size > maxBytes) return {error: "Tamaño de imagen no admitido"};
    const data_url = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob); });
    return {data_url, mime};
  } catch (error) { return {error: error.message}; }
}
