// Gambito: app shell (onboarding, path, play, stats, profile, self-test).
import { Chess } from '../../lib/chess.js';
import { Engine } from './engine.js';
import { S, save, resetAll, rollDay, prog, TEST, streakNow, doneToday, recordActivity } from './state.js';
import { streakCard, streakModal, calendar, weekRow } from './streak.js';
import { Lesson, fenKey } from './lesson.js';
import { Game } from './play.js';
import { toast, modal, pct, esc, sound } from './ui.js';
import { loadData } from './load.js';

const $ = id => document.getElementById(id);
const UNIT_COLORS = ['#58cc02', '#1cb0f6', '#ce82ff', '#ff9600', '#ff4b4b', '#00cd9c', '#ff86d0', '#2b70c9'];
const OFFSETS = [0, 44, 70, 44, 0, -44, -70, -44];
const ctx = { bands: [], band: null, course: null, engine: null, cache: {} };
window.GAMBITO = ctx;   // debug/test handle

// ---------------------------------------------------------------- data
async function loadIndex() { ctx.bands = await loadData('bands'); }
function getBand(id) {                 // load + cache a band without switching the learner's band
  if (!ctx.cache[id]) ctx.cache[id] = loadData('band_' + id).then(d => {
    for (const c of Object.values(d.courses)) { c.linesById = {}; for (const L of c.lines) c.linesById[L.id] = L; }
    return d;
  }, e => { delete ctx.cache[id]; throw e; });
  return ctx.cache[id];               // a promise, so two quick clicks share one load
}
async function loadBand(id) {
  ctx.band = await getBand(id); S.profile.band = id; save();
  setCourse();
}
function setCourse() { ctx.course = ctx.band.courses[S.profile.color]; }
function engine() { if (!ctx.engine) ctx.engine = new Engine(); return ctx.engine; }

// ---------------------------------------------------------------- chrome
function refreshTop() {
  rollDay();
  $('streakN').textContent = streakNow(); $('xpN').textContent = S.xp;
  const pill = document.querySelector('.topbar .stat-pill.streak'); pill.classList.toggle('cold', !doneToday());
  pill.title = doneToday() ? 'Streak extended today' : 'Finish a lesson or game today to extend your streak';
  if ($('streakCard')) $('streakCard').innerHTML = streakCard();
  if (ctx.band) $('bandChipText').textContent = ctx.band.meta.label;
  $('colorChipImg').src = `pieces/${S.profile.color}K.svg`; $('colorChipText').textContent = S.profile.color === 'w' ? 'White' : 'Black';
  const g = S.profile.goal; $('goalFill').style.width = Math.min(100, 100 * S.day.xp / g) + '%'; $('goalText').textContent = `${Math.min(S.day.xp, g)}/${g} XP`;
}
function show(screen) {
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('on', s.id === 'screen-' + screen));
  document.querySelectorAll('.navbtn').forEach(b => b.classList.toggle('on', b.dataset.screen === screen));
  ctx.screen = screen;
  if (screen === 'learn') renderPath(); else if (screen === 'stats') renderStats(); else if (screen === 'profile') renderProfile(); else if (screen === 'play') renderPlaySetup();
  refreshTop();
}

