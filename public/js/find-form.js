// Card finder — the "Find a Card" request form.
//
// Posts to /api/sell with kind=source, so the worker subjects the mail
// "Card wanted — <name>" and adds the budget line. Same endpoint and same
// inbox as the old sell-to-us form, which is why the route is still /api/sell.
//
// The sell-to-us form was removed from the site on 2026-09-21: across 265
// logged purchases it had sourced exactly zero — every card came from Whatnot,
// eBay, card shows or Instagram — and it was the second form on a one-page
// site. Its handler (and ~100 lines of browser-side photo downscaling) went
// with it. If a sell form ever comes back, the photo-shrink code is in git.

const findForm = document.getElementById('find-form');
if (findForm) {
  const findStatus = findForm.querySelector('#find-status');
  const findBtn = findForm.querySelector('#find-submit');

  const findSay = (msg, kind) => {
    findStatus.textContent = msg;
    findStatus.className = 'sell-status' + (kind ? ` sell-status--${kind}` : '');
    findStatus.hidden = false;
  };

  findForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(findForm);
    data.append('kind', 'source');

    const name = (data.get('name') || '').toString().trim();
    const email = (data.get('email') || '').toString().trim();
    const details = (data.get('details') || '').toString().trim();
    if (!name || !email || !details) {
      return findSay('Please fill in your name, email and what you are looking for.', 'error');
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      return findSay('That email address does not look right.', 'error');
    }

    findBtn.disabled = true;
    findSay('Sending…');
    try {
      const res = await fetch('/api/sell', { method: 'POST', body: data });
      const out = await res.json().catch(() => ({}));
      if (res.ok && out.ok) {
        findForm.querySelector('.find-form-fields').hidden = true;
        return findSay("Got it — we'll start looking and come back to you within a day or two.", 'ok');
      }
      findBtn.disabled = false;
      return findSay(out.error || 'Something went wrong. Please try again.', 'error');
    } catch {
      findBtn.disabled = false;
      return findSay('Could not reach us just now. Please try again, or email info@duxburytradingpost.com.', 'error');
    }
  });
}
