// "Play it out": a full game vs a rival that plays like a real player of the chosen band.
//  - opening: samples moves from the band's real move frequencies (book)
//  - after the book: Stockfish MultiPV + the band's measured error profile (best/good/inaccuracy/mistake/blunder rates)
//  - your moves are graded live (book stats in the opening, Stockfish everywhere)
import { Chess } from '../../lib/chess.js';
import { Board } from './board.js';
import { winp } from './engine.js';
import { S, addXP, recordGame, recordActivity, streakNow, localDay } from './state.js';
import { celebrate } from './streak.js';
import { sound, confetti, modal, pct, esc, fmtEval, sanLabel } from './ui.js';
import { fenKey } from './lesson.js';

const $ = id => document.getElementById(id);
const CATS = [['best', 0, 0.02], ['good', 0.02, 0.05], ['inaccuracy', 0.05, 0.10], ['mistake', 0.10, 0.20], ['blunder', 0.20, 1.01]];
const VERDICT = { best: ['Best move!', 'best'], excellent: ['Excellent', 'best'], good: ['Good move', 'good'], inaccuracy: ['Inaccuracy', 'inacc'], mistake: ['Mistake', 'mistake'], blunder: ['Blunder', 'blunder'] };
const sleep = ms => new Promise(r => setTimeout(r, ms));
function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; [a[i], a[j]] = [a[j], a[i]]; } return a; }
const accOf = loss => Math.max(0, Math.min(100, 103.1668 * Math.exp(-0.04354 * loss * 100) - 3.1669));

function kingSq(c) { if (!c.inCheck()) return null; const t = c.turn(); for (const row of c.board()) for (const p of row) if (p && p.type === 'k' && p.color === t) return p.square; return null; }

