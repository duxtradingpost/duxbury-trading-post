// Sell-to-us form.
//
// Photos are downscaled in the browser before they are sent. A phone camera
// produces 3-5 MB per shot, and six of those would exceed what an email can
// carry — but a card only needs enough resolution to read a serial number and
// judge corners. 1600px on the long edge at 82% JPEG does that in ~250 KB, and
// it makes the upload fast enough on a phone that people finish it.
//
// The form posts to /api/sell, which emails the shop inbox with the photos
// attached. Nothing is stored anywhere.

const MAX_PHOTOS = 8;
const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.82;
const MAX_TOTAL_BYTES = 8 * 1024 * 1024;

const form = document.getElementById('sell-form');
if (form) {
  const fileInput = form.querySelector('#sell-photos');
  const fileList = form.querySelector('#sell-file-list');
  const statusEl = form.querySelector('#sell-status');
  const submitBtn = form.querySelector('#sell-submit');

  let chosen = [];

  fileInput.addEventListener('change', () => {
    // Append rather than replace: on a phone the picker often only allows one
    // shot at a time, and replacing would silently discard the previous pick.
    for (const f of fileInput.files) {
      if (chosen.length >= MAX_PHOTOS) break;
      if (!f.type.startsWith('image/')) continue;
      chosen.push(f);
    }
    fileInput.value = '';
    paintFileList();
  });

  function paintFileList() {
    if (!chosen.length) {
      fileList.hidden = true;
      fileList.innerHTML = '';
      return;
    }
    fileList.hidden = false;
    fileList.innerHTML = chosen
      .map(
        (f, i) =>
          `<li><span>${escapeHtml(f.name)}</span>` +
          `<button type="button" data-i="${i}" aria-label="Remove ${escapeHtml(f.name)}">&times;</button></li>`
      )
      .join('');
    fileList.querySelectorAll('button').forEach(b =>
      b.addEventListener('click', () => {
        chosen.splice(Number(b.dataset.i), 1);
        paintFileList();
      })
    );
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    submitBtn.disabled = true;
    say('Preparing photos…');

    const data = new FormData();
    for (const field of ['name', 'email', 'phone', 'details', 'company']) {
      data.append(field, form.querySelector(`[name="${field}"]`)?.value || '');
    }

    let total = 0;
    try {
      for (let i = 0; i < chosen.length; i++) {
        say(`Preparing photo ${i + 1} of ${chosen.length}…`);
        const shrunk = await shrink(chosen[i]);
        total += shrunk.size;
        if (total > MAX_TOTAL_BYTES) {
          return fail('Those photos add up to more than we can email. Try sending fewer at a time.');
        }
        data.append('photos', shrunk, shrunk.name);
      }
    } catch (err) {
      // A HEIC or an image the browser cannot decode lands here. Send the
      // original and let the size check decide.
      console.warn('resize failed, sending originals:', err);
      data.delete('photos');
      for (const f of chosen) data.append('photos', f, f.name);
    }

    say('Sending…');
    try {
      const res = await fetch('/api/sell', { method: 'POST', body: data });
      const out = await res.json().catch(() => ({}));
      if (res.ok && out.ok) {
        form.querySelector('.sell-form-fields').hidden = true;
        say("Got it — we'll take a look and get back to you within a day or two.", 'ok');
        return;
      }
      return fail(out.error || 'Something went wrong. Please try again.');
    } catch {
      return fail('Could not reach us just now. Please try again, or email info@duxburytradingpost.com.');
    }
  });

  function say(msg, kind) {
    statusEl.textContent = msg;
    statusEl.className = 'sell-status' + (kind ? ` sell-status--${kind}` : '');
    statusEl.hidden = false;
  }
  function fail(msg) {
    say(msg, 'error');
    submitBtn.disabled = false;
  }
}

// Draw the image onto a canvas at a bounded size and re-encode as JPEG. Returns
// the original untouched if it is already small — re-encoding a small file
// usually makes it bigger, not smaller.
async function shrink(file) {
  if (file.size < 400 * 1024) return file;

  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  canvas.getContext('2d').drawImage(bitmap, 0, 0, w, h);
  bitmap.close?.();

  const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', JPEG_QUALITY));
  if (!blob || blob.size >= file.size) return file;

  const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
  return new File([blob], name, { type: 'image/jpeg' });
}

const escapeHtml = s =>
  String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));


// ---------------------------------------------------------------------------
// Card finder ("Find a Card"). Deliberately its own small handler rather than
// generalising the sell form above: that one is built around photo downscaling
// and a file list this form does not have, and bending it to serve both would
// have put the riskier path at risk for no gain. Same endpoint, kind=source, so
// the email lands labelled "Card wanted" and is never read as an offer to sell.
const findForm = document.getElementById('find-form');
if (findForm) {
  const findStatus = findForm.querySelector('#find-status');
  const findBtn = findForm.querySelector('#find-submit');

  const findSay = (msg, kind) => {
    findStatus.textContent = msg;
    findStatus.className = 'sell-status' + (kind ? ` sell-status--${kind}` : '');
    findStatus.hidden = false;
  };

  findForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = new FormData(findForm);
    data.append('kind', 'source');

    const name = (data.get('name') || '').toString().trim();
    const email = (data.get('email') || '').toString().trim();
    const details = (data.get('details') || '').toString().trim();
    if (!name || !email || !details) {
      return findSay('Please fill in your name, email and what you are looking for.', 'error');
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      return findSay('That email address does not look right.', 'error');
    }

    findBtn.disabled = true;
    findSay('Sending…');
    try {
      const res = await fetch('/api/sell', { method: 'POST', body: data });
      const out = await res.json().catch(() => ({}));
      if (res.ok && out.ok) {
        findForm.querySelector('.find-form-fields').hidden = true;
        return findSay("Got it — we'll start looking and come back to you within a day or two.", 'ok');
      }
      findBtn.disabled = false;
      return findSay(out.error || 'Something went wrong. Please try again.', 'error');
    } catch {
      findBtn.disabled = false;
      return findSay('Could not reach us just now. Please try again, or email info@duxburytradingpost.com.', 'error');
    }
  });
}
