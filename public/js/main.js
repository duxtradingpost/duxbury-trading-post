// Footer year
document.getElementById('year').textContent = new Date().getFullYear();

// Mobile nav toggle
const navToggle = document.getElementById('nav-toggle');
const mainNav = document.getElementById('main-nav');
navToggle.addEventListener('click', () => {
  const isOpen = mainNav.classList.toggle('open');
  navToggle.setAttribute('aria-expanded', isOpen);
});
mainNav.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => mainNav.classList.remove('open'));
});

// --- Shopify Featured Items (live) ---
// Runs itself. Anything in the Shopify "Featured" collection is shown first; the
// rest of the grid fills automatically with the highest-priced cards in stock, so
// the section is never empty and never needs maintenance. Cards that sell stay up
// with a SOLD badge for a few days, then drop off on their own.
//
// To spotlight something specific, add it to the "Featured" collection in Shopify.
// To go back to fully automatic, empty the collection. No code changes either way.
//
// Uses the public, read-only Storefront API token — safe to expose client-side.
const SHOPIFY_DOMAIN = 'duxburytradingpost.myshopify.com';
const SHOPIFY_STOREFRONT_TOKEN = '6e9ad9c0de82756dc160e72ea5d6c3c5';
const SHOPIFY_API_VERSION = '2025-10';
const FEATURED_COLLECTION_HANDLE = 'featured';
// Website prices undercut the eBay listing by this much. MUST MATCH
// WEBSITE_DISCOUNT in js/inventory.js and the live Shopify automatic discount
// "Website price - 12% off every card"
// gid://shopify/DiscountAutomaticNode/1394920390742
// Three places, one number. Change one without the others and the site quotes a
// price the checkout will not honour, or the two pages disagree with each other.
const WEBSITE_DISCOUNT = 0;   // was 0.12 - discount switched OFF 2026-09-21
const webPrice = list => (list * (1 - WEBSITE_DISCOUNT)).toFixed(2);

// See the long note in js/inventory.js: the 12% is applied at the CART, not on
// the product page, so Buy Now has to land on the cart or the shopper sees the
// undiscounted price straight after this grid promised the discounted one.
const buyUrl = (variantGid, productUrl) => {
  const id = String(variantGid || '').split('/').pop();
  return /^\d+$/.test(id) ? `https://${SHOPIFY_DOMAIN}/cart/${id}:1` : productUrl;
};
// Everything for sale. An automated Shopify collection (price > 0, excluding
// the Personal Collection), so cards that are not for sale can never leak into
// the Featured grid with a working Buy Now button.
const SHOP_ALL_COLLECTION_HANDLE = 'shop-all';

// Personal Collection cards can ALSO be listed on eBay, at a price Craig would
// take, and the eBay sync then drops them into Shop All with that price - so
// Shop All does NOT keep them out, whatever it was meant to do. On this site
// they never show a price or a Buy Now: they read "Personal Collection" and ask
// by email. Marker: membership in the Personal Collection (handle unchanged),
// or the `Personal` tag the report scripts use. Same rule in js/inventory.js
// and src/index.js.
const PERSONAL_COLLECTION_HANDLE = 'coming-soon';
const isPersonal = node => (node.tags || []).includes('Personal') ||
  (node.collections?.edges || []).some(e => e.node.handle === PERSONAL_COLLECTION_HANDLE);
const askUrl = title =>
  `mailto:info@duxburytradingpost.com?subject=${encodeURIComponent(`Question: ${title}`)}` +
  `&body=${encodeURIComponent(`Hi Duxbury Trading Post,\r\n\r\nI have a question about:\r\n${title}\r\n\r\nThanks!`)}`;
const MAX_FEATURED = 8;
const SOLD_WINDOW_DAYS = 3;   // how long a sold card stays up with a SOLD badge
// Most slots a hand-picked card can take. Raise it to lean on the Featured
// collection, lower it for more movement; at MAX_FEATURED the grid stops
// rotating whenever the collection is full.
const MAX_PICKED_PER_DAY = 3;

// --- Daily rotation ---------------------------------------------------------
// The grid used to be the eight priciest cards in stock. That is automatic but
// motionless: the same eight sit there until one sells, so a repeat visitor has
// no reason to look twice. The pool stays the priciest cards — the query asks
// for 24, sorted by price, so nothing from the bands that lose money can reach
// the front page — and the eight shown are drawn from that 24 in an order that
// turns over with the date.
//
// Seeded by the day, not random per load. Reshuffling on every load would move
// the grid under anyone who reloaded or came back from a listing, which reads
// as a glitch rather than as freshness. This way a visitor sees one stable grid
// all day and a different one tomorrow. Local midnight, so it turns over on the
// visitor's clock.
const dayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
};

