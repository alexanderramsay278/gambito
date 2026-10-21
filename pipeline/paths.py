"""Paths and external tools. Override any of them with environment variables."""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.environ.get("CHESS_DATA", os.path.join(ROOT, "data"))              # raw games + Stockfish cache (not in git)
SITE_DIR = os.path.join(ROOT, "docs")                                        # the website (GitHub Pages)
TRAINER_DIR = os.path.join(ROOT, "out", "trainer")
REP_DIR = os.path.join(ROOT, "out", "repertoire")
STOCKFISH = os.environ.get("STOCKFISH_PATH", "stockfish")                    # Stockfish 19 binary
ESBUILD = os.environ.get("ESBUILD_PATH", "esbuild")                          # npm i -g esbuild
BROWSER = os.environ.get("BROWSER_PATH", r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")  # any Chromium
for _d in (DATA, TRAINER_DIR, REP_DIR):
    os.makedirs(_d, exist_ok=True)
