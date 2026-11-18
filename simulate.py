"""
Logiflex: Monte Carlo simulation of service effectiveness, AS-IS vs. TO-BE.

Python reproduction of the Excel model our team built for the capstone of the
Laboratory of Analysis and Modeling of Processes (Politecnico di Milano).

One simulated run = one crew-month:
  1. Draw the number of delivery requests from its empirical distribution.
  2. For each rescheduling cause, draw a rescheduling rate from its empirical
     distribution, multiply it by the requests, round, and cap it at the
     historical maximum for that cause.
  3. Customers served = requests - all rescheduled deliveries.
  4. Service effectiveness = customers served / requests.

TO-BE uses the same distributions, with each rescheduling rate reduced by the
improvement the redesign targets for that cause. Because those targets are
assumptions, the script also stress-tests them: what if the redesign delivers
only part of the targeted reduction?

Distributions were fitted on 1,390 cleaned crew-month records. Only the
aggregated distributions are published here (data/*.csv), not the records.

Usage:
    python simulate.py                    # 100,000 runs per scenario, seed 42
    python simulate.py --runs 1000        # same size as the original Excel model
    python simulate.py --plot             # also save the figures
"""

import argparse
import csv
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
DATA = HERE / "data"

CAUSES = ["transport", "assembly_type1", "assembly_type2", "assembly_type3", "customer_client"]

# Historical maximum of rescheduled deliveries per crew-month, by cause
# (the cap used in the Excel model).
CAPS = {"transport": 24, "assembly_type1": 11, "assembly_type2": 15,
        "assembly_type3": 4, "customer_client": 5}

# Reduction in the rescheduling rate that the TO-BE redesign targets, by cause.
TARGET_REDUCTION = {"transport": 0.40, "assembly_type1": 0.50, "assembly_type2": 0.50,
                    "assembly_type3": 0.50, "customer_client": 0.40}


def load_table(name: str):
    """Return (cumulative_probability, value) arrays for an empirical distribution."""
    with open(DATA / f"{name}.csv") as f:
        rows = list(csv.DictReader(f))
    cum = np.array([float(r["cumulative_probability"]) for r in rows])
    val = np.array([float(r["value"]) for r in rows])
    return cum, val


TABLES = {name: load_table(name) for name in ["requests"] + CAUSES}


def draw(table, u):
    """Inverse-transform sampling, equivalent to Excel's VLOOKUP(RAND(), table, 2, TRUE)."""
    cum, val = table
    idx = np.searchsorted(cum, u, side="right") - 1
    return val[idx]


def excel_round(x):
    """Excel's ROUND(x, 0): halves round away from zero (NumPy rounds halves to even)."""
    return np.floor(x + 0.5)


def simulate(runs: int, rng: np.random.Generator, achieved: float = 0.0):
    """Simulate `runs` crew-months.

    achieved = share of the targeted reductions that is actually delivered:
    0.0 is the AS-IS process, 1.0 is the TO-BE redesign exactly as planned.
    """
    requests = excel_round(draw(TABLES["requests"], rng.random(runs)))

    rescheduled = {}
    for cause in CAUSES:
        rate = draw(TABLES[cause], rng.random(runs)) * (1 - achieved * TARGET_REDUCTION[cause])
        rescheduled[cause] = np.minimum(excel_round(rate * requests), CAPS[cause])

    total = sum(rescheduled.values())
    return {"requests": requests, "rescheduled": total, "by_cause": rescheduled,
            "effectiveness": (requests - total) / requests}


def describe(eff, resched):
    lo, hi = np.percentile(eff, [5, 95])
    return eff.mean(), lo, hi, (eff >= 0.95).mean(), resched.mean()


def main():
    parser = argparse.ArgumentParser(description="Logiflex Monte Carlo, AS-IS vs. TO-BE")
    parser.add_argument("--runs", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--plot", action="store_true", help="save the figures in figures/")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)

    as_is = simulate(args.runs, rng, achieved=0.0)
    to_be = simulate(args.runs, rng, achieved=1.0)

    print(f"Runs per scenario: {args.runs:,}  (seed {args.seed})\n")
    print(f"{'Scenario':<9}{'Mean':>8}{'P5':>8}{'P95':>8}{'>=95%':>8}{'Rescheduled/crew-month':>25}")
    for name, res in [("AS-IS", as_is), ("TO-BE", to_be)]:
        m, lo, hi, share, r = describe(res["effectiveness"], res["rescheduled"])
        print(f"{name:<9}{m:>8.1%}{lo:>8.1%}{hi:>8.1%}{share:>8.1%}{r:>25.1f}")

    # Uncertainty on the improvement itself (independent samples).
    a, b = as_is["effectiveness"], to_be["effectiveness"]
    diff = b.mean() - a.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    print(f"\nImprovement in mean effectiveness: {diff * 100:+.2f} pp "
          f"(95% CI {(diff - 1.96 * se) * 100:+.2f} to {(diff + 1.96 * se) * 100:+.2f} pp)")

    # Stress test: what if the redesign delivers only part of the targeted reductions?
    print("\nStress test: share of targeted reductions actually achieved")
    print(f"{'Achieved':<10}{'Mean':>8}{'>=95%':>8}")
    stress = []
    for achieved in [0.0, 0.25, 0.5, 0.75, 1.0]:
        res = simulate(args.runs, rng, achieved=achieved)
        m, _, _, share, _ = describe(res["effectiveness"], res["rescheduled"])
        stress.append((achieved, m, share))
        print(f"{achieved:<10.0%}{m:>8.1%}{share:>8.1%}")

    if args.plot:
        plot(as_is, to_be, stress)


def plot(as_is, to_be, stress):
    import matplotlib.pyplot as plt

    out = HERE / "figures"
    out.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

    fig, ax = plt.subplots(figsize=(7.5, 3.8), dpi=160)
    bins = np.arange(0.70, 1.0001, 0.01)
    for res, label, style in [(as_is, "AS-IS", dict(histtype="stepfilled", color="#C9CED8")),
                              (to_be, "TO-BE", dict(histtype="step", color="#1F4E8C", linewidth=2))]:
        eff = np.clip(res["effectiveness"], bins[0], 1.0)
        ax.hist(eff, bins=bins, weights=np.ones_like(eff) / len(eff),
                label=f"{label}: mean {res['effectiveness'].mean():.1%}", **style)
    ax.axvline(0.95, color="#333", linestyle="--", linewidth=1)
    ax.annotate("95% service target", (0.95, ax.get_ylim()[1] * 0.95), xytext=(-4, 0),
                textcoords="offset points", ha="right", fontsize=8)
    ax.set_xlabel("Service effectiveness of a crew-month (values below 70% grouped at 70%)")
    ax.set_ylabel("Share of simulated crew-months")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "effectiveness.png")

    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=160)
    x = [s[0] for s in stress]
    ax.plot(x, [s[2] for s in stress], marker="o", color="#1F4E8C")
    for xi, _, share in stress:
        ax.annotate(f"{share:.0%}", (xi, share), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=8)
    ax.set_xlabel("Share of the targeted reductions actually achieved")
    ax.set_ylabel("Crew-months at or above 95%")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xticks(x)
    ax.set_ylim(0, max(s[2] for s in stress) * 1.25)
    fig.tight_layout()
    fig.savefig(out / "stress_test.png")
    print(f"\nSaved figures to {out}/")


if __name__ == "__main__":
    main()
