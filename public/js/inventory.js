// Live inventory search.
//
// The whole catalog is small enough (~130 one-of-a-kind cards) to fetch once and
// filter in the browser, so typing feels instant — no request per keystroke, no
// search index to keep warm, nothing to pay for.

const SHOPIFY_DOMAIN = 'duxburytradingpost.myshopify.com';
const SHOPIFY_STOREFRONT_TOKEN = '6e9ad9c0de82756dc160e72ea5d6c3c5';
const SHOPIFY_API_VERSION = '2025-10';

// Tag prefixes are for grouping in Shopify's admin, not for customers to read.
const stripPrefix = tag => tag.replace(/^(Player|Team|Brand|League|Year):\s*/i, '');

// Shown as one-click chips above the grid. Kept short on purpose — these are
// the ways people actually browse cards, not an exhaustive list.
const QUICK_FILTERS = ['Football', 'Baseball', 'Basketball', 'Soccer',
                       'Auto', 'Graded', 'Numbered', 'Parallel', 'Rookie'];

const grid = document.getElementById('inv-grid');
const status = document.getElementById('inv-status');
const input = document.getElementById('inv-search');
const clearBtn = document.getElementById('inv-clear');
const countEl = document.getElementById('inv-count');
const chipWrap = document.getElementById('quick-filters');
const moreBtn = document.getElementById('inv-more');
const sortSel = document.getElementById('inv-sort');

let CARDS = [];
const ACTIVE = new Set();   // chips currently toggled on

document.getElementById('year').textContent = new Date().getFullYear();

const navToggle = document.getElementById('nav-toggle');
const mainNav = document.getElementById('main-nav');
if (navToggle) {
  navToggle.addEventListener('click', () => {
    const open = mainNav.classList.toggle('open');
    navToggle.setAttribute('aria-expanded', String(open));
  });
}

async function loadInventory() {
  const query = `
    query {
      collectionByHandle(handle: "shop-all") {
        products(first: 250, sortKey: PRICE, reverse: true) {
          edges {
            node {
              title
              handle
              onlineStoreUrl
              tags
              createdAt
              availableForSale
              images(first: 12) { edges { node { url altText } } }
              priceRange { minVariantPrice { amount } }
            }
          }
        }
      }
    }
  `;

  try {
    const res = await fetch(`https://${SHOPIFY_DOMAIN}/api/${SHOPIFY_API_VERSION}/graphql.json`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shopify-Storefront-Access-Token': SHOPIFY_STOREFRONT_TOKEN
      },
      body: JSON.stringify({ query })
    });
    const data = await res.json();
    const edges = data?.data?.collectionByHandle?.products?.edges || [];

    CARDS = edges
      .filter(({ node }) => node.availableForSale)
      .map(({ node }) => {
        const imgs = node.images.edges.map(e => e.node);
        const image = imgs[0];
        // Pre-compute the haystack once so keystrokes stay cheap.
        const haystack = [node.title, ...node.tags.map(stripPrefix), ...node.tags]
          .join(' ')
          .toLowerCase();
        return {
          title: node.title,
          url: node.onlineStoreUrl || `https://${SHOPIFY_DOMAIN}/products/${node.handle}`,
          price: Number(node.priceRange.minVariantPrice.amount).toFixed(2),
          img: image ? image.url : '',
          alt: image?.altText || node.title,
          photos: imgs.map(x => x.url),
          tags: node.tags,
          created: node.createdAt,
          haystack
        };
      });

    if (!CARDS.length) {
      status.textContent = 'No cards in stock right now — check back soon.';
      return;
    }

    buildChips();
    render(CARDS);
    input.disabled = false;
    input.focus();
  } catch (err) {
    status.textContent = 'Couldn\'t load the inventory right now — browse our eBay store instead.';
    console.error('Inventory load error:', err);
  }
}

