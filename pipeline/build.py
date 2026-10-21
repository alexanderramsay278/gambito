"""Build trainer data + PGN from repertoire text files, with legality, engine and coverage checks.

Repertoire file format (rep_white.txt / rep_black.txt):
  @ Section | Line name          <- starts a line
  e4 {comment} e5 d4 {!trap comment}  ...   (moves may span several lines; blank line ends it)
  Comments attach to the move before them. A leading "!trap" or "!gambit" tags the move.
  A comment only needs writing once; later lines that repeat the move inherit it.

py build.py check   -> legality + conflicts + coverage + engine audit (no output files)
py build.py build   -> also writes out/trainer.html, out/*.pgn, out/lines_*.md
"""
import json, os, pickle, re, sys, base64, datetime, hashlib
import chess, chess.pgn
from tree import key
from sf import Engine

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
OUT = TRAINER_DIR
DEPTH = 20
COURSES = [
    {"id": "white", "file": "rep_white.txt", "color": "w", "tab": "White",
     "title": "White · Danish-Gambit repertoire", "subtitle": "1.e4 and attack. Built from 116k real 200–400 rapid games."},
    {"id": "black", "file": "rep_black.txt", "color": "b", "tab": "Black",
     "title": "Black · Englund + anti-Scholar repertoire", "subtitle": "1...e5 against almost everything. Built from 116k real 200–400 rapid games."},
]
TOKEN = re.compile(r"\{[^}]*\}|[^\s{}]+")


def load_trees():
    t1 = pickle.load(open(os.path.join(DATA, "tree_200_400.pkl"), "rb"))["nodes"]
    t2 = pickle.load(open(os.path.join(DATA, "tree_150_450.pkl"), "rb"))["nodes"]
    return t1, t2


def parse_rep(path):
    lines, cur = [], None
    for raw in open(path, encoding="utf-8").read().splitlines() + [""]:
        s = raw.strip()
        if s.startswith("#"):
            continue
        if s.startswith("@"):
            sec, name = [x.strip() for x in s[1:].split("|", 1)]
            cur = {"sec": sec, "name": name, "text": ""}
            lines.append(cur)
        elif s and cur is not None:
            cur["text"] += " " + s
        elif not s:
            cur = None
    for L in lines:
        mv = []
        for tok in TOKEN.findall(L["text"]):
            if tok.startswith("{"):
                c = tok[1:-1].strip()
                tag = None
                for t in ("!trap", "!gambit", "!ok"):
                    if c.startswith(t):
                        tag, c = t[1:], c[len(t):].strip()
                if not mv:
                    raise ValueError(f"comment before first move in {L['name']}")
                mv[-1]["t"] = c
                mv[-1]["g"] = None if tag == "ok" else tag
                mv[-1]["ok"] = tag == "ok"
            else:
                tok = re.sub(r"^\d+\.(\.\.)?", "", tok)
                if tok:
                    mv.append({"s": tok, "t": "", "g": None})
        L["moves"] = mv
    return lines


def freq(T1, T2, b, san):
    """share of random-side players choosing san at position b; prefer 200-400 band, fall back to 150-450"""
    for T, minn in ((T1, 30), (T2, 15)):
        nd = T.get(key(b))
        if nd and nd["nr"] >= minn:
            e = nd["mv"].get(san)
            r = e[1] if e else 0
            return r / nd["nr"], r, nd["nr"]
    return None, 0, 0


