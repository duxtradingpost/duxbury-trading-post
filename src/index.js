// duxtradingpost.com is a shorter alias registered to catch people who type it
// from memory. It should never serve the site itself — two domains with identical
// content splits search ranking — so everything 301s to the canonical domain.
//
// Worth knowing: assets are normally served before Worker code runs, which would
// bypass this entirely. `run_worker_first: true` in wrangler.jsonc is what makes
// this file see the request at all.

import { EmailMessage } from 'cloudflare:email';

const CANONICAL_HOST = 'duxburytradingpost.com';
const ALIAS_HOSTS = new Set(['duxtradingpost.com', 'www.duxtradingpost.com']);

const SELL_TO = 'info@duxburytradingpost.com';
const SELL_FROM = 'website@duxburytradingpost.com';

// The browser downscales photos before upload (see js/sell-form.js), so these
// ceilings are a backstop against someone posting to the endpoint directly
// rather than a limit real submissions will approach.
const MAX_FILES = 8;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;
const ALLOWED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/heic']);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (ALIAS_HOSTS.has(url.hostname)) {
      url.hostname = CANONICAL_HOST;
      // 301, not 302 — a permanent redirect passes search ranking to the
      // canonical domain. Path and query are preserved by reusing the URL.
      return Response.redirect(url.toString(), 301);
    }

    // The morning briefing posts itself here from the Mac. Guarded by a shared
    // secret set as a Worker secret — without it anyone could fill the inbox.
    if (url.pathname === '/api/briefing') {
      return request.method === 'POST'
        ? handleBriefing(request, env)
        : json({ ok: false, error: 'Method not allowed' }, 405);
    }

    if (url.pathname === '/api/sell') {
      return request.method === 'POST'
        ? handleSell(request, env)
        : json({ ok: false, error: 'Method not allowed' }, 405);
    }

    return env.ASSETS.fetch(request);
  }
};

async function handleBriefing(request, env) {
  // Constant-time-ish compare is overkill here, but a plain !== leaks length by
  // timing and costs nothing to avoid.
  const given = request.headers.get('X-DTP-Key') || '';
  const want = env.BRIEFING_KEY || '';
  if (!want || given.length !== want.length || given !== want) {
    return json({ ok: false, error: 'Not authorised' }, 401);
  }

  // Two shapes are accepted: a JSON body carrying both a text and an HTML part,
  // and a bare text/plain body. The plain form is what the script used to send
  // and is kept working so an older copy of it, or a curl from a terminal, is
  // still delivered rather than silently 400ing.
  const body = (await request.text()).slice(0, 400000);
  if (!body.trim()) return json({ ok: false, error: 'Empty briefing' }, 400);

  let text = body;
  let html = '';
  let subject = '';
  if ((request.headers.get('Content-Type') || '').includes('application/json')) {
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch {
      return json({ ok: false, error: 'Body was not valid JSON' }, 400);
    }
    text = String(parsed.text || '').slice(0, 60000);
    html = String(parsed.html || '').slice(0, 300000);
    subject = String(parsed.subject || '').slice(0, 120);
    if (!text.trim() && !html.trim()) {
      return json({ ok: false, error: 'Empty briefing' }, 400);
    }
  }

  // First line of the briefing carries the date; use it as the subject so the
  // inbox threads them sensibly rather than collapsing on an identical subject.
  if (!subject) subject = text.split('\n', 1)[0].trim().slice(0, 120);

  const raw = buildMime({
    from: SELL_FROM,
    fromName: 'Duxbury Trading Post',
    to: SELL_TO,
    replyTo: SELL_TO,
    subject: subject || 'DTP morning briefing',
    text,
    html,
    attachments: []
  });

  try {
    await env.SELL_EMAIL.send(new EmailMessage(SELL_FROM, SELL_TO, raw));
  } catch (err) {
    console.error('briefing send failed:', err && err.message);
    return json({ ok: false, error: 'Send failed' }, 502);
  }
  return json({ ok: true });
}

