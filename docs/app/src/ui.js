// Small UI helpers: sounds (WebAudio, no files), confetti, toast, modal.
import { S } from './state.js';
const $ = id => document.getElementById(id);
let actx = null;
function tone(freq, t0, dur, type = 'sine', vol = 0.18) {
  const o = actx.createOscillator(), g = actx.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, actx.currentTime + t0);
  g.gain.setValueAtTime(0.0001, actx.currentTime + t0);
  g.gain.exponentialRampToValueAtTime(vol, actx.currentTime + t0 + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + t0 + dur);
  o.connect(g).connect(actx.destination); o.start(actx.currentTime + t0); o.stop(actx.currentTime + t0 + dur + 0.02);
}
export function sound(kind) {
  if (!S.profile.sound) return;
  try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
  if (kind === 'move') tone(520, 0, 0.06, 'triangle', 0.12);
  else if (kind === 'capture') { tone(330, 0, 0.07, 'square', 0.08); tone(220, 0.05, 0.08, 'triangle', 0.1); }
  else if (kind === 'good') { tone(784, 0, 0.12); tone(1047, 0.09, 0.18); }
  else if (kind === 'bad') { tone(180, 0, 0.18, 'sawtooth', 0.09); tone(140, 0.12, 0.22, 'sawtooth', 0.08); }
  else if (kind === 'win') { [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.11, 0.22)); }
}
export function toast(msg, ms = 2200) {
  const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), ms);
}
export function modal(html, onReady) {
  const m = $('modal'); $('modalBody').innerHTML = html; m.hidden = false;
  const close = () => { m.hidden = true; };
  onReady && onReady($('modalBody'), close);
  return close;
}
export function confetti() {
  const c = $('confetti'), ctx = c.getContext('2d'); c.width = innerWidth; c.height = innerHeight;
  const cols = ['#58cc02', '#1cb0f6', '#ffc800', '#ff4b4b', '#ce82ff', '#ff9600'];
  const P = Array.from({ length: 140 }, () => ({ x: innerWidth / 2 + (Math.random() - .5) * 200, y: innerHeight * .35, vx: (Math.random() - .5) * 14, vy: -Math.random() * 14 - 4, s: 6 + Math.random() * 6, r: Math.random() * 6, vr: (Math.random() - .5) * .3, c: cols[(Math.random() * cols.length) | 0] }));
  let f = 0;
  (function step() {
    ctx.clearRect(0, 0, c.width, c.height);
    for (const p of P) { p.vy += .35; p.x += p.vx; p.y += p.vy; p.r += p.vr; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.c; ctx.fillRect(-p.s / 2, -p.s / 3, p.s, p.s * .66); ctx.restore(); }
    if (++f < 150) requestAnimationFrame(step); else ctx.clearRect(0, 0, c.width, c.height);
  })();
}
export const pct = p => p >= 0.095 ? Math.round(p * 100) + '%' : (p * 100).toFixed(1) + '%';
export const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;');
export const fmtEval = cp => cp == null ? '' : Math.abs(cp) >= 9000 ? (cp > 0 ? '+' : '−') + 'M' + Math.max(1, Math.ceil((10000 - Math.abs(cp)) / 2)) : (cp >= 0 ? '+' : '−') + (Math.abs(cp) / 100).toFixed(1);
export function sanLabel(san, ply) { return (ply % 2 === 0 ? (ply / 2 + 1) + '.' : Math.floor(ply / 2) + 1 + '...') + san; }
export function plyOfFen(fen) { const p = fen.split(' '); return (parseInt(p[5]) - 1) * 2 + (p[1] === 'b' ? 1 : 0); }
