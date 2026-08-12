// duxtradingpost.com is a shorter alias registered to catch people who type it
// from memory. It should never serve the site itself — two domains with identical
// content splits search ranking — so everything 301s to the canonical domain.
//
// Worth knowing: assets are normally served before Worker code runs, which would
// bypass this entirely. `run_worker_first: true` in wrangler.jsonc is what makes
// this file see the request at all.

const CANONICAL_HOST = 'duxburytradingpost.com';
const ALIAS_HOSTS = new Set(['duxtradingpost.com', 'www.duxtradingpost.com']);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (ALIAS_HOSTS.has(url.hostname)) {
      url.hostname = CANONICAL_HOST;
      // 301, not 302 — a permanent redirect passes search ranking to the
      // canonical domain. Path and query are preserved by reusing the URL.
      return Response.redirect(url.toString(), 301);
    }

    return env.ASSETS.fetch(request);
  }
};
