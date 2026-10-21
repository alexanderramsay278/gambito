"""Build an opening tree from data/games.jsonl and pickle it.

Node key = position (FEN without move counters, legal-ep only) so transpositions merge.
Per node we store, for each move played from that position:
  all  : count over all games in band
  rand : count over games where the side to move was NOT the crawled archive owner
         (i.e. a matchmaking draw -> an unbiased sample of the rating pool)
  wsum : White's total score after that move (1 win, .5 draw, 0 loss), all games
Usage: py tree.py [low] [high]   (default band: both players 200-400)
"""
import json, pickle, sys, os
from collections import defaultdict, Counter
import chess

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
MAXPLY = 24


def key(b):
    return " ".join(b.fen(en_passant="legal").split()[:4])


def wscore(g):
    if g["wres"] == "win":
        return 1.0
    if g["bres"] == "win":
        return 0.0
    return 0.5


def iter_games(LOW, HIGH):
    with open(os.path.join(DATA, "games.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                g = json.loads(line)
            except Exception:
                continue  # tolerate a partially-written last line while the crawler runs
            if LOW <= g["wr"] <= HIGH and LOW <= g["br"] <= HIGH:
                yield g


def main():
    LOW = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    HIGH = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    MIN_KEEP = 3   # two-pass: only keep positions reached by >= MIN_KEEP games (memory)
    # pass 1: count position visits (by hash of key) using SAN path replay
    seen = Counter()
    for g in iter_games(LOW, HIGH):
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
    meta = Counter()
    lengths, terms = [], Counter()
    n = 0
    for g in iter_games(LOW, HIGH):
        n += 1
        s = wscore(g)
        lengths.append(g["plies"])
        t = g["term"].lower()
        terms["checkmate" if "checkmate" in t else "resignation" if "resignation" in t else
              "time" if "time" in t else "abandoned" if "abandon" in t else "draw" if ("draw" in t or "stalemate" in t or "repetition" in t or "agreement" in t or "insufficient" in t) else "other"] += 1
        b = chess.Board()
        for ply, san in enumerate(g["mv"][:MAXPLY]):
            k = key(b)
            if hash(k) not in keep:
                break
            node = nodes[k]
            node["n"] += 1
            side = "w" if b.turn == chess.WHITE else "b"
            rand = g["owner"] != side
            if rand:
                node["nr"] += 1
            try:
                mv = b.parse_san(san)
            except Exception:
                meta["bad_san"] += 1
                break
            c_san = b.san(mv)
            e = node["mv"][c_san]
            e[0] += 1
            e[1] += 1 if rand else 0
            e[2] += s
            e[3] = mv.uci()
            b.push(mv)
    out = {k: {"n": v["n"], "nr": v["nr"], "mv": {m: tuple(x) for m, x in v["mv"].items()}} for k, v in nodes.items()}
    summary = {"games": n, "band": [LOW, HIGH], "terms": dict(terms),
               "median_plies": sorted(lengths)[len(lengths) // 2] if lengths else 0, "meta": dict(meta)}
    pickle.dump({"nodes": out, "summary": summary}, open(os.path.join(DATA, f"tree_{LOW}_{HIGH}.pkl"), "wb"))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
