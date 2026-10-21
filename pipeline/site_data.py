"""Build the website's per-band data files.

For each Elo band:
  tree   : opening tree from the band's games (random-side shares, like tree.py)
  book   : positions reached by >= BOOK_MIN games (ply <= BOOK_MAXPLY) with move shares, scores,
           Stockfish evals (depth 12) and a practical-best move for the side to move
  human  : how often real players at this band play best / good / inaccurate / mistake / blunder moves
           (measured by Stockfish on a sample of real games) -> the bot's error model
  course : lesson tree. ~300 band = the hand-built repertoire; other bands = auto-built from the book
           (practical-best moves for us, most common replies for them, auto-written explanations)
  stats  : what this band plays, how games end
Usage: py site_data.py [band ids...]   (default: every band whose games file exists)
"""
import json, os, sys, pickle, random, math, time, csv, hashlib
from collections import defaultdict, Counter
import chess
from evaldb import EvalDB, fkey
from site_build import write_data_js, read_data_js   # data ships as .js so the site works from disk

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR, SITE_DIR
DATA = DATA
BDIR = os.path.join(DATA, "bands")
OUT = os.path.join(SITE_DIR, "data")
OPEN_DIR = os.path.join(HERE, "openings")

BANDS = [
    dict(id="r0300", label="Under 400", rng="200–400", lo=200, hi=400, nick="Pawn", games=os.path.join(DATA, "games.jsonl"),
         tree=os.path.join(DATA, "tree_200_400.pkl"), curated=True),
    dict(id="r0500", label="400–600", rng="400–600", lo=400, hi=600, nick="Knight"),
    dict(id="r0700", label="600–800", rng="600–800", lo=600, hi=800, nick="Bishop"),
    dict(id="r0900", label="800–1000", rng="800–1000", lo=800, hi=1000, nick="Rook"),
    dict(id="r1100", label="1000–1200", rng="1000–1200", lo=1000, hi=1200, nick="Queen"),
    dict(id="r1300", label="1200–1400", rng="1200–1400", lo=1200, hi=1400, nick="King"),
    dict(id="r1500", label="1400–1600", rng="1400–1600", lo=1400, hi=1600, nick="Club player"),
    dict(id="r1700", label="1600–1800", rng="1600–1800", lo=1600, hi=1800, nick="Expert"),
    dict(id="r1900", label="1800–2000", rng="1800–2000", lo=1800, hi=2000, nick="Master class"),
    dict(id="r2200", label="2000+", rng="2000–2400", lo=2000, hi=2400, nick="Elite"),
]
for B in BANDS:
    B.setdefault("games", os.path.join(BDIR, B["id"], "games.jsonl"))
    B.setdefault("tree", os.path.join(BDIR, B["id"], "tree.pkl"))
    B.setdefault("curated", False)

MAXPLY, MIN_KEEP = 24, 3
BOOK_MIN, BOOK_MAXPLY = 15, 20
EV_DEPTH, HUMAN_DEPTH = 12, 10
COURSE_MAXPLY, COURSE_MAXLINES = 16, 70
PIECE_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def key(b):
    return " ".join(b.fen(en_passant="legal").split()[:4])


def wp(cp):
    cp = max(-2000, min(2000, cp))
    return 1 / (1 + math.exp(-0.00368208 * cp))


def iter_games(path, lo, hi):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                g = json.loads(line)
            except Exception:
                continue
            if lo <= g["wr"] <= hi and lo <= g["br"] <= hi:
                yield g


