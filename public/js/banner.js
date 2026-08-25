// Site-wide notice bars.
//
// Only the away notice lives here now. The DIRECT10 promo bar was removed on
// 2026-08-25; git history has the markup, CSS and dismissal logic if a future
// promo wants them back.

// --- Away / shipping delay notice --------------------------------------------
// Expires on its own. AWAY_UNTIL is the last day it should show; after that the
// bar never renders, so an out-of-date "I'm away" message cannot be left up by
// forgetting to remove it. To use it again, change the date and the copy in the
// HTML — nothing here needs touching.
const AWAY_UNTIL = '2026-08-28';   // inclusive; hides from the 29th

(function () {
  const bar = document.getElementById('away-bar');
  if (!bar) return;
  // Compare as local dates, not UTC — an ISO string parses as midnight UTC,
  // which is the previous evening here and would hide the bar a day early.
  const [y, m, d] = AWAY_UNTIL.split('-').map(Number);
  const lastDay = new Date(y, m - 1, d, 23, 59, 59);
  if (new Date() > lastDay) { bar.remove(); return; }
  bar.hidden = false;
})();
