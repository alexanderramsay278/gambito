"""Print Stockfish top-N moves (White-POV cp) for positions given as SAN sequences, one per line in a file or args.
py top.py [depth] [multipv] < positions.txt"""
import sys
import chess
from sf import Engine

depth = int(sys.argv[1]) if len(sys.argv) > 1 else 20
mpv = int(sys.argv[2]) if len(sys.argv) > 2 else 3
seqs = [l.strip() for l in sys.stdin if l.strip() and not l.startswith("#")]
with Engine() as E:
    for s in seqs:
        b = chess.Board()
        try:
            for m in s.split():
                b.push_san(m)
        except Exception as ex:
            print(f"[{s}] ILLEGAL: {ex}")
            continue
        res = E.eval(b, depth, mpv)
        parts = []
        for r in res:
            if r["san"] is None:
                parts.append("game over")
                continue
            sc = f"#{r['mate']}" if r["mate"] is not None else f"{r['cp']/100:+.2f}"
            bb = b.copy()
            pv = []
            for u in r["pv"][:6]:
                mv = chess.Move.from_uci(u)
                pv.append(bb.san(mv))
                bb.push(mv)
            parts.append(f"{r['san']} {sc} ({' '.join(pv)})")
        print(f"[{s}]\n    " + "\n    ".join(parts), flush=True)