# ---------------------------------------------------------------- tree
def build_tree(B):
    if os.path.exists(B["tree"]):
        return pickle.load(open(B["tree"], "rb"))["nodes"]
    log(B["id"], "building tree")
    seen = Counter()
    for g in iter_games(B["games"], B["lo"], B["hi"]):
        b = chess.Board()
        for san in g["mv"][:MAXPLY]:
            seen[hash(key(b))] += 1
            try:
                b.push_san(san)
            except Exception:
                break
    keep = {h for h, c in seen.items() if c >= MIN_KEEP}
    del seen
    nodes = defaultdict(lambda: {"n": 0, "nr": 0, "mv": defaultdict(lambda: [0, 0, 0.0, None])})
    for g in iter_games(B["games"], B["lo"], B["hi"]):
        s = 1.0 if g["wres"] == "win" else 0.0 if g["bres"] == "win" else 0.5
        b = chess.Board()
        for san in g["mv"][:MAXPLY]:
            k = key(b)
            if hash(k) not in keep:
                break
            nd = nodes[k]
            nd["n"] += 1
            rand = g["owner"] != ("w" if b.turn else "b")
            nd["nr"] += 1 if rand else 0
            try:
                mv = b.parse_san(san)
            except Exception:
                break
            e = nd["mv"][b.san(mv)]
            e[0] += 1
            e[1] += 1 if rand else 0
            e[2] += s
            e[3] = mv.uci()
            b.push(mv)
    out = {k: {"n": v["n"], "nr": v["nr"], "mv": {m: tuple(x) for m, x in v["mv"].items()}} for k, v in nodes.items()}
    os.makedirs(os.path.dirname(B["tree"]), exist_ok=True)
    pickle.dump({"nodes": out}, open(B["tree"], "wb"))
    return out


def share(nd, san):
    a, r, ws, uci = nd["mv"][san]
    return (r / nd["nr"]) if nd["nr"] >= 10 else (a / nd["n"])


# ---------------------------------------------------------------- book + evals
def book_positions(T):
    S = {}
    stack = [(chess.Board(), 0)]
    while stack:
        b, ply = stack.pop()
        k = key(b)
        if k in S:
            continue
        nd = T.get(k)
        if not nd or nd["n"] < BOOK_MIN:
            continue
        S[k] = (b.fen(), ply)
        if ply >= BOOK_MAXPLY:
            continue
        for san, (a, r, ws, uci) in nd["mv"].items():
            if a >= 3:
                b2 = b.copy()
                b2.push(chess.Move.from_uci(uci))
                stack.append((b2, ply + 1))
    return S


def child_fen(fen, uci):
    b = chess.Board(fen)
    b.push(chess.Move.from_uci(uci))
    return b.fen()


def evaluate_book(B, T, S, db):
    fens = [f for f, _ in S.values()]
    EV = db.eval_many(fens, EV_DEPTH, label=f"{B['id']} positions")
    extra = []
    for k, (fen, ply) in S.items():
        nd = T[k]
        for san, (a, r, ws, uci) in nd["mv"].items():
            if a >= 5 or share(nd, san) >= 0.02:
                extra.append(child_fen(fen, uci))
        best = EV.get(fkey(fen), (None, None, None))[2]
        if best:
            extra.append(child_fen(fen, best))
    EV.update(db.eval_many(extra, EV_DEPTH, label=f"{B['id']} children"))
    return EV


def practical_best(k, fen, T, EV):
    """Among moves within 4 win-% points of Stockfish's best, pick the one that scores best against
    the real reply distribution of this band (1-ply lookahead). Returns (uci, engine_best_uci)."""
    b = chess.Board(fen)
    side = b.turn
    sign = 1 if side == chess.WHITE else -1
    ev = EV.get(fkey(fen))
    if not ev:
        return None, None
    nd = T.get(k)
    cands = set()
    if ev[2]:
        cands.add(ev[2])
    if nd:
        for san, (a, r, ws, uci) in nd["mv"].items():
            if a >= 8:
                cands.add(uci)

    def after(uci):
        b2 = b.copy()
        b2.push(chess.Move.from_uci(uci))
        return b2

    def v_engine(uci):
        e2 = EV.get(fkey(after(uci).fen()))
        return None if not e2 else wp(sign * e2[0])

    def v_prac(uci, base):
        b2 = after(uci)
        nd2 = T.get(key(b2))
        if not nd2 or nd2["nr"] < 30:
            return base
        acc = cov = 0.0
        for san2, (a2, r2, ws2, u2) in nd2["mv"].items():
            sh = r2 / nd2["nr"]
            if sh < 0.02:
                continue
            b3 = b2.copy()
            b3.push(chess.Move.from_uci(u2))
            e3 = EV.get(fkey(b3.fen()))
            if not e3:
                continue
            acc += sh * wp(sign * e3[0])
            cov += sh
        return acc + (1 - cov) * base

    eng = {u: v_engine(u) for u in cands}
    eng = {u: v for u, v in eng.items() if v is not None}
    if not eng:
        return ev[2], ev[2]
    top = max(eng.values())
    ok = [u for u, v in eng.items() if v >= top - 0.04]
    prac = {u: v_prac(u, eng[u]) for u in ok}
    return max(prac, key=prac.get), ev[2]


