// Duolingo-style lesson: learn -> recall -> "which move is best?" -> "what do most players play?"
import { Chess } from '../../lib/chess.js';
import { Board } from './board.js';
import { S, lessonDone, lineReviewed, lineSeen, addXP, recordActivity, streakNow } from './state.js';
import { celebrate } from './streak.js';
import { sound, confetti, modal, pct, esc, fmtEval, sanLabel, plyOfFen } from './ui.js';

const $ = id => document.getElementById(id);
export const fenKey = f => f.split(' ').slice(0, 4).join(' ');
const shuffle = a => { for (let i = a.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; [a[i], a[j]] = [a[j], a[i]]; } return a; };

function checkSquare(fen) {
  const c = new Chess(fen); if (!c.inCheck()) return null;
  const t = c.turn(); const rows = c.board();
  for (const row of rows) for (const p of row) if (p && p.type === 'k' && p.color === t) return p.square;
  return null;
}

export class Lesson {
  constructor(ctx, lesson, { onDone, auto = false } = {}) {
    this.ctx = ctx; this.lesson = lesson; this.onDone = onDone; this.auto = auto;   // auto: self-test drives inputs
    this.course = ctx.course; this.nodes = ctx.course.nodes; this.color = ctx.course.color; this.band = ctx.band;
    this.correct = 0; this.total = 0; this.mistakes = 0; this.idx = 0;
    this.board = new Board($('lessonBoard'), { orientation: this.color, legalFrom: sq => this.legalFrom(sq), onMove: (f, t, p) => this.onUserMove(f, t, p) });
    this.challenges = this.build();
  }
  get label() { return this.band.meta.label; }
  legalFrom(sq) { try { return new Chess(this.fen).moves({ square: sq, verbose: true }).map(m => m.to); } catch (e) { return []; } }

  // ---------------------------------------------------------------- build the challenge list
  build() {
    const lines = this.lesson.lines.map(id => this.course.linesById[id]).filter(Boolean);
    const ch = [];
    for (const L of lines) {
      if (!lineSeen(this.band.meta.id, this.color, L.id)) ch.push({ type: 'walk', line: L, mode: 'learn' });
      ch.push({ type: 'walk', line: L, mode: 'recall' });
    }
    const book = this.band.book;
    const chooseC = [], predictC = [];
    for (const L of lines) {
      for (let i = 0; i < L.path.length - 1; i++) {
        const nd = this.nodes[L.path[i]], m = nd.m.find(x => x.c === L.path[i + 1]); if (!m) continue;
        const be = book[fenKey(nd.f)]; if (!be) continue;
        if (m.o) {
          const alts = be.m.filter(x => x[1].slice(0, 4) !== m.u.slice(0, 4) && x[2] >= 0.04).slice(0, 2);
          if (alts.length) chooseC.push({ type: 'choose', fen: nd.f, m, alts, popular: be.m[0] });
        } else {
          const reps = be.m.filter(x => x[2] >= 0.05).slice(0, 3);
          if (reps.length >= 2) predictC.push({ type: 'predict', fen: nd.f, reps });
        }
      }
    }
    if (chooseC.length) ch.push(chooseC[(Math.random() * chooseC.length) | 0]);
    if (predictC.length) ch.push(predictC[(Math.random() * predictC.length) | 0]);
    return ch;
  }

  // ---------------------------------------------------------------- flow
  open() {
    $('lesson').hidden = false;
    $('lessonClose').onclick = () => this.quit();
    this.updateTop(); this.next();
  }
  updateTop() {
    $('lessonProgress').style.width = (100 * this.idx / Math.max(1, this.challenges.length)) + '%';
  }
  sheet(state, html, btn = 'Continue', onClick = null, enabled = true) {
    const s = $('sheet'); s.className = 'sheet' + (state ? ' ' + state : '');
    $('sheetMsg').innerHTML = html || ''; const b = $('sheetBtn'); b.textContent = btn; b.disabled = !enabled; b.hidden = !btn;
    b.onclick = onClick;
  }
  bubble(html) { $('lessonBubble').innerHTML = html; }
  // the purpose of a move: the hand-written coach note (Under 400 course, your moves) or the generated explanation
  expl(m) { return (this.course.source === 'curated' && m.o && m.t) ? m.t : (m.x || m.t || ''); }
  note(m) {
    if (this.course.source === 'curated') return !m.o && m.t && m.t !== m.x ? m.t : '';
    return m.o ? (m.d || '') : '';
  }
  sub(t) { $('lessonSub').textContent = t || ''; }
  next() {
    this.updateTop();
    if (this.idx >= this.challenges.length) return this.finish();
    const c = this.challenges[this.idx];
    $('lessonOptions').hidden = true; $('lessonBadge').hidden = true; this.board.setArrows([]);
    if (c.type === 'walk') this.runWalk(c); else if (c.type === 'choose') this.runChoose(c); else this.runPredict(c);
  }
  advance() { this.idx++; this.next(); }

