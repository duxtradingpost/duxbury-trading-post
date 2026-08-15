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

The order matters. Skipping step 2 creates a duplicate Shopify product later.

1. Create the product in Shopify: title, **SKU** (own convention, e.g.
   `DTP-2025-PRIZM-MAYE-329`), image, **inventory 0**, track quantity ON,
   "continue selling when out of stock" OFF
2. **InfoShore → Shopify Products → Fetch Shopify Products** — registers the
   product with the app so it can be mapped
3. Add it to the **Coming Soon** collection
4. When ready to sell: list on eBay with the **same title and same SKU**
5. InfoShore links the eBay item to the existing Shopify product and updates it
6. Remove it from the Coming Soon collection

InfoShore does not match on SKU alone — it maintains its own eBay-item ↔
Shopify-product mapping, which is why the Fetch step is required.

## When a card sells

- **eBay sale** — inventory zeroes automatically; Shopify order self-fulfills
  hourly; the site shows a SOLD badge for 3 days
- **Private/local sale** — set Shopify inventory to 0 by hand. That ends the
  eBay listing automatically. Self-report MA sales tax; no platform collects it.
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
