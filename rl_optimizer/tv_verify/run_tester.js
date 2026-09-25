// Runs trend_core_wae_professional.pine in TradingView's Strategy Tester for each symbol, prints the report and
// writes tester_results.json plus screenshots next to this file.
// Needs: node >= 18, `npm i playwright@1.56 ws@8`, a Chromium binary, and a signed-in TradingView session supplied as
// cookies in TV_SESSIONID and TV_SESSIONID_SIGN (adding a script to a chart requires a login).
// Inside the Claude cloud container, set CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome; bridge.js
// tunnels the chart websockets and the ';' Pine-facade REST calls through the container's HTTPS proxy.
// The run works in a new chart layout named by TV_LAYOUT_NAME (default "tv_verify <date>") so the account's
// saved layouts are left alone; delete it from Manage layouts when done.
const { chromium } = require('playwright'); const { install, installRestFix, UA } = require('./bridge'); const fs = require('fs'); const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'trend_core_wae_professional.pine'), 'utf8');
const SYMBOLS = (process.env.TV_SYMBOLS || 'AMEX:SPY,NASDAQ:QQQ,NASDAQ:SMH,AMEX:IWM').split(',');
const LAYOUT = process.env.TV_LAYOUT_NAME || ('tv_verify ' + new Date().toISOString().slice(0, 10));
const STRATEGY = 'Trend-Core WAE Professional';
const t0 = Date.now(); const L = m => console.log(((Date.now() - t0) / 1000).toFixed(1) + 's ' + m);
const shot = (p, name) => p.screenshot({ path: path.join(__dirname, name) });
const bodyText = p => p.evaluate(() => document.body.innerText.replace(/[ \t]+/g, ' ').replace(/\n{2,}/g, '\n'));
const legend = p => p.evaluate(() => Array.from(document.querySelectorAll('[data-qa-id="legend-source-item"]')).map(e => { const s = e.querySelector('[data-qa-id="legend-source-item-status"]'); return [(e.innerText || '').split('\n')[0], s ? s.getAttribute('title') : null]; }));
const totalTrades = p => p.evaluate(() => (document.body.innerText.match(/(\d+)\nTotal trades/) || [])[1] || null);
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const grab = (text, label) => { const m = text.match(new RegExp(esc(label) + '\\n([^\\n]+)')); return m ? m[1] : null; };
async function clickText(p, text) { const l = p.getByText(text, { exact: true }).last(); if (await l.count()) { await l.click({ force: true }).catch(() => {}); await p.waitForTimeout(1500); return true; } return false; }
async function clickView(p, idx) { // report header view switch: 0 = overview, 1 = list of trades
  const b = await p.evaluate(i => { const bs = Array.from(document.querySelectorAll('button[class*="lightTabButton"]')).filter(x => x.getBoundingClientRect().width > 0 && x.getBoundingClientRect().y < 120); if (!bs[i]) return null; const r = bs[i].getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }, idx);
  if (!b) throw new Error('report view button ' + idx + ' not found'); await p.mouse.click(b.x, b.y); await p.waitForTimeout(2500);
}
function parseOverview(t) {
  const o = { total_pnl: grab(t, 'Total PnL'), max_drawdown: grab(t, 'Max drawdown'), profitable_trades: grab(t, 'Profitable trades'), profit_factor: grab(t, 'Profit factor'),
    gross_profit: grab(t, 'Gross profit'), gross_loss: grab(t, 'Gross loss'), commission_load: grab(t, 'Commission load'), expectancy: grab(t, 'Expectancy'),
    largest_profit: grab(t, 'Largest profit'), largest_loss: grab(t, 'Largest loss') };
  const m = t.match(/(\d+)\nTotal trades\nWinners\n(\d+) trades\n([\d.]+%)\nLosers\n(\d+) trades/); if (m) { o.total_trades = +m[1]; o.winners = +m[2]; o.losers = +m[4]; }
  o.pnl_by_signal = {}; const sig = t.match(/Profits and losses\nBy signals\nBy side\n([\s\S]*?)\nTrades analysis/);
  if (sig) { const re = /([^\n]+)\n([+−-][\d,.]+)\nUSD/g; let x; while ((x = re.exec(sig[1]))) o.pnl_by_signal[x[1]] = x[2]; }
  return o;
}
let PAGE = null;
(async () => {
  const launch = { args: ['--no-sandbox', '--disable-http2'] };
  if (process.env.CHROME) launch.executablePath = process.env.CHROME;
  if (process.env.HTTPS_PROXY) launch.proxy = { server: process.env.HTTPS_PROXY };
  const b = await chromium.launch(launch);
  const ctx = await b.newContext({ viewport: { width: 1800, height: 1100 }, userAgent: UA, locale: 'en-US', timezoneId: 'America/New_York' });
  if (process.env.TV_SESSIONID) {
    await ctx.addCookies([
      { name: 'sessionid', value: process.env.TV_SESSIONID, domain: '.tradingview.com', path: '/', secure: true, httpOnly: true },
      ...(process.env.TV_SESSIONID_SIGN ? [{ name: 'sessionid_sign', value: process.env.TV_SESSIONID_SIGN, domain: '.tradingview.com', path: '/', secure: true, httpOnly: true }] : []),
    ]);
  } else { L('WARNING: TV_SESSIONID not set; TradingView will ask to sign in when the script is added'); }
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'https://www.tradingview.com' });
  const p = await ctx.newPage(); PAGE = p;
  if (process.env.HTTPS_PROXY) { await install(p, L); await installRestFix(p, L); }
  await p.goto('https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(SYMBOLS[0]) + '&interval=D', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForTimeout(15000);
  const signed = await p.evaluate(() => !!(window.user && window.user.username));
  L('signed in: ' + signed);
  if (!signed) { await shot(p, 'signin_failed.png'); throw new Error('not signed in: check TV_SESSIONID / TV_SESSIONID_SIGN'); }
  // Clear whatever the last-used layout left open: a maximized bottom panel or the Pine Editor cover the header.
  const maxBtn = p.locator('[data-name="toggle-maximize-button"]');
  if (await maxBtn.count() && !/Maximize/.test((await maxBtn.getAttribute('aria-label')) || '')) { await maxBtn.click(); await p.waitForTimeout(1500); L('restored bottom panel'); }
  const closeEd = p.locator('#overlap-manager-root button[aria-label="Close"]');
  if (await closeEd.count()) { await closeEd.first().click().catch(() => {}); await p.waitForTimeout(1500); }
  // Work in a fresh layout so the account's saved layouts are not modified by the autosave.
  await p.click('[data-name="save-load-menu"]'); await p.waitForTimeout(1500);
  await clickText(p, 'Create new layout…');
  await p.locator('#overlap-manager-root input').first().fill(LAYOUT);
  const cb = p.locator('#overlap-manager-root input[type="checkbox"]').first(); if (await cb.count() && await cb.isChecked()) await cb.uncheck({ force: true }); // "Open in new tab"
  await p.locator('[data-qa-id="save-btn"]').click(); await p.waitForTimeout(12000);
  L('layout: ' + await p.title());
  // Paste the script into the Pine Editor and add it to the chart.
  await p.click('[data-name="pine-dialog-button"]'); await p.waitForTimeout(5000);
  await p.locator('#overlap-manager-root .monaco-editor .view-lines').first().click(); await p.keyboard.press('Control+A');
  await p.evaluate(s => navigator.clipboard.writeText(s), SRC); await p.keyboard.press('Control+V'); await p.waitForTimeout(3000);
  await p.locator('#overlap-manager-root button', { hasText: /^Add to chart$/ }).first().click(); L('added to chart');
  await p.waitForTimeout(40000);
  await p.locator('#overlap-manager-root button[aria-label="Close"]').first().click(); await p.waitForTimeout(2000);
  const lg = await legend(p); L('legend: ' + JSON.stringify(lg));
  const ours = lg.find(r => r[0].startsWith(STRATEGY));
  if (!ours || /error/i.test(ours[1] || '')) { await shot(p, 'add_failed.png'); throw new Error('strategy missing or in error: ' + JSON.stringify(lg)); }
  // Open and maximize the Strategy Tester.
  const tog = p.locator('[data-name="toggle-visibility-button"]');
  if (/Open/.test((await tog.getAttribute('aria-label')) || '')) { await tog.click(); await p.waitForTimeout(3000); }
  await p.click('[data-name="toggle-maximize-button"]'); await p.waitForTimeout(2500);
  const results = {};
  for (const [i, s] of SYMBOLS.entries()) {
    const tag = s.replace(':', '_');
    if (i > 0) {
      const prev = await totalTrades(p);
      await p.evaluate(x => window.TradingViewApi.activeChart().setSymbol(x), s);
      for (let k = 0; k < 40; k++) { await p.waitForTimeout(2000); const cur = await totalTrades(p); if (cur && cur !== prev) break; }
      await p.waitForTimeout(6000);
    }
    await clickView(p, 0); await clickText(p, 'Breakdown');
    const active = await legend(p); if (!active.some(r => r[0].startsWith(STRATEGY) && r[1] === 'Active strategy')) L('WARNING: ' + STRATEGY + ' is not the active strategy: ' + JSON.stringify(active));
    let text = await bodyText(p);
    const r = parseOverview(text);
    r.symbol_on_chart = await p.evaluate(() => window.TradingViewApi.activeChart().symbol());
    r.range = (text.match(/[A-Z][a-z]{2} \d{1,2}, \d{4} — [A-Z][a-z]{2} \d{1,2}, \d{4}/) || [null])[0];
    await shot(p, 'tester_' + tag + '.png');
    await clickText(p, 'Growth and decline'); text = await bodyText(p);
    r.max_drawdown_pct_of_initial_capital = grab(text, 'Max drawdown as % of initial capital');
    await clickView(p, 1); text = await bodyText(p);
    const ft = text.match(/1Long[\s\S]{0,40}?Exit\nEntry\n \n([^\n]+)\n([^\n]+)\n \n([^\n]+)\n([^\n]+)/);
    if (ft) r.first_trade = { entry_date: ft[2], entry_signal: ft[4], exit_date: ft[1], exit_signal: ft[3] };
    await shot(p, 'tester_' + tag + '_list_of_trades.png');
    await clickView(p, 0);
    results[s] = r; L('TESTER ' + s + ': ' + JSON.stringify(r));
  }
  fs.writeFileSync(path.join(__dirname, 'tester_results.json'), JSON.stringify(results, null, 1));
  L('wrote tester_results.json');
  await b.close();
})().catch(async e => { console.error('ERR', e.message); if (PAGE) await PAGE.screenshot({ path: path.join(__dirname, 'error.png') }).catch(() => {}); process.exit(1); });
