"""Rank the repertoire's traps by how often they actually arise in real 200-400 games.
reach(node) = probability a game reaches that position following the repertoire (DAG DP);
trap frequency = reach(position before the trap move) x real share of the trap move."""
import json, sys, os
import chess
import build
from tree import key


def reach_probs(R, color):
    nodes = R["nodes"]
    order = sorted(range(len(nodes)), key=lambda i: len(nodes[i]["_k"]))  # by ply of first path (DAG is ply-consistent)
    # recompute ply precisely from FEN
    def ply(i):
        p = nodes[i]["f"].split()
        return (int(p[5]) - 1) * 2 + (p[1] == "b")
    order = sorted(range(len(nodes)), key=ply)
    reach = [0.0] * len(nodes)
    reach[0] = 1.0
    for i in order:
        for m in nodes[i]["m"]:
            w = 1.0 if m["o"] else (m["p"] if m["p"] is not None else 0.0)
            reach[m["c"]] += reach[i] * w
    return reach


def main():
    T1, T2 = build.load_trees()
    out = {}
    for C in build.COURSES:
        R = build.build_course(C, T1, T2, None, do_engine=False)
        color = chess.WHITE if C["color"] == "w" else chess.BLACK
        reach = reach_probs(R, color)
        rows = []
        for i, nd in enumerate(R["nodes"]):
            for m in nd["m"]:
                if m["g"] == "trap" and not m["o"] and m["p"] is not None:
                    f = reach[i] * m["p"]
                    rows.append((f, " ".join(build.path_san(R["nodes"], i)), m["s"], m["p"], m["n"]))
        rows.sort(reverse=True)
        print(f"\n===== {C['id']}: traps ranked by real frequency")
        for f, path, san, p, n in rows:
            print(f"  {build.freq_text(f):>18s}  ({100*p:4.1f}% fall for it, n={n:4d})  {path} -> {san}")
        out[C["id"]] = [{"freq": f, "path": path, "move": san, "share": p, "n": n} for f, path, san, p, n in rows]
    json.dump(out, open(os.path.join(getattr(build, "DATA", os.path.join(build.HERE, "data")), "trap_stats.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
