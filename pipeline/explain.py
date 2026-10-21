"""Plain-English layer for the Gambito courses:
  * the official opening name of every line (lichess-org/chess-openings, matched by position, so transpositions count);
  * "why it's good" for every line (end position: material, Stockfish, king safety; the key moment; how often it comes up);
  * the purpose of EVERY move on every line, yours and the opponent's.

Everything is derived from the board (python-chess) and the Stockfish evals already stored in the course data.
Hand-written comments from rep_white.txt / rep_black.txt (Under 400 course) are kept and shown first for your moves.

Fields written (idempotent, the original fields are never overwritten):
  move: x = purpose sentence, d = data note (auto courses: how many players find it, the common mistake to watch for)
  line: name = official opening name, eco, moves = full movetext, head = short headline, why = why it's good
  lessons are regrouped so each lesson covers one named opening; book positions get o = opening name.

Usage:  py -B explain.py [band ids]      rewrites data/band_*.js in place, prints a sample
"""
import csv, hashlib, math, os, sys
import chess
from site_build import SITE, read_data_js, write_data_js

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN_DIR = next(p for p in (os.path.join(HERE, "openings"), os.path.join(HERE, "vendor", "openings")) if os.path.isdir(p))

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
CENTRE = {chess.D4, chess.E4, chess.D5, chess.E5}
FLANK_CENTRE = {chess.C4, chess.C5, chess.F4, chess.F5}


def key(b):
    return " ".join(b.fen(en_passant="legal").split()[:4])


def wp(cp, color):
    """win chance for `color` from a White-POV centipawn score"""
    cp = max(-2000, min(2000, cp if color == chess.WHITE else -cp))
    return 1 / (1 + math.exp(-0.00368208 * cp))


def pct(x):
    return f"{100 * x:.0f}%" if x >= 0.095 else f"{100 * x:.1f}%"


def fmt_cp(cp):
    if abs(cp) >= 9000:
        return "mate"
    return ("+" if cp >= 0 else "−") + f"{abs(cp) / 100:.1f}"


def load_names():
    names = {}
    for fn in "abcde":
        p = os.path.join(OPEN_DIR, fn + ".tsv")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            rd = csv.reader(f, delimiter="\t")
            next(rd)
            for row in rd:
                if len(row) < 3:
                    continue
                b = chess.Board()
                try:
                    for t in row[2].split():
                        if not t.endswith("."):
                            b.push_san(t)
                except Exception:
                    continue
                names[key(b)] = (row[0], row[1])
    return names


# ---------------------------------------------------------------- board analysis
def material(b, color):
    return sum(len(b.pieces(pt, color)) * VAL[pt] for pt in VAL)


def swap_gain(b, mv):
    """Static exchange: material the mover nets from capture `mv` if both sides keep recapturing on that square
    with their cheapest piece and may stop when continuing would lose."""
    sq = mv.to_square
    if b.is_en_passant(mv):
        first = 1
    else:
        p = b.piece_at(sq)
        first = VAL[p.piece_type] if p else 0
    on_sq = VAL[mv.promotion] if mv.promotion else VAL[b.piece_type_at(mv.from_square)]
    if mv.promotion:
        first += VAL[mv.promotion] - 1
    gains = [first]
    bb = b.copy(stack=False)
    bb.push(mv)
    for _ in range(12):
        caps = [m for m in bb.legal_moves if m.to_square == sq]
        if not caps:
            break
        m = min(caps, key=lambda m: 100 if bb.piece_type_at(m.from_square) == chess.KING else VAL[bb.piece_type_at(m.from_square)])
        gains.append(on_sq - gains[-1])
        pt = bb.piece_type_at(m.from_square)
        on_sq = 100 if pt == chess.KING else VAL[pt]
        bb.push(m)
    for i in range(len(gains) - 1, 0, -1):
        gains[i - 1] = -max(-gains[i - 1], gains[i])
    return gains[0]


def as_turn(b, side):
    """the position with `side` to move (a null move if needed); None if that isn't possible (check)"""
    if b.turn == side:
        return b
    if b.is_check():
        return None
    bb = b.copy(stack=False)
    bb.push(chess.Move.null())
    return bb


