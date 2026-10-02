#!/usr/bin/env python3
"""Best-so-far of each running study, per objective, for watching a search converge."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pareto  # noqa: E402

for name in sys.argv[1:]:
    df, names = pareto.front(name)
    df = df.sort_values("number")
    n = len(df)
    parts = [f"{name}: {n} trials, front {int(df.pareto.sum())}"]
    for k in names:
        best = df[k].cummax()
        at = [best.iloc[min(i, n - 1)] for i in (n // 2, n - 1)]
        parts.append(f"{k} default {df[k].iloc[0]:.3f} half {at[0]:.3f} now {at[1]:.3f}")
    if "green_bias" in df:
        ok = df[(df.green_bias.sub(1).abs() < 0.25) & (df.readability > -0.25)] if "readability" in df else df
        if len(ok):
            b = ok.loc[ok.green_kappa.idxmax()]
            parts.append(f"best kappa within bias±25%/readable: #{int(b.number)} kappa {b.green_kappa:.3f} ba {b.green_ba:.3f} bias {b.green_bias:.2f}")
    print("\n   ".join(parts))
