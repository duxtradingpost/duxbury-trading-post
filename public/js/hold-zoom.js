// --- Tap and hold to zoom ----------------------------------------------------
// On a phone a tap turns a card over (main.js / inventory.js). Holding a finger
// on the photo instead magnifies it under the finger, the way you would hold a
// card up to your eye to check the corners or the serial number. Sliding the
// finger moves the magnified spot; letting go puts it back.
//
// Delegated from the document so it covers cards rendered after load, on the
// homepage, the inventory grid and the collection page alike. Mouse users
// already get the full-size photo viewer on click, so this is touch only.
(() => {
  const HOLD_MS = 350;     // shorter than this is a tap (flip)
  const SLOP = 10;         // px a finger may drift before it counts as a scroll

  let timer = null, wrap = null, startX = 0, startY = 0, zoomed = false, swallowClick = false;

  function aim(t) {
    const r = wrap.getBoundingClientRect();
    const x = Math.min(100, Math.max(0, ((t.clientX - r.left) / r.width) * 100));
    const y = Math.min(100, Math.max(0, ((t.clientY - r.top) / r.height) * 100));
    wrap.style.setProperty('--zoom-x', `${x}%`);
    wrap.style.setProperty('--zoom-y', `${y}%`);
  }

  function reset() {
    clearTimeout(timer);
    timer = null;
    if (wrap && zoomed) {
      wrap.classList.remove('is-zoomed');
      // The finger lifting fires a click; it must not also turn the card over.
      swallowClick = true;
      setTimeout(() => { swallowClick = false; }, 450);
    }
    zoomed = false;
    wrap = null;
  }

  document.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) return reset();
    const w = e.target.closest('.product-image-wrap');
    if (!w) return;
    wrap = w;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    const t = e.touches[0];
    timer = setTimeout(() => {
      if (!wrap) return;
      zoomed = true;
      aim(t);
      wrap.classList.add('is-zoomed');
    }, HOLD_MS);
  }, { passive: true });

  // Not passive: once zoomed, the finger pans the photo instead of the page.
  document.addEventListener('touchmove', e => {
    if (!wrap) return;
    const t = e.touches[0];
    if (zoomed) {
      e.preventDefault();
      aim(t);
    } else if (Math.abs(t.clientX - startX) > SLOP || Math.abs(t.clientY - startY) > SLOP) {
      reset();   // a scroll, not a hold
    }
  }, { passive: false });

  document.addEventListener('touchend', reset, { passive: true });
  document.addEventListener('touchcancel', reset, { passive: true });

  // Capture phase, so it runs before the flip and photo-viewer handlers.
  document.addEventListener('click', e => {
    if (!swallowClick || !e.target.closest('.product-image-wrap')) return;
    swallowClick = false;
    e.preventDefault();
    e.stopImmediatePropagation();
  }, true);

  // A long press would otherwise raise the phone's save-image / open-link menu.
  document.addEventListener('contextmenu', e => {
    if (window.matchMedia('(hover: none)').matches && e.target.closest('.product-image-wrap')) e.preventDefault();
  });
})();