def wins(b, side):
    """{square: (gain, captured piece type)} for captures `side` could make with a positive swap, if it were to move"""
    bb = as_turn(b, side)
    out = {}
    if bb is None:
        return out
    for m in bb.legal_moves:
        if bb.is_capture(m):
            g = swap_gain(bb, m)
            if g >= 1 and g > out.get(m.to_square, (0,))[0]:
                pt = chess.PAWN if bb.is_en_passant(m) else bb.piece_type_at(m.to_square)
                out[m.to_square] = (g, pt)
    return out


def mate_threat(b, side):
    """a square `side` could deliver mate on if it were to move, else None"""
    bb = as_turn(b, side)
    if bb is None:
        return None
    for m in bb.legal_moves:
        bb.push(m)
        mate = bb.is_checkmate()
        bb.pop()
        if mate:
            return m.to_square
    return None


def developed(b, color):
    n = 0
    home = 0 if color == chess.WHITE else 7
    for pt in (chess.KNIGHT, chess.BISHOP):
        n += sum(1 for sq in b.pieces(pt, color) if chess.square_rank(sq) != home)
    k = b.king(color)
    if k is not None and chess.square_file(k) in (2, 6) and chess.square_rank(k) == home:
        n += 1
    return n


def slider_reach(b, color):
    return sum(len(b.attacks(sq)) for pt in (chess.BISHOP, chess.QUEEN) for sq in b.pieces(pt, color))