function buildChips() {
  const present = QUICK_FILTERS.filter(f => CARDS.some(c => c.tags.includes(f)));
  if (!present.length) return;
  chipWrap.innerHTML = present
    .map(f => `<button type="button" class="chip" data-term="${f}" aria-pressed="false">${f}</button>`)
    .join('');
  chipWrap.hidden = false;
  chipWrap.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      // Chips stack: Football + Auto + Numbered narrows to cards with all three.
      const term = btn.dataset.term;
      ACTIVE.has(term) ? ACTIVE.delete(term) : ACTIVE.add(term);
      applySearch();
    });
  });
}

// Chips and typed words both narrow, and they combine: Football + Auto plus
// "brady" means all three must match. Chips test the tag exactly; typed words
// match anywhere in the title or tags.
function applySearch() {
  const q = input.value.trim().toLowerCase();
  const words = q ? q.split(/\s+/) : [];
  clearBtn.hidden = !q && !ACTIVE.size;

  chipWrap.querySelectorAll('.chip').forEach(btn => {
    btn.classList.toggle('chip--on', ACTIVE.has(btn.dataset.term));
    btn.setAttribute('aria-pressed', String(ACTIVE.has(btn.dataset.term)));
  });

  if (!words.length && !ACTIVE.size) return render(CARDS);
  render(CARDS.filter(c =>
    [...ACTIVE].every(t => c.tags.includes(t)) &&
    words.every(w => c.haystack.includes(w))
  ));
}

// Searching stays instant because the whole catalog is already in memory, but
// painting 120+ cards with images at once is slow on a phone. So the results
// render a page at a time — the filter still runs across everything.
const PAGE_SIZE = 24;
let CURRENT = [];   // the active result set, however long
let shown = 0;      // how much of it is on screen

const IDX = new Map();   // card object -> stable index for the rendered buttons

function cardHtml(c) {
  return `
    <div class="product-card">
      <div class="product-image-wrap">
        <button type="button" class="photo-btn" data-idx="${IDX.get(c)}"
                aria-label="View photos of ${escapeAttr(c.title)}">
          <img src="${c.img}" alt="${escapeAttr(c.alt)}" class="product-image" loading="lazy">
          ${c.photos.length > 1 ? `<span class="photo-count">${c.photos.length} photos</span>` : ''}
        </button>
      </div>
      <h3>${escapeHtml(c.title)}</h3>
      <p class="product-price">$${c.price}</p>
      <div class="product-actions">
        <a href="${c.url}" target="_blank" rel="noopener" class="btn btn-primary btn-small">Buy Now</a>
        <button type="button" class="btn btn-outline btn-small share-btn"
                data-share-url="${c.url}" data-share-title="${escapeAttr(c.title)}"
                aria-label="Share this listing">Share</button>
      </div>
    </div>
  `;
}

function wirePhotos(scope) {
  scope.querySelectorAll('.photo-btn:not([data-wired])').forEach(btn => {
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => {
      const card = [...IDX.entries()].find(([, i]) => String(i) === btn.dataset.idx)?.[0];
      if (card) openLightbox(card);
    });
  });
}

function wireShare(scope) {
  scope.querySelectorAll('.share-btn:not([data-wired])').forEach(btn => {
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => shareListing(btn.dataset.shareUrl, btn.dataset.shareTitle, btn));
  });
}

function updateCount() {
  const total = CURRENT.length;
  const scope = total === CARDS.length ? `${CARDS.length} cards in stock` : `${total} of ${CARDS.length} cards`;
  countEl.textContent = shown < total ? `${scope} — showing ${shown}` : scope;
  moreBtn.hidden = shown >= total;
  moreBtn.textContent = `Load ${Math.min(PAGE_SIZE, total - shown)} more`;
}

function appendPage() {
  const next = CURRENT.slice(shown, shown + PAGE_SIZE);
  next.forEach(c => { if (!IDX.has(c)) IDX.set(c, IDX.size); });
  grid.insertAdjacentHTML('beforeend', next.map(cardHtml).join(''));
  shown += next.length;
  wireShare(grid);
  wirePhotos(grid);
  updateCount();
}

