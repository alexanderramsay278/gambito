"""Dark 'quant desk' charts for the opening-model backtest (data/backtest/*.json).
Usage: py -B charts.py [out_dir]"""
import json, os, sys, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import DATA, TRAINER_DIR, REP_DIR
SRC = os.path.join(DATA, "backtest")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATA, "backtest", "charts")
NAME = "ALEXANDER RAMSAY"
STAMP = "Data: 511k rated chess.com 10|0 games, Sep 1 – Oct 17 2026 · Stockfish 19"
GREEN, RED, YEL, GREY = "#3ddc4a", "#ff5a36", "#ffd400", "#8a8a8a"

plt.rcParams.update({
    "figure.facecolor": "black", "axes.facecolor": "black", "savefig.facecolor": "black",
    "text.color": "white", "axes.labelcolor": "white", "xtick.color": "white", "ytick.color": "white",
    "axes.edgecolor": "#555", "grid.color": "#333", "grid.linestyle": "-", "grid.linewidth": 0.6,
    "font.family": "DejaVu Sans", "font.size": 11, "axes.titleweight": "bold", "legend.frameon": False,
})

R = sorted((json.load(open(p)) for p in glob.glob(os.path.join(SRC, "r*.json"))), key=lambda r: r["band"])
LABELS = [r["label"].replace("Under 400", "<400").replace("2000+", "2000+") for r in R]


def header(fig, title, sub):
    fig.text(0.03, 0.965, title, fontsize=22, fontweight="bold", va="top")
    fig.text(0.03, 0.915, sub, fontsize=11.5, color="#dddddd", va="top")
    fig.text(0.5, 0.018, NAME, fontsize=15, fontweight="bold", ha="center", va="bottom")
    fig.text(0.97, 0.018, STAMP, fontsize=8, color=GREY, ha="right", va="bottom")


# ---------------------------------------------------------------- 1. human error surface (3D)
def surface():
    moves = np.arange(1, 21)
    Z = np.zeros((len(R), len(moves)))
    for i, r in enumerate(R):
        lb = {int(k): v for k, v in r["calibration"]["loss_by_ply"].items()}
        nb = {int(k): v for k, v in r["calibration"]["n_by_ply"].items()}
        for j, m in enumerate(moves):
            ps = [p for p in (2 * m - 2, 2 * m - 1) if p in lb]
            Z[i, j] = 100 * sum(lb[p] * nb[p] for p in ps) / max(1, sum(nb[p] for p in ps))
    raw = Z.copy()
    for j in range(len(moves)):                     # 3-move rolling mean (raw values kept in the JSON)
        Z[:, j] = raw[:, max(0, j - 1):j + 2].mean(axis=1)
    X, Y = np.meshgrid(moves, np.arange(len(R)))
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_axes([0.0, 0.07, 0.86, 0.82], projection="3d")
    ax.set_facecolor("black")
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.set_pane_color((0, 0, 0, 1))
        a._axinfo["grid"]["color"] = (0.25, 0.25, 0.25, 1)
    zmax = Z.max() * 1.1
    surf = ax.plot_surface(X, Y, Z, cmap=cm.turbo, rstride=1, cstride=1, linewidth=0.15, edgecolor=(1, 1, 1, 0.15),
                           antialiased=True, vmin=0, vmax=Z.max())
    # projections on the back walls: profile by move number (per band) and by rating (per move)
    for i in range(len(R)):
        ax.plot(moves, np.full_like(moves, len(R) - 0.4, dtype=float), Z[i], color=cm.turbo(0.12 + 0.8 * i / (len(R) - 1)), lw=1.1, alpha=0.9)
    for j in (0, 4, 9, 14, 19):
        ax.plot(np.full(len(R), 20.6), np.arange(len(R)), Z[:, j], color=cm.turbo(0.12 + 0.8 * j / 19), lw=1.1, alpha=0.9)
    ax.text(6, len(R) + 0.2, zmax * 1.02, "Profile by move number", color="white", fontsize=10)
    ax.text(21.5, 2, zmax * 1.02, "Profile by rating", color="white", fontsize=10)
    ax.set_xticks([1, 5, 10, 15, 20])
    ax.set_xlabel("Move number", labelpad=10)
    ax.set_ylabel("Rating band", labelpad=22)
    ax.set_zlabel("Win chance lost per move (%)", labelpad=10)
    ax.set_yticks(range(len(R)))
    ax.set_yticklabels(LABELS, fontsize=8.5)
    ax.set_zlim(0, zmax)
    ax.view_init(elev=24, azim=-128)
    cax = fig.add_axes([0.89, 0.2, 0.022, 0.6])
    cb = fig.colorbar(surf, cax=cax)
    cb.outline.set_edgecolor("#555")
    cb.set_label("% win chance lost", color="white")
    header(fig, "Human Error Surface: chess.com Rapid",
           f"Win chance thrown away per move · {sum(r['calibration']['games'] for r in R):,} held-out games, every move graded by Stockfish · 3-move rolling mean")
    fig.savefig(os.path.join(OUT, "1_error_surface.png"), dpi=200)
    plt.close(fig)
    return Z


