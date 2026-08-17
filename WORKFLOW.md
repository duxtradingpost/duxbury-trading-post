# Duxbury Trading Post — operating workflow

Confirmed with InfoShore support Aug 2026. Keep this current; it's the thing
that stops duplicate products and double-sold cards.

## How the pieces connect

```
HeyStack  ──push──>  eBay  ──InfoShore──>  Shopify  ──>  duxburytradingpost.com
                       ^                      |
                       └────inventory sync────┘
```

- **eBay is the primary channel.** Product details, price, and inventory flow
  eBay → Shopify.
- **Inventory syncs both ways.** A Shopify sale reduces eBay quantity, and when
  it hits zero the eBay listing ends automatically.
- **Product import is manual.** New eBay listings sit in InfoShore →
  eBay Products until you select them and hit Import. There is no auto-import.
- **Shopify → eBay listing creation is manual too**, from the app's Shopify
  Products page. Nothing gets pushed up automatically.

## Per-batch routine

1. List on eBay via HeyStack
2. **InfoShore → eBay Products → Fetch → Import** (the step that's easy to forget)
3. Products → select all → **Include in sales channels** (Online Store, Headless,
   Shop, POS, Facebook & Instagram) — imports land on Online Store only
4. Tag by sport in Shopify (Football / Baseball / Basketball / Soccer)
5. Enter **Cost per item**
6. Set **Best Offer auto-decline** = the 20% floor
7. Log the purchase in `whatnot/purchase-log.xlsx`

## Coming Soon cards (not yet listed for sale)

A Coming Soon product is a **placeholder, not a draft listing**. The website
section only reads `title` and the first image — it never queries price, SKU, or
inventory. So don't build anything you'd want to keep.

**To add one:**

1. Shopify → Products → Add product — title and photo
2. Inventory 0
3. Add to the **Coming Soon** collection

**When it's ready to sell:**

1. **Delete** the Shopify placeholder
2. List on HeyStack like any other card, and let the normal
   eBay → InfoShore → Shopify import create the real product

Don't try to convert the placeholder into the real listing. InfoShore maps by
its own eBay-item ↔ Shopify-product table, and a relisted card gets a new eBay
item ID — so reusing a placeholder is how you end up with duplicate products.
The placeholder holds no cost, no SKU, and no sales history. Throwing it away
costs nothing.

## When a card sells

- **eBay sale** — inventory zeroes automatically; Shopify order self-fulfills
  hourly; the site shows a SOLD badge for 3 days
- **Private/local sale** — **end the eBay listing by hand FIRST, then zero
  Shopify.** Order matters: InfoShore's inventory sync runs on a schedule, not
  instantly, so a card zeroed in Shopify can stay buyable on eBay for an hour or
  more. That gap is how you end up selling the same card twice and taking a
  cancellation defect. Ending it manually is safe — Shopify is already at 0, so
  the sync has nothing to undo.
  Record the sale as **Orders → Create order → mark as paid (Cash/Other)**, which
  captures the revenue instead of leaving it only in the spreadsheet.
  Self-report MA sales tax; no platform collects it.
- **After the SOLD badge window** — archive the product. Sold one-of-ones
  otherwise accumulate in the catalog forever.

**Never set inventory to 0 unless the card is actually sold** — it ends the eBay
listing.

## Shipping

Pirate Ship is connected to both eBay and Shopify, so eBay sales appear twice.
**Ship the eBay row** — tracking has to reach the eBay buyer. A row that appears
only from Shopify is a genuine Shopify/Instagram sale.

Graded cards: USPS Ground Advantage, slab between cardboard in a bubble mailer.
eBay Standard Envelope is not allowed for graded cards. Put the **Order ID only**
on the label, never the card name.

## Pricing rules

- **Never below 20% margin.** Floor = `(cost + 0.40) / 0.6675` on eBay
  (13.25% + $0.40 fees). Private sales have no fees, so floor = `cost / 0.80`.
- **Comp before you bid and before you list.** eBay's Price Guide is built into
  every listing; 130point and Card Ladder for anything unusual.
- **List price comes from comps, not from cost.** The floor is a walk-away line,
  not an asking price.
- **Local premium is real, but only in person.** eBay is a national market —
  being in Patriots country doesn't reach an eBay buyer. It does at a show or a
  face-to-face handoff.
