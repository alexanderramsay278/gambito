"""Practical value of an opening policy against the REAL 200-400 player pool.

Expectimax: on our turn we play the policy move (or Stockfish's best move if the policy
doesn't cover the position); on the opponent's turn we average over the moves 200-400
opponents actually played there (random-side sample). Replies under MIN_SHARE are
grouped as 'other' and valued at the engine eval of the current position (assumes the
opponent finds a decent move). Stop at the ply horizon or where data gets thin (<MIN_N);
leaves are scored by Stockfish win-probability for OUR side.

Also reports trap rate: P(opponent makes a >=30pt win-chance blunder within the horizon).
"""
import pickle, os, sys
import chess
from tree import key
from sf import Engine, wp

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
MIN_N, MIN_SHARE = 30, 0.02


class Practical:
    def __init__(self, band="200_400", depth=14):
        self.T = pickle.load(open(os.path.join(DATA, f"tree_{band}.pkl"), "rb"))["nodes"]
        self.E = Engine()
        self.depth = depth

    def wp_us(self, b, our):
        p = wp(self.E.cp(b, self.depth))
        return p if our == chess.WHITE else 1 - p

    def run(self, b, policy, our, plies):
        """returns (expected win-prob for us, P(opponent blunder along the way))"""
        if plies == 0 or b.is_game_over():
            return self.wp_us(b, our), 0.0
        if b.turn == our:
            san = policy.get(key(b))
            mv = b.parse_san(san) if san else chess.Move.from_uci(self.E.eval(b, self.depth)[0]["uci"])
            b.push(mv)
            r = self.run(b, policy, our, plies - 1)
            b.pop()
            return r
        nd = self.T.get(key(b))
        here = self.wp_us(b, our)
        if not nd or nd["nr"] < MIN_N:
            return here, 0.0
        tot, val, blunder, covered = nd["nr"], 0.0, 0.0, 0
        best_for_opp = 1 - here
        for san, (a, r, ws, uci) in nd["mv"].items():
            share = r / tot
            if share < MIN_SHARE:
                continue
            covered += r
            b.push(chess.Move.from_uci(uci))
            after_opp = 1 - self.wp_us(b, our)  # opponent's win chance after their move
            v, bl = self.run(b, policy, our, plies - 1)
            b.pop()
            is_bl = (best_for_opp - after_opp) >= 0.30
            val += share * v
            blunder += share * (1.0 if is_bl else bl)
        rest = (tot - covered) / tot
        val += rest * here
        return val, blunder


def policy_from_lines(lines):
    """lines: list of SAN strings from the start position. Our moves = every move in the lines."""
    pol = {}
    for ln in lines:
        b = chess.Board()
        for san in ln.split():
            pol.setdefault(key(b), san)
            b.push_san(san)
    return pol


if __name__ == "__main__":
    pass