// ---------------------------------------------------------------- learn path
function renderPath() {
  if (!ctx.band) return;
  const course = ctx.course, p = prog(ctx.band.meta.id, S.profile.color);
  let html = '', current = null, idx = 0;
  course.units.forEach((u, ui) => {
    const col = UNIT_COLORS[ui % UNIT_COLORS.length];
    html += `<div class="unit"><div class="unit-head" style="background:${col}"><div><h3>Unit ${ui + 1}</h3><p>${esc(u.title)}</p><p style="opacity:.85;font-size:13px">${esc(u.sub)}</p></div><button class="guide" data-guide="${ui}">📖 Guide</button></div><div class="nodes">`;
    u.lessons.forEach((L, li) => {
      const st = p.lessons[L.id]; const done = st && st.level > 0;
      let cls = done ? 'done' : 'locked';
      if (!done && !current) { cls = 'current'; current = [ui, li]; }
      const off = OFFSETS[idx++ % OFFSETS.length];
      const icon = L.kind === 'match' ? '⚔️' : done ? '👑' : '★';
      html += `<div class="node-wrap ${off < 0 ? 'flip' : ''}" style="transform:translateX(${off}px)">${cls === 'current' ? '<div class="start-bubble">START</div>' : ''}
        <button class="node ${cls} ${L.kind}" data-u="${ui}" data-l="${li}" ${cls === 'current' && L.kind !== 'match' ? `style="background:${col}"` : ''} title="${esc(L.title)}">${icon}${done && st.level > 1 ? `<span class="crowns">${st.level}</span>` : ''}</button>
        <div class="node-label">${L.kind === 'match' ? esc('Play it out vs a ' + ctx.band.meta.label + ' rival') : `<b>${esc(L.title)}</b>${L.sub ? `<small>${esc(L.sub)}</small>` : ''}`}</div></div>`;
    });
    html += '</div></div>';
  });
  $('pathCol').innerHTML = html;
  $('pathCol').querySelectorAll('.node').forEach(b => b.onclick = () => {
    const u = course.units[+b.dataset.u], L = u.lessons[+b.dataset.l];
    if (b.classList.contains('locked')) {
      modal(`<div class="big-emoji">🔒</div><h2>Jump ahead?</h2><p>This unlocks after the lessons above, but you can start it now.</p>
        <button class="btn wide" id="mGo">Start lesson</button><button class="btn ghost wide" id="mNo">Not now</button>`, (el, cl) => {
        el.querySelector('#mGo').onclick = () => { cl(); startLesson(L); }; el.querySelector('#mNo').onclick = cl; });
    } else startLesson(L);
  });
  $('pathCol').querySelectorAll('[data-guide]').forEach(b => b.onclick = () => showGuide(course.units[+b.dataset.guide]));
  const cur = $('pathCol').querySelector('.node.current'); if (cur && !TEST) cur.scrollIntoView({ block: 'center', behavior: 'smooth' });
  renderBandCard();
}
function lineSans(L) {
  const nodes = ctx.course.nodes; const out = [];
  for (let i = 0; i < L.path.length - 1; i++) { const m = nodes[L.path[i]].m.find(x => x.c === L.path[i + 1]); const ply = i;
    out.push((ply % 2 === 0 ? (ply / 2 + 1) + '.' : '') + (m.o ? `<b>${m.s}</b>` : m.s)); }
  return out.join(' ');
}
function showGuide(u) {
  const rows = u.lessons.filter(L => L.kind === 'learn').flatMap(L => L.lines).map(id => ctx.course.linesById[id]).filter(Boolean)
    .map(L => `<div class="guide-line"><b>${esc(L.name)}</b>${L.eco ? ` <small>${esc(L.eco)}</small>` : ''}<br><span class="mv">${lineSans(L)}</span>${L.why ? `<p>${esc(L.why)}</p>` : ''}</div>`).join('');
  modal(`<h2>📖 ${esc(u.title)}</h2><p>${esc(u.sub)} · <b>bold</b> = your moves</p>${rows}<p class="sub">Opening names come from the lichess chess-openings database (ECO codes). Sidelines with no official name show the opening they branch from.</p><button class="btn wide" id="mOk">Got it</button>`, (el, cl) => el.querySelector('#mOk').onclick = cl);
}
function startLesson(L) {
  if (L.kind === 'match') return startGame(S.profile.color, L.start || []);
  ctx.lesson = new Lesson(ctx, L, { onDone: () => { refreshTop(); renderPath(); } }); ctx.lesson.open();
}
function renderBandCard() {
  const b = ctx.band, st = b.stats, src = b.meta.curated ? 'Hand-built gambit repertoire (coach)' : 'Auto-built from the data + Stockfish';
  $('bandCard').innerHTML = `<div class="card-title">Your league</div><div class="big">${esc(b.meta.label)}</div>
    <p><b>${st.games.toLocaleString()}</b> real games · <b>${st.players.toLocaleString()}</b> players</p>
    <p>Course: ${src}</p><p>Real players here average <b>${b.human.accuracy}%</b> accuracy in the first 20 moves.</p>
    <button class="btn white wide" id="cardPlay">⚔️ Play it out</button>`;
  $('cardPlay').onclick = () => show('play');
}

