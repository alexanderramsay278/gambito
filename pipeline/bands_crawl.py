"""Multi-band crawl of chess.com rated 10|0 rapid games.

1. find seeds: sample accounts from several country lists, keep active players (rapid game in the last
   45 days) whose current rapid rating falls in each band.
2. crawl each band: snowball through opponents inside the band; store games where BOTH players are in
   the band. Same "owner" bookkeeping as crawl.py (the non-owner side is a matchmaking draw).
Serial requests only. Resumable per band.
Usage: py bands_crawl.py [target_per_band]
"""
import json, os, random, re, sys, time
from collections import deque
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
DATA = DATA
BDIR = os.path.join(DATA, "bands")
API = "https://api.chess.com/pub"
UA = {"User-Agent": "personal-opening-research/1.0 (one-off rating-band opening study; serial requests)"}
MONTHS = [(2026, 10), (2026, 9)]
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
BANDS = [("r0500", 400, 600), ("r0700", 600, 800), ("r0900", 800, 1000), ("r1100", 1000, 1200),
         ("r1300", 1200, 1400), ("r1500", 1400, 1600), ("r1700", 1600, 1800), ("r1900", 1800, 2000),
         ("r2200", 2000, 2400)]
COUNTRIES = ["AU", "NZ", "IE", "SG", "ZA", "CA", "GB", "IN"]
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
MAX_PLAYERS = 4000

s = requests.Session()
s.headers.update(UA)
CLK = re.compile(r"\{[^}]*\}")
NUM = re.compile(r"\d+\.(?:\.\.)?")
TERM = re.compile(r'\[Termination "([^"]*)"\]')
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(url):
    for attempt in range(6):
        try:
            r = s.get(url, timeout=30)
        except Exception:
            time.sleep(2 + 2 * attempt)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
        if r.status_code in (403, 404, 410):
            return None
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        time.sleep(2)
    return None


def parse_moves(pgn):
    body = pgn.split("\n\n", 1)[-1]
    body = NUM.sub(" ", CLK.sub(" ", body))
    return [t for t in body.split() if t not in RESULTS]


def band_of(r):
    for bid, lo, hi in BANDS:
        if lo <= r < hi or (bid == BANDS[-1][0] and lo <= r <= hi):
            return bid
    return None


def find_seeds(per_band=3, max_checks=3000):
    path = os.path.join(BDIR, "seeds.json")
    seeds = json.load(open(path)) if os.path.exists(path) else {b[0]: [] for b in BANDS}
    now = time.time()
    checked = 0
    rnd = random.Random(11)
    for cc in COUNTRIES:
        if all(len(seeds[b[0]]) >= per_band for b in BANDS) or checked >= max_checks:
            break
        cache = os.path.join(BDIR, f"players_{cc}.json")
        if os.path.exists(cache):
            players = json.load(open(cache))
        else:
            d = get(f"{API}/country/{cc}/players")
            players = (d or {}).get("players", [])
            if len(players) > 200000:
                players = rnd.sample(players, 200000)
            json.dump(players, open(cache, "w"))
        rnd.shuffle(players)
        log(f"country {cc}: {len(players)} accounts")
        for u in players[:900]:
            if all(len(seeds[b[0]]) >= per_band for b in BANDS) or checked >= max_checks:
                break
            st = get(f"{API}/player/{u}/stats")
            checked += 1
            last = (st or {}).get("chess_rapid", {}).get("last", {})
            if not last or now - last.get("date", 0) > 45 * 86400:
                continue
            b = band_of(last.get("rating", 0))
            if b and len(seeds[b]) < per_band and u.lower() not in seeds[b]:
                seeds[b].append(u.lower())
                log(f"seed {b}: {u} ({last['rating']}) after {checked} checks")
                json.dump(seeds, open(path, "w"), indent=1)
    json.dump(seeds, open(path, "w"), indent=1)
    return seeds


def crawl_band(bid, lo, hi, seed_list):
    d = os.path.join(BDIR, bid)
    os.makedirs(d, exist_ok=True)
    out_path, st_path = os.path.join(d, "games.jsonl"), os.path.join(d, "state.json")
    seen = set()
    if os.path.exists(out_path):
        for line in open(out_path, encoding="utf-8"):
            try:
                seen.add(json.loads(line)["id"])
            except Exception:
                pass
    if os.path.exists(st_path):
        st = json.load(open(st_path))
        visited, queue = set(st["visited"]), deque(st["queue"])
    else:
        visited, queue = set(), deque(seed_list)
    queued = set(queue) | visited
    out = open(out_path, "a", encoding="utf-8")
    t0, reqs = time.time(), 0
    log(f"{bid} [{lo},{hi}] start: {len(seen)} games, queue {len(queue)}")
    while queue and len(seen) < TARGET and len(visited) < MAX_PLAYERS:
        owner = queue.popleft()
        visited.add(owner)
        for (y, m) in MONTHS:
            arch = get(f"{API}/player/{owner}/games/{y}/{m:02d}")
            reqs += 1
            for g in (arch or {}).get("games", []):
                try:
                    if g.get("rules") != "chess" or not g.get("rated") or g.get("time_control") != "600":
                        continue
                    if g.get("initial_setup", START_FEN) != START_FEN:
                        continue
                    w, b = g["white"], g["black"]
                    wr, br = w.get("rating", 0), b.get("rating", 0)
                    owner_is_white = w["username"].lower() == owner.lower()
                    opp, opp_r = (b["username"], br) if owner_is_white else (w["username"], wr)
                    if lo <= opp_r <= hi and opp.lower() not in queued:
                        queue.append(opp.lower())
                        queued.add(opp.lower())
                    if not (lo <= wr <= hi and lo <= br <= hi):
                        continue
                    gid = g.get("uuid") or g["url"]
                    if gid in seen:
                        continue
                    pgn = g.get("pgn", "")
                    mv = parse_moves(pgn)
                    tm = TERM.search(pgn)
                    out.write(json.dumps({
                        "id": gid, "t": g.get("end_time"), "w": w["username"], "b": b["username"],
                        "wr": wr, "br": br, "wres": w.get("result"), "bres": b.get("result"),
                        "eco": (g.get("eco") or "").rsplit("/", 1)[-1], "term": tm.group(1) if tm else "",
                        "owner": "w" if owner_is_white else "b", "plies": len(mv), "mv": mv[:40]}) + "\n")
                    seen.add(gid)
                except Exception as e:
                    log("skip game:", e)
            time.sleep(0.05)
        if len(visited) % 25 == 0:
            out.flush()
            json.dump({"visited": sorted(visited), "queue": list(queue)}, open(st_path, "w"))
            log(f"{bid}: players={len(visited)} queue={len(queue)} games={len(seen)} reqs={reqs} ({time.time()-t0:.0f}s)")
    out.close()
    json.dump({"visited": sorted(visited), "queue": list(queue)}, open(st_path, "w"))
    log(f"{bid} DONE games={len(seen)} players={len(visited)} reqs={reqs} secs={time.time()-t0:.0f}")


def main():
    os.makedirs(BDIR, exist_ok=True)
    seeds = find_seeds()
    log("seeds:", json.dumps({k: len(v) for k, v in seeds.items()}))
    for bid, lo, hi in BANDS:
        sl = seeds.get(bid) or []
        if not sl:
            log(f"{bid}: no seeds, skipping")
            continue
        crawl_band(bid, lo, hi, sl)
    log("ALL BANDS DONE")


if __name__ == "__main__":
    main()