async function handleSell(request, env) {
  let form;
  try {
    form = await request.formData();
  } catch {
    return json({ ok: false, error: 'Could not read that submission.' }, 400);
  }

  // Bots fill in every field they find. This one is hidden from people, so
  // anything in it is automated — answer 200 so the bot believes it worked and
  // does not retry with a different shape.
  if ((form.get('company') || '').toString().trim()) {
    return json({ ok: true });
  }

  const name = clean(form.get('name'), 120);
  const email = clean(form.get('email'), 200);
  const phone = clean(form.get('phone'), 40);
  const details = clean(form.get('details'), 4000, true);

  if (!name || !email || !details) {
    return json({ ok: false, error: 'Please fill in your name, email and a description.' }, 400);
  }
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return json({ ok: false, error: 'That email address does not look right.' }, 400);
  }

  const photos = form.getAll('photos').filter(f => typeof f === 'object' && f.size > 0);
  if (photos.length > MAX_FILES) {
    return json({ ok: false, error: `Please send no more than ${MAX_FILES} photos.` }, 400);
  }
  let total = 0;
  for (const p of photos) {
    if (!ALLOWED_TYPES.has(p.type)) {
      return json({ ok: false, error: 'Photos need to be JPEG, PNG or WebP.' }, 400);
    }
    total += p.size;
  }
  if (total > MAX_TOTAL_BYTES) {
    return json({ ok: false, error: 'Those photos are too large. Try sending fewer at a time.' }, 400);
  }

  const attachments = [];
  for (let i = 0; i < photos.length; i++) {
    const p = photos[i];
    attachments.push({
      filename: safeName(p.name, i, p.type),
      type: p.type,
      data: base64(new Uint8Array(await p.arrayBuffer()))
    });
  }

  const body =
    `New sell-to-us submission from the website.\n\n` +
    `Name:   ${name}\n` +
    `Email:  ${email}\n` +
    `Phone:  ${phone || '(not given)'}\n` +
    `Photos: ${photos.length}\n\n` +
    `----- what they wrote -----\n\n${details}\n\n` +
    `---------------------------\n` +
    `Reply straight to this email — it goes back to ${email}.\n`;

  const raw = buildMime({
    from: SELL_FROM,
    fromName: 'Duxbury Trading Post website',
    to: SELL_TO,
    replyTo: email,
    subject: `Cards to sell — ${name}`,
    text: body,
    attachments
  });

  try {
    await env.SELL_EMAIL.send(new EmailMessage(SELL_FROM, SELL_TO, raw));
  } catch (err) {
    // Never lose a submission to a mail failure — tell them how to reach us
    // directly rather than showing a dead end.
    console.error('sell form send failed:', err && err.message);
    return json({
      ok: false,
      error: `Something went wrong sending that. Please email ${SELL_TO} directly and we'll pick it up.`
    }, 502);
  }

  return json({ ok: true });
}

// --- helpers ---------------------------------------------------------------

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }
  });

// Header injection: a newline in a field would let someone append their own
// headers to the message. Control characters are stripped and the value capped.
// The details field keeps its line breaks - it is body text, not a header.
const clean = (v, max, keepNewlines = false) => {
  const str = v == null ? '' : String(v);
  const stripped = keepNewlines
    ? str.replace(/[\x00-\x09\x0B\x0C\x0E-\x1F\x7F]/g, '')
    : str.replace(/[\x00-\x1F\x7F]/g, ' ');
  return stripped.trim().slice(0, max);
};

function safeName(name, i, type) {
  const ext = (type.split('/')[1] || 'jpg').replace('jpeg', 'jpg');
  const base = String(name || '').replace(/[^A-Za-z0-9._-]/g, '_').slice(0, 60);
  return base && /\.[A-Za-z0-9]+$/.test(base) ? base : `photo-${i + 1}.${ext}`;
}

function base64(bytes) {
  // Chunked so a large photo does not blow the argument limit on String.fromCharCode.
  let bin = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

// Hand-rolled rather than pulling in a MIME library — the Worker has no build
// step, and this is a fixed, simple shape: one text part plus base64 attachments.
// Headers are ASCII-only. A subject with an em dash in it — which every briefing
// subject has — must go out as an RFC 2047 encoded word or clients render mojibake.
function encodeHeader(value) {
  if (/^[\x20-\x7E]*$/.test(value)) return value;
  return `=?UTF-8?B?${base64(new TextEncoder().encode(value))}?=`;
}

function buildMime({ from, fromName, to, replyTo, subject, text, html, attachments }) {
  const stamp = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const outer = `dtp-mixed-${stamp}`;
  const inner = `dtp-alt-${stamp}`;

  const head = [
    `From: ${encodeHeader(fromName)} <${from}>`,
    `To: ${to}`,
    `Reply-To: ${replyTo}`,
    `Subject: ${encodeHeader(subject)}`,
    `Message-ID: <${outer}@${CANONICAL_HOST}>`,
    `Date: ${new Date().toUTCString()}`,
    'MIME-Version: 1.0',
    `Content-Type: multipart/mixed; boundary="${outer}"`,
    ''
  ].join('\r\n');

  // Both parts are base64'd. The HTML in particular has lines well past the
  // 998-character SMTP limit, and an over-long line is dropped or wrapped
  // mid-tag rather than rejected outright — which shows up as a broken layout
  // that is very hard to trace back to line length.
  const b64 = s => base64(new TextEncoder().encode(s)).replace(/(.{76})/g, '$1\r\n');

  const parts = [];

  if (html) {
    // multipart/alternative, least-preferred part first: a client picks the
    // last one it can render, so HTML has to come after plain text.
    parts.push(
      `--${outer}`,
      `Content-Type: multipart/alternative; boundary="${inner}"`,
      '',
      `--${inner}`,
      'Content-Type: text/plain; charset="utf-8"',
      'Content-Transfer-Encoding: base64',
      '',
      b64(text),
      `--${inner}`,
      'Content-Type: text/html; charset="utf-8"',
      'Content-Transfer-Encoding: base64',
      '',
      b64(html),
      `--${inner}--`
    );
  } else {
    parts.push(
      `--${outer}`,
      'Content-Type: text/plain; charset="utf-8"',
      'Content-Transfer-Encoding: base64',
      '',
      b64(text)
    );
  }

  for (const a of attachments) {
    parts.push(
      `--${outer}`,
      `Content-Type: ${a.type}; name="${a.filename}"`,
      `Content-Disposition: attachment; filename="${a.filename}"`,
      'Content-Transfer-Encoding: base64',
      '',
      // RFC 2045 caps encoded lines at 76 characters.
      a.data.replace(/(.{76})/g, '$1\r\n')
    );
  }
  parts.push(`--${outer}--`, '');

  return head + '\r\n' + parts.join('\r\n');
}
