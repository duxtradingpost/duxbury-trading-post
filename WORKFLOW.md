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
6. Set **Best Offer auto-decline** = **10% below ask**. Leave auto-accept blank.
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

### Never mark an order shipped without tracking

Buying a label is what marks something shipped. The manual "mark as shipped"
option lies to eBay, Shopify, and the buyer at the same time, and nothing
downstream catches it. A Jordan slab sat unmailed for three days in Aug 2026
while every system showed it in transit.

**Check Pirate Ship's Ship page every few days.** Anything reading *Ready to
Ship* that isn't in your hand about to go out is a package you owe someone. It
is the only screen in the stack that reports what physically moved.

### eBay Standard Envelope

- **$0.78**, trading cards only, and the limits are hard: **item + shipping ≤ $20**
  (combined orders ≤ $50), max 3 oz, **max 0.25" thick**, 6.125" × 11.5".
- Graded cards and anything in a magnetic case fail on thickness. Those go
  Ground Advantage.
- ESE is eBay-exclusive — Pirate Ship cannot sell it.
- No acceptance scan needed; it can go straight in the mailbox.

### Best Offer

**Auto-decline at 10% below ask on every listing. Auto-accept stays blank.**

Bulk-editable at Seller Hub -> Listings -> Actions -> Edit Best Offer. Best Offer
is not part of eBay business policies, so HeyStack does not inherit it — check
whether it has its own default, or set it per batch.

Auto-accept stays off because eBay takes the first qualifying offer without
telling you. The Burrow in Aug 2026 came in at $200 against a $250 ask; countering
at $235 landed $30.36 more than accepting would have. An auto-accept would have
taken the $200 silently.

**What the 10% rule does and does not do.** It kills lowball noise — the $35
offers on $66 cards — and that is worth the time it saves. It is not margin
protection: 78 listings were already below break-even at full ask in Aug 2026, and
a percentage floor cannot fix a price that is too low to start with. Check the
break-even before countering anything, not the auto-decline number.

### Shipping policy: set it before every HeyStack batch

HeyStack has one global shipping policy, not a per-listing rule, so whatever is
selected applies to everything in the batch. Two policies exist on eBay:

| Policy | Service | Use for |
|---|---|---|
| `Shipping (DTP)` | Ground Advantage | slabs, mags, anything over $19 |
| `Shipping (DTP)- ESE` | eBay Standard Envelope | raw cards at or under $19 |

**Set it in HeyStack -> eBay Marketplace Defaults before listing, and set it back
afterwards.** Leaving it on ESE and then listing a $300 card produces a listing
eBay will reject or that cannot ship at the quoted rate. Leaving it on Ground
Advantage costs $5.29 of postage on every cheap card that sells.

As of Aug 2026 there were 132 active listings under $19 on the Ground Advantage
policy — about $700 of avoidable postage. The switch is two clicks; forgetting
it is the expensive part.

### Printing 4x6 labels on the Rollo

Set the format **before buying the label** — it cannot be changed afterward.

1. Seller Hub → Orders → Purchase shipping label
2. **Switch to advanced shipping** (top right) — the basic view hides this
3. **Print format → Change → 4 x 6 Thermal Label** (defaults to 8.5 x 11)
4. Fix weight and dimensions — they default from the listing and are usually
   wrong. A slab in a bubble mailer is **5 oz, 9 x 6 x 1**. Underdeclaring
   invites a USPS adjustment fee.
5. Then buy.

Print dialog: ThermalPrinter, paper **4 x 6**, Auto Rotate on, **Scale 100%**
(the radio, not "Scale to Fit"). If it forces Scale to Fit at ~47%, eBay sent
an 8.5x11 PDF — crop it in Preview (⇧⌘A → rectangular select → ⌘K) and reprint.
Save the working settings as the macOS preset `Label 4x6`.

## Pricing rules

**The floor is a walk-away line, not an asking price.** List price comes from
comps. The catalog already averages ~44% margin at list; repricing everything
down to these floors would destroy roughly $600 of it. Floors exist to reject
bad buys and to catch listings that have drifted below the line.

### Margin floors by price band

| Band | Target | Floor formula |
|---|---|---|
| $1–20 | 40% | `(cost + 1.18) / 0.4675`  (use 1.08 if listing ≤ $10) |
| $20–100 | 20% | `(cost + 5.30) / 0.6675` |
| $100+ | 15% | `(cost + 5.30) / 0.7175` |

Bands are set by **sale price**. The $20 boundary is the ESE cap, so it marks a
real $4.12 jump in shipping cost, not an arbitrary line.

Constants: eBay fee 13.25%; per-order fee $0.30 at ≤$10, else $0.40; shipping
$0.78 under ESE, $4.90 Ground Advantage. Private/cash sales have no fees or
shipping, so the floor is just `cost / (1 − target)`.

### Max bid — the rule that actually prevents losses

Every loss in the catalog traces to what was paid, not what was asked. Enforce
the floor at purchase:

| Comp | Don't pay over |
|---|---|
| under $20 | `0.4675 × comp − 1.18` |
| $20–100 | `0.6675 × comp − 5.30` |
| $100+ | `0.7175 × comp − 5.30` |

$10 comp → $3.60.  $50 → $28.  $150 → $102.  $600 → $425.  $700 → $497.

