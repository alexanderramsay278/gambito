// Stockfish 19 (WASM, lite, single-threaded) in a Web Worker. Serialised job queue.
// analyse(fen, {depth, multipv}) -> { best, lines: [{uci, cp (White POV, mate = +/-10000), mate, pv}] }
//
// Hosted (http/https): a normal Worker from lib/. Opened straight from disk (file://), browsers refuse
// Workers from file URLs and fetch() of the .wasm. So lib/sf-embed.js (built by site_build.py) carries
// the worker source plus the wasm as base64, and the worker starts from a blob: URL.
import { loadScript } from './load.js';

async function makeWorker() {
  if (location.protocol !== 'file:') return new Worker('lib/stockfish-19-lite-single.js');
  if (!window.SF_SRC) await loadScript('lib/sf-embed.js');
  const code = 'self.__SFW="data:application/wasm;base64,' + window.SF_WASM_B64 + '";\n' + window.SF_SRC;
  return new Worker(URL.createObjectURL(new Blob([code], { type: 'text/javascript' })));
}

export class Engine {
  constructor() {
    this.ok = true;
    this.listeners = new Set();
    this.waits = new Set();        // reject functions of pending waits, flushed if the engine dies
    this.q = Promise.resolve();
    this.ready = this._init();
    this.ready.catch(e => this._fail(e));
  }
  _fail(e) {
    this.ok = false; this.err = this.err || e;
    for (const rej of [...this.waits]) rej(this.err);
  }
  _send(c) { this.w.postMessage(c); }
  _wait(pred, ms = 30000) {
    return new Promise((res, rej) => {
      const done = () => { clearTimeout(t); this.listeners.delete(f); this.waits.delete(fail); };
      const fail = e => { done(); rej(e instanceof Error ? e : new Error('engine error')); };
      const f = l => { if (pred(l)) { done(); res(l); } };
      const t = setTimeout(() => fail(new Error('engine timeout')), ms);
      this.listeners.add(f); this.waits.add(fail);
    });
  }
  async _init() {
    this.w = await makeWorker();
    this.w.onmessage = e => { const line = typeof e.data === 'string' ? e.data : String(e.data); for (const f of [...this.listeners]) f(line); };
    this.w.onerror = e => this._fail(new Error('engine crashed: ' + ((e && e.message) || 'worker error')));
    this._send('uci'); await this._wait(l => l === 'uciok');
    this._send('setoption name Hash value 32');
    this._send('isready'); await this._wait(l => l === 'readyok');
  }
  analyse(fen, { depth = 12, multipv = 1 } = {}) {
    if (!this.ok) return Promise.reject(this.err || new Error('engine unavailable'));
    const job = this.q.then(() => this._run(fen, depth, multipv));
    this.q = job.catch(() => {});
    return job;
  }
  async _run(fen, depth, multipv) {
    await this.ready;
    const stm = fen.split(' ')[1];
    const lines = {};
    const f = l => {
      if (!l.startsWith('info') || l.indexOf(' pv ') < 0) return;
      const m = l.match(/ multipv (\d+)/), k = m ? +m[1] : 1;
      const d = +(l.match(/ depth (\d+)/) || [0, 0])[1];
      let cp = null, mate = null;
      const sc = l.match(/ score (cp|mate) (-?\d+)/); if (!sc) return;
      if (sc[1] === 'cp') cp = +sc[2]; else { mate = +sc[2]; cp = mate > 0 ? 10000 - mate : -10000 - mate; }
      if (stm === 'b') { cp = -cp; if (mate !== null) mate = -mate; }
      const pv = l.split(' pv ')[1].trim().split(' ');
      if (!lines[k] || d >= lines[k].d) lines[k] = { k, d, uci: pv[0], cp, mate, pv };
    };
    this.listeners.add(f);
    this._send('setoption name MultiPV value ' + multipv);
    this._send('position fen ' + fen);
    this._send('go depth ' + depth);
    let bm;
    try { bm = await this._wait(l => l.startsWith('bestmove'), 60000); }
    finally { this.listeners.delete(f); }
    const best = bm.split(' ')[1];
    return { best: best === '(none)' ? null : best, lines: Object.values(lines).sort((a, b) => a.k - b.k) };
  }
}

export const winp = cp => 1 / (1 + Math.exp(-0.00368208 * Math.max(-2000, Math.min(2000, cp))));