def build_book(B, T, S, EV):
    book = {}
    for k, (fen, ply) in S.items():
        nd = T[k]
        ev = EV.get(fkey(fen))
        if not ev:
            continue
        moves = []
        for san, (a, r, ws, uci) in nd["mv"].items():
            sh = share(nd, san)
            if sh < 0.01 and a < 5:
                continue
            e2 = EV.get(fkey(child_fen(fen, uci)))
            moves.append([san, uci, round(sh, 4), a, round(ws / a, 3), None if not e2 else e2[0]])
        moves.sort(key=lambda m: -m[2])
        pb, eb = practical_best(k, fen, T, EV)
        book[k] = {"n": nd["n"], "nr": nd["nr"], "ply": ply, "e": ev[0], "b": eb, "p": pb, "m": moves[:12]}
    return book


# ---------------------------------------------------------------- human error model
def human_model(B, db, n_games=150, seed=7):
    rnd = random.Random(seed)
    sample = []
    for i, g in enumerate(iter_games(B["games"], B["lo"], B["hi"])):
        if len(g["mv"]) < 20:
            continue
        if len(sample) < n_games:
            sample.append(g)
        else:
            j = rnd.randint(0, i)
            if j < n_games:
                sample[j] = g
    # games.jsonl keeps only the first 40 plies, so this measures moves 1-20 (opening + early middlegame)
    seqs, fens = [], []
    for g in sample:
        b = chess.Board()
        seq = [b.fen()]
        for san in g["mv"]:
            try:
                b.push_san(san)
            except Exception:
                break
            seq.append(b.fen())
        seqs.append(seq)
        fens.extend(seq)
    EV = db.eval_many(fens, HUMAN_DEPTH, label=f"{B['id']} human")
    cats = {"opening": Counter(), "middle": Counter()}
    accs = []
    for seq in seqs:
        for i in range(len(seq) - 1):
            before, after = EV.get(fkey(seq[i])), EV.get(fkey(seq[i + 1]))
            if not before or not after:
                continue
            white = seq[i].split()[1] == "w"
            sign = 1 if white else -1
            loss = max(0.0, wp(sign * before[0]) - wp(sign * after[0]))
            phase = "opening" if i < 20 else "middle"
            c = "best" if loss <= 0.02 else "good" if loss <= 0.05 else "inaccuracy" if loss <= 0.10 else "mistake" if loss <= 0.20 else "blunder"
            cats[phase][c] += 1
            accs.append(max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss * 100) - 3.1669)))
    out = {}
    for ph, c in cats.items():
        tot = sum(c.values()) or 1
        out[ph] = {k: round(c[k] / tot, 4) for k in ("best", "good", "inaccuracy", "mistake", "blunder")}
        out[ph]["n"] = sum(c.values())
    out["accuracy"] = round(sum(accs) / max(1, len(accs)), 1)
    out["games"] = len(sample)
    return out


# ---------------------------------------------------------------- opening names
def load_openings():
    names = {}
    for fn in "abcde":
        p = os.path.join(OPEN_DIR, f"{fn}.tsv")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            rd = csv.reader(f, delimiter="\t")
            next(rd)
            for row in rd:
                if len(row) < 3:
                    continue
                eco, name, pgn = row[0], row[1], row[2]
                b = chess.Board()
                ok = True
                for tok in pgn.split():
                    if tok.endswith("."):
                        continue
                    try:
                        b.push_san(tok)
                    except Exception:
                        ok = False
                        break
                if ok:
                    names[key(b)] = name
    return names


# ---------------------------------------------------------------- auto explanations
def pct(x):
    return f"{100*x:.0f}%" if x >= 0.095 else f"{100*x:.1f}%"


def fmt_eval(cp_white):
    if cp_white is None:
        return ""
    if abs(cp_white) >= 9000:
        return ("+" if cp_white > 0 else "−") + "mate"
    return ("+" if cp_white >= 0 else "−") + f"{abs(cp_white)/100:.1f}"


