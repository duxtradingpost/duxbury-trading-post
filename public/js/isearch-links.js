// In Search Of page: each checklist card name opens an eBay search for that card,
// and a small button beside it copies the name. Added at runtime so the
// build-*-checklist.py rebuilds (which rewrite the <ul> blocks) never drop it.
// Sets hunted only in PSA 10 add "PSA 10" to the search. (5 Nov 2026)
(function () {
  const PSA10_SETS = ['color-blast-set', 'downtown-uptown-set'];

  function cardName(li) {
    const yr = li.querySelector('.cb-yr')?.textContent.trim() || '';
    const name = li.querySelector('.cb-name')?.textContent.replace(/\s+/g, ' ').trim() || '';
    return `${yr} ${name} Josh Allen`.trim();
  }

  function copy(text) {
    if (typeof copyText === 'function') return copyText(text);   // main.js helper
    return navigator.clipboard?.writeText(text).then(() => true, () => false) ?? Promise.resolve(false);
  }

  document.querySelectorAll('.cb-set').forEach(set => {
    const psa10 = PSA10_SETS.includes(set.id);
    set.querySelectorAll('.cb-list li').forEach(li => {
      const nameEl = li.querySelector('.cb-name');
      if (!nameEl || li.querySelector('.cb-link')) return;
      const title = cardName(li);
      const q = psa10 ? `${title} PSA 10` : title;

      const a = document.createElement('a');
      a.className = 'cb-link';
      a.href = 'https://www.ebay.com/sch/i.html?_nkw=' + encodeURIComponent(q);
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = 'Search eBay for this card';
      nameEl.replaceWith(a);
      a.appendChild(nameEl);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cb-copy';
      btn.setAttribute('aria-label', 'Copy card name');
      btn.title = 'Copy card name';
      btn.textContent = 'Copy';
      btn.addEventListener('click', () => {
        copy(title).then(ok => {
          btn.textContent = ok ? 'Copied' : 'Copy failed';
          btn.classList.toggle('is-done', ok);
          clearTimeout(btn._t);
          btn._t = setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('is-done'); }, 1600);
        });
      });
      li.appendChild(btn);
    });
  });
})();
