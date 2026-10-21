"""Split-half robustness (back up tree_150_450.pkl first: tree.main() overwrites it, this script then renames it): build trees from two disjoint halves of the games (by game id hash),
so the opening comparison can be re-run on each half.  py split_tree.py 150 450 0|1"""
import sys, zlib, json, os
import tree

LOW, HIGH, HALF = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
orig_iter = tree.iter_games


def half_iter(low, high):
    for g in orig_iter(low, high):
        if zlib.crc32(g["id"].encode()) % 2 == HALF:
            yield g


tree.iter_games = half_iter
sys.argv = [sys.argv[0], str(LOW), str(HIGH)]
tree.main()
DATA = getattr(tree, "DATA", os.path.join(tree.HERE, "data"))
src = os.path.join(DATA, f"tree_{LOW}_{HIGH}.pkl")
# tree.main wrote tree_LOW_HIGH.pkl: move it aside so the full tree isn't overwritten
dst = os.path.join(DATA, f"tree_{LOW}_{HIGH}h{HALF}.pkl")
os.replace(src, dst)
print("wrote", dst)