def describe_ours(b, mv, ev_after, own_share, band_label, notes):
    b2 = b.copy()
    b2.push(mv)
    us, them = b.turn, not b.turn
    piece = b.piece_at(mv.from_square)
    pname = PIECE_NAME[piece.piece_type]
    if b2.is_checkmate():
        return "Checkmate! 🎉"
    cap = b.piece_at(mv.to_square)
    if b.is_en_passant(mv):
        cap = chess.Piece(chess.PAWN, them)
    to = chess.square_name(mv.to_square)
    hits = [sq for sq in b2.attacks(mv.to_square) if b2.piece_at(sq) and b2.piece_at(sq).color == them]
    safe = (not b2.is_attacked_by(them, mv.to_square)) or b2.is_attacked_by(us, mv.to_square)
    weak = chess.F7 if us == chess.WHITE else chess.F2
    pins = [sq for sq in chess.SQUARES if b2.piece_at(sq) and b2.piece_at(sq).color == them
            and b2.piece_at(sq).piece_type != chess.KING and b2.is_pinned(them, sq) and not b.is_pinned(them, sq)]
    if b.is_castling(mv):
        main = "Castle: your king is safe and your rook joins the game"
    elif cap:
        main = f"Take the {PIECE_NAME[cap.piece_type]}"
    elif piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(mv.from_square) in (0, 7):
        main = f"Develop your {pname}"
    elif piece.piece_type == chess.PAWN and to in ("e4", "d4", "e5", "d5", "c4", "c5", "f4", "f5"):
        main = "Claim the centre with a pawn"
    elif piece.piece_type == chess.PAWN:
        main = f"Push your {to[0]}-pawn"
    elif piece.piece_type == chess.QUEEN:
        main = f"Bring your queen to {to}"
    else:
        main = f"{pname.capitalize()} to {to}"
    big = [sq for sq in hits if b2.piece_at(sq).piece_type in (chess.QUEEN, chess.ROOK, chess.KING)
           or (VAL[b2.piece_at(sq).piece_type] >= 3 and not b2.is_attacked_by(them, sq))]
    undefended = [sq for sq in hits if VAL[b2.piece_at(sq).piece_type] >= 3 and b2.piece_at(sq).piece_type != chess.KING
                  and not b2.is_attacked_by(them, sq)]
    if len(big) >= 2 and safe:
        extra = ". Fork! It hits the " + " and the ".join(PIECE_NAME[b2.piece_at(sq).piece_type] for sq in big[:2])
    elif b2.is_check():
        extra = " with check"
    elif pins:
        extra = f", pinning the {PIECE_NAME[b2.piece_at(pins[0]).piece_type]}"
    elif any(b2.piece_at(sq).piece_type == chess.QUEEN for sq in hits) and not cap:
        extra = ", hitting the queen"
    elif piece.piece_type == chess.PAWN and any(b2.piece_at(sq).piece_type != chess.PAWN for sq in hits):
        nm = next(PIECE_NAME[b2.piece_at(sq).piece_type] for sq in hits if b2.piece_at(sq).piece_type != chess.PAWN)
        extra = f", kicking the {nm}"
    elif undefended and safe:
        extra = f", attacking the loose {PIECE_NAME[b2.piece_at(undefended[0]).piece_type]}"
    elif piece.piece_type in (chess.BISHOP, chess.QUEEN) and weak in b2.attacks(mv.to_square):
        extra = f", aiming at {chess.square_name(weak)}, the weakest square"
    else:
        extra = ""
    text = main + extra + "."
    for n in notes:
        text += " " + n
    if own_share:
        text += f" {pct(own_share)} of {band_label} players find this."
    if ev_after is not None:
        text += f" Stockfish: {fmt_eval(ev_after)}."
    return text


def describe_theirs(loss, sh, n, band_label):
    t = f"{pct(sh)} of {band_label} players play this here" + (f" (n={n})." if n else ".")
    if loss >= 0.30:
        return "Blunder! " + t + " Punish it."
    if loss >= 0.15:
        return "A mistake. " + t
    if loss >= 0.07:
        return "Slightly inaccurate. " + t
    return t


