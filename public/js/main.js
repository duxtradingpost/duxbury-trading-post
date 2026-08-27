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
// Everything for sale. An automated Shopify collection (price > 0, excluding
// Coming Soon), so unlisted cards can never leak into the Featured grid with a
// working Buy Now button.
const SHOP_ALL_COLLECTION_HANDLE = 'shop-all';
const MAX_FEATURED = 8;
const SOLD_WINDOW_DAYS = 3;   // how long a sold card stays up with a SOLD badge

async function loadFeaturedItems() {
  const grid = document.getElementById('product-grid');
  const status = document.getElementById('shop-status');

  const query = `
    fragment card on Product {
      title
      onlineStoreUrl
      handle
      availableForSale
      updatedAt
      images(first: 2) { edges { node { url altText width height } } }
      priceRange { minVariantPrice { amount currencyCode } }
    }
    query {
      featured: collectionByHandle(handle: "${FEATURED_COLLECTION_HANDLE}") {
        products(first: 24) { edges { node { ...card } } }
      }
      topPriced: collectionByHandle(handle: "${SHOP_ALL_COLLECTION_HANDLE}") {
        products(first: 24, sortKey: PRICE, reverse: true) { edges { node { ...card } } }
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

    // Top up with the priciest cards in stock so the grid is never sparse, skipping
    // anything already hand-picked. Empty the Featured collection and this becomes
    // fully automatic on its own.
    const seen = new Set(picked.map(({ node }) => node.handle));
    const filler = topPriced.filter(e => isAvailable(e) && !seen.has(e.node.handle));

    // Landscape (horizontal) photos go last so the grid stays visually consistent —
    // most card photos are portrait/square, and mixing in landscape ones mid-grid looks off.
    const isLandscape = ({ node: product }) => {
      const image = product.images.edges[0]?.node;
      return image && image.width > image.height;
    };

    // Reserve room for the sold cards so the grid never overflows MAX_FEATURED.
    const availableSlots = Math.max(0, MAX_FEATURED - pickedSold.length);
    const inStock = [...pickedAvailable, ...filler].slice(0, availableSlots);
    const sortedProducts = [
      ...inStock.filter(p => !isLandscape(p)),
      ...inStock.filter(isLandscape),
      ...pickedSold
    ];

    if (sortedProducts.length === 0) {
      status.textContent = 'No featured items right now — check back soon, or browse our full inventory.';
      return;
    }

    grid.innerHTML = '';
    sortedProducts.forEach(({ node: product }) => {
      const image = product.images.edges[0]?.node;
      // Second image is the card back, used for the hover flip.
      const back = product.images.edges[1]?.node?.url || '';
      const price = parseFloat(product.priceRange.minVariantPrice.amount).toFixed(2);
      const url = product.onlineStoreUrl || `https://${SHOPIFY_DOMAIN}/products/${product.handle}`;

      const sold = !product.availableForSale;

      const card = document.createElement('div');
      card.className = sold ? 'product-card product-card--sold' : 'product-card';
      card.innerHTML = `
        <div class="product-image-wrap${back ? ' has-back' : ''}">
          <a href="${url}" target="_blank" rel="noopener">
            <span class="card-flip">
              <img src="${image ? image.url : ''}" alt="${image?.altText || product.title}" class="product-image card-face card-face--front">
              ${back ? `<img src="${back}" alt="" class="card-face card-face--back" loading="lazy" aria-hidden="true">` : ''}
            </span>
          </a>
          ${sold ? '<span class="sold-badge">Sold</span>' : ''}
        </div>
        <h3><button type="button" class="copy-title" data-title="${product.title.replace(/"/g, '&quot;')}"
          title="Click to copy this title">${product.title}</button></h3>
        <p class="product-price">$${price}</p>
        <div class="product-actions">
          ${sold
            ? '<span class="btn btn-small btn-sold" aria-disabled="true">Sold</span>'
            : `<a href="${url}" target="_blank" rel="noopener" class="btn btn-primary btn-small">Buy Now</a>`}
          <button type="button" class="btn btn-outline btn-small share-btn" data-share-url="${url}" data-share-title="${product.title.replace(/"/g, '&quot;')}" aria-label="Share this listing">Share</button>
        </div>
      `;
      grid.appendChild(card);
    });

    grid.querySelectorAll('.share-btn').forEach(btn => {
      btn.addEventListener('click', () => shareListing(btn.dataset.shareUrl, btn.dataset.shareTitle, btn));
    });
  } catch (err) {
    status.textContent = 'Couldn\'t load featured items right now — browse our full inventory instead.';
    console.error('Shopify Featured Items error:', err);
  }
}

loadFeaturedItems();

// --- Coming Soon ---
// Cards that aren't listed yet: in transit, or in hand but not priced. Managed
// entirely from the "Coming Soon" collection in Shopify — add a product to show
// it here, remove it to take it down. No price is shown on purpose; the point is
// to collect offers rather than anchor a number before the card is researched.
//
// The whole section stays hidden unless the collection has products in it, so an
// empty collection looks like nothing rather than like something broken.
const COMING_SOON_HANDLE = 'coming-soon';

async function loadComingSoon() {
  const section = document.getElementById('coming-soon');
  const grid = document.getElementById('coming-soon-grid');
  if (!section || !grid) return;

  const query = `
    query {
      collectionByHandle(handle: "${COMING_SOON_HANDLE}") {
        products(first: 24) {
          edges {
            node {
              title
              handle
              images(first: 1) { edges { node { url altText width height } } }
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
    if (products.length === 0) return;   // leave the section hidden

    grid.innerHTML = '';
    products.forEach(({ node: product }) => {
      const image = product.images.edges[0]?.node;
      const subject = encodeURIComponent(`Offer: ${product.title}`);
      const body = encodeURIComponent(
        `Hi Duxbury Trading Post,\r\n\r\nI'd like to make an offer on:\r\n${product.title}\r\n\r\nMy offer: $\r\n\r\nThanks!`
      );

      const card = document.createElement('div');
      card.className = 'product-card product-card--soon';
      card.innerHTML = `
        <div class="product-image-wrap">
          <img src="${image ? image.url : ''}" alt="${image?.altText || product.title}" class="product-image">
          <span class="soon-badge">Coming Soon</span>
        </div>
        <h3><button type="button" class="copy-title" data-title="${product.title.replace(/"/g, '&quot;')}"
          title="Click to copy this title">${product.title}</button></h3>
        <div class="product-actions">
          <a href="mailto:info@duxburytradingpost.com?subject=${subject}&body=${body}" class="btn btn-primary btn-small">Make an Offer</a>
        </div>
      `;
      grid.appendChild(card);
    });

    section.hidden = false;
  } catch (err) {
    console.error('Coming Soon error:', err);   // stays hidden on failure
  }
}

loadComingSoon();

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
document.addEventListener('click', (e) => {
  if (!window.matchMedia('(hover: none)').matches) return;
  const wrap = e.target.closest('.product-image-wrap.has-back');
  if (!wrap || !e.target.closest('a')) return;
  e.preventDefault();
  wrap.classList.toggle('is-flipped');
});

// --- Copy a card title ------------------------------------------------------
// Titles in the grid are not links, so clicking one copies it. Checking comps
// means pasting an exact title into eBay or 130point, and selecting it by hand
// is the fiddliest part of that.
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.copy-title');
  if (!btn) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.title);
  } catch {
    const r = document.createRange();
    r.selectNodeContents(btn);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
    return;
  }
  btn.classList.add('copy-title--done');
  clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.classList.remove('copy-title--done'), 1400);
});