// ---------------------------------------------------------------- band picker / onboarding
function bandGrid(cb) {
  return ctx.bands.map(b => `<button class="band-opt ${ctx.band && ctx.band.meta.id === b.id ? 'on' : ''}" data-b="${b.id}"><div class="r">${esc(b.label)}</div><small>${esc(b.nick)} · ${b.games.toLocaleString()} games</small></button>`).join('');
}
function pickBand(after) {
  modal(`<h2>What's your chess.com rapid rating?</h2><p>Everything (lessons, rival, stats) gets rebuilt from real games at that level.</p><div class="band-grid" style="margin-top:16px">${bandGrid()}</div>`, (el, cl) => {
    el.querySelectorAll('.band-opt').forEach(b => b.onclick = async () => { cl(); await loadBand(b.dataset.b); refreshTop(); after ? after() : show(ctx.screen || 'learn'); });
  });
}
function onboard() {
  const ov = document.createElement('div'); ov.className = 'lesson'; ov.id = 'onboard';
  ov.innerHTML = `<div class="onboard" id="ob"></div>`; document.body.appendChild(ov);
  const ob = ov.querySelector('#ob');
  const step1 = () => { ob.innerHTML = `<div class="mascot big"><img src="pieces/bN.svg"></div><h1>Hi, I'm Gambito!</h1>
      <p>I'll teach you openings the way you'd learn a language: built from <b>real chess.com games at your rating</b> and checked by Stockfish.</p>
      <button class="btn green" id="obGo">Get started</button>`; ob.querySelector('#obGo').onclick = step2; };
  const step2 = () => { ob.innerHTML = `<h1>What's your rapid rating?</h1><p>Pick your chess.com 10-minute rating band.</p><div class="band-grid">${bandGrid()}</div>`;
    ob.querySelectorAll('.band-opt').forEach(b => b.onclick = async () => { await loadBand(b.dataset.b); step3(); }); };
  const step3 = () => { ob.innerHTML = `<h1>Which side first?</h1><p>You can switch any time with the colour button up top.</p>
      <div class="choice-row" style="width:420px;max-width:100%"><button class="pick" data-c="w"><img src="pieces/wK.svg"><span>White</span></button><button class="pick" data-c="b"><img src="pieces/bK.svg"><span>Black</span></button></div>`;
    ob.querySelectorAll('.pick').forEach(b => b.onclick = () => { S.profile.color = b.dataset.c; S.profile.onboarded = true; save(); setCourse(); ov.remove(); show('learn'); }); };
  step1();
}

// ---------------------------------------------------------------- play it out
let playColor = 'w', playBand = null, game = null;
function renderPlaySetup() {
  if (game && !game.over) return;
  $('playSetup').hidden = false; $('game').hidden = true;
  if (!playBand || !ctx.bands.some(b => b.id === playBand)) playBand = ctx.band ? ctx.band.meta.id : ctx.bands[0].id;
  const pb = ctx.bands.find(b => b.id === playBand);
  $('playBandName').textContent = pb ? pb.label + ' player' : 'player';
  $('rivalBands').innerHTML = ctx.bands.map(b => `<button class="band-opt ${b.id === playBand ? 'on' : ''}" data-rb="${b.id}"><div class="r">${esc(b.label)}</div><small>${esc(b.nick)}</small></button>`).join('');
  $('rivalBands').querySelectorAll('[data-rb]').forEach(x => x.onclick = () => { playBand = x.dataset.rb; renderPlaySetup(); });
  playColor = S.profile.color;
  document.querySelectorAll('#playSetup .pick').forEach(b => { b.classList.toggle('on', b.dataset.color === playColor); b.onclick = () => { playColor = b.dataset.color; document.querySelectorAll('#playSetup .pick').forEach(x => x.classList.toggle('on', x === b)); }; });
  $('startGameBtn').onclick = () => startGame(playColor === 'r' ? (Math.random() < .5 ? 'w' : 'b') : playColor, [], playBand);
}
async function startGame(color, start, bandId) {
  const band = bandId ? await getBand(bandId) : ctx.band;
  show('play'); $('playSetup').hidden = true; $('game').hidden = false;
  const eng = engine();
  eng.ready.catch(() => toast('The chess engine could not start in this browser.', 4000));
  game = ctx.game = new Game({ band, engine: eng }, color, { start, onEnd: r => { refreshTop(); if (r && r.again) startGame(color, start, bandId); else { game = null; renderPlaySetup(); } } });
  game.begin();
}