# ---------------------------------------------------------------- courses
def auto_course(B, T, book, EV, color, names, db):
    """Course tree built straight from the band's opening tree (not just the exported book):
    our side = practical-best move (within 4 win-% points of Stockfish's best, then the one that scores best
    against this band's real replies); their side = replies played by >= 6% of the band, plus rarer ones
    (>= 3%) that are real blunders. Positions are evaluated on demand."""
    our = chess.WHITE if color == "w" else chess.BLACK
    sign = 1 if our == chess.WHITE else -1
    nodes, index = [], {}
    budget = [1800]

    def need(fens):
        miss = list({fkey(f): f for f in fens if fkey(f) not in EV}.values())
        if miss:
            EV.update(db.eval_many(miss, EV_DEPTH, log_every=0))

    def cp(fen):
        return EV[fkey(fen)][0]

    def node_for(b, path):
        k = key(b)
        if k not in index:
            index[k] = len(nodes)
            nodes.append({"f": b.fen(), "m": [], "_k": path})
        return index[k]

    def practical(b):
        fen = b.fen()
        nd = T.get(key(b))
        need([fen])
        best = EV[fkey(fen)][2]
        cands = {best} if best else set()
        if nd:
            cands |= {uci for san, (a, r, ws, uci) in nd["mv"].items() if a >= 6}
        kids = {u: child_fen(fen, u) for u in cands}
        need(list(kids.values()))
        gk = []
        for u, cf in kids.items():
            nd2 = T.get(fkey(cf))
            if nd2 and nd2["nr"] >= 20:
                gk += [child_fen(cf, u2) for s2, (a2, r2, w2, u2) in nd2["mv"].items() if r2 / nd2["nr"] >= 0.04]
        need(gk)
        eng = {u: wp(sign * cp(cf)) for u, cf in kids.items()}
        top = max(eng.values())
        ok = [u for u, v in eng.items() if v >= top - 0.04]

        def prac(u):
            cf = kids[u]
            nd2 = T.get(fkey(cf))
            if not nd2 or nd2["nr"] < 20:
                return eng[u]
            acc = cov = 0.0
            for s2, (a2, r2, w2, u2) in nd2["mv"].items():
                sh = r2 / nd2["nr"]
                if sh >= 0.04:
                    acc += sh * wp(sign * cp(child_fen(cf, u2)))
                    cov += sh
            return acc + (1 - cov) * eng[u]
        pr = {u: prac(u) for u in ok}
        return max(pr, key=pr.get), best

    def common_mistake(b2):
        """after our move: the most damaging reply that this band plays often"""
        nd2 = T.get(key(b2))
        if not nd2 or nd2["nr"] < 20:
            return None
        f2 = b2.fen()
        reps = [(r2 / nd2["nr"], s2, u2) for s2, (a2, r2, w2, u2) in nd2["mv"].items() if r2 / nd2["nr"] >= 0.08]
        need([f2] + [child_fen(f2, u) for _, _, u in reps])
        best_wp = wp(-sign * cp(f2))
        worst = None
        for sh, s2, u2 in reps:
            loss = best_wp - wp(-sign * cp(child_fen(f2, u2)))
            if loss >= 0.08 and (worst is None or sh * loss > worst[0]):
                worst = (sh * loss, s2, sh, loss)
        return worst

    def expand(b, ply, path):
        ni = node_for(b, path)
        nd = T.get(key(b))
        if ply >= COURSE_MAXPLY or not nd or nodes[ni]["m"] or budget[0] <= 0:
            return
        budget[0] -= 1
        if b.turn == our:
            if nd["n"] < 8:
                return
            pu, best = practical(b)
            mv = chess.Move.from_uci(pu)
            san = b.san(mv)
            b2 = b.copy()
            b2.push(mv)
            own = share(nd, san) if san in nd["mv"] else None
            notes = []
            cm = common_mistake(b2)
            if cm:
                notes.append(f"Watch for {cm[1]}: {pct(cm[2])} of {B['label']} players answer with it, and it's a mistake you can punish.")
            elif best and pu != best:
                notes.append(f"Stockfish rates it as good as the top move, and {B['label']} opponents go wrong after it more often.")
            e2 = cp(b2.fen())
            ci = node_for(b2, path + (pu,))
            nodes[ni]["m"].append({"s": san, "u": pu, "c": ci, "o": 1, "p": None, "n": 0, "g": None, "e": e2,
                                   "t": describe_ours(b, mv, e2, own, B["label"], notes)})
            expand(b2, ply + 1, path + (pu,))
        else:
            if nd["nr"] < 20:
                return
            fen = b.fen()
            reps = []
            for san, (a, r, ws, uci) in nd["mv"].items():
                sh = r / nd["nr"]
                if sh < 0.03:
                    continue
                c2 = T.get(fkey(child_fen(fen, uci)))
                if not c2 or c2["n"] < 8:
                    continue
                reps.append((sh, san, uci, a))
            reps.sort(reverse=True)
            need([fen] + [child_fen(fen, u) for _, _, u, _ in reps])
            best_wp = wp(-sign * cp(fen))
            chosen = []
            for sh, san, uci, a in reps:
                loss = max(0.0, best_wp - wp(-sign * cp(child_fen(fen, uci))))
                if sh >= 0.06 or loss >= 0.25:
                    chosen.append((sh, san, uci, a, loss))
            for sh, san, uci, a, loss in chosen[:5]:
                b2 = b.copy()
                b2.push(chess.Move.from_uci(uci))
                ci = node_for(b2, path + (uci,))
                nodes[ni]["m"].append({"s": san, "u": uci, "c": ci, "o": 0, "p": round(sh, 4), "n": a, "q": round(sh, 4),
                                       "t": describe_theirs(loss, sh, a, B["label"]), "g": "trap" if loss >= 0.30 else None,
                                       "e": cp(b2.fen())})
                expand(b2, ply + 1, path + (uci,))

    expand(chess.Board(), 0, ())
    return finish_course(B, nodes, color, names, source="auto")


