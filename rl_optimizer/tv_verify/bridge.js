// Bridge every wss:// the page opens through a Node ws client tunnelled via the agent proxy (CONNECT).
// installRestFix additionally serves the Pine-facade REST calls whose path holds a ';' (script ids look
// like USER;<hash>) through the same tunnel: the agent proxy rejects those paths from Chromium with
// "request rejected: path contains matrix parameter separator", which leaves the strategy on the chart
// with "Error: cannot compile script".
const net = require('net'), tls = require('tls'), https = require('https'), fs = require('fs'); const WebSocket = require('ws');
const u = new URL(process.env.HTTPS_PROXY);
const UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
function tunnel(host, port) {
  return new Promise((resolve, reject) => {
    const sock = net.connect(+u.port, u.hostname, () => sock.write(`CONNECT ${host}:${port} HTTP/1.1\r\nHost: ${host}:${port}\r\n\r\n`));
    sock.once('data', d => { if (!/ 200 /.test(String(d).split('\r\n')[0])) return reject(new Error('CONNECT ' + String(d).split('\r\n')[0]));
      const t = tls.connect({ socket: sock, servername: host, ca: fs.readFileSync('/root/.ccr/ca-bundle.crt'), ALPNProtocols: ['http/1.1'] }, () => resolve(t)); t.on('error', reject); });
    sock.on('error', reject);
  });
}
async function install(page, log = () => {}) {
  await page.routeWebSocket(/^wss:\/\//, async route => {
    const url = new URL(route.url());
    let upstream;
    try {
      const t = await tunnel(url.hostname, 443);
      upstream = new WebSocket(route.url(), { createConnection: () => t, origin: 'https://www.tradingview.com', headers: { 'User-Agent': UA } });
    } catch (e) { log('bridge fail ' + url.hostname + ' ' + e.message); route.close({ code: 1006 }); return; }
    const q = [];
    upstream.on('open', () => { log('bridge open ' + url.hostname); for (const m of q) upstream.send(m); q.length = 0; });
    upstream.on('message', (m, isBinary) => route.send(isBinary ? m : m.toString()));
    upstream.on('close', (c, r) => route.close({ code: c >= 1000 && c < 5000 ? c : 1000, reason: String(r || '') }));
    upstream.on('error', e => { log('bridge err ' + url.hostname + ' ' + e.message); });
    upstream.on('unexpected-response', (_, r) => { log('bridge unexpected ' + url.hostname + ' ' + r.statusCode); route.close({ code: 1006 }); });
    route.onMessage(m => { if (upstream.readyState === WebSocket.OPEN) upstream.send(m); else q.push(m); });
    route.onClose(() => { try { upstream.close(); } catch (_) {} });
  });
}
async function installRestFix(page, log = () => {}) {
  await page.route(/^https:\/\/pine-facade\.tradingview\.com\/.*(%3B|;)/i, async route => {
    const r = route.request(); const url = new URL(r.url());
    try {
      const t = await tunnel(url.hostname, 443);
      const headers = Object.assign({}, r.headers()); delete headers['content-length']; delete headers.connection; headers.host = url.hostname; headers['accept-encoding'] = 'identity';
      const body = r.postDataBuffer();
      const res = await new Promise((resolve, reject) => {
        const rq = https.request({ createConnection: () => t, host: url.hostname, path: url.pathname + url.search, method: r.method(), headers, agent: false }, resp => {
          const chunks = []; resp.on('data', c => chunks.push(c)); resp.on('end', () => resolve({ status: resp.statusCode, headers: resp.headers, body: Buffer.concat(chunks) })); });
        rq.on('error', reject); if (body) rq.write(body); rq.end();
      });
      const h = {}; for (const [k, v] of Object.entries(res.headers)) if (!/^(transfer-encoding|connection|content-encoding|set-cookie)$/i.test(k)) h[k] = String(v);
      h['content-length'] = String(res.body.length);
      log('rest via tunnel ' + r.method() + ' ' + url.pathname.slice(0, 70) + ' -> ' + res.status);
      await route.fulfill({ status: res.status, headers: h, body: res.body });
    } catch (e) { log('rest fix fail ' + url.pathname.slice(0, 70) + ' ' + e.message); await route.abort().catch(() => {}); }
  });
}
module.exports = { install, installRestFix, UA };
