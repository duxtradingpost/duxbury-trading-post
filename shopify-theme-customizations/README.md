# Shopify theme customizations

Code pasted manually into the Shopify **Drive** theme. Shopify theme edits are not
version-controlled, so keep copies here — a theme update or reset will wipe them.

Nothing in this folder is deployed to the website. Only `public/` is served
(see `wrangler.jsonc`).

## product-share-button.html

Adds a "Share this card" button below "Buy it now" on every product page.
Native share sheet (Messages, Instagram, Mail) on mobile; copy-link fallback on desktop.

**Where it lives:** `layout/theme.liquid`, immediately before the closing `</body>` tag.

**To reinstall:** Online Store → Themes → (Drive, Active) → ... → Edit code →
`layout/theme.liquid` → paste before `</body>` → Save.

Anchored to `.buy-buttons-block`, which appears exactly once on product pages and
nowhere else, so it doubles as the product-page gate.