// mulberry32 off an FNV-hashed seed. Math.random cannot be seeded, and this only
// has to be uneven, not unpredictable.
function seededRandom(seed) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return () => {
    h = (h + 0x6D2B79F5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Fisher-Yates on a copy, so the caller's array is left alone.
function shuffled(list, rand) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

async function loadFeaturedItems() {
  const grid = document.getElementById('product-grid');
  const status = document.getElementById('shop-status');
  if (!grid) return;   // collection.html shares this script but has no shop grid

  const query = `
    fragment card on Product {
      title
      onlineStoreUrl
      handle
      availableForSale
      updatedAt
      tags
      collections(first: 10) { edges { node { handle } } }
      images(first: 2) { edges { node { url altText width height } } }
      priceRange { minVariantPrice { amount currencyCode } }
      # Needed to build the cart permalink — see buyUrl().
      variants(first: 1) { edges { node { id } } }
    }
    query {
      featured: collectionByHandle(handle: "${FEATURED_COLLECTION_HANDLE}") {
        products(first: 24) { edges { node { ...card } } }
      }
      topPriced: collectionByHandle(handle: "${SHOP_ALL_COLLECTION_HANDLE}") {
        products(first: 24, sortKey: PRICE, reverse: true) { edges { node { ...card } } }
      }
      newest: collectionByHandle(handle: "${SHOP_ALL_COLLECTION_HANDLE}") {
        products(first: 24, sortKey: CREATED, reverse: true) { edges { node { ...card } } }
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
    const picked = data?.data?.featured?.products?.edges || [];   // hand-picked in Shopify
    const topPriced = data?.data?.topPriced?.products?.edges || [];  // automatic fallback

    // Cards are one-of-a-kind, so a sold item must never keep a working Buy Now
    // button. But a recent sale is good social proof, so we hold sold cards on
    // the page for a few days with a SOLD badge before they drop off.
    //
    // Shopify's Storefront API doesn't expose a sale date, so updatedAt stands in
    // for it — inventory hitting zero updates the product. Caveat: any edit to a
    // product also bumps updatedAt, so a bulk edit can make a sold card linger a
    // little longer than SOLD_WINDOW_DAYS. Harmless, just not exact.
    const soldCutoff = Date.now() - SOLD_WINDOW_DAYS * 24 * 60 * 60 * 1000;
    const isAvailable = ({ node }) => node.availableForSale;
    const soldRecently = ({ node }) =>
      !node.availableForSale && new Date(node.updatedAt).getTime() >= soldCutoff;

    const pickedAvailable = picked.filter(isAvailable);
    const pickedSold = picked.filter(soldRecently);

    // Hand-picked cards go first, but only MAX_PICKED_PER_DAY of them, drawn fresh
    // each day. Exempting them from the rotation entirely sounds respectful of the
    // choice and isn't: with seven in the collection and eight slots, the grid was
    // frozen solid and only one slot could ever turn over. Capping them means the
    // page still moves no matter how full that collection gets, and a pick that
    // waits a day is still seen far more often than a card in the general pool.
    //
    // Then top up with the priciest cards in stock so the grid is never sparse,
    // skipping anything hand-picked. Both lists are shuffled off the same daily
    // seed, so the whole grid turns over together.
    const rand = seededRandom(dayKey());
    const pickedToday = shuffled(pickedAvailable, rand).slice(0, MAX_PICKED_PER_DAY);

    const seen = new Set(picked.map(({ node }) => node.handle));
    const filler = shuffled(topPriced.filter(e => isAvailable(e) && !seen.has(e.node.handle)), rand);

    // Landscape (horizontal) photos go last so the grid stays visually consistent —
    // most card photos are portrait/square, and mixing in landscape ones mid-grid looks off.
    const isLandscape = ({ node: product }) => {
      const image = product.images.edges[0]?.node;
      return image && image.width > image.height;
    };

    // Reserve room for the sold cards so the grid never overflows MAX_FEATURED.
    const availableSlots = Math.max(0, MAX_FEATURED - pickedSold.length);
    // "Just Added": the newest cards in stock, so the section changes every time
    // something is listed. The hand-picked rotation above stays as the fallback
    // if the newest query comes back empty.
    const newest = (data?.data?.newest?.products?.edges || []).filter(isAvailable);
    const inStock = (newest.length ? newest : [...pickedToday, ...filler]).slice(0, availableSlots);
    const sortedProducts = [
      ...inStock.filter(p => !isLandscape(p)),
      ...inStock.filter(isLandscape),
      ...pickedSold
    ];

    if (sortedProducts.length === 0) {
      grid.innerHTML = '<p class="grid-status">No new cards right now — check back soon, or browse the full inventory.</p>';
      grid.removeAttribute('aria-busy');
      return;
    }

    grid.innerHTML = '';
    grid.removeAttribute('aria-busy');
    sortedProducts.forEach(({ node: product }) => {
      const image = product.images.edges[0]?.node;
      // Second image is the card back, used for the hover flip.
      const back = product.images.edges[1]?.node?.url || '';
      // `price` is the LIST price (what eBay and Shopify both show); `web` is what
      // this site actually charges after the automatic discount.
      const price = parseFloat(product.priceRange.minVariantPrice.amount).toFixed(2);
      const web = webPrice(parseFloat(product.priceRange.minVariantPrice.amount));
      const url = product.onlineStoreUrl || `https://${SHOPIFY_DOMAIN}/products/${product.handle}`;
      const buy = buyUrl(product.variants?.edges?.[0]?.node?.id, url);

      const sold = !product.availableForSale;
      const personal = isPersonal(product);
      const flip = `
            <span class="card-flip">
              <img src="${image ? image.url : ''}" alt="${image?.altText || product.title}" class="product-image card-face card-face--front">
              ${back ? `<img src="${back}" alt="" class="card-face card-face--back" loading="lazy" aria-hidden="true">` : ''}
            </span>`;

      const card = document.createElement('div');
      card.className = sold ? 'product-card product-card--sold' : 'product-card';
      // A Personal Collection card's photo must not link to the Shopify product
      // page either - that page would show the price.
      card.innerHTML = `
        <div class="product-image-wrap${back ? ' has-back' : ''}">
          ${personal ? flip : `<a href="${url}" target="_blank" rel="noopener">${flip}</a>`}
          ${sold ? '<span class="sold-badge">Sold</span>' : ''}
        </div>
        <h3><button type="button" class="copy-title" data-title="${product.title.replace(/"/g, '&quot;')}"
          title="Click to copy this title">${product.title}</button></h3>
        ${personal
          ? '<p class="product-price product-price--pc">Personal Collection</p>'
          : `<p class="product-price">
          $${web}
          ${WEBSITE_DISCOUNT > 0 ? `<span class="product-price__was">$${price}</span>
          <span class="product-price__off">${Math.round(WEBSITE_DISCOUNT * 100)}% off</span>` : ''}
        </p>`}
        <div class="product-actions">
          ${sold
            ? '<span class="btn btn-small btn-sold" aria-disabled="true">Sold</span>'
            : personal
              ? `<a href="${askUrl(product.title)}" class="btn btn-primary btn-small">Ask About This Card</a>`
              : `<a href="${buy}" target="_blank" rel="noopener" class="btn btn-primary btn-small">Buy Now</a>`}
          <button type="button" class="btn btn-outline btn-small card-send" data-share-url="https://duxburytradingpost.com/inventory?card=${encodeURIComponent(product.handle)}" data-share-title="${product.title.replace(/"/g, '&quot;')}" aria-label="Share this listing">Share</button>
        </div>
      `;
      grid.appendChild(card);
    });

    // Not "share-btn": content blockers hide that class. See js/inventory.js.
    grid.querySelectorAll('.card-send').forEach(btn => {
      btn.addEventListener('click', () => shareListing(btn.dataset.shareUrl, btn.dataset.shareTitle, btn));
    });
  } catch (err) {
    grid.innerHTML = '<p class="grid-status">Couldn\'t load the newest cards right now — browse the full inventory instead.</p>';
    grid.removeAttribute('aria-busy');
    console.error('Shopify Featured Items error:', err);
  }
}

