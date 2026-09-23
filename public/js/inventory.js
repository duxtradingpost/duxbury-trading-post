// Live inventory search.
//
// The whole catalog is small enough (~130 one-of-a-kind cards) to fetch once and
// filter in the browser, so typing feels instant — no request per keystroke, no
// search index to keep warm, nothing to pay for.

const SHOPIFY_DOMAIN = 'duxburytradingpost.myshopify.com';
const SHOPIFY_STOREFRONT_TOKEN = '6e9ad9c0de82756dc160e72ea5d6c3c5';
const SHOPIFY_API_VERSION = '2025-10';

// Website prices undercut the eBay listing by this much.
//
// It has to be hardcoded. Shopify prices are locked to eBay — InfoShore syncs
// price eBay -> Shopify continuously, so the discount CANNOT be a price edit; it
// is a Shopify *automatic discount* applied at checkout. But an automatic discount
// never touches `priceRange.minVariantPrice`, which is what the Storefront API
// returns and what this page renders. So the checkout would charge 12% less than
// the grid displayed, and the shopper would never see a reason to buy here rather
// than on eBay.
//
// MUST MATCH the live Shopify automatic discount
// "Website price - 12% off every card"
// gid://shopify/DiscountAutomaticNode/1394920390742
// Change one and you must change the other, or this page lies about the price.
//
// The rate is capped by arithmetic, not taste: eBay's fixed $5.30 (postage +
// per-order) is a big share of a cheap sale and a trivial share of a dear one, so
// the fees saved shrink as price rises. 12% is safe up to a $384 ask; 15% only to
// $118.62. See "Website pricing vs eBay" in WORKFLOW.md.
const WEBSITE_DISCOUNT = 0;   // was 0.12 - discount switched OFF 2026-09-21

const webPrice = list => (list * (1 - WEBSITE_DISCOUNT)).toFixed(2);

// Buy Now must land somewhere the 12% is VISIBLE.
//
// The automatic discount is applied by Shopify at the CART, not on the product
// page — so linking to /products/<handle> showed the shopper $100 right after
// this grid promised $88. They have no reason to trust the site and every reason
// to assume the discount is a trick. (Craig spotted this 2026-09-16.)
//
// A cart permalink (/cart/<variantId>:1) adds the card and lands on the cart,
// where the discount line is rendered before any payment step. Falls back to the
// product page when the variant id is missing, which is never worse than today.
const buyUrl = (variantGid, productUrl) => {
  const id = String(variantGid || '').split('/').pop();
  return /^\d+$/.test(id) ? `https://${SHOPIFY_DOMAIN}/cart/${id}:1` : productUrl;
};

// Personal Collection cards can ALSO be listed on eBay, at a price Craig would
// take, and the eBay sync then drops them into Shop All with that price. On this
// site they never show a price or a Buy Now: they read "Personal Collection" and
// ask by email instead. The marker is membership in the Shopify Personal
// Collection (handle coming-soon, the same one collection.html shows), or the
// `Personal` tag the report scripts use. Same rule in js/main.js and src/index.js.
const PERSONAL_COLLECTION_HANDLE = 'coming-soon';
const isPersonal = node => (node.tags || []).includes('Personal') ||
  (node.collections?.edges || []).some(e => e.node.handle === PERSONAL_COLLECTION_HANDLE);
const askUrl = title =>
  `mailto:info@duxburytradingpost.com?subject=${encodeURIComponent(`Question: ${title}`)}` +
  `&body=${encodeURIComponent(`Hi Duxbury Trading Post,\r\n\r\nI have a question about:\r\n${title}\r\n\r\nThanks!`)}`;

// Tag prefixes are for grouping in Shopify's admin, not for customers to read.
const stripPrefix = tag => tag.replace(/^(Player|Team|Brand|League|Year):\s*/i, '');