def join(parts):
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ---------------------------------------------------------------- the purpose of one move
def purpose(b, mv, you, e_before=None, e_after=None, prev_mv=None):
    """(sentence, tags, loss). `you` = the learner makes this move (imperative); otherwise third person."""
    us, them = b.turn, not b.turn
    col = "White" if us == chess.WHITE else "Black"
    b2 = b.copy(stack=False)
    b2.push(mv)
    pc = b.piece_at(mv.from_square)
    P = NAME[pc.piece_type]
    to, frm = chess.square_name(mv.to_square), chess.square_name(mv.from_square)
    home = 0 if us == chess.WHITE else 7
    tags = set()
    T = lambda imp, third: imp if you else third          # noqa: E731
    their = "the" if you else "your"                         # the other side's things, from the learner's view

    loss = None
    if e_before is not None and e_after is not None:
        loss = wp(e_before, us) - wp(e_after, us)

    if b2.is_checkmate():
        return ("Checkmate!" if you else f"{col} gives checkmate."), {"mate"}, loss

    main = None
    if b.is_castling(mv):
        main = T("castle: your king is safe and your rook joins the game", "castles: the king is safe and the rook joins the game")
        tags.add("castle")
    elif b.is_capture(mv):
        cap = chess.PAWN if b.is_en_passant(mv) else b.piece_type_at(mv.to_square)
        C = NAME[cap]
        g = swap_gain(b, mv)
        recaptures = [m for m in b2.legal_moves if m.to_square == mv.to_square]
        if prev_mv is not None and prev_mv.to_square == mv.to_square and g >= 0:
            main = T(f"take back on {to}", f"takes back on {to}")
            tags.add("recapture")
        elif not recaptures:
            main = T(f"grab the free {C} on {to}", f"grabs your free {C} on {to}")
            tags.add("win")
        elif g >= 1:
            main = T(f"take the {C} on {to}, winning material", f"takes your {C} on {to}, winning material")
            tags.add("win")
        elif g == 0:
            main = (T(f"trade {P}s on {to}", f"trades {P}s on {to}") if cap == pc.piece_type
                    else T(f"swap your {P} for the {C} on {to}", f"swaps the {P} for your {C} on {to}"))
            tags.add("trade")
        else:
            main = T(f"sacrifice your {P} on {to}", f"sacrifices the {P} on {to}")
            if you and loss is not None and loss < 0.06:
                main += " (Stockfish says it works)"
            tags.add("sac")
    elif b.is_check():
        if pc.piece_type == chess.KING:
            main = T("step out of check", "steps the king out of check")
        else:
            main = T(f"block the check with your {P}", f"blocks the check with the {P}")
        tags.add("defend")
    elif pc.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(mv.from_square) == home:
        main = T(f"develop your {P}", f"develops the {P}")
        tags.add("develop")
    elif pc.piece_type == chess.PAWN and mv.to_square in CENTRE:
        main = T("take space in the centre", "takes space in the centre")
        tags.add("centre")
    elif pc.piece_type == chess.PAWN and mv.to_square in FLANK_CENTRE:
        main = T("fight for the centre with a pawn", "fights for the centre with a pawn")
        tags.add("centre")

    # was the moving piece in danger before?  (moving it away is then the point)
    before_wins = wins(b, them)
    if main is None and mv.from_square in before_wins:
        main = T(f"move your {P} out of attack", f"moves the {P} out of attack")
        tags.add("escape")
    if main is None and pc.piece_type == chess.QUEEN and frm in ("d1", "d8") and b.fullmove_number <= 6:
        main = T(f"bring your queen out to {to}", f"brings the queen out early, to {to}")
        tags.add("queen_out")
    if main is None and pc.piece_type == chess.KING:
        main = T(f"move your king to {to}", f"moves the king to {to}")
    if main is None and pc.piece_type == chess.PAWN:
        gain_b = max([len(b2.attacks(sq)) - len(b.attacks(sq)) for sq in b2.pieces(chess.BISHOP, us)] or [0])
        gain_q = sum(len(b2.attacks(sq)) - len(b.attacks(sq)) for sq in b2.pieces(chess.QUEEN, us))
        fian = {chess.G3: chess.F1, chess.B3: chess.C1, chess.G6: chess.F8, chess.B6: chess.C8}.get(mv.to_square)
        if fian is not None and b.piece_at(fian) == chess.Piece(chess.BISHOP, us) and chess.square_rank(mv.from_square) in (1, 6):
            spot = chess.square_name(mv.from_square)
            main = T(f"make room for your bishop on {spot} (a fianchetto: it will aim down the long diagonal)",
                     f"makes room for the bishop on {spot} (a fianchetto: it will aim down the long diagonal)")
            tags.add("fianchetto")
        elif gain_b >= 2 or gain_q >= 2:
            who = "bishop and queen" if gain_b >= 2 and gain_q >= 2 else "bishop" if gain_b >= 2 else "queen"
            main = T(f"open a path for your {who}", f"opens a path for the {who}")
            tags.add("open")
        else:
            main = T(f"push your {to[0]}-pawn", f"pushes the {to[0]}-pawn")
            tags.add("pawn")
    if main is None:
        main = T(f"put your {P} on {to}", f"puts the {P} on {to}")
        tags.add("reposition")

    check = b2.is_check()
    extra = []
    # what the moved piece now attacks
    hits = []
    for sq in b2.attacks(mv.to_square):
        q = b2.piece_at(sq)
        if q and q.color == them:
            hits.append((sq, q.piece_type))
    after_wins = wins(b2, us)
    valuable = [(sq, pt) for sq, pt in hits if pt in (chess.KING, chess.QUEEN, chess.ROOK) or sq in after_wins
                or VAL[pt] > VAL[pc.piece_type]]
    safe = mv.to_square not in wins(b2, them)
    if len(valuable) >= 2 and safe:
        names_ = [("king" if pt == chess.KING else f"{NAME[pt]} on {chess.square_name(sq)}") for sq, pt in valuable[:2]]
        extra.append(T(f"fork the {names_[0]} and the {names_[1]}", f"forks your {names_[0]} and {names_[1]}"))
        tags.add("fork")
    else:
        pins = [sq for sq in chess.SQUARES if b2.piece_at(sq) and b2.piece_at(sq).color == them
                and b2.piece_type_at(sq) != chess.KING and b2.is_pinned(them, sq) and not b.is_pinned(them, sq)]
        if pins and not check:
            extra.append(T(f"pin the {NAME[b2.piece_type_at(pins[0])]} to the king", f"pins your {NAME[b2.piece_type_at(pins[0])]} to the king"))
            tags.add("pin")
        q_hit = [sq for sq, pt in hits if pt == chess.QUEEN]
        if q_hit and not b.is_capture(mv):
            extra.append(T("attack the queen", "attacks your queen"))
            tags.add("hit_queen")
        elif pc.piece_type == chess.PAWN and not b.is_capture(mv):
            kicked = [(sq, pt) for sq, pt in hits if pt not in (chess.PAWN, chess.KING)]
            if kicked:
                sq, pt = kicked[0]
                extra.append(T(f"attack the {NAME[pt]} on {chess.square_name(sq)}", f"attacks your {NAME[pt]} on {chess.square_name(sq)}"))
                tags.add("kick")
    # new threats
    mt = mate_threat(b2, us) if not check else None
    if mt is not None and mate_threat(b, us) is None:
        extra.append(T(f"threaten mate on {chess.square_name(mt)}", f"threatens mate on {chess.square_name(mt)}"))
        tags.add("threat_mate")
    elif not check and not tags & {"fork"}:
        old = wins(b, us)
        new = [(g, sq, pt) for sq, (g, pt) in after_wins.items() if sq not in old and sq != mv.to_square]
        mentioned = {sq for sq, _ in hits if "kick" in tags or "hit_queen" in tags}
        new = [x for x in new if x[1] not in mentioned or "kick" not in tags]
        if new and not tags & {"kick", "hit_queen"}:
            g, sq, pt = max(new)
            extra.append(T(f"threaten to win the {NAME[pt]} on {chess.square_name(sq)}", f"threatens to win your {NAME[pt]} on {chess.square_name(sq)}"))
            tags.add("threat")
    # defence
    if b.turn == us:
        saved = [sq for sq in before_wins if sq != mv.from_square and sq not in wins(b2, them) and b2.piece_at(sq)
                 and b2.piece_at(sq).color == us]
        if saved and "escape" not in tags and not b.is_check() and not b2.is_check():
            sq = saved[0]
            extra.append(T(f"defend your {NAME[b2.piece_type_at(sq)]} on {chess.square_name(sq)}", f"defends the {NAME[b2.piece_type_at(sq)]} on {chess.square_name(sq)}"))
            tags.add("defend")
    if mate_threat(b, them) is not None and mate_threat(b2, them) is None and not b.is_check():
        extra.append(T("stop the mate threat", "stops your mate threat"))
        tags.add("defend")
    # aims at f7 / f2
    weak = chess.F7 if us == chess.WHITE else chess.F2
    ek = b2.king(them)
    if (pc.piece_type in (chess.BISHOP, chess.QUEEN) and weak in b2.attacks(mv.to_square) and weak not in b.attacks(mv.from_square)
            and ek in (chess.E8, chess.E1) and not tags & {"fork", "threat_mate"}):
        extra.append(T(f"aim at {chess.square_name(weak)}, the weak spot next to the king", f"aims at {chess.square_name(weak)}, the weak spot next to your king"))
        tags.add("aim_f7")
    # pawn moves that open lines or take squares away
    if pc.piece_type == chess.PAWN and not b.is_capture(mv):
        if chess.square_rank(mv.from_square) in (1, 6) and slider_reach(b2, us) - slider_reach(b, us) >= 3 and "centre" in tags:
            extra.append(T("open lines for your bishop and queen", "opens lines for the bishop and queen"))
        elif not extra:
            bt = as_turn(b, them)
            if bt is not None:
                denied = []
                for sq in b2.attacks(mv.to_square):
                    for m in bt.legal_moves:
                        if m.to_square == sq and bt.piece_type_at(m.from_square) in (chess.KNIGHT, chess.BISHOP):
                            denied.append((sq, bt.piece_type_at(m.from_square)))
                if denied:
                    sq, pt = denied[0]
                    extra.append(T(f"take {chess.square_name(sq)} away from {their} {NAME[pt]}", f"takes {chess.square_name(sq)} away from your {NAME[pt]}"))
                    tags.add("prophylaxis")
    # material left hanging by this move: a gambit if it's ours and Stockfish doesn't mind, otherwise a drawback
    newly = {sq: v for sq, v in wins(b2, them).items() if sq not in before_wins and sq != mv.to_square or
             (sq == mv.to_square and not b.is_capture(mv))} if not check else {}
    gambit_txt = None
    if newly:
        sq, (g, pt) = max(newly.items(), key=lambda kv: kv[1])
        if you and loss is not None and loss < 0.06 and pt == chess.PAWN:
            extra.append("offer a pawn (a gambit)")
            tags.add("gambit")
        elif loss is None or loss >= 0.06:
            if sq == mv.to_square:
                gambit_txt = T(f"but your {NAME[pt]} is unprotected there", f"but the {NAME[pt]} is unprotected there")
            else:
                gambit_txt = T(f"but it leaves your {NAME[pt]} on {chess.square_name(sq)} unprotected",
                               f"but it leaves the {NAME[pt]} on {chess.square_name(sq)} unprotected")
            tags.add("hangs")

    # drawbacks
    buts = []
    if pc.piece_type in (chess.KNIGHT, chess.BISHOP, chess.QUEEN):
        for fl in (3, 4):                                   # d- and e-file
            ahead = chess.square(fl, 2 if us == chess.WHITE else 5)
            pawn_home = chess.square(fl, 1 if us == chess.WHITE else 6)
            if mv.to_square == ahead and b2.piece_at(pawn_home) == chess.Piece(chess.PAWN, us):
                stuck = chess.C1 if us == chess.WHITE else chess.C8
                txt = T(f"but it blocks your {'de'[fl - 3]}-pawn", f"but it blocks its own {'de'[fl - 3]}-pawn")
                if fl == 3 and b2.piece_at(stuck) == chess.Piece(chess.BISHOP, us):
                    txt += f", so the {chess.square_name(stuck)}-bishop is stuck"
                buts.append(txt)
                tags.add("blocks_pawn")
    if pc.piece_type == chess.PAWN and frm in ("f7", "f2") and b2.king(us) in (chess.E8, chess.E1):
        diag = (chess.G6, chess.H5) if us == chess.BLACK else (chess.G3, chess.H4)
        if b2.piece_at(diag[0]) is None:
            buts.append(T("but it weakens your king's diagonal", f"but it opens the diagonal to the king ({'h5-e8' if us == chess.BLACK else 'h4-e1'})"))
            tags.add("weakens_king")
    if (pc.piece_type == chess.KING and b.has_castling_rights(us) and not b2.has_castling_rights(us)
            and not b.is_castling(mv)):
        buts.append(T("but you can no longer castle", "and can no longer castle"))
    if gambit_txt:
        buts.insert(0, gambit_txt)
    if pc.piece_type == chess.PAWN and not b.is_capture(mv):
        for sq in b2.pieces(chess.BISHOP, us):
            if chess.square_rank(sq) == home and len(b.attacks(sq)) - len(b2.attacks(sq)) >= 2:
                buts.append(T(f"but it shuts in your {chess.square_name(sq)}-bishop", f"but it shuts in its own {chess.square_name(sq)}-bishop"))
                tags.add("blocks_bishop")
                break
    if "queen_out" in tags and not you:
        buts.append("but you can gain time by attacking it")

    s = main + (" with check" if check and "check" not in main else "")
    if extra:
        s += (" and " if len(extra) == 1 and len(s) <= 32 else ", ") + join(extra[:2])
    if buts:
        s += ", " + buts[0]
    s = (s[0].upper() + s[1:]) if you else f"{col} {s}"
    s += "."
    if check:
        tags.add("check")

    if loss is not None and not you:
        swing = fmt_cp(e_after if us == chess.BLACK else -e_after)     # for the learner
        if loss >= 0.25:
            s += f" It's a blunder: Stockfish now has you at {swing}. Punish it!"
            tags.add("blunder")
        elif loss >= 0.12:
            s += f" It's a mistake (Stockfish: {swing} for you)."
            tags.add("mistake")
        elif loss >= 0.06:
            s += " It's a little inaccurate."
            tags.add("inaccuracy")
    return s, tags, loss


