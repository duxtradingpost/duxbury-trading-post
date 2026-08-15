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
const QUICK_FILTERS = ['Football', 'Baseball', 'Basketball', 'Auto', 'Graded', 'Numbered', 'Rookie'];

const grid = document.getElementById('inv-grid');
const status = document.getElementById('inv-status');
const input = document.getElementById('inv-search');
const clearBtn = document.getElementById('inv-clear');
const countEl = document.getElementById('inv-count');
const chipWrap = document.getElementById('quick-filters');

let CARDS = [];

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
              availableForSale
              images(first: 1) { edges { node { url altText } } }
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
        const image = node.images.edges[0]?.node;
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
          tags: node.tags,
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
    .map(f => `<button type="button" class="chip" data-term="${f}">${f}</button>`)
    .join('');
  chipWrap.hidden = false;
  chipWrap.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const term = btn.dataset.term;
      // Clicking the active chip clears it, so chips toggle rather than trap you.
      input.value = input.value.trim().toLowerCase() === term.toLowerCase() ? '' : term;
      applySearch();
      input.focus();
    });
  });
}

// Every whitespace-separated word must appear somewhere in the card, so
// "allen numbered" narrows rather than widening the way an OR match would.
function applySearch() {
  const q = input.value.trim().toLowerCase();
  clearBtn.hidden = !q;
  chipWrap.querySelectorAll('.chip').forEach(btn => {
    btn.classList.toggle('chip--on', btn.dataset.term.toLowerCase() === q);
  });
  if (!q) return render(CARDS);
  const words = q.split(/\s+/);
  render(CARDS.filter(c => words.every(w => c.haystack.includes(w))));
}

function render(list) {
  countEl.textContent = list.length === CARDS.length
    ? `${CARDS.length} cards in stock`
    : `${list.length} of ${CARDS.length} cards`;

  if (!list.length) {
    grid.innerHTML = '<p class="grid-status">No cards match that search. Try a player, team, or set name.</p>';
    return;
  }

  grid.innerHTML = list.map(c => `
    <div class="product-card">
      <div class="product-image-wrap">
        <a href="${c.url}" target="_blank" rel="noopener">
          <img src="${c.img}" alt="${escapeAttr(c.alt)}" class="product-image" loading="lazy">
        </a>
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
  `).join('');

  grid.querySelectorAll('.share-btn').forEach(btn => {
    btn.addEventListener('click', () => shareListing(btn.dataset.shareUrl, btn.dataset.shareTitle, btn));
  });
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

input.addEventListener('input', applySearch);
clearBtn.addEventListener('click', () => { input.value = ''; applySearch(); input.focus(); });
input.disabled = true;
loadInventory();
