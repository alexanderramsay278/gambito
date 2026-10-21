"""Bulk Stockfish evaluation with a SQLite cache and a pool of engines (parallel).
key = first 4 FEN fields + depth.  value = (cp_white, mate_white, best_uci)."""
import os, sqlite3, threading, queue, time
from concurrent.futures import ThreadPoolExecutor
import chess, chess.engine

from paths import STOCKFISH as SF_PATH
HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
DB_PATH = os.path.join(DATA, "evals.sqlite")


def fkey(fen):
    return " ".join(fen.split()[:4])


class EvalDB:
    def __init__(self, n_engines=4, threads=2, hash_mb=128, path=DB_PATH):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS ev (k TEXT PRIMARY KEY, cp INTEGER, mate INTEGER, best TEXT)")
        self.db.commit()
        self.lock = threading.Lock()
        self.n = n_engines
        self.pool = queue.Queue()
        self.engines = []
        for _ in range(n_engines):
            e = chess.engine.SimpleEngine.popen_uci(SF_PATH)
            e.configure({"Threads": threads, "Hash": hash_mb})
            self.engines.append(e)
            self.pool.put(e)

    def get(self, fen, depth):
        with self.lock:
            r = self.db.execute("SELECT cp, mate, best FROM ev WHERE k=?", (f"{fkey(fen)}|{depth}",)).fetchone()
        return r

    def _eval_one(self, fen, depth):
        b = chess.Board(fen)
        if b.is_game_over():
            o = b.outcome()
            cp = 0 if o.winner is None else (10000 if o.winner else -10000)
            return (cp, 0 if o.winner is not None else None, None)
        e = self.pool.get()
        try:
            info = e.analyse(b, chess.engine.Limit(depth=depth))
        finally:
            self.pool.put(e)
        sc = info["score"].white()
        pv = info.get("pv") or []
        return (sc.score(mate_score=10000), sc.mate(), pv[0].uci() if pv else None)

    def eval_many(self, fens, depth, log_every=2000, label=""):
        todo, out = [], {}
        seen = set()
        for f in fens:
            k = fkey(f)
            if k in seen:
                continue
            seen.add(k)
            r = self.get(f, depth)
            if r is None:
                todo.append(f)
            else:
                out[k] = r
        t0 = time.time()
        done = 0
        with ThreadPoolExecutor(max_workers=self.n) as ex:
            for f, r in zip(todo, ex.map(lambda f: self._eval_one(f, depth), todo)):
                out[fkey(f)] = r
                with self.lock:
                    self.db.execute("INSERT OR REPLACE INTO ev VALUES (?,?,?,?)", (f"{fkey(f)}|{depth}", r[0], r[1], r[2]))
                done += 1
                if done % 200 == 0:
                    with self.lock:
                        self.db.commit()
                if log_every and done % log_every == 0:
                    rate = done / max(1e-6, time.time() - t0)
                    print(f"  [{label}] {done}/{len(todo)} evals ({rate:.0f}/s)", flush=True)
        with self.lock:
            self.db.commit()
        return out

    def close(self):
        with self.lock:
            self.db.commit()
        for e in self.engines:
            try:
                e.quit()
            except Exception:
                pass
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