# ---------------------------------------------------------------- lines
def san_seq(b0, ucis):
    b = b0.copy()
    out = []
    for u in ucis:
        m = chess.Move.from_uci(u)
        num = f"{b.fullmove_number}." if b.turn == chess.WHITE else (f"{b.fullmove_number}..." if not out else "")
        out.append(num + b.san(m))
        b.push(m)
    return " ".join(out)


def san_num(b, mv):
    return (f"{b.fullmove_number}." if b.turn == chess.WHITE else f"{b.fullmove_number}...") + b.san(mv)


def mat_phrase(v):
    return {1: "a pawn", 2: "two pawns' worth of material", 3: "a piece", 4: "a piece and a pawn", 5: "a rook"}.get(v, "a queen" if v >= 9 else "a rook and more")


def line_why(steps, learner, band_label, w, color_word):
    fb = steps[-1]["b2"]
    if steps[-1]["you"]:                      # if the line ends on our capture, count their obvious recapture
        to = steps[-1]["to"]
        caps = [m for m in fb.legal_moves if m.to_square == to and swap_gain(fb, m) >= 0]
        if caps:
            fb = fb.copy(stack=False)
            fb.push(min(caps, key=lambda m: VAL[fb.piece_type_at(m.from_square)] or 100))
    us, them = learner, not learner
    e = next((s["e_after"] for s in reversed(steps) if s["e_after"] is not None), None)
    mat = material(fb, us) - material(fb, them)
    parts = []
    if e is not None:
        cpu = e if us == chess.WHITE else -e
        ev = ("winning for you" if cpu >= 300 else "clearly better for you" if cpu >= 100 else "a little better for you" if cpu >= 40
              else "about equal" if cpu > -40 else "slightly better for them on paper")
        evs = f"Stockfish rates it {ev} ({fmt_cp(cpu)})"
    else:
        evs = ""
    if mat >= 1:
        parts.append(f"You end up {mat_phrase(mat)} up" + (f", and {evs}." if evs else "."))
    elif mat <= -1:
        ahead = developed(fb, us) > developed(fb, them)
        parts.append(f"You're {mat_phrase(-mat)} down for now" + (f", but {evs}" if evs else "")
                     + (", because you're ahead in development." if ahead else "."))
    else:
        parts.append("Material is level" + (f" and {evs}." if evs else "."))
    ek = fb.king(them)
    if not fb.has_castling_rights(them) and ek in (chess.E8, chess.E1, chess.D8, chess.D1, chess.F8, chess.F1, chess.E7, chess.E2, chess.F7, chess.F2):
        parts.append("Their king has lost the right to castle.")
    # the key moment
    mistakes = [(s["loss"], i) for i, s in enumerate(steps) if not s["you"] and s["loss"] is not None and s["loss"] >= 0.12]
    if mistakes:
        _, i = max(mistakes)
        s = steps[i]
        word = "blunder" if s["loss"] >= 0.25 else "mistake"
        reply = steps[i + 1]["san"] if i + 1 < len(steps) and steps[i + 1]["you"] else None
        parts.append(f"The key moment: {s['san']} is a {word}" + (f", and {reply} punishes it." if reply else "."))
    else:
        star = next((s for s in steps if s["you"] and s["tags"] & {"fork", "pin", "win", "threat_mate", "hit_queen", "sac"}), None)
        if star:
            t = star["x"].split(". ")[0].rstrip(".")
            parts.append(f"The key move is {star['san']}: {t[0].lower() + t[1:]}.")
        elif any(s["you"] and "gambit" in s["tags"] for s in steps):
            parts.append("You offer a pawn as a gambit, and Stockfish says you get enough for it.")
        else:
            dev = sum(1 for s in steps if s["you"] and s["tags"] & {"develop", "centre", "castle"})
            if dev >= 2:
                parts.append("You take the centre and get your pieces out quickly.")
    if w and w >= 0.005:
        parts.append(f"About {pct(w)} of your games as {color_word} against {band_label} players go this way.")
    elif w:
        parts.append(f"It's rare (about 1 game in {round(1 / w):,}), but worth knowing.")
    return " ".join(parts)