def build_course(C, T1, T2, E, do_engine=True):
    color = chess.WHITE if C["color"] == "w" else chess.BLACK
    reps = parse_rep(os.path.join(HERE, C["file"]))
    nodes = [{"f": chess.Board().fen(), "m": [], "_k": ()}]
    index = {key(chess.Board()): 0}   # position-keyed: transpositions merge into one node
    errors, warns = [], []
    line_paths = []
    for L in reps:
        b = chess.Board()
        path_keys, node_path = (), [0]
        for i, mv in enumerate(L["moves"]):
            try:
                m = b.parse_san(mv["s"])
            except Exception as ex:
                errors.append(f"[{L['name']}] illegal move {mv['s']} at ply {i+1} ({b.fen()}): {ex}")
                break
            san = b.san(m)
            ni = index[key(b)]
            node = nodes[ni]
            ours = b.turn == color
            existing = next((x for x in node["m"] if x["u"] == m.uci()), None)
            if ours:
                other = next((x for x in node["m"] if x["o"] and x["u"] != m.uci()), None)
                if other:
                    errors.append(f"[{L['name']}] CONFLICT at {' '.join(k for k in path_keys)}: repertoire already plays {other['s']}, line wants {san}")
                    break
            if existing is None:
                p, r, n = (None, 0, 0) if ours else freq(T1, T2, b, san)
                b.push(m)
                nk = path_keys + (m.uci(),)
                if key(b) not in index:
                    nodes.append({"f": b.fen(), "m": [], "_k": nk})
                    index[key(b)] = len(nodes) - 1
                existing = {"s": san, "u": m.uci(), "c": index[key(b)], "o": 1 if ours else 0,
                            "p": None if p is None else round(p, 4), "n": r, "t": mv["t"], "g": mv["g"], "_pos": nodes[ni]["f"], "_ok": mv.get("ok", False)}
                node["m"].append(existing)
            else:
                if mv["t"] and not existing["t"]:
                    existing["t"], existing["g"] = mv["t"], mv["g"]
                elif mv["t"] and existing["t"] and mv["t"] != existing["t"]:
                    warns.append(f"[{L['name']}] second comment for {san} ignored")
                b.push(m)
                nk = path_keys + (m.uci(),)
            path_keys = nk
            node_path.append(index[key(b)])
        line_paths.append((L, node_path))

    # auto-link transpositions: if a real opponent reply reaches a position already in the repertoire,
    # add that edge so the trainer (and coverage) follow it without a hand-written connector line.
    linked = 0
    for ni in range(len(nodes)):
        nd = nodes[ni]
        b = chess.Board(nd["f"])
        if b.turn == color or not nd["m"]:
            continue
        for T, minn in ((T1, 30), (T2, 15)):
            dn = T.get(key(b))
            if not (dn and dn["nr"] >= minn):
                continue
            have = {m["u"] for m in nd["m"]}
            for san, (a, r, ws, uci) in dn["mv"].items():
                if uci in have or r < 3:
                    continue
                b2 = b.copy()
                b2.push(chess.Move.from_uci(uci))
                tgt = index.get(key(b2))
                if tgt is None or tgt == 0:
                    continue
                nd["m"].append({"s": san, "u": uci, "c": tgt, "o": 0, "p": round(r / dn["nr"], 4), "n": r,
                                "t": "Transposes into a line you already know.", "g": None, "_pos": nd["f"], "_ok": False})
                linked += 1
            break
    if linked:
        warns.append(f"auto-linked {linked} transposition edge(s)")

    # sampling/ordering weight q: the real share where we have data; where a node has no data,
    # split evenly among the covered replies (i.e. assume the opponent stays in book there).
    for nd in nodes:
        opp = [m for m in nd["m"] if not m["o"]]
        if not opp:
            continue
        if all(m["p"] is None for m in opp):
            for m in opp:
                m["q"] = round(1.0 / len(opp), 4)
        else:
            for m in opp:
                m["q"] = m["p"] if m["p"] is not None else 0.0

    # lines = every root-to-leaf path in the position DAG (so transposed move orders become lines too)
    rep_paths = [(L, p) for L, p in line_paths]
    all_paths = []

    def dfs(ni, path):
        if len(path) > 60:
            return
        if not nodes[ni]["m"]:
            all_paths.append(list(path))
            return
        for m in nodes[ni]["m"]:
            if m["c"] in path:
                continue
            path.append(m["c"])
            dfs(m["c"], path)
            path.pop()
    dfs(0, [0])

    def common(a, b):
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        return k
    out_lines = []
    for p in all_paths:
        best = max(rep_paths, key=lambda lp: (common(lp[1], p), -len(lp[1])))
        L, lp = best
        if lp != p:
            leaf_owner = next((L2 for L2, p2 in rep_paths if p2[-1] == p[-1]), None)
            name = L["name"] + (" → " + leaf_owner["name"] if leaf_owner and leaf_owner is not L else "")
        else:
            name = L["name"]
        w = 1.0
        ucis = []
        for a, bnode in zip(p, p[1:]):
            m = next(x for x in nodes[a]["m"] if x["c"] == bnode)
            ucis.append(m["u"])
            if not m["o"]:
                w *= m["q"]
        lid = C["id"][0] + "-" + hashlib.sha1(" ".join(ucis).encode()).hexdigest()[:10]
        out_lines.append({"id": lid, "sec": L["sec"], "name": name, "path": p, "w": round(w, 6)})
    for L, p in line_paths:
        if nodes[p[-1]]["m"] and not any(common(p, q) == len(p) for q in all_paths):
            warns.append(f"[{L['name']}] not on any leaf path?")

    # legal moves at our nodes; engine evals
    audit = []
    for ni, nd in enumerate(nodes):
        b = chess.Board(nd["f"])
        if b.turn == color and nd["m"]:
            nd["L"] = [m.uci() for m in b.legal_moves]
        for m in nd["m"]:
            if not do_engine:
                m["e"] = None
                continue
            b2 = chess.Board(nd["f"])
            b2.push(chess.Move.from_uci(m["u"]))
            m["e"] = E.cp(b2, DEPTH)
            if m["o"]:
                best = E.eval(chess.Board(nd["f"]), DEPTH)[0]
                sign = 1 if color == chess.WHITE else -1
                loss = sign * (best["cp"] - m["e"])
                if loss > 70 and m["g"] != "gambit" and not m.get("_ok"):
                    audit.append(f"  our move {m['s']:7s} loses {loss:4d}cp vs best {best['san']} @ {' '.join(path_san(nodes, ni))}")
    # coverage: common opponent replies not in repertoire (only where the opponent is to move)
    cover = []
    for ni, nd in enumerate(nodes):
        b = chess.Board(nd["f"])
        if b.turn == color or not nd["m"]:
            continue
        for T, minn in ((T1, 30), (T2, 15)):
            dn = T.get(key(b))
            if dn and dn["nr"] >= minn:
                have = {m["s"] for m in nd["m"]}
                for san, (a, r, ws, uci) in sorted(dn["mv"].items(), key=lambda kv: -kv[1][1]):
                    sh = r / dn["nr"]
                    if san not in have and sh >= 0.05 and r >= 8:
                        cover.append((sh, " ".join(path_san(nodes, ni)), san, r, dn["nr"]))
                break
    traps = []
    if do_engine:
        for ni, nd in enumerate(nodes):
            for m in nd["m"]:
                if m["g"] == "trap" and m.get("e") is not None:
                    e = m["e"] if color == chess.WHITE else -m["e"]
                    traps.append(f"  {e/100:+7.2f} (for us) after {' '.join(path_san(nodes, ni))} {m['s']}")
    return {"nodes": nodes, "lines": out_lines, "errors": errors, "warns": warns, "audit": audit, "cover": cover, "traps": traps}