### The $20–$24.75 dead zone

```
list $20.00  ->  net $16.17
list $21.00  ->  net $12.92   <- less than $20
list $24.75  ->  net $16.17   <- finally back to even
list $25.00  ->  net $16.39
```

Above $20 you lose ESE and the postage eats more than the price gain. **Never
price a card between $20.01 and $24.75.** Hold at $20 or go to $25+.

### When the floor is unreachable

If comps sit below the floor, raising the price doesn't recover money — it
converts the card into inventory that never sells. Work down in order:

1. **Market ≥ tier floor** → price at the tier floor
2. **Market between break-even and tier floor** → price at market, take the thin
   margin, move it.  Break-even = `(cost + ship + per) / 0.8675`
3. **Market < break-even** → hold or cut. Cutting recovers capital; holding
   returns nothing until the market moves.

Bulk-box cards can't be priced into profitability. Delist and bin them.

### Other

- **Comp before you bid and before you list.** eBay's Price Guide is built into
  every listing; 130point is free and shows accepted Best Offer prices;
  TCGplayer or PriceCharting for Pokémon.
- **Watch for junk in the comp data.** A $20 "poster" sale dragged the median on
  a $700 Downtown by nearly $100. Read the actual sold rows, not just the median.
- **Local premium is real, but only in person.** eBay is a national market —
  being in Patriots country doesn't reach an eBay buyer. It does at a show or a
  face-to-face handoff.

## What to list vs. what to bin

**List individually at $5 and up**, and only if you paid under about $2.25 for
it. Below that it goes in a bin — no listing, no SKU, no photo, no number.

| Comp value | Where it goes |
|---|---|
| $10+ | listed individually |
| $6–12 | $10 bin |
| $2–6 | $5 bin |
| under $2 | $1 bin |

Bin cards carry **no per-card record**. Their cost lives as a pool — one line per
bulk purchase — and is expensed as the bins sell through. At a shop they become
three generic SKUs: `BIN-1`, `BIN-5`, `BIN-10`, no quantity tracking.

Bins have no eBay fee, no label, no packing, no listing time, and they bring
people to the counter. A $0.10 card sold for $1 is a 10x on inventory that would
otherwise never move.

## Storing and finding cards

**Sort by how you retrieve, not by what the card is.** Filing by player or set
breaks down — 40+ Josh Allens, cards that belong in two categories, and every
purchase forces a re-file. Sequential filing only appends.

**Triage once, at intake**, right after comping: **≥ $10 → listing path,
< $10 → bin path.** Deferring creates a pile that has to be re-triaged later.

| Box | Contents | Protection | Key | Marking |
|---|---|---|---|---|
| Padded carry box | PSA/GAS slabs | slab | **cert number** | none — already printed |
| Padded carry box | raw $40+ in mags | one-touch + team bag | `M-001`+ | removable label, case top edge |
| 1100-ct boxes | raw under $40 | sleeve + toploader | `R-0001`+ | Sharpie, toploader top lip |
| Staging box | bought, not yet listed | sleeve | none — it's a queue | — |
| Row boxes ×3 | $1 / $5 / $10 bins | sleeve only | none | sport → team |

Rules:

- **Slabs use their cert number.** It's unique, permanent, machine-readable, and
  doubles as the authenticity record. Nothing adhesive ever touches a slab.
- **Number at listing time, not purchase time.** Unlisted cards don't need to be
  findable yet.
- **Never write on a card or a penny sleeve.** Sleeves get replaced and the
  number walks off with the trash. Never sticky notes — they shed under box
  pressure, and a card whose number fell off is worse than one never numbered.
- The number goes in Shopify's **Barcode** field. Not SKU (eBay/InfoShore manage
  it), not tags (the site's inventory search reads tags, so a location tag would
  surface in customer searches).
- **Never renumber.** When a card sells, pull it and leave the gap. New cards
  append: `R-0085`, `M-049`.
- Divider card every 50 in the R boxes. Slabs and mags file in ascending order,
  lowest at the front.
- **Release valve:** a listed card sitting 90 days with no watchers gets
  unlisted and demoted to a bin. Without this the numbered boxes fill with dead
  stock and the system slows every month.

**Mags:** buy them for **$100+ cards** or for thick cards that won't fit a 35pt
toploader. Cards already in mags stay there — the cost is sunk and the case
costs nothing operationally above $20, where ESE is off the table anyway. Pull a
card out of a mag only if it's **under $20**, where a mag turns a $0.78
shipment into $5.40.

## Payments

All business money moves through business accounts. Personal Venmo for shop
transactions violates Venmo's terms, risks a freeze, and commingles funds in a
way that undermines the LLC.

- **Local handoffs → cash.** No fee, instant, no dispute window.
- **Remote → Zelle** where the buyer will use it. No fee.
- **Venmo business profile** otherwise — 1.9% + $0.10 on payments received. Two
  dollars on a $100 sale, against eBay's ~$18.
- **Purchases go out through the business account too.** Free to send, and it
  keeps cost basis in the business record.

Payments to a business profile carry **buyer purchase protection**, so a buyer
can claw funds back on a not-received claim. Always ship tracked, keep the DM
thread, and never ship before payment clears.