  // ---------------------------------------------------------------- walk (learn / recall)
  runWalk(c) {
    this.cur = c; this.step = 0; this.wrongHere = 0; this.lineMistakes = 0; this.lastOpp = '';
    const L = c.line;
    $('lessonTitle').textContent = L.name; this.sub(L.moves);
    this.fen = this.nodes[L.path[0]].f; this.board.setPosition(this.fen); this.board.movable = null;
    if (c.mode === 'learn') {
      const head = L.head && L.head !== L.moves ? `<span class="meta">${esc(L.head)}</span>` : '';
      this.bubble(`<b>Why it's good:</b> ${esc(L.why || '')}${head}`);
      const go = () => { this.sheet('', 'Follow the arrows. Every move is explained as it happens.', '', null, false); this.walkStep(); };
      if (this.auto) return go();
      this.sheet('', `<span class="head">New line</span>${esc(L.name)}`, 'Start', go);
    } else {
      this.sheet('', 'Play your moves from memory.', '', null, false);
      this.bubble(`From memory: the <b>${esc(L.name)}</b>.`);
      setTimeout(() => this.walkStep(), this.auto ? 0 : 450);
    }
  }
  walkStep() {
    const L = this.cur.line;
    if (this.step >= L.path.length - 1) return this.walkDone();
    const nd = this.nodes[L.path[this.step]], m = nd.m.find(x => x.c === L.path[this.step + 1]);
    const ply = plyOfFen(nd.f);
    if (!m.o) {
      const go = () => {
        this.apply(m);
        const share = m.p != null ? `${pct(m.p)} of ${this.label} players play this here.` : '';
        const extra = this.note(m) ? `<span class="meta">${esc(this.note(m))}</span>` : '';
        const trap = m.g === 'trap' ? '⚠️ ' : '';
        this.lastOpp = `${trap}Opponent plays <b>${sanLabel(m.s, ply)}</b>. ${esc(this.expl(m))}<span class="meta">${share}</span>${extra}`;
        this.bubble(this.lastOpp);
        this.step++; this.walkStep();
      };
      if (this.auto) go(); else setTimeout(go, 700);
      return;
    }
    this.expect = m; this.wrongHere = 0; this.board.movable = this.color;
    if (this.cur.mode === 'learn') {
      $('lessonBadge').hidden = false;
      this.board.setArrows([{ from: m.u.slice(0, 2), to: m.u.slice(2, 4), color: 'g' }]);
      const ex = this.expl(m), nt = this.note(m);
      const sf = m.e != null && !/Stockfish/.test(ex + nt) ? ` Stockfish: ${fmtEval(m.e)}.` : '';
      const opp = this.lastOpp ? `<div class="opp-said">${this.lastOpp}</div>` : '';
      this.bubble(`${opp}Your move: <b>${sanLabel(m.s, ply)}</b>. ${esc(ex)}${nt || sf ? `<span class="meta">${esc(nt)}${sf}</span>` : ''}`);
    } else {
      $('lessonBadge').hidden = true;
      const prev = $('lessonBubble').innerHTML.includes('Opponent plays') ? $('lessonBubble').innerHTML : '';
      this.bubble(prev + (prev ? '<span class="meta"><b>Your move.</b></span>' : 'Your move.'));
    }
    if (this.auto) setTimeout(() => this.onUserMove(m.u.slice(0, 2), m.u.slice(2, 4), m.u[4]), 0);
  }
  apply(m) {
    const from = m.u.slice(0, 2), to = m.u.slice(2, 4);
    const before = this.fen; this.fen = this.nodes[m.c].f;
    const capture = before.split(' ')[0] !== this.fen.split(' ')[0] && this.isCapture(before, m.u);
    this.board.setPosition(this.fen, { last: [from, to], animate: this.auto ? null : { from, to }, check: checkSquare(this.fen) });
    sound(capture ? 'capture' : 'move');
  }
  isCapture(fen, uci) { try { const c = new Chess(fen); const mv = c.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || 'q' }); return !!(mv && mv.captured); } catch (e) { return false; } }
  onUserMove(from, to, promo) {
    const m = this.expect; if (!m) return;
    const uci = from + to;
    if (uci === m.u.slice(0, 4)) {
      this.expect = null; this.lastOpp = ''; this.board.movable = null; this.total++; if (!this.wrongHere) this.correct++;
      this.apply(m); this.board.setArrows([]); this.board.setMarks({ [to]: 'good' }); sound('good');
      this.step++;
      setTimeout(() => { this.board.setMarks({}); this.walkStep(); }, this.auto ? 0 : 450);
    } else {
      this.wrongHere++; this.lineMistakes++; this.mistakes++; sound('bad'); this.board.shake();
      this.board.setMarks({ [from]: 'bad', [to]: 'bad' });
      const ply = plyOfFen(this.fen);
      this.board.setArrows([{ from: m.u.slice(0, 2), to: m.u.slice(2, 4), color: 'g' }]);
      this.bubble(`Not quite. The move is <b>${sanLabel(m.s, ply)}</b>. ${esc(this.expl(m))}`);
      setTimeout(() => this.board.setMarks({}), 600);
    }
  }
  walkDone() {
    const L = this.cur.line;
    lineReviewed(this.band.meta.id, this.color, L.id, this.cur.mode === 'recall' && this.lineMistakes === 0);
    const clean = this.lineMistakes === 0;
    sound(clean ? 'good' : 'move');
    this.sheet(clean ? 'good' : '', `<span class="head">${clean ? (this.cur.mode === 'learn' ? 'Line learned!' : 'Perfect!') : 'Line done'}</span>${clean ? 'Nice work.' : 'You got there. It will come back for review.'}`, 'Continue', () => this.advance());
    if (this.auto) this.advance();
  }

  // ---------------------------------------------------------------- multiple choice
  runChoose(c) {
    this.fen = c.fen; this.board.setPosition(c.fen); this.board.movable = null;
    const ply = plyOfFen(c.fen);
    $('lessonTitle').textContent = 'Which move is best here?'; this.sub('');
    const pop = c.popular && c.popular[1].slice(0, 4) !== c.m.u.slice(0, 4) ? `Most ${this.label} players play <b>${c.popular[0]}</b> here (${pct(c.popular[2])}). ` : '';
    this.bubble(`${pop}Pick the move from your repertoire.`);
    const opts = shuffle([{ san: c.m.s, uci: c.m.u, right: true }, ...c.alts.map(a => ({ san: a[0], uci: a[1], share: a[2], ev: a[5] }))]);
    this.renderOptions(opts, o => sanLabel(o.san, ply), sel => {
      this.total++;
      const right = opts[sel].right;
      const box = $('lessonOptions').children;
      [...box].forEach((b, i) => { if (opts[i].right) b.classList.add('right'); else if (i === sel) b.classList.add('wrong'); });
      this.board.setArrows([{ from: c.m.u.slice(0, 2), to: c.m.u.slice(2, 4), color: 'g' }]);
      if (right) { this.correct++; sound('good'); this.sheet('good', `<span class="head">Correct!</span>${esc(this.expl(c.m))}`, 'Continue', () => this.advance()); }
      else { this.mistakes++; sound('bad');
        this.sheet('bad', `<span class="head">Correct answer: ${sanLabel(c.m.s, ply)}</span>${esc(this.expl(c.m))}`, 'Continue', () => this.advance()); }
      if (this.auto) this.advance();
    });
    if (this.auto) this.pickAuto(opts.findIndex(o => o.right));
  }
  // ---------------------------------------------------------------- predict the opponent
  runPredict(c) {
    this.fen = c.fen; this.board.setPosition(c.fen); this.board.movable = null;
    const ply = plyOfFen(c.fen);
    $('lessonTitle').textContent = `What do most ${this.label} players play here?`; this.sub('');
    this.bubble('Knowing what your opponents usually play is half the battle. Take a guess!');
    const opts = shuffle(c.reps.map((r, i) => ({ san: r[0], uci: r[1], share: r[2], right: i === 0 })));
    this.renderOptions(opts, o => sanLabel(o.san, ply), sel => {
      const box = $('lessonOptions').children;
      [...box].forEach((b, i) => { b.innerHTML += `<small>${pct(opts[i].share)}</small>`; if (opts[i].right) b.classList.add('right'); else if (i === sel) b.classList.add('wrong'); });
      const top = opts.find(o => o.right);
      this.board.setArrows([{ from: top.uci.slice(0, 2), to: top.uci.slice(2, 4), color: 'b' }]);
      if (opts[sel].right) { sound('good'); this.sheet('good', `<span class="head">Spot on!</span>${pct(top.share)} of ${this.label} players choose ${top.san} here.`, 'Continue', () => this.advance()); }
      else { sound('bad'); this.sheet('bad', `<span class="head">Most play ${top.san}</span>${pct(top.share)} of ${this.label} players choose it. Now you know!`, 'Continue', () => this.advance()); }
      if (this.auto) this.advance();
    });
    if (this.auto) this.pickAuto(opts.findIndex(o => o.right));
  }
  renderOptions(opts, label, onCheck) {
    const box = $('lessonOptions'); box.hidden = false; this.selOpt = -1;
    box.innerHTML = opts.map((o, i) => `<button class="opt" data-i="${i}">${label(o)}</button>`).join('');
    box.querySelectorAll('.opt').forEach(b => b.onclick = () => {
      if (this.checked) return; this.selOpt = +b.dataset.i;
      box.querySelectorAll('.opt').forEach(x => x.classList.toggle('sel', x === b));
      this.sheet('', '', 'Check', () => { this.checked = true; onCheck(this.selOpt); }, true);
    });
    this.checked = false; this.sheet('', 'Choose an answer.', 'Check', null, false);
  }
  pickAuto(i) { const b = $('lessonOptions').querySelectorAll('.opt')[i]; b.onclick(); $('sheetBtn').onclick(); }

  // ---------------------------------------------------------------- end states
  finish() {
    const perfect = this.mistakes === 0;
    const xp = 10 + (perfect ? 5 : 0);
    lessonDone(this.band.meta.id, this.color, this.lesson.id, perfect); addXP(xp);
    const st = recordActivity();                      // a finished lesson keeps the daily streak alive
    $('lessonProgress').style.width = '100%';
    if (!this.auto) { sound('win'); confetti(); }
    const acc = this.total ? Math.round(100 * this.correct / this.total) : 100;
    const close = () => { $('lesson').hidden = true; this.onDone && this.onDone({ xp, perfect, acc, streak: st }); };
    if (this.auto) return close();
    const next = () => (st.extended ? celebrate(st.n, close) : close());
    modal(`<div class="big-emoji">${perfect ? '🏆' : '🎉'}</div><h2>${perfect ? 'Perfect lesson!' : 'Lesson complete!'}</h2>
      <div class="kpis"><div class="kpi"><b>+${xp}</b><span>XP</span></div><div class="kpi"><b>${acc}%</b><span>Accuracy</span></div>
      <div class="kpi"><b>${this.lesson.lines.length}</b><span>Lines</span></div><div class="kpi"><b>🔥 ${streakNow()}</b><span>Day streak</span></div></div>
      <button class="btn green wide" id="mOk">Continue</button>`, (el, cl) => { el.querySelector('#mOk').onclick = () => { cl(); next(); }; });
  }
  quit() {
    modal(`<div class="big-emoji">🥺</div><h2>Wait, don't go!</h2><p>You'll lose your progress in this lesson.</p>
      <button class="btn wide" id="mStay">Keep learning</button><button class="btn ghost wide" id="mQuit">End lesson</button>`, (el, cl) => {
      el.querySelector('#mStay').onclick = cl;
      el.querySelector('#mQuit').onclick = () => { cl(); $('lesson').hidden = true; this.onDone && this.onDone(null); };
    });
  }
}
