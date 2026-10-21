// Persistent state + gamification: XP, daily goal, daily streak, lesson progress, spaced repetition.
const KEY = 'gambito-v1';
const DAY = 86400000;
let mem = null;            // test mode keeps state in memory only
export const TEST = new URLSearchParams(location.search).get('selftest') === '1';

// Local calendar day (YYYY-MM-DD). The streak rolls over at the learner's own midnight, not UTC.
export function localDay(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function dayShift(day, delta) { const [y, m, d] = day.split('-').map(Number); return localDay(new Date(y, m - 1, d + delta)); }
export function dayDate(day) { const [y, m, d] = day.split('-').map(Number); return new Date(y, m - 1, d); }

function defaults() {
  return { v: 1, profile: { band: null, color: 'w', sound: true, onboarded: false, goal: 30 },
    xp: 0, day: { date: localDay(), xp: 0 }, streak: { n: 0, last: '', best: 0, days: [] }, prog: {}, games: [] };
}
function migrate(s) {
  delete s.hearts;                                         // hearts were removed
  s.streak = Object.assign({ n: 0, last: '', best: 0, days: [] }, s.streak || {});
  if (!Array.isArray(s.streak.days)) s.streak.days = [];
  s.streak.best = Math.max(s.streak.best || 0, s.streak.n || 0);
  return s;
}
function load() {
  if (TEST) return mem || (mem = defaults());
  try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && s.v === 1) return migrate(Object.assign(defaults(), s)); } catch (e) {}
  return defaults();
}
export const S = load();
export function save() { if (TEST) { mem = S; return; } try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
export function resetAll() { const d = defaults(); for (const k of Object.keys(S)) delete S[k]; Object.assign(S, d); save(); }

// ---------------------------------------------------------------- XP + daily goal
export function rollDay() { const t = localDay(); if (S.day.date !== t) { S.day = { date: t, xp: 0 }; save(); } }
export function addXP(n) { rollDay(); S.xp += n; S.day.xp += n; save(); }

// ---------------------------------------------------------------- daily streak
// One finished lesson or one real game on a day keeps the streak alive. Miss a whole day and it resets.
export function streakNow(today = localDay()) {
  const s = S.streak; return (s.last === today || s.last === dayShift(today, -1)) ? s.n : 0;
}
export function doneToday(today = localDay()) { return S.streak.last === today; }
export function streakAtRisk(today = localDay()) { return !doneToday(today) && streakNow(today) > 0; }
export function recordActivity(today = localDay()) {
  const s = S.streak;
  if (s.last === today) return { extended: false, n: s.n };
  s.n = s.last === dayShift(today, -1) ? s.n + 1 : 1;
  s.last = today; s.best = Math.max(s.best || 0, s.n);
  if (!s.days.includes(today)) s.days.push(today);
  s.days.sort(); if (s.days.length > 800) s.days = s.days.slice(-800);
  save();
  return { extended: true, n: s.n };
}
export function activeOn(day) { return S.streak.days.includes(day); }

// ---------------------------------------------------------------- progress + spaced repetition
export function prog(band, color) {
  S.prog[band] = S.prog[band] || {}; S.prog[band][color] = S.prog[band][color] || { lessons: {}, lines: {} };
  return S.prog[band][color];
}
export function lessonDone(band, color, id, perfect) {
  const p = prog(band, color); const L = p.lessons[id] || { level: 0, perfect: 0 };
  L.level = Math.min(5, L.level + 1); L.last = Date.now(); if (perfect) L.perfect++; p.lessons[id] = L; save();
}
const BOX_DAYS = [0, 1, 3, 7, 16, 35];
export function lineReviewed(band, color, lineId, clean) {
  const p = prog(band, color); const L = p.lines[lineId] || { box: 0 };
  L.box = clean ? Math.min(BOX_DAYS.length - 1, L.box + 1) : 1; L.due = Date.now() + BOX_DAYS[L.box] * DAY; L.seen = true; p.lines[lineId] = L; save();
}
export function lineSeen(band, color, lineId) { return !!(prog(band, color).lines[lineId] || {}).seen; }
export function recordGame(g) { S.games.unshift(g); S.games = S.games.slice(0, 50); save(); }