def finish_course(B, nodes, color, names, source, sections=None):
    """Enumerate lines, keep the most common, name them, group into units/lessons."""
    our = chess.WHITE if color == "w" else chess.BLACK
    paths = []

    def dfs(ni, path):
        if not nodes[ni]["m"] or len(path) > 40:
            paths.append(list(path))
            return
        for m in nodes[ni]["m"]:
            if m["c"] in path:
                continue
            path.append(m["c"])
            dfs(m["c"], path)
            path.pop()
    dfs(0, [0])
    lines = []
    for p in paths:
        w, ucis, sans = 1.0, [], []
        b = chess.Board()
        last_name = None
        for a, c in zip(p, p[1:]):
            m = next(x for x in nodes[a]["m"] if x["c"] == c)
            if not m["o"]:
                w *= (m.get("q") if m.get("q") is not None else (m["p"] if m["p"] is not None else 0.0))
            ucis.append(m["u"])
            sans.append(m["s"])
            b.push(chess.Move.from_uci(m["u"]))
            nm = names.get(key(b))
            if nm:
                last_name = nm
        if len(p) < 3:
            continue
        lid = color + "-" + hashlib.sha1(" ".join(ucis).encode()).hexdigest()[:10]
        lines.append({"id": lid, "path": p, "w": round(w, 6), "name": last_name or " ".join(sans[:4]), "ucis": ucis, "sans": sans})
    lines.sort(key=lambda L: -L["w"])
    if source == "auto":
        lines = lines[:COURSE_MAXLINES]
    # units: by the first opponent move (for black: white's 1st move; for white: black's reply to our 1st move)
    first_opp = 0 if our == chess.BLACK else 1
    units = {}
    for L in lines:
        if sections and L.get("sec"):
            ukey = L["sec"]
        else:
            ukey = L["sans"][first_opp] if len(L["sans"]) > first_opp else "other"
        units.setdefault(ukey, []).append(L)
    unit_list = []
    for ukey, Ls in sorted(units.items(), key=lambda kv: -sum(L["w"] for L in kv[1])):
        uw = sum(L["w"] for L in Ls)
        if sections:
            title = ukey
        else:
            mv = ("1." if our == chess.BLACK else "1..." ) + ukey
            nm = None
            b = chess.Board()
            for u in Ls[0]["ucis"][:first_opp + 1]:
                b.push(chess.Move.from_uci(u))
            nm = names.get(key(b))
            title = f"vs {mv}" + (f" · {nm}" if nm else "")
        lessons = []
        Ls = sorted(Ls, key=lambda L: -L["w"])
        for i in range(0, len(Ls), 2):
            chunk = Ls[i:i + 2]
            lessons.append({"id": hashlib.sha1((color + ukey + chunk[0]["id"]).encode()).hexdigest()[:10], "kind": "learn",
                            "title": chunk[0]["name"], "lines": [L["id"] for L in chunk]})
        lessons.append({"id": hashlib.sha1((color + ukey + "match").encode()).hexdigest()[:10], "kind": "match",
                        "title": "Play it out", "start": Ls[0]["ucis"][:first_opp + 1]})
        unit_list.append({"id": hashlib.sha1((color + ukey).encode()).hexdigest()[:8], "title": title,
                          "sub": f"Comes up in about {pct(uw)} of games" if uw >= 0.001 else "Rare but deadly", "lessons": lessons})
    # legal moves for our nodes (the trainer-style input check)
    for nd in nodes:
        b = chess.Board(nd["f"])
        if b.turn == our and nd["m"]:
            nd["L"] = [m.uci() for m in b.legal_moves]
    clean_nodes = [{k: v for k, v in n.items() if not k.startswith("_")} for n in nodes]
    for n in clean_nodes:
        n["m"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in n["m"]]
    return {"color": color, "source": source, "nodes": clean_nodes,
            "lines": [{"id": L["id"], "path": L["path"], "w": L["w"], "name": L["name"]} for L in lines], "units": unit_list}


