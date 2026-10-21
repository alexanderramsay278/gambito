"""Stockfish 19 wrapper with a persistent eval cache (data/evals.json).
eval(board, depth, multipv) -> list of {san, uci, cp (White POV, mate=+-10000), mate, pv}"""
import json, math, os, time
import chess, chess.engine

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
from paths import STOCKFISH as SF_PATH
CACHE = os.path.join(DATA, "evals.json")


def wp(cp):
    """Lichess win-probability curve (0..1) for White given centipawns from White's POV."""
    return 1 / (1 + math.exp(-0.00368208 * cp))


class Engine:
    def __init__(self, threads=8, hash_mb=1024):
        self.eng = chess.engine.SimpleEngine.popen_uci(SF_PATH)
        self.eng.configure({"Threads": threads, "Hash": hash_mb})
        self.cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
        self.dirty = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def eval(self, board, depth=18, multipv=1):
        k = f"{board.fen()}|{depth}|{multipv}"
        if k in self.cache:
            return self.cache[k]
        if board.is_game_over():
            o = board.outcome()
            cp = 0 if o.winner is None else (10000 if o.winner else -10000)
            res = [{"san": None, "uci": None, "cp": cp, "mate": 0 if o.winner is not None else None, "pv": []}]
        else:
            infos = self.eng.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
            if isinstance(infos, dict):
                infos = [infos]
            res = []
            for info in infos:
                pv = info.get("pv", [])
                sc = info["score"].white()
                res.append({"san": board.san(pv[0]) if pv else None, "uci": pv[0].uci() if pv else None,
                            "cp": sc.score(mate_score=10000), "mate": sc.mate(),
                            "pv": [m.uci() for m in pv[:10]]})
        self.cache[k] = res
        self.dirty += 1
        if self.dirty >= 50:
            self.save()
        return res

    def cp(self, board, depth=18):
        return self.eval(board, depth)[0]["cp"]

    def save(self):
        # merge with whatever another process may have written, then atomic replace (retry: Windows locks)
        try:
            disk = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
        except Exception:
            disk = {}
        disk.update(self.cache)
        self.cache = disk
        tmp = f"{CACHE}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.cache, f)
        for i in range(20):
            try:
                os.replace(tmp, CACHE)
                break
            except PermissionError:
                time.sleep(0.2)
        self.dirty = 0

    def close(self):
        """Call explicitly (or use `with Engine() as E`). Never rely on atexit: on Python 3.14 the
        interpreter joins python-chess's engine thread before atexit runs -> deadlock at exit."""
        try:
            self.save()
        finally:
            try:
                self.eng.quit()
            except Exception:
                pass