// Shown as one-click chips above the grid. Kept short on purpose — these are
// the ways people actually browse cards, not an exhaustive list.
//
// A chip is either a plain tag, or a label with the tags it accepts. The second
// form exists because sealed product gets tagged half a dozen ways depending on
// what it is — a hobby box, a blaster, a loose pack, a case — and a shopper
// browsing for sealed wants all of it behind one chip rather than four.
const QUICK_FILTERS = ['Football', 'Baseball', 'Basketball', 'Hockey', 'Soccer',
                       { label: 'Pokémon', tags: ['Pokemon', 'Brand: Pokemon'] },
                       'Auto', 'Graded', 'Numbered', 'Parallel', 'Rookie', 'Relic',
                       { label: 'Sealed',
                         tags: ['Sealed', 'Box', 'Boxes', 'Hobby Box', 'Blaster',
                                'Mega Box', 'Pack', 'Packs', 'Case', 'Wax'] }];

// Normalise both forms to {label, tags} so the rest of the code has one shape.
const FILTERS = QUICK_FILTERS.map(f =>
  typeof f === 'string' ? { label: f, tags: [f] } : f);

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
// Homepage "Shop Fast" tiles link here with ?q= (words), ?f= (a chip label)
// or ?max= (price ceiling, website price). MAX_PRICE has no chip of its own.
const PARAMS = new URLSearchParams(location.search);
let MAX_PRICE = Number(PARAMS.get('max')) || 0;

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
  // PAGINATED. The Storefront API caps a page at 250, and "Shop All" passed that
  // on 2026-09-21 - the grid silently showed the 250 dearest cards and the
  // header read "250 cards in stock" no matter how many were really listed.
  // first:250 with no cursor loop is a truncation, not a limit.
  const query = `
    query($after: String) {
      collectionByHandle(handle: "shop-all") {
        products(first: 250, after: $after, sortKey: PRICE, reverse: true) {
          pageInfo { hasNextPage endCursor }
          edges {
            node {
              title
              handle
              onlineStoreUrl
              tags
              createdAt
              availableForSale
              collections(first: 10) { edges { node { handle } } }
              # Front and back only — the extra angles are for eBay, not here.
              images(first: 2) { edges { node { url altText } } }
              priceRange { minVariantPrice { amount } }
              # Needed to build a cart permalink — see buyUrl() below.
              variants(first: 1) { edges { node { id } } }
            }
          }
        }
      }
    }
  `;

  try {
    const edges = [];
    let after = null;
    // Walk every page. Capped at 40 round trips (10,000 cards) so a bad cursor
    // can never spin forever.
    for (let page = 0; page < 40; page++) {
      const res = await fetch(`https://${SHOPIFY_DOMAIN}/api/${SHOPIFY_API_VERSION}/graphql.json`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Shopify-Storefront-Access-Token': SHOPIFY_STOREFRONT_TOKEN
        },
        body: JSON.stringify({ query, variables: { after } })
      });
      const data = await res.json();
      const conn = data?.data?.collectionByHandle?.products;
      if (!conn) break;
      edges.push(...(conn.edges || []));
      if (!conn.pageInfo?.hasNextPage) break;
      after = conn.pageInfo.endCursor;
    }

    CARDS = edges
      .filter(({ node }) => node.availableForSale)
      .map(({ node }) => {
        const imgs = node.images.edges.map(e => e.node);
        const image = imgs[0];
        // Pre-compute the haystack once so keystrokes stay cheap.
        const haystack = [node.title, ...node.tags.map(stripPrefix), ...node.tags]
          .join(' ')
          .toLowerCase()
          .normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        const productUrl = node.onlineStoreUrl
          || `https://${SHOPIFY_DOMAIN}/products/${node.handle}`;
        const personal = isPersonal(node);
        return {
          title: node.title,
          handle: node.handle,
          // `url` is what the Share button sends: this card on OUR site, not the
          // Shopify theme page. The Worker fills in the card's photo and price
          // for the link preview (see cardPreview in src/index.js).
          url: shareUrl(node.handle),
          // `buy` goes to the cart so the price the grid shows is the first
          // number the shopper sees.
          // A Personal Collection card asks by email instead - never a cart link.
          buy: personal ? askUrl(node.title) : buyUrl(node.variants?.edges?.[0]?.node?.id, productUrl),
          personal,
          // `price` stays the LIST price — it is what Shopify and eBay both show,
          // and what the sorts compare. `web` is what this site actually charges.
          price: Number(node.priceRange.minVariantPrice.amount).toFixed(2),
          web: webPrice(Number(node.priceRange.minVariantPrice.amount)),
          img: image ? image.url : '',
          alt: image?.altText || node.title,
          photos: imgs.map(x => x.url),
          // Second image is the card back — HeyStack uploads front then back.
          back: imgs[1] ? imgs[1].url : '',
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
    input.disabled = false;
    if (PARAMS.get('q')) input.value = PARAMS.get('q');
    if (PARAMS.get('f') && FILTERS.some(f => f.label === PARAMS.get('f'))) ACTIVE.add(PARAMS.get('f'));
    if (PARAMS.get('q') || PARAMS.get('f') || MAX_PRICE) applySearch(); else render(CARDS);
    if (!openSharedCard() && !PARAMS.get('q')) input.focus();
  } catch (err) {
    status.textContent = 'Couldn\'t load the inventory right now — browse our eBay store instead.';
    console.error('Inventory load error:', err);
  }
}

function buildChips() {
  // A chip only exists if something in stock carries one of its tags, so the row
  // stays honest — no chip that filters to nothing.
  const present = FILTERS.filter(f => CARDS.some(c => f.tags.some(t => c.tags.includes(t))));
  if (!present.length && !MAX_PRICE) return;
  // A price ceiling from a homepage link shows as its own chip, so the narrowing
  // is visible and one tap undoes it.
  const priceChip = MAX_PRICE
    ? `<button type="button" class="chip chip--on chip--price" id="price-chip" aria-label="Remove price limit">Under $${MAX_PRICE} <span aria-hidden="true">&times;</span></button>`
    : '';
  chipWrap.innerHTML = priceChip + present
    .map(f => `<button type="button" class="chip" data-term="${f.label}" aria-pressed="false">${f.label}</button>`)
    .join('');
  chipWrap.hidden = false;
  const pc = document.getElementById('price-chip');
  if (pc) pc.addEventListener('click', () => { MAX_PRICE = 0; pc.remove(); applySearch(); });
  chipWrap.querySelectorAll('.chip[data-term]').forEach(btn => {
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
  // Accents are stripped on both sides, so "pokémon" finds titles spelled
  // "Pokemon" (which is how the listings are written).
  const q = input.value.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const words = q ? q.split(/\s+/) : [];
  clearBtn.hidden = !q && !ACTIVE.size && !MAX_PRICE;

  chipWrap.querySelectorAll('.chip[data-term]').forEach(btn => {
    btn.classList.toggle('chip--on', ACTIVE.has(btn.dataset.term));
    btn.setAttribute('aria-pressed', String(ACTIVE.has(btn.dataset.term)));
  });

  // Personal Collection cards have no price on this site, so a price ceiling
  // can't honestly include them.
  const underMax = c => !MAX_PRICE || (!c.personal && Number(c.web) <= MAX_PRICE);
  if (!words.length && !ACTIVE.size && !MAX_PRICE) return render(CARDS);
  // A chip is satisfied by any one of its tags — "Sealed" matches a Hobby Box or
  // a loose Pack — but every active chip still has to be satisfied.
  const accepts = label => (FILTERS.find(f => f.label === label) || { tags: [label] }).tags;
  render(CARDS.filter(c =>
    [...ACTIVE].every(label => accepts(label).some(t => c.tags.includes(t))) &&
    words.every(w => c.haystack.includes(w)) && underMax(c)
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
      <div class="product-image-wrap${c.back ? ' has-back' : ''}">
        <button type="button" class="photo-btn" data-idx="${IDX.get(c)}"
                aria-label="View photos of ${escapeAttr(c.title)}">
          <span class="card-flip">
            <img src="${c.img}" alt="${escapeAttr(c.alt)}" class="product-image card-face card-face--front" loading="lazy">
            ${c.back ? `<img src="${c.back}" alt="Back of ${escapeAttr(c.title)}" class="card-face card-face--back" loading="lazy" aria-hidden="true">` : ''}
          </span>
        </button>
      </div>
      <h3><button type="button" class="copy-title" data-title="${escapeAttr(c.title)}"
        title="Click to copy this title">${escapeHtml(c.title)}</button></h3>
      ${c.personal
        ? '<p class="product-price product-price--pc">Personal Collection</p>'
        : `<p class="product-price">
        $${c.web}
        ${WEBSITE_DISCOUNT > 0 ? `<span class="product-price__was">$${c.price}</span>
        <span class="product-price__off">${Math.round(WEBSITE_DISCOUNT * 100)}% off</span>` : ''}
      </p>`}
      <div class="product-actions">
        ${c.personal
          ? `<a href="${c.buy}" class="btn btn-primary btn-small">Ask About This Card</a>`
          : `<a href="${c.buy}" target="_blank" rel="noopener" class="btn btn-primary btn-small">Buy Now</a>`}
        <button type="button" class="btn btn-outline btn-small card-send"
                data-share-url="${c.url}" data-share-title="${escapeAttr(c.title)}"
                aria-label="Share this listing">Share</button>
      </div>
    </div>
  `;
}

// Titles are not links on this page, so a click has nothing better to do than
// hand you the text. People check comps constantly and the alternative is
// selecting 60 characters by hand.
function wireCopyTitles(scope) {
  scope.querySelectorAll('.copy-title:not([data-wired])').forEach(btn => {
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => copyTitle(btn));
  });
}

// Copy text from a tap, in every browser that matters here. Most traffic comes
// from Instagram's in-app browser, where navigator.clipboard is missing or
// refused - and the old fallback only SELECTED the title, which on a phone looks
// like nothing happened (reported from mobile 2026-09-23). So the textarea +
// execCommand route runs FIRST and synchronously, while the tap still counts as
// a user gesture: a fallback that waits for the clipboard promise to reject has
// already lost the gesture on iOS. Resolves true when something was copied.
function copyText(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');                     // no keyboard on iOS
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px';  // 16px: no zoom
  const back = document.activeElement;
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, text.length);                // iOS ignores select()
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  if (back && back.focus) back.focus({ preventScroll: true });
  if (ok) return Promise.resolve(true);
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text).then(() => true, () => false);
  }
  return Promise.resolve(false);
}

// Nothing could copy: select the title and say so, rather than fail silently.
function copyFailed(btn) {
  const r = document.createRange();
  r.selectNodeContents(btn);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(r);
  btn.classList.add('copy-title--manual');
  clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.classList.remove('copy-title--manual'), 2600);
}

async function copyTitle(btn) {
  if (!(await copyText(btn.dataset.title))) return copyFailed(btn);
  btn.classList.remove('copy-title--manual');
  btn.classList.add('copy-title--done');
  clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.classList.remove('copy-title--done'), 1400);
}

function wirePhotos(scope) {
  scope.querySelectorAll('.photo-btn:not([data-wired])').forEach(btn => {
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => {
      const card = [...IDX.entries()].find(([, i]) => String(i) === btn.dataset.idx)?.[0];
      if (!card) return;
      const wrap = btn.closest('.product-image-wrap');

      // On a phone the tap only turns the card, back and forth, the way you
      // would in your hands — nothing opens over the top of the grid. The
      // lightbox holds these same two shots (the query asks for
      // images(first: 2)), so on touch it was a heavier way to see what the
      // turn already shows.
      //
      // Cards with no back have nothing to turn to, so a tap on one still
      // opens the photo — otherwise it would do nothing at all. .has-back is
      // only set when there is a back.
      if (window.matchMedia('(hover: none)').matches &&
          wrap.classList.contains('has-back')) {
        wrap.classList.toggle('is-flipped');
        return;
      }

      openLightbox(card);
    });
  });
}

// The class is deliberately NOT "share-btn". Content blockers (Safari content
// blockers, Brave, AdGuard, uBlock's annoyance lists) hide anything with that
// name as a social-share widget, so on many phones the button simply was not
// there. Keep "share" out of the class name.
function wireShare(scope) {
  scope.querySelectorAll('.card-send:not([data-wired])').forEach(btn => {
    btn.dataset.wired = '1';
    btn.addEventListener('click', () => shareListing(btn.dataset.shareUrl, btn.dataset.shareTitle, btn));
  });
}

// "cards" stops being true the moment a sealed box is in stock, so the noun
// follows the catalogue rather than being hard-coded. Singles only: "cards".
// Anything sealed in the mix: "items".
function stockNoun() {
  const sealed = FILTERS.find(f => f.label === 'Sealed');
  return CARDS.some(c => sealed.tags.some(t => c.tags.includes(t))) ? 'items' : 'cards';
}

function updateCount() {
  const total = CURRENT.length;
  const noun = stockNoun();
  const scope = total === CARDS.length ? `${CARDS.length} ${noun} in stock` : `${total} of ${CARDS.length} ${noun}`;
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
  wireCopyTitles(grid);
  updateCount();
}

// Sorting acts on whatever is currently matched, so it composes with search
// rather than resetting it.
const SORTS = {
  // Personal Collection cards sort after everything priced, either way round,
  // so the order never hints at a price the page doesn't show.
  'price-desc': (a, b) => (a.personal - b.personal) || Number(b.price) - Number(a.price),
  'price-asc':  (a, b) => (a.personal - b.personal) || Number(a.price) - Number(b.price),
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

// A shared link is inventory?card=<handle>. It opens that card's photos over
// the grid so whoever tapped the link lands on the card, not on 130 others.
function shareUrl(handle) {
  return `https://duxburytradingpost.com/inventory?card=${encodeURIComponent(handle)}`;
}

function openSharedCard() {
  const handle = new URLSearchParams(location.search).get('card');
  if (!handle) return false;
  const card = CARDS.find(c => c.handle === handle);
  if (!card) {
    // Sold, or pulled. Say so rather than silently showing the grid.
    countEl.textContent = 'That card has sold — here\'s everything else in stock.';
    return false;
  }
  if (!IDX.has(card)) IDX.set(card, IDX.size);
  openLightbox(card);
  return true;
}

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
  close: document.getElementById('lb-close'),
  share: document.getElementById('lb-send')
};
let lbCard = null, lbAt = 0;

// The caption title is wired once. openLightbox only refreshes the text and
// the data attribute, so there is no handler stacking up per open.
if (lb.title) lb.title.addEventListener('click', () => copyTitle(lb.title));
if (lb.share) lb.share.addEventListener('click', () =>
  shareListing(lb.share.dataset.shareUrl, lb.share.dataset.shareTitle, lb.share));

function openLightbox(card, at = 0) {
  lbCard = card; lbAt = at;
  lb.title.textContent = card.title;
  lb.title.dataset.title = card.title;
  lb.title.classList.remove('copy-title--done');
  lb.buy.href = card.buy || card.url;
  // Same swap as the grid: a Personal Collection card asks, it doesn't sell.
  // mailto: in a new tab just leaves an empty tab behind, hence no target.
  lb.buy.textContent = card.personal ? 'Ask About This Card' : 'Buy Now';
  if (card.personal) lb.buy.removeAttribute('target'); else lb.buy.target = '_blank';
  if (lb.share) {
    lb.share.dataset.shareUrl = card.url;
    lb.share.dataset.shareTitle = card.title;
  }
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
clearBtn.addEventListener('click', () => { input.value = ''; ACTIVE.clear(); MAX_PRICE = 0; document.getElementById('price-chip')?.remove(); applySearch(); input.focus(); });
input.disabled = true;
loadInventory();