def curated_courses(names):
    """The hand-built ~300 repertoire (rep_white/rep_black via build.py, depth-20 evals cached)."""
    import build
    from sf import Engine
    T1, T2 = build.load_trees()
    out = {}
    with Engine() as E:
        for C in build.COURSES:
            R = build.build_course(C, T1, T2, E, do_engine=True)
            nodes = R["nodes"]
            lines = []
            for L in sorted(R["lines"], key=lambda L: -L["w"]):
                lines.append({"id": L["id"], "path": L["path"], "w": L["w"], "name": L["name"], "sec": L["sec"]})
            units = {}
            order = []
            for L in R["lines"]:
                if L["sec"] not in units:
                    units[L["sec"]] = []
                    order.append(L["sec"])
            for L in lines:
                units[L["sec"]].append(L)
            first_opp = 0 if C["color"] == "b" else 1
            unit_list = []
            for sec in sorted(order, key=lambda s: -sum(L["w"] for L in units[s])):
                Ls = units[sec]
                uw = sum(L["w"] for L in Ls)
                lessons = []
                for i in range(0, len(Ls), 2):
                    chunk = Ls[i:i + 2]
                    lessons.append({"id": hashlib.sha1((C["color"] + sec + chunk[0]["id"]).encode()).hexdigest()[:10], "kind": "learn",
                                    "title": chunk[0]["name"], "lines": [x["id"] for x in chunk]})
                # match starts after the unit's defining moves
                p = Ls[0]["path"]
                ucis = []
                for a, c in zip(p, p[1:]):
                    m = next(x for x in nodes[a]["m"] if x["c"] == c)
                    ucis.append(m["u"])
                lessons.append({"id": hashlib.sha1((C["color"] + sec + "match").encode()).hexdigest()[:10], "kind": "match",
                                "title": "Play it out", "start": ucis[:first_opp + 1]})
                unit_list.append({"id": hashlib.sha1((C["color"] + sec).encode()).hexdigest()[:8], "title": sec,
                                  "sub": f"Comes up in about {pct(uw)} of games" if uw >= 0.001 else "Rare but deadly", "lessons": lessons})
            clean = [{k: v for k, v in n.items() if not k.startswith("_")} for n in nodes]
            for n in clean:
                n["m"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in n["m"]]
            out[C["color"]] = {"color": C["color"], "source": "curated", "nodes": clean,
                               "lines": [{k: v for k, v in L.items() if k != "sec"} for L in lines], "units": unit_list}
    return out


