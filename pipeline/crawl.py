"""Crawl chess.com public API for rated 10|0 rapid games in a low rating band.

Method (snowball sample):
  1. Seed: random Australian accounts whose current rapid rating is in the crawl band
     and who played rapid in the last 40 days.
  2. For each crawled player ("owner"), pull their monthly game archives.
  3. Keep games that are: standard chess, rated, time_control == "600" (10|0),
     and BOTH players rated within [STORE_LOW, STORE_HIGH] at game time.
  4. Opponents in the crawl band are queued -> breadth-first over the 300-level pool.
  Each game stores which side was the archive owner. The other side was a
  matchmaking draw, so it is a random sample of the pool. Analysis uses that side
  for "what do opponents play" frequencies.

Serial requests only (chess.com: serial access is unlimited, parallel may 429).
Output: data/games.jsonl (one game per line). Resumable.
"""
import json, os, random, re, sys, time
from collections import deque

import requests

API = "https://api.chess.com/pub"
UA = {"User-Agent": "personal-opening-research/1.0 (one-off rating-band opening study; serial requests)"}
MONTHS = [(2026, 10), (2026, 9)]
STORE_LOW, STORE_HIGH = 150, 450      # both players must be in this band to store the game
ENQ_LOW, ENQ_HIGH = 200, 420          # opponents in this band get crawled next
TARGET_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
MAX_PLAYERS = 9000
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
DATA = DATA
OUT = os.path.join(DATA, "games.jsonl")
STATE = os.path.join(DATA, "crawl_state.json")

s = requests.Session()
s.headers.update(UA)
NOW = time.time()

CLK = re.compile(r"\{[^}]*\}")
NUM = re.compile(r"\d+\.(?:\.\.)?")
TERM = re.compile(r'\[Termination "([^"]*)"\]')
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


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


def find_seeds(n=4, max_checks=800):
    players = json.load(open(os.path.join(DATA, "au_players.json")))["players"]
    rnd = random.Random(7)
    rnd.shuffle(players)
    seeds = []
    for i, u in enumerate(players[:max_checks]):
        st = get(f"{API}/player/{u}/stats")
        last = (st or {}).get("chess_rapid", {}).get("last", {})
        if last and ENQ_LOW <= last.get("rating", 0) <= ENQ_HIGH and NOW - last.get("date", 0) < 40 * 86400:
            seeds.append(u)
            print(f"seed {u} rapid={last['rating']} (checked {i + 1})", flush=True)
            if len(seeds) >= n:
                break
    return seeds


def main():
    os.makedirs(DATA, exist_ok=True)
    seen_games = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                try:
                    seen_games.add(json.loads(line)["id"])
                except Exception:
                    pass
    if os.path.exists(STATE):
        st = json.load(open(STATE))
        visited, queue = set(st["visited"]), deque(st["queue"])
    else:
        visited, queue = set(), deque(find_seeds())
    queued = set(queue) | visited
    print(f"resume: {len(seen_games)} games, {len(visited)} visited, {len(queue)} queued", flush=True)

    out = open(OUT, "a", encoding="utf-8")
    reqs, t0 = 0, time.time()
    while queue and len(seen_games) < TARGET_GAMES and len(visited) < MAX_PLAYERS:
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
                    if ENQ_LOW <= opp_r <= ENQ_HIGH and opp.lower() not in queued:
                        queue.append(opp.lower())
                        queued.add(opp.lower())
                    if not (STORE_LOW <= wr <= STORE_HIGH and STORE_LOW <= br <= STORE_HIGH):
                        continue
                    gid = g.get("uuid") or g["url"]
                    if gid in seen_games:
                        continue
                    pgn = g.get("pgn", "")
                    mv = parse_moves(pgn)
                    tm = TERM.search(pgn)
                    rec = {
                        "id": gid, "url": g.get("url"), "t": g.get("end_time"),
                        "w": w["username"], "b": b["username"], "wr": wr, "br": br,
                        "wres": w.get("result"), "bres": b.get("result"),
                        "eco": (g.get("eco") or "").rsplit("/", 1)[-1],
                        "term": tm.group(1) if tm else "",
                        "owner": "w" if owner_is_white else "b",
                        "plies": len(mv), "mv": mv[:40],
                    }
                    out.write(json.dumps(rec) + "\n")
                    seen_games.add(gid)
                except Exception as e:
                    print("skip game:", e, flush=True)
            time.sleep(0.05)
        if len(visited) % 25 == 0:
            out.flush()
            json.dump({"visited": sorted(visited), "queue": list(queue)}, open(STATE, "w"))
            el = time.time() - t0
            print(f"[{el:6.0f}s] players={len(visited)} queue={len(queue)} games={len(seen_games)} reqs={reqs}", flush=True)
    out.close()
    json.dump({"visited": sorted(visited), "queue": list(queue)}, open(STATE, "w"))
    print(f"DONE games={len(seen_games)} players={len(visited)} reqs={reqs} secs={time.time() - t0:.0f}", flush=True)


if __name__ == "__main__":
    main()
