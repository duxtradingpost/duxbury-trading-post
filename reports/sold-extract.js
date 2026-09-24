/* Paste into the console on an eBay SOLD search page (LH_Sold=1&LH_Complete=1).
   Copy the JSON it returns into sold.json, then:
       python3 reports/comp.py <itemid> --sold sold.json                     */
JSON.stringify([...document.querySelectorAll('li.s-item, li.s-card')].map(li=>{
  const t=(li.querySelector('.s-item__title, .s-card__title')?.innerText||'')
            .replace(/\n.*/s,'').replace(/^NEW LISTING/,'').trim();
  const a=li.innerText;
  return {t,
    p:parseFloat(((li.querySelector('.s-item__price, .s-card__price')?.innerText)||'').replace(/[^0-9.]/g,'')),
    d:(a.match(/Sold\s+(\w{3}\s+\d{1,2},\s+\d{4})/)||[])[1],
    b:(a.match(/(\d+)\s+bids?/)||[])[1]||'BIN'};
}).filter(r=>r.t&&r.d&&r.t!=='Shop on eBay'))
