"""Compare opening policies by practical value vs the real 300-level pool.
py compare.py white|black [band] [depth] [plies]"""
import sys, time
import chess
from practical import Practical, policy_from_lines

WHITE_START = "e4 e5"
WHITE = {
    "Italian -> Evans + Fried Liver": ["e4 e5 Nf3 Nc6 Bc4 Bc5 b4", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5"],
    "Italian quiet (c3/d3)": ["e4 e5 Nf3 Nc6 Bc4 Bc5 c3", "e4 e5 Nf3 Nc6 Bc4 Nf6 d3"],
    "Scotch Gambit": ["e4 e5 Nf3 Nc6 d4 exd4 Bc4"],
    "Scotch": ["e4 e5 Nf3 Nc6 d4 exd4 Nxd4"],
    "Ruy Lopez": ["e4 e5 Nf3 Nc6 Bb5"],
    "Four Knights / 3.Nc3": ["e4 e5 Nf3 Nc6 Nc3"],
    "Danish Gambit": ["e4 e5 d4 exd4 c3 dxc3 Bc4 cxb2 Bxb2"],
    "Centre Game": ["e4 e5 d4 exd4 Qxd4"],
    "King's Gambit": ["e4 e5 f4"],
    "Vienna": ["e4 e5 Nc3"],
    "Bishop's Opening": ["e4 e5 Bc4"],
    "Wayward Queen 2.Qh5": ["e4 e5 Qh5"],
    "Engine only (2.Nf3...)": ["e4 e5 Nf3"],
}
BLACK_VS_E4 = {
    "1...e5 + Stafford (2...Nf6 3.Nxe5 Nc6)": ["e4 e5 Nf3 Nf6 Nxe5 Nc6"],
    "1...e5 + Petrov (2...Nf6 3.Nxe5 d6)": ["e4 e5 Nf3 Nf6 Nxe5 d6"],
    "1...e5 + 2...Nc6 (engine after)": ["e4 e5 Nf3 Nc6"],
    "1...e5 + 2...Nc6, Traxler vs Ng5": ["e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 Bc5"],
    "1...e5 + 2...Nc6, Blackburne Shilling 3...Nd4": ["e4 e5 Nf3 Nc6 Bc4 Nd4"],
    "1...e5 + Elephant (2...d5)": ["e4 e5 Nf3 d5"],
    "1...e5 + Latvian (2...f5)": ["e4 e5 Nf3 f5"],
    "1...d5 Scandinavian": ["e4 d5"],
    "1...c5 Sicilian": ["e4 c5"],
    "1...e6 French": ["e4 e6"],
    "1...c6 Caro-Kann": ["e4 c6"],
    "1...Nc6 Nimzowitsch": ["e4 Nc6"],
    "1...Nf6 Alekhine": ["e4 Nf6"],
}
BLACK_VS_D4 = {
    "Englund 1...e5": ["d4 e5"],
    "1...d5": ["d4 d5"],
    "1...d5 + Albin vs c4": ["d4 d5 c4 e5"],
    "1...Nf6": ["d4 Nf6"],
    "1...e6": ["d4 e6"],
    "1...Nc6": ["d4 Nc6"],
    "Dutch 1...f5": ["d4 f5"],
}


def run(sets, start, our, P, plies):
    rows = []
    for name, lines in sets.items():
        t0 = time.time()
        pol = policy_from_lines(lines)
        b = chess.Board()
        for san in start.split():
            b.push_san(san)
        # walk the forced prefix of the first line beyond start if it's ours (e.g. 1...e5 for black)
        v, bl = P.run(b, pol, our, plies)
        rows.append((v, bl, name, time.time() - t0))
        print(f"  {name:48s} expected win% {100*v:5.1f}   opp-blunder rate {100*bl:5.1f}%   ({time.time()-t0:.0f}s)", flush=True)
    print("\nRanked:")
    for v, bl, name, _ in sorted(rows, reverse=True):
        print(f"  {100*v:5.1f}  blunder {100*bl:5.1f}%  {name}")


if __name__ == "__main__":
    which = sys.argv[1]
    band = sys.argv[2] if len(sys.argv) > 2 else "150_450"
    depth = int(sys.argv[3]) if len(sys.argv) > 3 else 14
    plies = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    P = Practical(band, depth)
    try:
        if which == "white":
            run(WHITE, WHITE_START, chess.WHITE, P, plies)
        elif which == "black_e4":
            run(BLACK_VS_E4, "e4", chess.BLACK, P, plies)
        elif which == "black_d4":
            run(BLACK_VS_D4, "d4", chess.BLACK, P, plies)
    finally:
        P.E.close()
