"""
Read the optuna studies back: trials as a table, Pareto fronts, and the few representative
parameter sets per front that the report compares.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STORAGE = optuna.storages.RDBStorage(f"sqlite:///{ROOT / 'work/optuna.db'}", engine_kwargs={"connect_args": {"timeout": 300}})


def trials(study_name: str) -> pd.DataFrame:
    st = optuna.load_study(study_name=study_name, storage=STORAGE)
    names = st.metric_names or [f"obj{i}" for i in range(len(st.directions))]
    rows = []
    for t in st.trials:
        if t.state != optuna.trial.TrialState.COMPLETE:
            continue
        r = {"number": t.number, **dict(zip(names, t.values)), "overrides": t.user_attrs.get("overrides", {}),
             "per_site": t.user_attrs.get("per_site", {}), "default": bool(t.user_attrs.get("default"))}
        # a few secondary metrics, averaged over sites, for the tables
        ps = r["per_site"]
        for k in ("green_bias", "open_bias", "ug_bias", "speckle", "boundary_ratio", "knoll_ratio",
                  "cliff_density", "rock_spearman", "open_f1", "ug_f1", "green_ba", "green_kappa"):
            vals = [m[k] for m in ps.values() if k in m and m[k] is not None and not
                    (isinstance(m[k], float) and math.isnan(m[k]))]
            if vals and k not in r:
                r[k] = float(np.mean(vals))
        rows.append(r)
    return pd.DataFrame(rows), names


def pareto_mask(values: np.ndarray) -> np.ndarray:
    """Non-dominated rows, all objectives maximised."""
    n = len(values)
    keep = np.ones(n, bool)
    for i in range(n):
        if not keep[i]:
            continue
        dom = np.all(values >= values[i], axis=1) & np.any(values > values[i], axis=1)
        if dom.any():
            keep[i] = False
    return keep


def front(study_name: str) -> tuple[pd.DataFrame, list[str]]:
    df, names = trials(study_name)
    v = df[names].to_numpy(dtype=float)
    v = np.nan_to_num(v, nan=-1e9)
    df["pareto"] = pareto_mask(v)
    return df, names


def pick(df: pd.DataFrame, names: list[str], weights: list[float], constraint=None) -> pd.Series:
    """
    Best trial by a weighted sum of min-max-normalised objectives, among the trials on the Pareto
    front of those meeting `constraint` (the constrained front, not the global one).
    """
    d = df if constraint is None else df[constraint(df)]
    if d.empty:
        raise ValueError("no trial meets the constraint")
    v = np.nan_to_num(d[names].to_numpy(dtype=float), nan=-1e9)
    d = d[pareto_mask(v)]
    z = sum(w * (d[n] - df[n].min()) / max(df[n].max() - df[n].min(), 1e-9) for n, w in zip(names, weights))
    return d.loc[z.idxmax()]


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=float))
