"""Query the opening tree.  py q.py "e4 e5 Nf3" [band]   -> reply distribution at that position.
Columns: move, share among random-side players (n), share among all games, White score after move (all games)."""
import pickle, sys, os
import chess
from tree import key

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR


def load(band="200_400"):
    return pickle.load(open(os.path.join(DATA, f"tree_{band}.pkl"), "rb"))


def show(T, moves, top=15, minshare=0.0):
    b = chess.Board()
    for m in moves.split():
        b.push_san(m)
    node = T["nodes"].get(key(b))
    side = "White" if b.turn else "Black"
    if not node:
        print(f"[{moves}] no games")
        return
    nr, na = node["nr"], node["n"]
    print(f"[{moves}]  {side} to move | games here: {na} (random-side n={nr})")
    rows = sorted(node["mv"].items(), key=lambda kv: -kv[1][1])
    for m, (a, r, ws, uci) in rows[:top]:
        sh_r = r / nr if nr else 0
        if sh_r < minshare and a / na < minshare:
            continue
        print(f"   {m:8s} rand {100*sh_r:5.1f}% (n={r:5d})   all {100*a/na:5.1f}% (n={a:5d})   White score {100*ws/a:5.1f}%")


if __name__ == "__main__":
    band = sys.argv[2] if len(sys.argv) > 2 else "200_400"
    T = load(band)
    show(T, sys.argv[1] if len(sys.argv) > 1 else "")
