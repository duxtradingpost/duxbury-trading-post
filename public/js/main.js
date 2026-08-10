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

// --- eBay live listings ---
// Pulls the public RSS feed for this seller's active listings and renders them as cards.
// Uses rss2json.com's free endpoint to convert RSS to JSON client-side (avoids CORS issues
// with fetching eBay's RSS feed directly from the browser). No API key required at low volume;
// see README if you outgrow the free tier.
const EBAY_SELLER_ID = 'duxburytradingpost';
const EBAY_RSS_URL = `https://www.ebay.com/sch/i.html?_ssn=${EBAY_SELLER_ID}&_rss=1`;
const RSS_TO_JSON_API = `https://api.rss2json.com/v1/api.json?rss_url=${encodeURIComponent(EBAY_RSS_URL)}`;
const MAX_EBAY_ITEMS = 8;

function extractImage(html) {
  const match = html && html.match(/<img[^>]+src="([^"]+)"/i);
  return match ? match[1] : null;
}

function extractPrice(html) {
  const match = html && html.match(/\$[\d,]+\.\d{2}/);
  return match ? match[0] : null;
}

async function loadEbayListings() {
  const grid = document.getElementById('ebay-grid');
  const status = document.getElementById('ebay-status');

  try {
    const res = await fetch(RSS_TO_JSON_API);
    const data = await res.json();

    if (data.status !== 'ok' || !data.items || data.items.length === 0) {
      status.textContent = 'No active listings found right now — check back soon, or visit the eBay store directly.';
      return;
    }

    const items = data.items.slice(0, MAX_EBAY_ITEMS);
    grid.innerHTML = '';

    items.forEach(item => {
      const image = extractImage(item.description) || item.thumbnail || 'images/logo.png';
      const price = extractPrice(item.description);

      const card = document.createElement('a');
      card.href = item.link;
      card.target = '_blank';
      card.rel = 'noopener';
      card.className = 'ebay-card';
      card.innerHTML = `
        <img src="${image}" alt="${item.title}" loading="lazy">
        <div class="ebay-card-body">
          <div class="ebay-card-title">${item.title}</div>
          ${price ? `<div class="ebay-card-price">${price}</div>` : ''}
        </div>
      `;
      grid.appendChild(card);
    });
  } catch (err) {
    status.textContent = 'Couldn\'t load live listings right now — visit the eBay store directly below.';
    console.error('eBay feed error:', err);
  }
}

loadEbayListings();

// --- Contact form (Formspree) ---
const contactForm = document.getElementById('contact-form');
const formStatus = document.getElementById('form-status');

contactForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const endpoint = contactForm.getAttribute('action');

  if (endpoint.includes('REPLACE_WITH_YOUR_FORM_ID')) {
    formStatus.textContent = 'Form not yet connected — set up Formspree and update the endpoint (see README).';
    return;
  }

  formStatus.textContent = 'Sending…';
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      body: new FormData(contactForm),
      headers: { 'Accept': 'application/json' }
    });
    if (res.ok) {
      formStatus.textContent = 'Thanks! We\'ll get back to you shortly.';
      contactForm.reset();
    } else {
      formStatus.textContent = 'Something went wrong — please email us directly at info@duxburytradingpost.com.';
    }
  } catch (err) {
    formStatus.textContent = 'Something went wrong — please email us directly at info@duxburytradingpost.com.';
  }
});