// ---------------------------------------------------------------- stats ("your league")
function bars(rows, prefix = '', alt = false) {
  const max = Math.max(...rows.map(r => r[1]), 0.0001);
  return `<div class="bars">${rows.map(r => `<div class="bar-row ${alt ? 'alt' : ''}"><span>${esc(prefix + r[0])}</span><div class="bar"><div style="width:${100 * r[1] / max}%"></div></div><span>${pct(r[1])}</span></div>`).join('')}</div>`;
}
function renderStats() {
  if (!ctx.band) return;
  const b = ctx.band, st = b.stats, h = b.human;
  const prof = ph => ['best', 'good', 'inaccuracy', 'mistake', 'blunder'].map(k => [k, h[ph][k]]);
  const mine = S.games.filter(g => g.band === b.meta.id);
  $('statsBody').innerHTML = `<div class="stats-wrap">
    <div class="card full hero"><div class="mascot big"><img src="pieces/bN.svg"></div><div><h2>${esc(b.meta.label)} league</h2>
      <p>Built from <b>${st.games.toLocaleString()}</b> rated chess.com 10|0 games between <b>${st.players.toLocaleString()}</b> players (both rated ${esc(b.meta.rng)}), Sep–Oct 2026.</p></div></div>
    <div class="card full"><div class="kpis"><div class="kpi"><b>${pct(st.results.w || 0)}</b><span>White wins</span></div><div class="kpi"><b>${pct(st.endings.checkmate || 0)}</b><span>End in mate</span></div>
      <div class="kpi"><b>${st.median_moves}</b><span>Median moves</span></div><div class="kpi"><b>${h.accuracy}%</b><span>Opening accuracy</span></div></div></div>
    <div class="card"><div class="card-title">White's first move</div>${bars(st.first.map(r => [r[0], r[1]]), '1.')}</div>
    <div class="card"><div class="card-title">Replies to 1.e4</div>${bars(st.vs_e4.map(r => [r[0], r[1]]), '1...', true)}</div>
    <div class="card"><div class="card-title">Replies to 1.d4</div>${bars(st.vs_d4.map(r => [r[0], r[1]]), '1...', true)}</div>
    <div class="card"><div class="card-title">After 1.e4 e5</div>${bars(st.after_e4e5.map(r => [r[0], r[1]]), '2.')}</div>
    <div class="card"><div class="card-title">How players here move (moves 1–10)</div>${bars(prof('opening'))}</div>
    <div class="card"><div class="card-title">How players here move (moves 11–20)</div>${bars(prof('middle'))}</div>
    <div class="card full"><div class="card-title">How games end</div>${bars(Object.entries(st.endings).sort((a, b) => b[1] - a[1]))}</div>
    <div class="card full"><div class="card-title">Your games vs ${esc(b.meta.label)} rivals</div>${mine.length ? mine.slice(0, 10).map(g => `<div class="setting"><span>${g.date} · ${g.color === 'w' ? 'White' : 'Black'} · ${g.res}</span><span>${g.acc}% accuracy</span></div>`).join('') : '<p>No games yet: try <b>Play it out</b>.</p>'}</div>
  </div>`;
}

// ---------------------------------------------------------------- profile
function renderProfile() {
  $('profileBody').innerHTML = `<div class="stats-wrap"><div class="card full">
    <div class="card-title">Profile</div>
    <div class="setting"><span>Rating band</span><button class="btn white" id="pBand">${ctx.band ? esc(ctx.band.meta.label) : 'Pick'}</button></div>
    <div class="setting"><span>Colour</span><button class="btn white" id="pColor">${S.profile.color === 'w' ? 'White' : 'Black'}</button></div>
    <div class="setting"><span>Sound</span><button class="btn white" id="pSound">${S.profile.sound ? 'On' : 'Off'}</button></div>
    <div class="setting"><span>Daily goal</span><span>${[10, 20, 30, 50].map(g => `<button class="btn ${S.profile.goal === g ? '' : 'white'}" data-goal="${g}" style="margin-left:6px">${g} XP</button>`).join('')}</span></div>
    <div class="setting"><span>Total XP</span><span>${S.xp} XP</span></div>
    <div class="setting"><span>Daily streak · best</span><span>🔥 ${streakNow()} days · ${S.streak.best || 0} best</span></div>
    <div class="setting"><span>Reset all progress</span><button class="btn red" id="pReset">Reset</button></div>
  </div><div class="card full"><div class="card-title">Streak calendar (last 6 weeks)</div>${calendar()}</div><div class="card full"><div class="card-title">About</div>
    <p>Lessons, rival moves and stats come from rated chess.com 10-minute games (public API, Sep–Oct 2026) per rating band. Every position is evaluated by Stockfish 19. The rival's out-of-book mistakes follow the error rates measured on real games at that band.</p>
    <p>Credits: Stockfish (GPL-3, stockfish.js by Nathan Rugg), chess.js (BSD-2, Jeff Hlywa), cburnett pieces (GPL-2+), Nunito font (OFL), opening names: lichess-org/chess-openings (CC0). See LICENSES.txt.</p></div></div>`;
  $('pBand').onclick = () => pickBand(() => show('profile'));
  $('pColor').onclick = () => { S.profile.color = S.profile.color === 'w' ? 'b' : 'w'; save(); setCourse(); show('profile'); };
  $('pSound').onclick = () => { S.profile.sound = !S.profile.sound; save(); show('profile'); };
  document.querySelectorAll('[data-goal]').forEach(b => b.onclick = () => { S.profile.goal = +b.dataset.goal; save(); show('profile'); });
  $('pReset').onclick = () => modal(`<h2>Reset everything?</h2><p>XP, streak and all lesson progress will be deleted.</p><button class="btn red wide" id="mYes">Reset</button><button class="btn ghost wide" id="mNo">Cancel</button>`,
    (el, cl) => { el.querySelector('#mYes').onclick = () => { cl(); resetAll(); location.reload(); }; el.querySelector('#mNo').onclick = cl; });
}