# ---------------------------------------------------------------- stats
def band_stats(B, T):
    res, term, plies, players, ratings = Counter(), Counter(), [], set(), []
    n = 0
    for g in iter_games(B["games"], B["lo"], B["hi"]):
        n += 1
        res["w" if g["wres"] == "win" else "b" if g["bres"] == "win" else "d"] += 1
        t = g["term"].lower()
        term["checkmate" if "checkmate" in t else "resignation" if "resignation" in t else "abandoned" if "abandon" in t else "time" if "time" in t else "draw"] += 1
        plies.append(g["plies"])
        players.add(g["w"].lower())
        players.add(g["b"].lower())
        ratings += [g["wr"], g["br"]]

    def top(moves_seq, k=8):
        b = chess.Board()
        for m in moves_seq.split():
            b.push_san(m)
        nd = T.get(key(b))
        if not nd:
            return []
        rows = sorted(nd["mv"].items(), key=lambda kv: -share(nd, kv[0]))[:k]
        return [[san, round(share(nd, san), 4), a, round(ws / a, 3)] for san, (a, r, ws, uci) in rows]
    plies.sort()
    ratings.sort()
    return {"games": n, "players": len(players), "median_moves": plies[len(plies) // 2] // 2 if plies else 0,
            "rating_p50": ratings[len(ratings) // 2] if ratings else 0,
            "results": {k: round(v / max(1, n), 4) for k, v in res.items()},
            "endings": {k: round(v / max(1, n), 4) for k, v in term.items()},
            "first": top(""), "vs_e4": top("e4"), "vs_d4": top("d4"), "after_e4e5": top("e4 e5")}


# ---------------------------------------------------------------- main
def process(B, db, names):
    t0 = time.time()
    T = build_tree(B)
    S = book_positions(T)
    log(B["id"], f"tree {len(T)} nodes, book {len(S)} positions")
    EV = evaluate_book(B, T, S, db)
    book = build_book(B, T, S, EV)
    human = human_model(B, db)
    if B["curated"]:
        courses = curated_courses(names)
        # the hand-built repertoire is the "best" pick wherever it has an opinion, so play-mode grading
        # agrees with the lessons (e.g. 1...e5 rather than the raw practical pick 1...d5 at this band)
        for c in courses.values():
            for nd in c["nodes"]:
                for m in nd["m"]:
                    if m["o"]:
                        k = " ".join(nd["f"].split()[:4])
                        if k in book:
                            book[k]["p"] = m["u"]
                            book[k]["src"] = "rep"
    else:
        courses = {c: auto_course(B, T, book, EV, c, names, db) for c in ("w", "b")}
    stats = band_stats(B, T)
    meta = {k: B[k] for k in ("id", "label", "rng", "lo", "hi", "nick", "curated")}
    os.makedirs(OUT, exist_ok=True)
    payload = {"meta": meta, "stats": stats, "human": human, "book": book, "courses": courses,
               "generated": time.strftime("%Y-%m-%d")}
    from explain import enrich_band, load_names       # opening names, why-it's-good, every move's purpose
    enrich_band(payload, load_names())
    path = os.path.join(OUT, f"band_{B['id']}.js")
    write_data_js(path, payload)
    log(B["id"], f"wrote {os.path.getsize(path)//1024} KB in {time.time()-t0:.0f}s: book {len(book)}, "
        f"courses w={len(courses['w']['lines'])} b={len(courses['b']['lines'])} lines, human acc {human['accuracy']}")
    return {"id": B["id"], "label": B["label"], "rng": B["rng"], "nick": B["nick"], "curated": B["curated"],
            "games": stats["games"], "players": stats["players"], "accuracy": human["accuracy"]}


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = load_openings()
    log(f"{len(names)} named opening positions")
    index_path = os.path.join(OUT, "bands.js")
    index = read_data_js(index_path) if os.path.exists(index_path) else []
    with EvalDB() as db:
        for B in BANDS:
            if want and B["id"] not in want:
                continue
            if not os.path.exists(B["games"]):
                log(B["id"], "no games file yet, skipping")
                continue
            info = process(B, db, names)
            index = [x for x in index if x["id"] != info["id"]] + [info]
    order = [B["id"] for B in BANDS]
    index.sort(key=lambda x: order.index(x["id"]))
    os.makedirs(OUT, exist_ok=True)
    write_data_js(index_path, index)
    log("index:", [x["id"] for x in index])


if __name__ == "__main__":
    main()