def book_note(book, b, mv, band_label, learner):
    """auto courses: how many players find our move, and the common mistake to watch for next"""
    notes = []
    be = book.get(key(b))
    if be:
        hit = next((x for x in be["m"] if x[1][:4] == mv.uci()[:4]), None)
        if hit:
            notes.append(f"{pct(hit[2])} of {band_label} players find this.")
    b2 = b.copy(stack=False)
    b2.push(mv)
    be2 = book.get(key(b2))
    if be2 and be2.get("e") is not None and be2.get("nr", be2.get("n", 0)) >= 20:
        opp = not learner
        best = wp(be2["e"], opp)
        worst = None
        for san, uci, sh, n, sc, ev in be2["m"]:
            if sh >= 0.08 and ev is not None:
                l = best - wp(ev, opp)
                if l >= 0.08 and (worst is None or sh * l > worst[0]):
                    worst = (sh * l, san, sh)
        if worst:
            notes.append(f"Watch for {worst[1]}: {pct(worst[2])} of {band_label} players answer with it, and it's a mistake you can punish.")
    return " ".join(notes)


def enrich_course(C, book, names, band_label, curated):
    nodes = C["nodes"]
    learner = chess.WHITE if C["color"] == "w" else chess.BLACK
    color_word = "White" if learner == chess.WHITE else "Black"
    first_opp = 1 if learner == chess.WHITE else 0
    done = {}
    lines_full = {}
    for L in C["lines"]:
        b = chess.Board()
        steps = []
        prev = None
        e_prev = 20
        deep, deep_ply = None, 0
        for i, (a, c) in enumerate(zip(L["path"], L["path"][1:])):
            m = next(x for x in nodes[a]["m"] if x["c"] == c)
            mv = chess.Move.from_uci(m["u"])
            you = b.turn == learner
            san = san_num(b, mv)
            if (a, c) not in done:
                x, tags, loss = purpose(b, mv, you, e_prev, m.get("e"), prev)
                m["x"] = x
                if not curated and you:
                    m["d"] = book_note(book, b, mv, band_label, learner)
                done[(a, c)] = (x, tags, loss)
            x, tags, loss = done[(a, c)]
            b2 = b.copy(stack=False)
            b2.push(mv)
            steps.append({"san": san, "you": you, "x": x if not (curated and you and m.get("t")) else m["t"], "tags": tags,
                          "loss": loss, "e_after": m.get("e"), "b2": b2, "to": mv.to_square})
            if m.get("e") is not None:
                e_prev = m["e"]
            prev = mv if b.is_capture(mv) else None      # only a capture can be "taken back"
            b = b2
            if key(b) in names:
                deep, deep_ply = names[key(b)], i + 1
        ucis = []
        for a, c in zip(L["path"], L["path"][1:]):
            ucis.append(next(x for x in nodes[a]["m"] if x["c"] == c)["u"])
        orig = L.get("head") or L["name"]
        L["eco"], L["name"] = deep if deep else ("", "Unnamed line")
        L["moves"] = san_seq(chess.Board(), ucis)
        if curated:
            L["head"] = orig
        else:
            bb = chess.Board()
            for u in ucis[:first_opp + 1]:
                bb.push_uci(u)
            L["head"] = san_seq(bb, ucis[first_opp + 1:first_opp + 5]) or L["moves"]
        L["why"] = line_why(steps, learner, band_label, L.get("w"), color_word)
        lines_full[L["id"]] = L
    # regroup lessons so each one teaches one named opening (most common lines first)
    for u in C["units"]:
        ids = [i for les in u["lessons"] if les["kind"] == "learn" for i in les["lines"]]
        match = [les for les in u["lessons"] if les["kind"] != "learn"]
        Ls = sorted((lines_full[i] for i in ids if i in lines_full), key=lambda L: -(L.get("w") or 0))
        left = list(Ls)
        lessons = []
        while left:
            a = left.pop(0)
            fam = a["name"].split(":")[0]
            mate = next((x for x in left if x["name"] == a["name"]), None) or next((x for x in left if x["name"].split(":")[0] == fam), None)
            chunk = [a] + ([mate] if mate else [])
            if mate:
                left.remove(mate)
            lessons.append({"id": hashlib.sha1((C["color"] + u["id"] + a["id"]).encode()).hexdigest()[:10], "kind": "learn",
                            "title": a["name"], "sub": a["head"], "lines": [x["id"] for x in chunk]})
        u["lessons"] = lessons + match


def enrich_band(payload, names):
    label = payload["meta"]["label"]
    curated = bool(payload["meta"].get("curated"))
    for c, C in payload["courses"].items():
        enrich_course(C, payload["book"], names, label, curated and C.get("source") == "curated")
    for k, be in payload["book"].items():
        if k in names:
            be["o"] = names[k][1]
    return payload


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = load_names()
    ddir = os.path.join(SITE, "data")
    for fn in sorted(os.listdir(ddir)):
        if not fn.startswith("band_") or (want and fn[5:-3] not in want):
            continue
        p = os.path.join(ddir, fn)
        d = enrich_band(read_data_js(p), names)
        write_data_js(p, d)
        n = sum(1 for C in d["courses"].values() for nd in C["nodes"] for m in nd["m"] if m.get("x"))
        print(f"{fn}: {n} moves explained, lessons w {sum(len(u['lessons']) for u in d['courses']['w']['units'])} / b {sum(len(u['lessons']) for u in d['courses']['b']['units'])}")


if __name__ == "__main__":
    main()