# ---------------------------------------------------------------- 2. strategy backtest (4 panels)
def backtest():
    fig = plt.figure(figsize=(13, 13))
    gs = fig.add_gridspec(2, 2, left=0.09, right=0.97, top=0.84, bottom=0.08, hspace=0.38, wspace=0.42)
    y = np.arange(len(R))

    # A: head-to-head practical vs engine
    ax = fig.add_subplot(gs[0, 0])
    hh = [r["strategy"].get("practical_vs_engine") for r in R]
    b = np.array([100 * h["beta"] if h else np.nan for h in hh])
    lo = np.array([100 * h["lo"] if h else np.nan for h in hh])
    hi = np.array([100 * h["hi"] if h else np.nan for h in hh])
    cols = [GREEN if (l > 0) else RED if (h < 0) else "#2f7d36" if v >= 0 else "#a3412a" for v, l, h in zip(b, lo, hi)]
    ax.barh(y, b, color=cols, height=0.62, edgecolor="none")
    ax.errorbar(b, y, xerr=[b - lo, hi - b], fmt="none", ecolor="white", elinewidth=1, capsize=3)
    ax.axvline(0, color=GREY, lw=1)
    ax.set_yticks(y); ax.set_yticklabels(LABELS); ax.invert_yaxis()
    ax.set_xlabel("Score difference (percentage points)")
    ax.set_title("Practical pick vs Stockfish's top move", loc="left", fontsize=13, pad=26)
    ax.text(0, 1.015, "Same position, same rating gap · 95% CI (game bootstrap)", transform=ax.transAxes, fontsize=9, color=GREY, va="bottom")
    ax.grid(axis="x")

    # B: following each strategy
    ax = fig.add_subplot(gs[0, 1])
    for k, (s, c, off) in enumerate((("engine", "#4fc3ff", -0.22), ("popular", YEL, 0.0), ("practical", GREEN, 0.22))):
        v = np.array([100 * r["strategy"][s]["beta"] for r in R])
        l = np.array([100 * r["strategy"][s]["lo"] for r in R]); h = np.array([100 * r["strategy"][s]["hi"] for r in R])
        ax.errorbar(v, y + off, xerr=[v - l, h - v], fmt="o", color=c, ms=5, elinewidth=1.2, capsize=2, label=s.capitalize())
    ax.axvline(0, color=GREY, lw=1)
    ax.set_yticks(y); ax.set_yticklabels(LABELS); ax.invert_yaxis()
    ax.set_xlabel("Score uplift from playing the strategy's move (pp)")
    ax.set_title("Out-of-sample uplift by strategy", loc="left", fontsize=13, pad=26)
    ax.text(0, 1.015, "Train: Sep 2026 games · Test: Oct 2026 games", transform=ax.transAxes, fontsize=9, color=GREY, va="bottom")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x")

    # C: calibration of the rival's error model
    ax = fig.add_subplot(gs[1, 0])
    for ph, mk in (("opening", "o"), ("middle", "s")):
        for cat, c in (("blunder", RED), ("mistake", "#ff9f1c"), ("inaccuracy", YEL)):
            m = np.array([100 * r["calibration"][ph][cat]["model"] for r in R])
            o = np.array([100 * r["calibration"][ph][cat]["obs"] for r in R])
            l = np.array([100 * r["calibration"][ph][cat]["lo"] for r in R]); h = np.array([100 * r["calibration"][ph][cat]["hi"] for r in R])
            ax.errorbar(m, o, yerr=[o - l, h - o], fmt=mk, color=c, ms=5, elinewidth=0.8, alpha=0.9,
                        label=f"{cat} ({'moves 1–10' if ph == 'opening' else 'moves 11–20'})")
    lim = max(ax.get_xlim()[1], ax.get_ylim()[1])
    ax.plot([0, lim], [0, lim], color=GREY, ls="--", lw=1)
    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Model rate (%), from the original 150 games per band")
    ax.set_ylabel("Observed rate (%), 200 new games per band")
    ax.set_title("Rival error model: calibration", loc="left", fontsize=13, pad=26)
    ax.text(0, 1.015, "On the dashed line = the model predicts held-out games", transform=ax.transAxes, fontsize=9, color=GREY, va="bottom")
    ax.legend(fontsize=7.5, loc="upper left")
    ax.grid()

    # D: sample sizes
    ax = fig.add_subplot(gs[1, 1])
    dec = np.array([r["strategy"]["decisions"] for r in R]) / 1000
    pos = np.array([r["strategy"]["positions"] for r in R])
    ax.barh(y, dec, color=cm.turbo(np.linspace(0.15, 0.9, len(R))), height=0.62)
    for i in range(len(R)):
        ax.text(dec[i] + dec.max() * 0.01, i, f"{pos[i]} positions", va="center", fontsize=8.5, color="#cccccc")
    ax.set_yticks(y); ax.set_yticklabels(LABELS); ax.invert_yaxis()
    ax.set_xlabel("Test decisions (thousands)")
    ax.set_xlim(0, dec.max() * 1.35)
    ax.set_title("Sample size", loc="left", fontsize=13, pad=26)
    ax.text(0, 1.015, f"{dec.sum() * 1000:,.0f} decisions in {sum(r['strategy']['test_games'] for r in R):,} test games", transform=ax.transAxes, fontsize=9, color=GREY, va="bottom")
    ax.grid(axis="x")

    header(fig, "Opening Model Backtest: Out-of-Sample",
           "Does the move a model recommends actually score better? Fixed-effects regression on 10 rating bands")
    fig.savefig(os.path.join(OUT, "2_backtest.png"), dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    surface()
    backtest()
    print("charts ->", OUT, [os.path.basename(p) for p in glob.glob(os.path.join(OUT, "*.png"))])
