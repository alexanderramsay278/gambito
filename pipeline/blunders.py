"""List the opponent blunders that drive a policy's practical value, weighted by reach probability.
py blunders.py "<start moves>" "<line1>|<line2>|..." white|black [band] [plies] [depth]"""
import sys
import chess
from practical import Practical, policy_from_lines, MIN_N, MIN_SHARE
from tree import key


def walk(P, b, pol, our, plies, reach, out, path):
    if plies == 0 or b.is_game_over():
        return
    if b.turn == our:
        san = pol.get(key(b))
        mv = b.parse_san(san) if san else chess.Move.from_uci(P.E.eval(b, P.depth)[0]["uci"])
        s = b.san(mv)
        b.push(mv)
        walk(P, b, pol, our, plies - 1, reach, out, path + [s])
        b.pop()
        return
    nd = P.T.get(key(b))
    if not nd or nd["nr"] < MIN_N:
        return
    here = P.wp_us(b, our)
    for san, (a, r, ws, uci) in nd["mv"].items():
        share = r / nd["nr"]
        if share < MIN_SHARE:
            continue
        b.push(chess.Move.from_uci(uci))
        after = P.wp_us(b, our)
        if after - here >= 0.30:
            out.append((reach * share, " ".join(path + [san]), share, nd["nr"], here, after))
        else:
            walk(P, b, pol, our, plies - 1, reach * share, out, path + [san])
        b.pop()


if __name__ == "__main__":
    start, lines, side = sys.argv[1], sys.argv[2].split("|"), sys.argv[3]
    band = sys.argv[4] if len(sys.argv) > 4 else "150_450"
    plies = int(sys.argv[5]) if len(sys.argv) > 5 else 12
    depth = int(sys.argv[6]) if len(sys.argv) > 6 else 14
    P = Practical(band, depth)
    our = chess.WHITE if side == "white" else chess.BLACK
    b = chess.Board()
    for s in start.split():
        b.push_san(s)
    out = []
    try:
        walk(P, b, policy_from_lines(lines), our, plies, 1.0, out, start.split())
    finally:
        P.E.close()
    out.sort(reverse=True)
    print(f"total blunder mass {100*sum(o[0] for o in out):.1f}%")
    for w, p, share, n, h, a in out[:25]:
        print(f"  {100*w:5.2f}%  {p:70s} share {100*share:4.1f}% of n={n:5d}  our win% {100*h:4.0f} -> {100*a:4.0f}")
