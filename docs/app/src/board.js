// Chessboard component: drag or click-click, legal-move dots, arrows, highlights, animation, promotion.
const FILES = 'abcdefgh';
const PIECE_URL = p => `pieces/${p}.svg`;

export function parseFenBoard(fen) {
  const pos = {}; const rows = fen.split(' ')[0].split('/');
  for (let r = 0; r < 8; r++) { let f = 0;
    for (const ch of rows[r]) { if (/\d/.test(ch)) f += +ch; else { pos[FILES[f] + (8 - r)] = (ch === ch.toUpperCase() ? 'w' : 'b') + ch.toUpperCase(); f++; } } }
  return pos;
}

export class Board {
  constructor(host, opts = {}) {
    this.host = host; this.opts = opts;
    this.orient = opts.orientation || 'w';
    this.fen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
    this.last = null; this.sel = null; this.marks = {}; this.arrowList = []; this.checkSq = null;
    this.movable = null;            // 'w' | 'b' | null  (whose pieces the user may move)
    host.innerHTML = '';
    this.el = document.createElement('div'); this.el.className = 'cb'; host.appendChild(this.el);
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('class', 'cb-arrows'); this.svg.setAttribute('viewBox', '0 0 8 8'); host.appendChild(this.svg);
    this.sqs = [];
    for (let i = 0; i < 64; i++) { const d = document.createElement('div'); this.el.appendChild(d); this.sqs.push(d); }
    this.drag = null;
    this.el.addEventListener('pointerdown', e => this._down(e));
    this.el.addEventListener('pointermove', e => this._move(e));
    this.el.addEventListener('pointerup', e => this._up(e));
    this.el.addEventListener('pointercancel', () => this._cancel());
    this.render();
  }
  idxToSq(i) { const r = Math.floor(i / 8), c = i % 8; return this.orient === 'w' ? FILES[c] + (8 - r) : FILES[7 - c] + (r + 1); }
  sqToXY(sq) { const f = FILES.indexOf(sq[0]), r = +sq[1]; return this.orient === 'w' ? [f, 8 - r] : [7 - f, r - 1]; }
  sqEl(sq) { return this.sqs.find(x => x.dataset.sq === sq); }
  setOrientation(o) { this.orient = o; this.render(); }
  flip() { this.setOrientation(this.orient === 'w' ? 'b' : 'w'); }
  setPosition(fen, { last = null, animate = null, check = null } = {}) {
    this.fen = fen; this.last = last; this.checkSq = check; this.sel = null; this.marks = {}; this.render();
    if (animate) this._animate(animate.from, animate.to);
  }
  setMarks(m) { this.marks = m || {}; this.render(); }
  addMark(sq, cls) { this.marks[sq] = cls; this.render(); }
  setArrows(list) { this.arrowList = list || []; this._drawArrows(); }
  shake() { this.el.classList.remove('shake'); void this.el.offsetWidth; this.el.classList.add('shake'); }

