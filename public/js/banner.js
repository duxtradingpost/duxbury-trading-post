// Direct-purchase promo bar.
//
// Shown above the sticky header, so it scrolls away and never eats screen space
// on a phone. Dismissal is remembered in localStorage against the code itself —
// change PROMO_CODE and everyone sees the bar again, without needing a new key
// or a version bump.
//
// The bar is in the HTML rather than injected here, so it paints with the page
// instead of flashing in a moment later. This script only hides it and wires the
// copy button.
const PROMO_CODE = 'DIRECT10';
const STORAGE_KEY = 'dtp-promo-dismissed';

(function () {
  const bar = document.getElementById('promo-bar');
  if (!bar) return;

  // A dismissal only counts for the code that was on screen at the time.
  let dismissed = null;
  try {
    dismissed = localStorage.getItem(STORAGE_KEY);
  } catch (err) {
    // Private browsing or storage disabled — just show the bar.
  }
  if (dismissed === PROMO_CODE) {
    bar.remove();
    return;
  }

  bar.hidden = false;

  const close = bar.querySelector('.promo-close');
  if (close) {
    close.addEventListener('click', () => {
      bar.remove();
      try {
        localStorage.setItem(STORAGE_KEY, PROMO_CODE);
      } catch (err) {
        // Not being able to remember it is harmless; it reappears next visit.
      }
    });
  }

  // Tapping the code copies it, so nobody has to retype it at checkout.
  const codeEl = bar.querySelector('.promo-code');
  if (codeEl) {
    codeEl.addEventListener('click', async () => {
      const original = codeEl.dataset.code;
      try {
        await navigator.clipboard.writeText(original);
        codeEl.textContent = 'Copied!';
      } catch (err) {
        // Clipboard blocked (no HTTPS, or permission denied) — select it instead
        // so a long-press or ctrl-C still works.
        const range = document.createRange();
        range.selectNodeContents(codeEl);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        return;
      }
      setTimeout(() => { codeEl.textContent = original; }, 1600);
    });
  }
})();

// --- Away / shipping delay notice --------------------------------------------
// Expires on its own. AWAY_UNTIL is the last day it should show; after that the
// bar never renders, so an out-of-date "I'm away" message cannot be left up by
// forgetting to remove it. To use it again, change the date and the copy in the
// HTML — nothing here needs touching.
const AWAY_UNTIL = '2026-08-28';   // inclusive; hides from the 29th

(function () {
  const bar = document.getElementById('away-bar');
  if (!bar) return;
  // Compare as local dates, not UTC — an ISO string parses as midnight UTC,
  // which is the previous evening here and would hide the bar a day early.
  const [y, m, d] = AWAY_UNTIL.split('-').map(Number);
  const lastDay = new Date(y, m - 1, d, 23, 59, 59);
  if (new Date() > lastDay) { bar.remove(); return; }
  bar.hidden = false;
})();