def path_san(nodes, ni):
    # reconstruct SAN path to node ni
    k = nodes[ni]["_k"]
    b, out = chess.Board(), []
    for u in k:
        m = chess.Move.from_uci(u)
        out.append(b.san(m))
        b.push(m)
    return out


def pieces():
    d = {}
    for c in "wb":
        for p in "KQRBNP":
            svg = open(os.path.join(HERE, "pieces", f"{c}{p}.svg"), "rb").read()
            d[c + p] = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    return d


def to_pgn(C, R):
    """One PGN game (= Lichess study chapter) per section, with all lines as variations + comments."""
    color = chess.WHITE if C["color"] == "w" else chess.BLACK
    nodes = R["nodes"]
    games = []
    secs = []
    for L in R["lines"]:
        if L["sec"] not in secs:
            secs.append(L["sec"])
    for sec in secs:
        g = chess.pgn.Game()
        g.headers["Event"] = f"{C['tab']} repertoire: {sec}"
        g.headers["Site"] = "JARVIS opening trainer"
        g.headers["Date"] = datetime.date.today().strftime("%Y.%m.%d")
        g.headers["White"] = "Repertoire" if C["color"] == "w" else "Opponent"
        g.headers["Black"] = "Opponent" if C["color"] == "w" else "Repertoire"
        g.headers["Result"] = "*"
        g.headers["Orientation"] = "white" if C["color"] == "w" else "black"
        sec_lines = sorted([L for L in R["lines"] if L["sec"] == sec], key=lambda L: -L["w"])
        for L in sec_lines:
            gn = g
            for a, bnode in zip(L["path"], L["path"][1:]):
                m = next(x for x in nodes[a]["m"] if x["c"] == bnode)
                mv = chess.Move.from_uci(m["u"])
                nxt = next((v for v in gn.variations if v.move == mv), None)
                if nxt is None:
                    nxt = gn.add_variation(mv)
                    txt = m["t"] or ""
                    if not m["o"] and m["p"] is not None:
                        txt = (f"[{100*m['p']:.0f}% of 300s] " + txt).strip()
                    nxt.comment = txt
                gn = nxt
        games.append(g)
    return "\n\n".join(str(g) for g in games) + "\n"


def freq_text(w):
    if not w:
        return "rare"
    if w >= 0.05:
        return f"{100*w:.0f}% of games"
    n = 1 / w
    r = round(n) if n < 100 else (round(n / 10) * 10 if n < 1000 else round(n / 100) * 100)
    return f"1 in {r:,} games"