  render() {
    const pos = parseFenBoard(this.fen);
    const dests = this.sel && this.opts.legalFrom ? this.opts.legalFrom(this.sel) : [];
    for (let i = 0; i < 64; i++) {
      const sq = this.idxToSq(i), el = this.sqs[i], f = FILES.indexOf(sq[0]), r = +sq[1];
      let cls = 'sq ' + ((f + r) % 2 === 0 ? 'l' : 'd');   // a1 (0+1) is dark, h1 (7+1) is light
      if (this.last && (this.last[0] === sq || this.last[1] === sq)) cls += ' last';
      if (this.sel === sq) cls += ' sel';
      if (this.checkSq === sq) cls += ' check';
      if (this.marks[sq]) cls += ' ' + this.marks[sq];
      el.className = cls; el.dataset.sq = sq;
      let h = '';
      if (pos[sq]) h += `<div class="pc" style="background-image:url('${PIECE_URL(pos[sq])}')"></div>`;
      if (dests.includes(sq)) h += pos[sq] ? '<div class="ring"></div>' : '<div class="dot"></div>';
      if (i % 8 === 0) h += `<span class="cr">${sq[1]}</span>`;
      if (i >= 56) h += `<span class="cf">${sq[0]}</span>`;
      el.innerHTML = h;
    }
    this._drawArrows();
  }
  _drawArrows() {
    const col = { g: '#58a700', b: '#1899d6', r: '#ea2b2b', y: '#e5b400', p: '#a568cc' };
    let h = '<defs>' + Object.entries(col).map(([k, c]) => `<marker id="ah-${k}" markerWidth="4" markerHeight="4" refX="2.05" refY="2" orient="auto"><path d="M0,0 L4,2 L0,4 z" fill="${c}"/></marker>`).join('') + '</defs>';
    for (const a of this.arrowList) {
      const [x1, y1] = this.sqToXY(a.from), [x2, y2] = this.sqToXY(a.to);
      const cx1 = x1 + .5, cy1 = y1 + .5, cx2 = x2 + .5, cy2 = y2 + .5, dx = cx2 - cx1, dy = cy2 - cy1, L = Math.hypot(dx, dy) || 1;
      const ex = cx2 - dx / L * .33, ey = cy2 - dy / L * .33, c = a.color || 'g';
      h += `<line x1="${cx1}" y1="${cy1}" x2="${ex}" y2="${ey}" stroke="${col[c]}" stroke-width="${a.width || .17}" stroke-linecap="round" opacity="${a.opacity || .85}" marker-end="url(#ah-${c})"/>`;
    }
    this.svg.innerHTML = h;
  }
  _animate(from, to) {
    const pe = this.sqEl(to)?.querySelector('.pc'); if (!pe) return;
    const [x1, y1] = this.sqToXY(from), [x2, y2] = this.sqToXY(to);
    const size = this.el.getBoundingClientRect().width / 8;
    pe.style.transition = 'none'; pe.style.transform = `translate(${(x1 - x2) * size}px, ${(y1 - y2) * size}px)`; pe.style.zIndex = 4;
    void pe.offsetWidth;
    pe.style.transition = 'transform .22s ease-out'; pe.style.transform = '';
    setTimeout(() => { pe.style.zIndex = ''; }, 260);
  }
  _sqFromPoint(x, y) {
    const r = this.el.getBoundingClientRect(); const c = Math.floor((x - r.left) / r.width * 8), rw = Math.floor((y - r.top) / r.height * 8);
    if (c < 0 || c > 7 || rw < 0 || rw > 7) return null; return this.idxToSq(rw * 8 + c);
  }
  _down(e) {
    const sq = this._sqFromPoint(e.clientX, e.clientY); if (!sq || !this.movable) return;
    const pos = parseFenBoard(this.fen), pc = pos[sq];
    if (this.sel && sq !== this.sel && !(pc && pc[0] === this.movable)) { const from = this.sel; this.sel = null; this._attempt(from, sq); return; }
    if (pc && pc[0] === this.movable) {
      this.sel = sq; this.render();
      const size = this.el.getBoundingClientRect().width / 8;
      const g = document.createElement('div'); g.className = 'drag-ghost'; g.style.width = g.style.height = size + 'px';
      g.style.backgroundImage = `url('${PIECE_URL(pc)}')`; g.style.left = e.clientX + 'px'; g.style.top = e.clientY + 'px';
      document.body.appendChild(g); this.drag = { from: sq, g };
      this.sqEl(sq)?.querySelector('.pc')?.classList.add('lift');
      this.el.setPointerCapture(e.pointerId);
    } else { this.sel = null; this.render(); }
  }
  _move(e) { if (!this.drag) return; this.drag.g.style.left = e.clientX + 'px'; this.drag.g.style.top = e.clientY + 'px'; }
  _up(e) {
    if (!this.drag) return; const d = this.drag; this.drag = null; d.g.remove();
    const to = this._sqFromPoint(e.clientX, e.clientY);
    if (to && to !== d.from) { this.sel = null; this._attempt(d.from, to); } else this.render();
  }
  _cancel() { if (this.drag) { this.drag.g.remove(); this.drag = null; this.render(); } }
  _attempt(from, to) {
    const pos = parseFenBoard(this.fen); const pc = pos[from];
    // castling by dropping the king on its rook
    const castle = { e1h1: 'g1', e1a1: 'c1', e8h8: 'g8', e8a8: 'c8' };
    if (pc && pc[1] === 'K' && castle[from + to]) to = castle[from + to];
    const legal = this.opts.legalFrom ? this.opts.legalFrom(from) : null;
    if (legal && !legal.includes(to)) { this.render(); return; }          // illegal: snap back silently
    const promoRank = pc && pc[1] === 'P' && (to[1] === '8' || to[1] === '1');
    if (promoRank) { this._promo(pc[0], p => this.opts.onMove && this.opts.onMove(from, to, p)); return; }
    this.render();
    this.opts.onMove && this.opts.onMove(from, to, undefined);
  }
  _promo(color, cb) {
    const box = document.createElement('div'); box.className = 'promo';
    box.innerHTML = '<div class="promo-row">' + ['q', 'r', 'b', 'n'].map(p => `<button data-p="${p}"><img src="${PIECE_URL(color + p.toUpperCase())}"></button>`).join('') + '</div>';
    this.host.appendChild(box);
    box.querySelectorAll('button').forEach(b => b.onclick = () => { box.remove(); this.render(); cb(b.dataset.p); });
  }
}