// ---------------------------------------------------------------- boot
async function boot() {
  document.querySelectorAll('.navbtn').forEach(b => b.onclick = () => show(b.dataset.screen));
  $('bandChip').onclick = () => pickBand();
  document.querySelector('.topbar .stat-pill.streak').onclick = () => streakModal();
  $('colorChip').onclick = () => { S.profile.color = S.profile.color === 'w' ? 'b' : 'w'; save(); setCourse(); show(ctx.screen || 'learn'); };
  $('hintBtn').onclick = () => game && game.hint();
  $('flipBtn').onclick = () => game && game.board.flip();
  $('resignBtn').onclick = () => game && !game.over && game.end('resigned', 'You ended the game');
  setInterval(refreshTop, 30000);
  try { await loadIndex(); } catch (e) { document.body.innerHTML = `<div class="onboard"><h1>Couldn't load the data</h1><p>${esc(e.message)}. Keep the whole <b>(C) site</b> folder together (data/, lib/, app/ next to index.html).</p></div>`; return; }
  if (TEST) return selftest();
  const want = S.profile.band && ctx.bands.some(b => b.id === S.profile.band) ? S.profile.band : null;
  if (!S.profile.onboarded || !want) { onboard(); return; }
  await loadBand(want); show('learn');
}

// ---------------------------------------------------------------- self-test (?selftest=1)
async function selftest() {
  const out = []; let pass = 0, fail = 0; const ok = (c, m) => { if (c) pass++; else { fail++; out.push('FAIL ' + m); } };
  const log = m => { out.push(m); $('selftest').hidden = false; $('selftest').textContent = out.join('\n'); };
  const only = new URLSearchParams(location.search).get('band');
  log(`opened via ${location.protocol}//, engine: ${location.protocol === 'file:' ? 'embedded copy (lib/sf-embed.js)' : 'lib/stockfish-19-lite-single.js'}`);
  await document.fonts.ready;
  const nunito = [...document.fonts].find(f => f.family.replace(/"/g, '') === 'Nunito');
  ok(nunito && nunito.status === 'loaded', `Nunito font loaded (${nunito ? nunito.status : 'not declared'})`);
  for (const b of ctx.bands) {
    if (only && b.id !== only) continue;
    let d; try { await loadBand(b.id); d = ctx.band; ok(true, ''); } catch (e) { ok(false, b.id + ' load ' + e.message); continue; }
    for (const col of ['w', 'b']) {
      const C = d.courses[col]; ok(C && C.units.length > 0, `${b.id} ${col} has units`);
      let bad = 0;
      for (const L of C.lines) for (let i = 0; i < L.path.length - 1; i++) if (!C.nodes[L.path[i]].m.some(x => x.c === L.path[i + 1])) bad++;
      ok(bad === 0, `${b.id} ${col} line paths connected (${bad} broken)`);
      let missing = 0; for (const u of C.units) for (const l of u.lessons) if (l.kind === 'learn') for (const id of l.lines) if (!C.linesById[id]) missing++;
      ok(missing === 0, `${b.id} ${col} lesson lines exist (${missing} missing)`);
      let illegal = 0; for (const nd of C.nodes) { const c = new Chess(nd.f); const legal = new Set(c.moves({ verbose: true }).map(m => m.from + m.to)); for (const m of nd.m) if (!legal.has(m.u.slice(0, 4))) illegal++; }
      ok(illegal === 0, `${b.id} ${col} course moves legal (${illegal} illegal)`);
      const unnamed = C.lines.filter(L => !L.name || /^\d/.test(L.name) || !L.why || !L.moves).length;
      ok(unnamed === 0, `${b.id} ${col} every line has an opening name, moves and a why (${unnamed} missing)`);
      let silent = 0; for (const L of C.lines) for (let i = 0; i < L.path.length - 1; i++) { const m = C.nodes[L.path[i]].m.find(x => x.c === L.path[i + 1]); if (!(m.x || m.t)) silent++; }
      ok(silent === 0, `${b.id} ${col} every move on every line is explained (${silent} without)`);
    }
    const keys = Object.keys(d.book); let bk = 0;
    for (const k of keys.slice(0, 400)) { const c = new Chess(k + ' 0 1'); const legal = new Set(c.moves({ verbose: true }).map(m => m.from + m.to)); for (const m of d.book[k].m) if (!legal.has(m[1].slice(0, 4))) bk++; }
    ok(bk === 0, `${b.id} book moves legal (${bk} illegal)`);
    log(`${b.id}: book ${keys.length} positions · courses w ${d.courses.w.lines.length} / b ${d.courses.b.lines.length} lines · human acc ${d.human.accuracy}`);
  }
  // run the first two lessons of each course for the default band, driven automatically
  await loadBand(only || ctx.bands[0].id);
  for (const col of ['w', 'b']) {
    S.profile.color = col; setCourse();
    for (const L of ctx.course.units[0].lessons.filter(l => l.kind === 'learn').slice(0, 2)) {
      const xp0 = S.xp;
      await new Promise(res => new Lesson(ctx, L, { auto: true, onDone: res }).open());
      ok(S.xp > xp0, `lesson ${col} "${L.title}" completed and gave XP`);
      ok((prog(ctx.band.meta.id, col).lessons[L.id] || {}).level >= 1, `lesson ${col} progress saved`);
    }
  }
  // play a capped game with the real engine on both sides
  show('play');
  const eng = engine();
  for (const col of ['b', 'w']) {
    const t0 = performance.now();
    const res = await new Promise(res => { $('playSetup').hidden = true; $('game').hidden = false;
      const g = new Game({ band: ctx.band, engine: eng }, col, { auto: true, maxPlies: 30, onEnd: r => res({ r, g }) }); g.begin(); });
    ok(res.g.graded.length >= 10, `game as ${col}: ${res.g.graded.length} graded moves, ${res.g.c.history().length} plies, ${Math.round(performance.now() - t0)} ms`);
    ok(res.g.graded.every(x => ['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder'].includes(x.cat)), `game as ${col}: grades valid (${res.g.graded.map(x => x.cat[0]).join('')})`);
    log(`game as ${col}: ${res.g.c.history().join(' ')}`);
  }
  // daily streak logic, with injected dates (local calendar days)
  ok(doneToday() && streakNow() >= 1, "finishing a lesson extended today's streak");
  const keep = JSON.stringify(S.streak);
  S.streak = { n: 0, last: '', best: 0, days: [] };
  ok(recordActivity('2026-01-01').n === 1, 'streak starts at 1');
  ok(recordActivity('2026-01-01').extended === false, 'a 2nd activity the same day does not extend');
  ok(recordActivity('2026-01-02').n === 2, 'next day extends to 2');
  ok(streakNow('2026-01-03') === 2, 'still alive the next day before playing');
  ok(streakNow('2026-01-04') === 0, 'broken after a missed day');
  ok(recordActivity('2026-01-04').n === 1 && S.streak.best === 2, 'restarts at 1 and keeps best = 2');
  S.streak = { n: 0, last: '', best: 0, days: [] };
  recordActivity('2026-01-31'); ok(recordActivity('2026-02-01').n === 2, 'crosses a month boundary');
  recordActivity('2026-02-02'); S.streak.last = '2026-02-28'; S.streak.n = 5; ok(recordActivity('2026-03-01').n === 6, 'Feb 28 -> Mar 1 counts as consecutive (2026 is not a leap year)');
  ok(calendar('2026-03-01').includes('cal-d') && weekRow('2026-03-01').includes('wd'), 'streak calendar and week row render');
  S.streak = JSON.parse(keep);
  log(`SELFTEST ${fail ? 'FAIL' : 'PASS'} pass=${pass} fail=${fail}`);
  document.title = `SELFTEST ${fail ? 'FAIL' : 'PASS'} ${pass}/${pass + fail}`;
}

ctx.startGame = startGame; ctx.show = show;
boot();
