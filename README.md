# Duxbury Trading Post — Website

Static site (no build tools needed). Just open `index.html` in a browser, or deploy the whole folder as-is.

## What's already wired up

- **eBay live listings** — pulls your active listings from `https://www.ebay.com/sch/i.html?_ssn=duxburytradingpost&_rss=1` and shows them under "Live on eBay". Updates automatically, no maintenance needed. If your eBay seller ID changes, update `EBAY_SELLER_ID` in `js/main.js`.
- **Instagram / Facebook links** — pointed at `instagram.com/duxburytradingpost` and `facebook.com/duxburytradingpost`. Update the URLs in `index.html` (search for `social-links`) if those aren't your exact handles.
- **Phone / email / address** — pulled from your promo flyer (781-217-2728, info@duxburytradingpost.com, Duxbury, MA). Update in the Contact section of `index.html` if anything's off.

## What you still need to do

### 1. Connect the contact form (Formspree)
1. Go to [formspree.io](https://formspree.io) and create a free account.
2. Create a new form, get your form ID (looks like `xayzabcd`).
3. In `index.html`, find:
   ```html
   <form class="contact-form" id="contact-form" action="https://formspree.io/f/REPLACE_WITH_YOUR_FORM_ID" method="POST">
   ```
   Replace `REPLACE_WITH_YOUR_FORM_ID` with your real form ID.

Until you do this, the form will show a friendly "not connected yet" message instead of failing silently.

### 2. Connect real products for direct checkout (Stripe)
1. Create a [Stripe](https://stripe.com) account (free, pay-per-transaction).
2. In the Stripe Dashboard, go to **Payment Links** → create one per item you want to sell directly (set the price, add a product photo).
3. Copy each Payment Link URL.
4. In `index.html`, find the `product-grid` section (4 example cards) and for each one:
   - Replace the placeholder title/price with your real item.
   - Replace `REPLACE_WITH_STRIPE_PAYMENT_LINK` in `data-stripe-link="..."` with your real Payment Link.
   - Swap the emoji placeholder image (`<div class="product-image placeholder">🏀</div>`) for a real photo: `<img src="images/your-photo.jpg" alt="...">` and drop the photo in the `images/` folder.
5. Duplicate a `<div class="product-card">...</div>` block to add more items.

Until you connect real links, clicking "Buy Now" shows a friendly reminder instead of a broken checkout.

### 3. Deploy the site
Any static host works. Two easy free options:

**Cloudflare Pages** (recommended, works well with your domain if it's on Cloudflare):
1. Push this folder to a GitHub repo.
2. In the Cloudflare dashboard → Pages → connect the repo → deploy (no build command needed, output directory is `/`).
3. Add `duxburytradingpost.com` as a custom domain in the Pages project settings.

**Netlify**:
1. Drag and drop this folder into [app.netlify.com/drop](https://app.netlify.com/drop) for instant deploy, or connect a GitHub repo for ongoing updates.
2. Add your domain under Site settings → Domain management.

Either way, point your domain's DNS at the host following their instructions (usually a CNAME or nameserver change).

## File structure

```
duxbury-trading-post/
├── index.html          # all page content/sections
├── css/styles.css       # styling, brand colors, responsive layout
├── js/main.js           # eBay feed, contact form, buy buttons, mobile nav
├── images/
│   ├── logo.png          # your DTP logo
│   └── promo-card.jpeg   # "We Buy Sports & Trading Cards" flyer image
└── README.md
```

## Brand colors used
- Forest green: `#0F3C1F` (sampled from your logo)
- Cream: `#F7F4EB` (sampled from your flyer background)