// Sorting acts on whatever is currently matched, so it composes with search
// rather than resetting it.
const SORTS = {
  'price-desc': (a, b) => Number(b.price) - Number(a.price),
  'price-asc':  (a, b) => Number(a.price) - Number(b.price),
  'newest':     (a, b) => (a.created < b.created ? 1 : a.created > b.created ? -1 : 0),
  'title':      (a, b) => a.title.localeCompare(b.title)
};

function render(list) {
  CURRENT = [...list].sort(SORTS[sortSel.value] || SORTS['price-desc']);
  shown = 0;
  grid.innerHTML = '';
  if (!list.length) {
    grid.innerHTML = '<p class="grid-status">No cards match that search. Try a player, team, or set name.</p>';
    countEl.textContent = `0 of ${CARDS.length} cards`;
    moreBtn.hidden = true;
    return;
  }
  appendPage();
}

const escapeHtml = s => s.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
const escapeAttr = s => escapeHtml(s).replace(/"/g, '&quot;');

async function shareListing(url, title, btn) {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
      return;
    } catch (err) {
      return; // user dismissed the share sheet
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    const original = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = original; }, 1600);
  } catch (err) {
    window.prompt('Copy this link:', url);
  }
}

moreBtn.addEventListener('click', appendPage);
sortSel.addEventListener('change', applySearch);

// ---- Photo viewer -------------------------------------------------------
// Cards are photographed front and back (some have a dozen shots), and the
// grid can only show one. Clicking the photo opens the rest in place rather
// than sending people to Shopify before they've decided to buy.
const lb = {
  el: document.getElementById('lightbox'),
  img: document.getElementById('lb-img'),
  title: document.getElementById('lb-title'),
  counter: document.getElementById('lb-counter'),
  buy: document.getElementById('lb-buy'),
  prev: document.getElementById('lb-prev'),
  next: document.getElementById('lb-next'),
  close: document.getElementById('lb-close')
};
let lbCard = null, lbAt = 0;

function openLightbox(card, at = 0) {
  lbCard = card; lbAt = at;
  lb.title.textContent = card.title;
  lb.buy.href = card.url;
  paintLightbox();
  lb.el.hidden = false;
  document.body.style.overflow = 'hidden';
  lb.close.focus();
}

function paintLightbox() {
  const shots = lbCard.photos.length ? lbCard.photos : [lbCard.img];
  lbAt = (lbAt + shots.length) % shots.length;
  lb.img.src = shots[lbAt];
  lb.img.alt = `${lbCard.title} — photo ${lbAt + 1} of ${shots.length}`;
  lb.counter.textContent = shots.length > 1 ? `${lbAt + 1} / ${shots.length}` : '';
  const solo = shots.length < 2;
  lb.prev.hidden = solo;
  lb.next.hidden = solo;
  // Preload the neighbours so arrowing through doesn't flash.
  if (!solo) [lbAt + 1, lbAt - 1].forEach(i => {
    new Image().src = shots[(i + shots.length) % shots.length];
  });
}

function stepLightbox(d) { if (lbCard) { lbAt += d; paintLightbox(); } }

function closeLightbox() {
  lb.el.hidden = true;
  lbCard = null;
  document.body.style.overflow = '';
}

lb.prev.addEventListener('click', () => stepLightbox(-1));
lb.next.addEventListener('click', () => stepLightbox(1));
lb.close.addEventListener('click', closeLightbox);
lb.el.addEventListener('click', e => { if (e.target === lb.el) closeLightbox(); });
document.addEventListener('keydown', e => {
  if (lb.el.hidden) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') stepLightbox(-1);
  if (e.key === 'ArrowRight') stepLightbox(1);
});
// Swipe, since most of the traffic arrives from Instagram on a phone.
let touchX = null;
lb.el.addEventListener('touchstart', e => { touchX = e.changedTouches[0].clientX; }, { passive: true });
lb.el.addEventListener('touchend', e => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  if (Math.abs(dx) > 45) stepLightbox(dx < 0 ? 1 : -1);
  touchX = null;
}, { passive: true });

input.addEventListener('input', applySearch);
clearBtn.addEventListener('click', () => { input.value = ''; ACTIVE.clear(); applySearch(); input.focus(); });
input.disabled = true;
loadInventory();
