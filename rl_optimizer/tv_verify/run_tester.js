// Runs trend_core_wae_professional.pine in TradingView's Strategy Tester for each symbol and prints the tester panel.
// Needs: node >= 18, `npm i playwright ws`, a Chromium binary, and a signed-in TradingView session supplied as
// cookies in TV_SESSIONID and TV_SESSIONID_SIGN (adding a script to a chart requires a login).
// Inside the Claude cloud container, set CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome; bridge.js
// tunnels the chart websockets through the container's HTTPS proxy, which Chromium cannot do on its own.
const { chromium } = require('playwright'); const { install, UA } = require('./bridge'); const fs = require('fs'); const path = require('path');
const SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'trend_core_wae_professional.pine'), 'utf8');
const SYMBOLS = (process.env.TV_SYMBOLS || 'AMEX:SPY,NASDAQ:QQQ,NASDAQ:SMH,AMEX:IWM').split(',');
const t0 = Date.now(); const L = m => console.log(((Date.now() - t0) / 1000).toFixed(1) + 's ' + m);
async function testerText(p) {
  return await p.evaluate(() => {
    const c = Array.from(document.querySelectorAll('div')).filter(e => /Strategy Tester/.test(e.innerText || '') && e.innerText.length < 6000).sort((a, b) => a.innerText.length - b.innerText.length);
    const best = c.find(e => /Net profit|Total P&L|Profit factor|Total trades|closed trades/i.test(e.innerText));
    return best ? best.innerText.replace(/\s+/g, ' ') : 'NO-TESTER';
  });
}
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
  const p = await ctx.newPage();
  if (process.env.HTTPS_PROXY) await install(p, L);
  await p.goto('https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(SYMBOLS[0]) + '&interval=D', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForTimeout(12000);
  L('signed in: ' + await p.evaluate(() => !!document.querySelector('[data-name="header-user-menu-button"], .tv-header__user-menu-button--logged')));
  await p.click('[data-name="pine-dialog-button"]'); await p.waitForTimeout(6000);
  const ed = p.locator('.monaco-editor textarea.inputarea').first();
  await ed.click({ force: true }); await p.keyboard.press('Control+A');
  await p.evaluate(s => navigator.clipboard.writeText(s), SRC); await p.keyboard.press('Control+V'); await p.waitForTimeout(2000);
  await p.getByText('Add to chart', { exact: true }).first().click(); L('added to chart');
  await p.waitForTimeout(25000);
  await p.screenshot({ path: path.join(__dirname, 'tester_' + SYMBOLS[0].replace(':', '_') + '.png') });
  L('TESTER ' + SYMBOLS[0] + ': ' + await testerText(p));
  for (const s of SYMBOLS.slice(1)) {
    await p.click('#header-toolbar-symbol-search'); await p.waitForTimeout(1500);
    await p.keyboard.type(s); await p.waitForTimeout(2500); await p.keyboard.press('Enter');
    await p.waitForTimeout(25000);
    await p.screenshot({ path: path.join(__dirname, 'tester_' + s.replace(':', '_') + '.png') });
    L('TESTER ' + s + ': ' + await testerText(p));
  }
  await b.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
