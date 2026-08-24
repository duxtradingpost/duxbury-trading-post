# Shopify theme customizations

Code pasted manually into the Shopify **Drive** theme, in
`layout/theme.liquid`, immediately before the closing `</body>` tag.

Shopify theme edits are not version-controlled, so keep copies here — a theme
update, theme switch, or reset will wipe them.

Nothing in this folder is deployed to the website. Only `public/` is served
(see `wrangler.jsonc`).

**To reinstall:** Online Store → Themes → (Drive, Active) → ... → Edit code →
`layout/theme.liquid` → paste before `</body>` → **Save**.
Watch for the unsaved-changes dot (●) on the file tab, and confirm you are in
the Drive theme, not the Radiant draft.

## product-share-button.html

Adds a "Share this card" button below "Buy it now" on every product page.
Native share sheet (Messages, Instagram, Mail) on mobile; copy-link fallback
on desktop.

Anchored to `.buy-buttons-block`, which appears exactly once on product pages
and nowhere else, so it doubles as the product-page gate.

## product-title-copy.html

Makes the product title on every product page click-to-copy. Checking comps
means pasting an exact card title into eBay or 130point, and hand-selecting
60 characters is the fiddliest part of that.

Gated on `.buy-buttons-block` like the share button, so it never fires on a
collection or cart page that happens to have an h1. Falls back to selecting the
text where the clipboard API is unavailable.

## home-links-to-main-site.html

Points Shopify navigation back at duxburytradingpost.com so customers are never
dropped on the bare Shopify storefront:

| Shopify link | Goes to |
| --- | --- |
| Header logo | duxburytradingpost.com |
| "Home" (desktop nav + mobile drawer) | duxburytradingpost.com |
| Footer copyright link | duxburytradingpost.com |
| "Contact" (desktop nav + mobile drawer) | duxburytradingpost.com#contact |

"Catalog" is deliberately left alone — that's the inventory customers should reach.

Both scripts re-apply themselves via MutationObserver, because this theme
re-renders on soft navigation and would otherwise undo the changes.