loadFeaturedItems();

// --- Personal Collection ---
// Cards from the owner's own collection. Managed entirely from the "Personal
// Collection" collection in Shopify — add a product to show it here, remove it
// to take it down. No price is shown on purpose. Some ARE listed on eBay at a
// price Craig would take, so the card says "Personal Collection" rather than
// "Not For Sale", and the button asks rather than sells.
//
// The whole section stays hidden unless the collection has products in it, so an
// empty collection looks like nothing rather than like something broken.
// PERSONAL_COLLECTION_HANDLE is declared near the top, beside the other handles.

async function loadPersonalCollection() {
  const section = document.getElementById('coming-soon');
  const grid = document.getElementById('coming-soon-grid');
  if (!section || !grid) return;

  const query = `
    query {
      collectionByHandle(handle: "${PERSONAL_COLLECTION_HANDLE}") {
        products(first: 24) {
          edges {
            node {
              title
              handle
              tags
              images(first: 2) { edges { node { url altText width height } } }
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
    const products = data?.data?.collectionByHandle?.products?.edges || [];
    if (products.length === 0) {         // homepage: stays hidden; own page: say so
      if (!section.hidden) grid.innerHTML = '<p class="grid-status">Nothing here yet — check back soon.</p>';
      return;
    }

    grid.innerHTML = '';
    products.forEach(({ node: product }) => {
      const image = product.images.edges[0]?.node;
      // Second image is the card back, same convention as the Featured grid.
      const back = product.images.edges[1]?.node?.url || '';
      // Cards away for grading carry an "At PSA" tag in Shopify. Tag it when the
      // card goes out, untag it when it comes back — no code change either way.
      const atPsa = (product.tags || []).includes('At PSA');

      const card = document.createElement('div');
      card.className = 'product-card product-card--soon';
      card.innerHTML = `
        <div class="product-image-wrap${back ? ' has-back' : ''}">
          <span class="card-flip">
            <img src="${image ? image.url : ''}" alt="${image?.altText || product.title}" class="product-image card-face card-face--front">
            ${back ? `<img src="${back}" alt="" class="card-face card-face--back" loading="lazy" aria-hidden="true">` : ''}
          </span>
        </div>
        <h3><button type="button" class="copy-title" data-title="${product.title.replace(/"/g, '&quot;')}"
          title="Click to copy this title">${product.title}</button></h3>
        <p class="product-price product-price--pc">Personal Collection</p>
        ${atPsa ? '<p class="pc-note">Out for grading at PSA</p>' : ''}
        <div class="product-actions">
          <a href="${askUrl(product.title)}" class="btn btn-primary btn-small">Ask About This Card</a>
        </div>
      `;
      grid.appendChild(card);
    });

    section.hidden = false;
  } catch (err) {
    console.error('Personal Collection error:', err);   // stays hidden on failure
  }
}

loadPersonalCollection();

// Shares a listing link — uses the native share sheet on mobile/supporting browsers,
// falls back to copying the link to the clipboard with a brief confirmation.
async function shareListing(url, title, btn) {
  if (navigator.share) {
    try {
      await navigator.share({ title, url });
    } catch (err) {
      // User cancelled the share sheet — not an error, do nothing.
    }
    return;
  }

  try {
    await navigator.clipboard.writeText(url);
    const original = btn.textContent;
    btn.textContent = 'Link copied!';
    setTimeout(() => { btn.textContent = original; }, 2000);
  } catch (err) {
    console.error('Copy to clipboard failed:', err);
  }
}


// --- Tap to flip -------------------------------------------------------------
// On a desktop the back of the card shows on hover. A phone has no hover, so
// that same tap used to open the eBay/Shopify listing in a new tab — you lost
// the page to see the back of a card. Here the tap turns it over instead, and
// tapping again turns it back; Buy Now, directly underneath, is how you get to
// the listing. Long-press still offers "Open in new tab", and cards with no
// second image are untouched — .has-back is only set when there is a back.
//
// Delegated from the document so it covers cards rendered after load, and
// re-checked per click because a hybrid device can gain or lose a mouse.
//
// Only a tap that would otherwise navigate needs stopping. Personal Collection
// cards have no link on the image — they are not listings — so there the tap
// turns the card with nothing to prevent.
document.addEventListener('click', (e) => {
  if (!window.matchMedia('(hover: none)').matches) return;
  const wrap = e.target.closest('.product-image-wrap.has-back');
  if (!wrap) return;
  if (e.target.closest('a')) e.preventDefault();
  wrap.classList.toggle('is-flipped');
});

// --- Copy a card title ------------------------------------------------------
// Titles in the grid are not links, so clicking one copies it. Checking comps
// means pasting an exact title into eBay or 130point, and selecting it by hand
// is the fiddliest part of that.
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

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.copy-title');
  if (!btn) return;
  if (!(await copyText(btn.dataset.title))) return copyFailed(btn);
  btn.classList.remove('copy-title--manual');
  btn.classList.add('copy-title--done');
  clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.classList.remove('copy-title--done'), 1400);
});

// --- Section reveal ---------------------------------------------------------
// Homepage sections settle in as they scroll into view. First added 2026-08-20
// (c88c10c) and lost by accident when the contact form was removed (51ac7bb) -
// the CSS stayed, the script went, so nothing ever animated. Restored here.
//
// The .reveal class is added from JS on purpose: if this script never runs, or
// the browser has no IntersectionObserver, nothing is ever hidden. The hero is
// skipped - it is above the fold, so fading it in would look like a slow page.
(function () {
  if (!('IntersectionObserver' in window)) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const sections = [...document.querySelectorAll('body > section')]
    .filter(el => !el.classList.contains('hero'));
  if (!sections.length) return;
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-in');
      io.unobserve(entry.target);   // once revealed, it stays revealed
    });
  }, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });
  sections.forEach(el => { el.classList.add('reveal'); io.observe(el); });
})();
