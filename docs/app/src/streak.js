// Daily streak UI: week row, calendar, streak card, celebration screen.
import { S, localDay, dayShift, dayDate, streakNow, doneToday, activeOn } from './state.js';
import { modal, sound } from './ui.js';

const WD = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const mondayOf = day => { const dow = (dayDate(day).getDay() + 6) % 7; return dayShift(day, -dow); };

export function weekRow(today = localDay()) {
  const mon = mondayOf(today);
  let h = '<div class="week-row">';
  for (let i = 0; i < 7; i++) {
    const d = dayShift(mon, i);
    const cls = activeOn(d) ? 'on' : d > today ? 'future' : d === today ? '' : 'miss';
    h += `<div class="wd ${cls} ${d === today ? 'today' : ''}"><span>${WD[i]}</span><div class="dot">${activeOn(d) ? '🔥' : ''}</div></div>`;
  }
  return h + '</div>';
}

export function calendar(today = localDay(), weeks = 6) {
  const start = dayShift(mondayOf(today), -7 * (weeks - 1));
  let h = '<div class="cal">' + WD.map(w => `<div class="cal-h">${w}</div>`).join('');
  for (let i = 0; i < weeks * 7; i++) {
    const d = dayShift(start, i);
    const cls = activeOn(d) ? 'on' : d > today ? 'future' : '';
    h += `<div class="cal-d ${cls} ${d === today ? 'today' : ''}" title="${d}">${dayDate(d).getDate()}</div>`;
  }
  return h + '</div>';
}

export function message(today = localDay()) {
  const n = streakNow(today);
  if (doneToday(today)) return `Streak extended today. Come back tomorrow to make it <b>${n + 1}</b>!`;
  if (n > 0) return `Finish one lesson or game today to keep your <b>${n}-day</b> streak alive!`;
  return 'Finish one lesson or game today to start a streak.';
}

export function streakCard(today = localDay()) {
  const n = streakNow(today), done = doneToday(today);
  return `<div class="streak-head"><div class="flame ${done ? '' : 'cold'}">🔥</div>
      <div><div class="streak-n">${n} day streak</div><div class="streak-best">Best: ${S.streak.best || 0} day${(S.streak.best || 0) === 1 ? '' : 's'}</div></div></div>
    ${weekRow(today)}<p class="streak-msg">${message(today)}</p>`;
}

export function streakModal() {
  modal(`<div class="card-title" style="font-size:22px">Daily streak</div>${streakCard()}<div class="card-title" style="margin-top:18px">Last 6 weeks</div>${calendar()}
    <p class="sub">One finished lesson, or a game of 6+ moves in Play it out, counts for the day. Days roll over at your local midnight.</p>
    <button class="btn wide" id="mOk">Got it</button>`, (el, cl) => el.querySelector('#mOk').onclick = cl);
}

export function celebrate(n, onClose) {
  sound('win');
  modal(`<div class="streak-celebrate"><div class="big-flame">🔥</div><div class="streak-big">${n}</div><h2>day streak!</h2>
      ${weekRow()}<p>${n === 1 ? 'Day one. Come back tomorrow to make it 2!' : `That's ${n} days in a row. Come back tomorrow to make it ${n + 1}!`}</p>
      <button class="btn green wide" id="mOk">Continue</button></div>`, (el, cl) => el.querySelector('#mOk').onclick = () => { cl(); onClose && onClose(); });
}
