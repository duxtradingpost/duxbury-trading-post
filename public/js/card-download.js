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
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'card-dl';
    b.setAttribute('aria-label', 'Download this photo');
    b.title = 'Download this photo';
    b.innerHTML = ICON;
    wrap.appendChild(b);
  }

  function scan(root) {
    (root.querySelectorAll ? root : document).querySelectorAll('.product-image-wrap').forEach(addButton);
  }

  // Shopify serves the grid at maxWidth 900; drop the size so the download is
  // the full original upload.
  function fullSize(src) {
    try {
      const u = new URL(src, location.href);
      ['width', 'height', 'crop'].forEach(k => u.searchParams.delete(k));
      return u.toString();
    } catch (e) { return src; }
  }

  function fileName(card, side) {
    const t = (card && (card.querySelector('[data-title]')?.dataset.title ||
               card.querySelector('h3')?.innerText)) || 'card';
    const slug = t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);
    return `${slug || 'card'}-${side}.jpg`;
  }

  async function download(wrap) {
    const flipped = wrap.classList.contains('is-flipped');
    const img = (flipped && wrap.querySelector('.card-face--back')) ||
                wrap.querySelector('.card-face--front, img');
    if (!img) return;
    const url = fullSize(img.currentSrc || img.src);
    const name = fileName(wrap.closest('.product-card'), flipped ? 'back' : 'front');
    try {
      const blob = await (await fetch(url, { mode: 'cors' })).blob();
      const file = new File([blob], name, { type: blob.type || 'image/jpeg' });
      if (window.matchMedia('(hover: none)').matches && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file] });
        return;
      }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch (err) {
      if (err && err.name === 'AbortError') return;   // share sheet dismissed
      window.open(url, '_blank', 'noopener');
    }
  }

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