export class Game {
  constructor(ctx, color, { start = [], onEnd, auto = false, botDelay = true, maxPlies = 0 } = {}) {
    this.maxPlies = maxPlies;
    this.ctx = ctx; this.band = ctx.band; this.engine = ctx.engine; this.color = color; this.onEnd = onEnd;
    this.auto = auto; this.botDelay = botDelay && !auto;
    this.c = new Chess(); this.graded = []; this.over = false; this.xp = 0; this.inBook = true;
    for (const u of start) { try { this.c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] || 'q' }); } catch (e) { break; } }
    this.board = new Board($('playBoard'), { orientation: color, legalFrom: sq => this.legalFrom(sq), onMove: (f, t, p) => this.onUserMove(f, t, p) });
    this.render(null);
  }
  get label() { return this.band.meta.label; }
  legalFrom(sq) { return this.c.moves({ square: sq, verbose: true }).map(m => m.to); }
  render(last, animate) {
    const bo = this.band.book[fenKey(this.c.fen())];        // official opening name while the game is in known theory
    if (bo && bo.o) this.opening = bo.o;
    this.board.setPosition(this.c.fen(), { last, animate: animate && !this.auto ? { from: last[0], to: last[1] } : null, check: kingSq(this.c) });
    const h = this.c.history({ verbose: true }); const start = h.length - this.graded.length;
    let html = '';
    h.forEach((m, i) => {
      if (i % 2 === 0) html += `<b>${i / 2 + 1}.</b> `;
      const g = this.graded.find(x => x.ply === i);
      html += `<span class="mv ${g ? g.cls : ''}">${m.san}</span> `;
    });
    $('playMoves').innerHTML = html || '<span>Game start</span>';
    $('playMoves').scrollTop = 1e6;
  }
  coach(verdict, cls, body, sub = '') {      // verdict on YOUR move (stays visible), rival line is added below
    this.lastGrade = { verdict, cls, body, sub }; this.rivalLine = null; this.coachRender();
  }
  coachRender(extra = '') {
    const g = this.lastGrade || {}; let h = this.opening ? `<div class="opening-name">📖 ${esc(this.opening)}</div>` : '';
    if (g.verdict) h += `<div class="verdict ${g.cls || ''}">${g.verdict}</div>`;
    if (g.body) h += `<p>${g.body}</p>`;
    if (g.sub) h += `<p class="sub">${g.sub}</p>`;
    if (this.rivalLine) h += `<p class="rival">${this.rivalLine}</p>`;
    $('playCoach').innerHTML = h + extra;
  }
  async begin() {
    const h = this.band.human;
    $('oppTag').innerHTML = `<div class="av"><img src="pieces/${this.color === 'w' ? 'b' : 'w'}N.svg"></div><div>Rival · ${esc(this.label)}<br><small>Plays like a real ${esc(this.label)} player · blunders on ${pct(((h.middle || {}).blunder) || 0)} of moves</small></div>`;
    $('youTag').innerHTML = `<div class="av"><img src="pieces/${this.color}K.svg"></div><div>You<br><small>🔥 ${streakNow()} day streak</small></div>`;
    this.coach('', '', this.c.turn() === this.color ? 'Your move. Find the best one!' : 'Your rival is thinking…');
    await this.loop();
  }
  async loop() {
    if (this.checkEnd()) return;
    if (this.maxPlies && this.c.history().length >= this.maxPlies) { this.end('draw', 'Move cap'); return; }
    if (this.c.turn() === this.color) return this.userTurn();
    await this.botMove();
    if (!this.checkEnd()) this.userTurn();
  }
  // ---------------------------------------------------------------- your move
  userTurn() {
    this.fenBefore = this.c.fen();
    this.pre = this.engine.analyse(this.fenBefore, { depth: 12 }).catch(() => null);
    this.board.movable = this.color;
    if (this.auto) this.autoMove();
  }
  async autoMove() {   // self-test: play Stockfish's choice
    const r = await this.pre; const u = r && r.best; if (!u) return;
    this.onUserMove(u.slice(0, 2), u.slice(2, 4), u[4]);
  }
  async onUserMove(from, to, promo) {
    if (this.board.movable !== this.color || this.over) return;
    let mv; try { mv = this.c.move({ from, to, promotion: promo || 'q' }); } catch (e) { return; }
    if (!mv) return;
    this.board.movable = null; sound(mv.captured ? 'capture' : 'move');
    this.render([from, to], false);
    this.lastGrade = { body: 'Checking your move…' }; this.rivalLine = null; this.coachRender();
    const res = await this.grade(mv);
    if ((res.cat === 'mistake' || res.cat === 'blunder') && !this.auto) return this.offerRetry(res);
    this.afterUser();
  }
  afterUser() { if (!this.checkEnd()) this.loop(); }
  async grade(mv) {
    const uci = mv.from + mv.to + (mv.promotion && mv.promotion !== 'q' ? mv.promotion : '');
    const be = this.band.book[fenKey(this.fenBefore)];
    const pre = await this.pre;
    let bestCp = pre && pre.lines[0] ? pre.lines[0].cp : (be ? be.e : 0);
    let bestUci = pre ? pre.best : (be ? be.b : null);
    let cpAfter = null, bm = null;
    if (be) { bm = be.m.find(x => x[1].slice(0, 4) === uci.slice(0, 4)); if (bm && bm[5] != null) cpAfter = bm[5]; }
    if (this.c.isCheckmate()) cpAfter = this.color === 'w' ? 10000 : -10000;
    if (cpAfter == null) { try { const r = await this.engine.analyse(this.c.fen(), { depth: 12 }); cpAfter = r.lines[0] ? r.lines[0].cp : 0; } catch (e) { cpAfter = bestCp; } }
    const sign = this.color === 'w' ? 1 : -1;
    let loss = Math.max(0, winp(sign * bestCp) - winp(sign * cpAfter));
    if (bestUci && bestUci.slice(0, 4) === uci.slice(0, 4)) loss = 0;
    const stat = be && be.p && be.p.slice(0, 4) === uci.slice(0, 4);
    let cat = loss <= 0.02 ? (loss === 0 || stat ? 'best' : 'excellent') : loss <= 0.05 ? 'good' : loss <= 0.10 ? 'inaccuracy' : loss <= 0.20 ? 'mistake' : 'blunder';
    const ply = this.c.history().length - 1;
    const [vt, cls] = VERDICT[cat];
    const bestSan = this.sanOf(this.fenBefore, bestUci);
    const statSan = be && be.p ? this.sanOf(this.fenBefore, be.p) : null;
    let body = '', sub = `Stockfish: ${fmtEval(cpAfter)}`;
    if (bm) {
      const score = this.color === 'w' ? bm[4] : 1 - bm[4];
      sub = `${pct(bm[2])} of ${esc(this.label)} players play ${bm[0]} here and score ${Math.round(score * 100)}% with it · ` + sub;
    }
    if (cat === 'best') body = stat && be.b && be.p !== be.b ? `That's the statistical pick: Stockfish-approved, and ${esc(this.label)} opponents go wrong after it most often.` : 'The engine\'s top choice. 🎯';
    else if (cat === 'excellent' || cat === 'good') body = `Solid. ${statSan && be.p.slice(0, 4) !== uci.slice(0, 4) ? `The best by the numbers was <b>${statSan}</b>.` : bestSan ? `Stockfish slightly prefers <b>${bestSan}</b>.` : ''}`;
    else body = `${cat === 'inaccuracy' ? 'Not the best.' : 'This costs you.'} Best was <b>${bestSan || '?'}</b> (you lost ${Math.round(loss * 100)}% win chance).`;
    this.coach(vt, cls, body, sub);
    if (cat === 'best' || cat === 'excellent' || cat === 'good') sound('good'); else if (cat !== 'inaccuracy') sound('bad');
    const xp = cat === 'best' ? 2 : (cat === 'excellent' || cat === 'good') ? 1 : 0; this.xp += xp;
    this.graded.push({ ply, cat, cls, loss, uci });
    this.render([mv.from, mv.to], false);
    if (cat === 'mistake' || cat === 'blunder' || cat === 'inaccuracy') {
      if (bestUci) this.board.setArrows([{ from: bestUci.slice(0, 2), to: bestUci.slice(2, 4), color: 'g' }]);
    } else this.board.setArrows([]);
    return { cat, loss, bestUci, bestSan };
  }
  sanOf(fen, uci) { if (!uci) return null; try { const c = new Chess(fen); const m = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || 'q' }); return m ? m.san : null; } catch (e) { return null; } }
  offerRetry(res) {
    const extra = `<div class="btn-row" style="margin-top:10px"><button class="btn white" id="retryBtn">↩️ Retry</button><button class="btn white" id="keepBtn">Keep my move</button></div>`;
    this.coachRender(extra);
    $('retryBtn').onclick = () => { this.c.undo(); this.graded.pop(); this.board.setArrows([]); this.render(null); this.coach('', '', 'Try again: find a better move.'); this.userTurn(); };
    $('keepBtn').onclick = () => { this.board.setArrows([]); this.afterUser(); };
  }
  hint() {
    if (this.board.movable !== this.color) return;
    this.pre.then(r => { if (r && r.best) { this.board.setArrows([{ from: r.best.slice(0, 2), to: r.best.slice(2, 4), color: 'y' }]); this.coach('💡 Hint', '', `Try <b>${this.sanOf(this.fenBefore, r.best)}</b>.`); this.hinted = true; } });
  }
  // ---------------------------------------------------------------- rival's move
  async botMove() {
    this.board.movable = null;
    const fen = this.c.fen(), be = this.band.book[fenKey(fen)], ply = this.c.history().length;
    let uci = null, note = '';
    if (be && be.nr >= 20 && be.m.length) {
      const opts = be.m.filter(m => m[2] >= 0.01);
      let r = Math.random() * opts.reduce((a, m) => a + m[2], 0);
      for (const m of opts) { r -= m[2]; if (r <= 0) { uci = m[1]; note = `${pct(m[2])} of ${esc(this.label)} players play ${m[0]} here.`; break; } }
      if (!uci && opts.length) uci = opts[0][1];
    }
    if (!uci) {
      if (this.inBook) { this.inBook = false; note = 'Out of book: your rival is on their own now (but makes mistakes at a real player\'s rate).'; }
      uci = await this.humanMove(fen, ply);
    }
    if (this.botDelay) await sleep(450 + Math.random() * 500);
    let mv; try { mv = this.c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || 'q' }); } catch (e) { mv = null; }
    if (!mv) { const ms = this.c.moves({ verbose: true }); mv = this.c.move(ms[(Math.random() * ms.length) | 0]); }
    sound(mv.captured ? 'capture' : 'move');
    this.board.setArrows([]);
    this.render([mv.from, mv.to], true);
    if (!this.checkEnd()) { this.rivalLine = `Rival played <b>${sanLabel(mv.san, ply)}</b>. Your move.` + (note ? `<br><span class="sub">${note}</span>` : ''); this.coachRender(); }
  }
  async humanMove(fen, ply) {
    const phase = ply < 20 ? 'opening' : 'middle';
    const prof = this.band.human[phase] || this.band.human.middle || { best: .5, good: .2, inaccuracy: .15, mistake: .1, blunder: .05 };
    let r; try { r = await this.engine.analyse(fen, { depth: 10, multipv: 6 }); } catch (e) { r = null; }
    if (!r || !r.lines.length) { const ms = new Chess(fen).moves({ verbose: true }); const m = ms[(Math.random() * ms.length) | 0]; return m.from + m.to + (m.promotion || ''); }
    const sign = fen.split(' ')[1] === 'w' ? 1 : -1;
    const cand = r.lines.map(l => ({ uci: l.uci, wp: winp(sign * l.cp) }));
    const top = Math.max(...cand.map(c => c.wp)); cand.forEach(c => c.loss = top - c.wp);
    // pick an error category at the band's measured rate
    let x = Math.random(), cat = 'best';
    for (const [k] of CATS) { x -= prof[k] || 0; if (x <= 0) { cat = k; break; } }
    const [, lo, hi] = CATS.find(c => c[0] === cat);
    let pool = cand.filter(c => c.loss >= lo && c.loss < hi);
    if (!pool.length && (cat === 'mistake' || cat === 'blunder' || cat === 'inaccuracy')) {
      // the top-6 lines are all decent: look for a genuinely worse move among the rest
      const others = new Chess(fen).moves({ verbose: true }).map(m => m.from + m.to + (m.promotion || '')).filter(u => !cand.some(c => c.uci === u));
      shuffle(others);
      for (const u of others.slice(0, 4)) {
        const c2 = new Chess(fen); c2.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] || 'q' });
        try { const r2 = await this.engine.analyse(c2.fen(), { depth: 8 }); const wp2 = winp(sign * (r2.lines[0] ? r2.lines[0].cp : 0)); const loss = top - wp2;
          if (loss >= lo && loss < hi + 0.15) { pool = [{ uci: u, loss }]; break; } } catch (e) {}
      }
    }
    if (!pool.length) pool = [cand.reduce((a, b) => (Math.abs(b.loss - lo) < Math.abs(a.loss - lo) ? b : a))];
    return pool[(Math.random() * pool.length) | 0].uci;
  }
  // ---------------------------------------------------------------- end
  checkEnd() {
    if (this.over) return true;
    if (!this.c.isGameOver()) return false;
    let res = 'draw', why = 'Draw';
    if (this.c.isCheckmate()) { res = this.c.turn() === this.color ? 'loss' : 'win'; why = 'Checkmate'; }
    else if (this.c.isStalemate()) why = 'Stalemate'; else if (this.c.isThreefoldRepetition()) why = 'Threefold repetition'; else if (this.c.isInsufficientMaterial()) why = 'Insufficient material';
    this.end(res, why); return true;
  }
  end(res, why) {
    if (this.over) return; this.over = true; this.board.movable = null;
    const n = this.graded.length;
    const acc = n ? Math.round(this.graded.reduce((a, g) => a + accOf(g.loss), 0) / n) : 0;
    const count = k => this.graded.filter(g => g.cat === k || (k === 'best' && g.cat === 'excellent')).length;
    let xp = this.xp + 5 + (res === 'win' ? 10 : 0);
    addXP(xp);
    const st = n >= 6 ? recordActivity() : { extended: false, n: streakNow() };   // a real game (6+ of your moves) keeps the streak
    recordGame({ date: localDay(), band: this.band.meta.id, color: this.color, res, acc, moves: n });
    if (this.auto) { this.onEnd && this.onEnd({ res, acc, n, streak: st }); return; }
    if (res === 'win') { sound('win'); confetti(); }
    const head = res === 'win' ? ['🏆', 'You won!'] : res === 'loss' ? ['😵', 'Checkmated'] : res === 'resigned' ? ['🏳️', 'Game over'] : ['🤝', why];
    modal(`<div class="big-emoji">${head[0]}</div><h2>${head[1]}</h2><p>${esc(why)} · vs a ${esc(this.label)} rival</p>
      <div class="kpis"><div class="kpi"><b>${acc}%</b><span>Accuracy</span></div><div class="kpi"><b>${count('best')}</b><span>Best / excellent</span></div>
      <div class="kpi"><b>${count('mistake') + count('blunder')}</b><span>Mistakes</span></div><div class="kpi"><b>+${xp}</b><span>XP</span></div></div>
      <p class="sub">Real ${esc(this.label)} players average ${this.band.human.accuracy}% accuracy in the opening phase.${n < 6 ? ' Play at least 6 moves for a game to count towards your streak.' : ''}</p>
      <button class="btn green wide" id="mAgain">Play again</button><button class="btn ghost wide" id="mBack">Back</button>`, (el, cl) => {
      const go = again => { cl(); const fin = () => this.onEnd && this.onEnd({ again }); st.extended ? celebrate(st.n, fin) : fin(); };
      el.querySelector('#mAgain').onclick = () => go(true);
      el.querySelector('#mBack').onclick = () => go(false);
    });
  }
}
