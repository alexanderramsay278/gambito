"""Out-of-sample tests of the Gambito opening model.

TEST 1 - strategy backtest (does the recommended move actually score better?)
  Train = games played before 1 Oct 2026, test = games from 1 Oct onwards (no overlap, later in time).
  From TRAIN only, at every position reached >= MIN_N times in the first PLY_MAX plies, three "strategies" pick a move:
    engine    : Stockfish 19's best move (depth 12)
    popular   : the move most players at the band chose
    practical : the site's pick: among moves within 4 win-% points of Stockfish's best, the one with the highest
                expected win chance against the band's real reply distribution (1-ply lookahead)
  On TEST games, every time a player reaches one of those positions we record which move they played and their final
  score (1 / 0.5 / 0). Estimate, per band:
      score = b * followed_strategy + c * rating_diff + position fixed effect
  i.e. at the SAME position, holding the rating gap fixed, how much more do players score when they play the strategy's
  move? 95% CIs from a cluster bootstrap over games (a game's decisions share one result).
  Head-to-head: at positions where practical != engine, players who chose the practical move vs the engine move.

TEST 2 - calibration of the rival's error model
  The site's rival makes mistakes at rates measured on 150 games per band (seed 7, all dates). Here: 200 DIFFERENT games
  per band from the test period, graded the same way (Stockfish depth 10, win-% loss per move). Compare rates; also
  gives the error surface (win-% lost per move, by band and move number).

Observational data: "followed" is not randomly assigned. Rating difference and position are controlled; skill differences
within a band beyond rating are not. Results are associations, labelled as such.

Usage: py -B backtest.py [band ids]     -> data/backtest/<band>.json  (cached per band; delete to recompute)
"""
import datetime, json, math, os, random, sys, time
from collections import Counter, defaultdict
import numpy as np
import chess
from evaldb import EvalDB, fkey
from site_data import BANDS, iter_games, wp, key, HUMAN_DEPTH, EV_DEPTH

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
OUT = os.path.join(DATA, "backtest")
SPLIT = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc).timestamp()
PLY_MAX, MIN_N, CAND_MIN, REPLY_MIN = 16, 50, 6, 0.04
N_BOOT, CAL_GAMES = 400, 200
DRAWS = {"agreed", "repetition", "stalemate", "insufficient", "50move", "timevsinsufficient"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def score_white(g):
    if g["wres"] == "win":
        return 1.0
    if g["bres"] == "win":
        return 0.0
    return 0.5 if g["wres"] in DRAWS or g["bres"] in DRAWS else None


def walk(g, nply):
    b = chess.Board()
    out = []
    for san in g["mv"][:nply]:
        try:
            mv = b.parse_san(san)
        except Exception:
            break
        out.append((b.copy(stack=False), mv.uci()))
        b.push(mv)
    return out


def child(fen, uci):
    b = chess.Board(fen)
    b.push(chess.Move.from_uci(uci))
    return b.fen()


# ---------------------------------------------------------------- test 1
def strategy_test(B, db, games):
    train = [g for g in games if g["t"] < SPLIT]
    test = [g for g in games if g["t"] >= SPLIT and score_white(g) is not None]
    tree = defaultdict(lambda: {"n": 0, "mv": Counter(), "fen": None})
    for g in train:
        for b, u in walk(g, PLY_MAX + 2):
            nd = tree[key(b)]
            nd["n"] += 1
            nd["mv"][u] += 1
            nd["fen"] = nd["fen"] or b.fen()
    ply = lambda fen: (int(fen.split()[5]) - 1) * 2 + (fen.split()[1] == "b")  # noqa: E731
    cand = {k: nd for k, nd in tree.items() if nd["n"] >= MIN_N and ply(nd["fen"]) < PLY_MAX}
    log(B["id"], f"train {len(train)} test {len(test)} games; {len(cand)} positions with >= {MIN_N} train games")
    # evals: positions, candidate children, grandchildren replies
    EV = db.eval_many([nd["fen"] for nd in cand.values()], EV_DEPTH, label=f"{B['id']} pos")
    kids = {}
    for k, nd in cand.items():
        moves = {u for u, c in nd["mv"].items() if c >= CAND_MIN}
        best = EV[fkey(nd["fen"])][2]
        if best:
            moves.add(best)
        kids[k] = {u: child(nd["fen"], u) for u in moves}
    EV.update(db.eval_many([f for d in kids.values() for f in d.values()], EV_DEPTH, label=f"{B['id']} kids"))
    gk = []
    for k, d in kids.items():
        for u, cf in d.items():
            c2 = tree.get(fkey(cf))
            if c2 and c2["n"] >= 20:
                gk += [child(cf, u2) for u2, c in c2["mv"].items() if c / c2["n"] >= REPLY_MIN]
    EV.update(db.eval_many(gk, EV_DEPTH, label=f"{B['id']} grandkids"))

    picks = {}
    for k, nd in cand.items():
        side = chess.WHITE if nd["fen"].split()[1] == "w" else chess.BLACK
        sgn = 1 if side == chess.WHITE else -1
        d = kids[k]
        eng = {u: wp(sgn * EV[fkey(cf)][0]) for u, cf in d.items()}
        best = EV[fkey(nd["fen"])][2]
        if not best or best not in eng:
            continue
        top = max(eng.values())
        ok = [u for u, v in eng.items() if v >= top - 0.04]

        def prac(u):
            cf = d[u]
            c2 = tree.get(fkey(cf))
            if not c2 or c2["n"] < 20:
                return eng[u]
            acc = cov = 0.0
            for u2, c in c2["mv"].items():
                sh = c / c2["n"]
                if sh >= REPLY_MIN and fkey(child(cf, u2)) in EV:
                    acc += sh * wp(sgn * EV[fkey(child(cf, u2))][0])
                    cov += sh
            return acc + (1 - cov) * eng[u]
        picks[k] = {"engine": best, "popular": nd["mv"].most_common(1)[0][0], "practical": max(ok, key=prac)}

    rows = []      # (pos index, game index, followed engine/popular/practical, played uci, rating diff, score)
    pos_ix = {k: i for i, k in enumerate(picks)}
    for gi, g in enumerate(test):
        sw = score_white(g)
        for b, u in walk(g, PLY_MAX):
            k = key(b)
            if k in picks:
                w = b.turn == chess.WHITE
                rd = (g["wr"] - g["br"]) if w else (g["br"] - g["wr"])
                p = picks[k]
                rows.append((pos_ix[k], gi, u == p["engine"], u == p["popular"], u == p["practical"], rd, sw if w else 1 - sw,
                             u))
    log(B["id"], f"{len(rows)} test decisions at {len(picks)} positions "
        f"(practical != engine at {sum(p['practical'] != p['engine'] for p in picks.values())})")
    pos = np.array([r[0] for r in rows]); gam = np.array([r[1] for r in rows])
    F = {s: np.array([r[2 + i] for r in rows], float) for i, s in enumerate(("engine", "popular", "practical"))}
    rd = np.array([r[5] for r in rows], float) / 100.0
    y = np.array([r[6] for r in rows], float)
    res = {"train_games": len(train), "test_games": len(test), "positions": len(picks), "decisions": len(rows),
           "differ": sum(p["practical"] != p["engine"] for p in picks.values())}
    rng = np.random.default_rng(11)
    ng = len(test)
    boots = [rng.integers(0, ng, ng) for _ in range(N_BOOT)]
    by_game = defaultdict(list)
    for i, gi in enumerate(gam):
        by_game[gi].append(i)
    idx_lists = [np.concatenate([by_game[g] for g in bs if g in by_game]) if len(bs) else np.array([], int) for bs in boots]

    def fe_ols(ix, x):
        """within-position OLS of y on [x, rating diff]; returns coefficient on x"""
        p, yy, xx, rr = pos[ix], y[ix], x[ix], rd[ix]
        cnt = np.bincount(p, minlength=len(picks)).astype(float)
        cnt[cnt == 0] = 1
        dm = lambda v: v - (np.bincount(p, weights=v, minlength=len(picks)) / cnt)[p]  # noqa: E731
        X = np.column_stack([dm(xx), dm(rr)])
        beta, *_ = np.linalg.lstsq(X, dm(yy), rcond=None)
        return float(beta[0])

    for s in ("engine", "popular", "practical"):
        x = F[s]
        allix = np.arange(len(y))
        est = fe_ols(allix, x)
        bs = np.array([fe_ols(ix, x) for ix in idx_lists])
        res[s] = {"beta": est, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
                  "share_followed": float(x.mean()), "raw_followed": float(y[x == 1].mean()), "raw_not": float(y[x == 0].mean())}
    # head-to-head where they differ
    for a, bname in (("practical", "engine"), ("popular", "engine")):
        diff_pos = np.array([picks[k][a] != picks[k][bname] for k in picks])
        m = diff_pos[pos] & ((F[a] == 1) | (F[bname] == 1))
        ix_all = np.where(m)[0]
        if len(ix_all) < 200:
            res[f"{a}_vs_{bname}"] = None
            continue
        est = fe_ols(ix_all, F[a])
        bs = np.array([fe_ols(ix[m[ix]], F[a]) for ix in idx_lists[:200]])
        res[f"{a}_vs_{bname}"] = {"beta": est, "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
                                  "n": int(len(ix_all)), "n_pos": int(len(set(pos[ix_all].tolist())))}
    return res


# ---------------------------------------------------------------- test 2
def model_sample_ids(B, n_games=150, seed=7):
    """the exact games the site's error model was measured on (same reservoir as site_data.human_model)"""
    rnd = random.Random(seed)
    sample = []
    for i, g in enumerate(iter_games(B["games"], B["lo"], B["hi"])):
        if len(g["mv"]) < 20:
            continue
        if len(sample) < n_games:
            sample.append(g["id"])
        else:
            j = rnd.randint(0, i)
            if j < n_games:
                sample[j] = g["id"]
    return set(sample)


def calibration(B, db, games, model):
    used = model_sample_ids(B)
    pool = [g for g in games if g["t"] >= SPLIT and g["id"] not in used and len(g["mv"]) >= 20]
    rng = random.Random(23)
    sample = rng.sample(pool, min(CAL_GAMES, len(pool)))
    seqs, fens = [], []
    for g in sample:
        b = chess.Board()
        seq = [b.fen()]
        for san in g["mv"][:40]:
            try:
                b.push_san(san)
            except Exception:
                break
            seq.append(b.fen())
        seqs.append(seq)
        fens += seq
    EV = db.eval_many(fens, HUMAN_DEPTH, label=f"{B['id']} calibration")
    per_ply = defaultdict(list)
    cats = {"opening": [], "middle": []}       # per game lists of categories, for the bootstrap
    for seq in seqs:
        gcats = {"opening": Counter(), "middle": Counter()}
        for i in range(len(seq) - 1):
            a, c = EV.get(fkey(seq[i])), EV.get(fkey(seq[i + 1]))
            if not a or not c:
                continue
            sgn = 1 if seq[i].split()[1] == "w" else -1
            loss = max(0.0, wp(sgn * a[0]) - wp(sgn * c[0]))
            per_ply[i].append(loss)
            cat = "best" if loss <= 0.02 else "good" if loss <= 0.05 else "inaccuracy" if loss <= 0.10 else "mistake" if loss <= 0.20 else "blunder"
            gcats["opening" if i < 20 else "middle"][cat] += 1
        for ph in cats:
            cats[ph].append(gcats[ph])
    out = {"games": len(sample), "loss_by_ply": {i: float(np.mean(v)) for i, v in sorted(per_ply.items())},
           "n_by_ply": {i: len(v) for i, v in sorted(per_ply.items())}}
    rng2 = np.random.default_rng(5)
    for ph in ("opening", "middle"):
        out[ph] = {}
        for cat in ("best", "good", "inaccuracy", "mistake", "blunder"):
            num = np.array([c[cat] for c in cats[ph]], float)
            den = np.array([sum(c.values()) for c in cats[ph]], float)
            obs = num.sum() / max(1, den.sum())
            bs = []
            for _ in range(1000):
                ix = rng2.integers(0, len(num), len(num))
                bs.append(num[ix].sum() / max(1, den[ix].sum()))
            out[ph][cat] = {"model": model[ph][cat], "obs": float(obs), "lo": float(np.percentile(bs, 2.5)),
                            "hi": float(np.percentile(bs, 97.5))}
    return out


def main():
    want = [a for a in sys.argv[1:] if not a.startswith("-")]
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, HERE)
    from site_build import SITE, read_data_js
    with EvalDB() as db:
        for B in BANDS:
            if want and B["id"] not in want:
                continue
            p = os.path.join(OUT, f"{B['id']}.json")
            if os.path.exists(p):
                log(B["id"], "cached")
                continue
            t0 = time.time()
            games = [g for g in iter_games(B["games"], B["lo"], B["hi"]) if "t" in g]
            model = read_data_js(os.path.join(SITE, "data", f"band_{B['id']}.js"))["human"]
            res = {"band": B["id"], "label": B["label"], "rng": B["rng"], "split": "2026-10-01",
                   "strategy": strategy_test(B, db, games), "calibration": calibration(B, db, games, model)}
            json.dump(res, open(p, "w"), indent=1)
            s = res["strategy"]
            log(B["id"], f"done in {time.time() - t0:.0f}s | practical {s['practical']['beta']:+.3f} "
                f"engine {s['engine']['beta']:+.3f} popular {s['popular']['beta']:+.3f} | prac-vs-eng {s['practical_vs_engine']}")


if __name__ == "__main__":
    main()
