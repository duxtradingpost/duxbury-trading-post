// --- Download a card photo ----------------------------------------------------
// A small download mark in the bottom-left corner of every card photo, opposite
// the flip mark in the bottom-right (Craig, 4 Oct 2026). It saves the side that
// is showing: the front, or the back once the card has been turned over.
//
// Most visitors arrive from Instagram's in-app browser on a phone, where a plain
// <a download> is ignored. So the order is: the phone's share sheet with the
// image file (it offers "Save Image"), then a normal file download, then opening
// the full-size photo in a new tab as the last resort.
//
// Added to every .product-image-wrap as cards render (homepage, inventory and
// My Collection alike), so no grid code needs to know about it. The click is
// caught in the capture phase so it never also flips the card, opens the photo
// viewer or follows the listing link underneath.
(() => {
  const ICON = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" ' +
    'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/></svg>';

  function addButton(wrap) {
    if (wrap.querySelector('.card-dl')) return;
    watch(wrap);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'card-dl';
    b.setAttribute('aria-label', 'Save this photo');
    b.title = 'Save this photo';
    b.innerHTML = ICON;
    wrap.appendChild(b);
  }

  function scan(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('.product-image-wrap').forEach(addButton);
  }

  // The grid shows 700px photos; the saved copy is 1400px wide (sharp on a
  // phone, small enough to hold a screenful of them in memory).
  function fullSize(src) {
    try {
      const u = new URL(src, location.href);
      ['width', 'height', 'crop'].forEach(k => u.searchParams.delete(k));
      u.pathname = u.pathname.replace(/_(\d+x\d*|\d*x\d+)(?=\.[a-z]+$)/i, '_1400x');
      return u.toString();
    } catch (e) { return src; }
  }

  function fileName(card, side) {
    const t = (card && (card.querySelector('[data-title]')?.dataset.title ||
               card.querySelector('h3')?.innerText)) || 'card';
    const slug = t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);
    return `${slug || 'card'}-${side}.jpg`;
  }

  // iPhone Safari only opens the share sheet straight from a tap, and Craig
  // (16 Nov 2026) wants the tap to go straight to "Save Image" with no download
  // step. So on phones each photo is quietly fetched while its card is on
  // screen, and the tap hands the ready file to the share sheet at once. If a
  // photo is not ready yet (or the browser cannot share files, e.g. Instagram's
  // in-app browser) the full photo opens with press-and-hold, which is the
  // phone's own Save to Photos menu.
  const isPhone = () => window.matchMedia('(hover: none)').matches;
  const cache = new Map();   // url -> {promise, file}; oldest dropped past KEEP
  const KEEP = 40;

  function target(wrap) {
    const flipped = wrap.classList.contains('is-flipped');
    const img = (flipped && wrap.querySelector('.card-face--back')) ||
                wrap.querySelector('.card-face--front, img');
    if (!img) return null;
    return { url: fullSize(img.currentSrc || img.src),
             name: fileName(wrap.closest('.product-card'), flipped ? 'back' : 'front') };
  }

  function load(t) {
    let c = cache.get(t.url);
    if (!c) {
      c = { file: null };
      c.promise = fetch(t.url, { mode: 'cors' }).then(r => r.blob()).then(blob => {
        c.file = new File([blob], t.name, { type: blob.type || 'image/jpeg' });
        return c.file;
      });
      c.promise.catch(() => cache.delete(t.url));
      cache.set(t.url, c);
      while (cache.size > KEEP) cache.delete(cache.keys().next().value);
    }
    return c;
  }

  const canShareFile = f => !!(navigator.canShare && navigator.share && navigator.canShare({ files: [f] }));

  function share(file) {
    return navigator.share({ files: [file] }).catch(err => {
      if (err && err.name !== 'AbortError') pressAndHold(URL.createObjectURL(file));
    });
  }

  function sheet(inner) {
    const o = document.createElement('div');
    o.className = 'card-dl-sheet';
    o.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.86);display:flex;' +
      'flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:24px 16px;' +
      'color:#fff;font:600 16px/1.35 system-ui,sans-serif;text-align:center';
    o.innerHTML = inner + '<button type="button" data-close style="background:none;border:1px solid rgba(255,255,255,.5);' +
      'color:#fff;border-radius:999px;padding:9px 22px;font:inherit;font-weight:500">Close</button>';
    o.addEventListener('click', e => { if (e.target === o || e.target.closest('[data-close]')) o.remove(); });
    document.body.appendChild(o);
    return o;
  }

  function pressAndHold(src) {
    sheet('<img alt="" src="' + src + '" style="max-width:100%;max-height:68vh;border-radius:6px;' +
      '-webkit-touch-callout:default;user-select:auto">' +
      '<div style="max-width:30ch">Press and hold the photo, then tap <b>Save to Photos</b>.</div>');
  }

  function desktopDownload(file) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(file);
    a.download = file.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  function download(wrap) {
    const t = wrap && target(wrap);
    if (!t) return;
    const c = load(t);
    if (c.file) {                       // ready: open the sheet on this very tap
      if (isPhone() && canShareFile(c.file)) return share(c.file);
      return isPhone() ? pressAndHold(t.url) : desktopDownload(c.file);
    }
    if (isPhone()) return pressAndHold(t.url);   // not loaded yet: no waiting, no download
    c.promise.then(desktopDownload).catch(() => window.open(t.url, '_blank', 'noopener'));
  }

  // Phones: load each card's photo while it is on screen (and the back once it
  // is flipped), so the save tap never has to wait.
  const seen = new IntersectionObserver(entries => entries.forEach(en => {
    if (!en.isIntersecting) return;
    const t = target(en.target);
    if (t) load(t);
  }), { rootMargin: '150px 0px' });
  function watch(wrap) { if (isPhone()) seen.observe(wrap); }
  document.addEventListener('click', e => {
    const w = e.target.closest && e.target.closest('.product-image-wrap');
    if (w && isPhone()) setTimeout(() => { const t = target(w); if (t) load(t); }, 400);
  });

  // Also start loading as soon as a finger (or mouse) lands on the button.
  ['touchstart', 'pointerdown'].forEach(ev => document.addEventListener(ev, e => {
    const b = e.target.closest && e.target.closest('.card-dl');
    const t = b && target(b.closest('.product-image-wrap'));
    if (t) load(t);
  }, { capture: true, passive: true }));

  document.addEventListener('click', e => {
    const b = e.target.closest('.card-dl');
    if (!b) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    download(b.closest('.product-image-wrap'));
  }, true);

  scan(document);
  new MutationObserver(muts => muts.forEach(m => m.addedNodes.forEach(n => {
    if (n.nodeType !== 1) return;
    if (n.matches && n.matches('.product-image-wrap')) addButton(n);
    scan(n);
  }))).observe(document.body, { childList: true, subtree: true });
})();