def lines_md(C, R):
    nodes = R["nodes"]
    tot = sum(L["w"] for L in R["lines"])
    out = [f"# {C['tab']}: every repertoire line (auto-generated)", "",
           f"> **Generated:** {datetime.date.today().isoformat()} by the pipeline in [[03 System/(C) Pipeline]]. Don't edit this note by hand: edit `rep_{C['id']}.txt` and rebuild.",
           "> **Bold** = your move. The frequency is how often a real game (200–400 rated, 10|0) follows the line all the way to its end; "
           "where the data runs out, the opponent is assumed to stay in book.",
           f"> {len(R['lines'])} lines; together they cover **{100*tot:.0f}%** of real games to the end of the book.", ""]
    sec = None
    for L in sorted(R["lines"], key=lambda L: (secorder(R, L["sec"]), -L["w"])):
        if L["sec"] != sec:
            sec = L["sec"]
            out.append(f"\n### {sec}\n")
        b = chess.Board()
        toks = []
        for a, bnode in zip(L["path"], L["path"][1:]):
            m = next(x for x in nodes[a]["m"] if x["c"] == bnode)
            mv = chess.Move.from_uci(m["u"])
            num = b.fullmove_number
            pre = f"{num}." if b.turn == chess.WHITE else (f"{num}..." if not toks else "")
            s = m["s"]
            toks.append(f"{pre}**{s}**" if m["o"] else f"{pre}{s}")
            b.push(mv)
        out.append(f"- **{L['name']}** ({freq_text(L['w'])}): {' '.join(toks)}")
    return "\n".join(out) + "\n"


def secorder(R, sec):
    order = []
    for L in R["lines"]:
        if L["sec"] not in order:
            order.append(L["sec"])
    return order.index(sec)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    do_engine = "--no-engine" not in sys.argv
    T1, T2 = load_trees()
    E = Engine() if do_engine else None
    results = {}
    try:
        for C in COURSES:
            if not os.path.exists(os.path.join(HERE, C["file"])):
                continue
            R = build_course(C, T1, T2, E, do_engine)
            results[C["id"]] = (C, R)
            tot = sum(L["w"] for L in R["lines"])
            print(f"\n===== {C['id']}: {len(R['lines'])} lines, {len(R['nodes'])} nodes, coverage {100*tot:.1f}% of games")
            for e in R["errors"]:
                print("ERROR", e)
            for w in R["warns"]:
                print("warn ", w)
            if R["audit"]:
                print("ENGINE AUDIT (our moves >70cp worse than best, not tagged !gambit):")
                print("\n".join(R["audit"]))
            if R.get("traps"):
                print("TRAP TRACE (eval for us right after each !trap move):")
                print("\n".join(R["traps"]))
            if R["cover"]:
                print("UNCOVERED common replies (>=5% share, n>=8):")
                for sh, p, san, r, n in sorted(R["cover"], key=lambda x: -x[0])[:60]:
                    print(f"  {100*sh:5.1f}% (n={r}/{n})  after [{p}]  -> {san}")
    finally:
        if E:
            E.close()
    if mode == "build":
        os.makedirs(OUT, exist_ok=True)
        data = {"meta": {"generated": datetime.date.today().isoformat()}, "pieces": pieces(), "courses": []}
        for cid, (C, R) in results.items():
            nodes = [{k: v for k, v in n.items() if not k.startswith("_")} for n in R["nodes"]]
            for n in nodes:
                n["m"] = [{k: v for k, v in m.items() if not k.startswith("_")} for m in n["m"]]
            data["courses"].append({"id": cid, "tab": C["tab"], "title": C["title"], "subtitle": C["subtitle"],
                                    "color": C["color"], "nodes": nodes, "lines": R["lines"]})
            open(os.path.join(TRAINER_DIR, f"(C) {C['tab']} Repertoire.pgn"), "w", encoding="utf-8").write(to_pgn(C, R))
            open(os.path.join(REP_DIR, f"(C) {C['tab']} - All Lines.md"), "w", encoding="utf-8").write(lines_md(C, R))
        tpl = open(os.path.join(HERE, "trainer_template.html"), encoding="utf-8").read()
        html = tpl.replace("/*__REP_DATA__*/null", json.dumps(data, separators=(",", ":")))
        open(os.path.join(TRAINER_DIR, "(C) Opening Trainer.html"), "w", encoding="utf-8").write(html)
        print(f"\nwrote {OUT}: trainer.html ({len(html)//1024} KB), pgn + lines md")


if __name__ == "__main__":
    main()
