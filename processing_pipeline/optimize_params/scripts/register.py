#!/usr/bin/env python3
"""
Estimate each reference map's georeferencing offset against the LiDAR.

omaps.me maps are placed by their uploaders, typically to within 5-30 m. The shift that best
aligns the reference's open land and green with karttapullautin's (default parameters) is found
by FFT cross-correlation within +-40 m, and saved to work/ref/<site>_shift.json, which score.py
applies. Open/forest edges are what both maps agree on most regardless of parameters.

    register.py [<site> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).parent))
import kp  # noqa: E402
import score  # noqa: E402

MAX_SHIFT = 40


def signal(veg: np.ndarray) -> np.ndarray:
    """+1 open land, -1 forest; green shades count as forest with a small weight for green."""
    s = np.zeros(veg.shape, np.float32)
    s[np.isin(veg, [2, 3])] = 1.0
    s[veg == 1] = -0.6
    s[np.isin(veg, [4, 5, 6])] = -1.0
    return s


def best_shift(ref_veg, kp_veg, mask) -> tuple[int, int, float, float]:
    a = np.where(mask, signal(ref_veg), 0)
    b = np.where(mask, signal(kp_veg), 0)
    a -= a[mask].mean() * mask
    b -= b[mask].mean() * mask
    cc = fftconvolve(b, a[::-1, ::-1], mode="same")
    cy, cx = np.array(cc.shape) // 2
    win = cc[cy - MAX_SHIFT : cy + MAX_SHIFT + 1, cx - MAX_SHIFT : cx + MAX_SHIFT + 1]
    iy, ix = np.unravel_index(win.argmax(), win.shape)
    dy, dx = iy - MAX_SHIFT, ix - MAX_SHIFT
    return int(dx), int(dy), float(win.max()), float(win[MAX_SHIFT, MAX_SHIFT])


def main() -> int:
    sites = kp.sites()
    for site in sys.argv[1:] or sites:
        s = sites[site]
        p = score.REF / f"{site}_shift.json"
        p.unlink(missing_ok=True)
        score.load_ref.cache_clear()
        ref = score.load_ref(site, tuple(s["core"]))
        dirs = {t: {"vege": kp.run_stage(t, "vege", {})} for t in s["core"]}
        k = score.kp_layers(ref, dirs)
        mask = ref.mask & (ref.veg > 0)
        # kp pixel (r, c) matches reference pixel (r - dy, c - dx): the reference must move by
        # (+dx, -dy) metres in easting/northing
        dx, dy, peak, zero = best_shift(ref.veg, k["veg"], mask)
        shift = (dx * ref.tf.a, dy * ref.tf.e)
        p.write_text(json.dumps({"shift": shift, "peak_over_zero": peak / max(zero, 1e-9)}))
        score.load_ref.cache_clear()
        before = score.score_vege(score.load_ref.__wrapped__(site, tuple(s["core"])) if False else ref, k)
        ref2 = score.load_ref(site, tuple(s["core"]))
        after = score.score_vege(ref2, score.kp_layers(ref2, dirs))
        print(f"{site}: shift E{shift[0]:+.0f} N{shift[1]:+.0f} m (peak/zero {peak / max(zero, 1e-9):.2f}); "
              f"open_f1 {before['open_f1']:.3f} -> {after['open_f1']:.3f}, "
              f"green_ba {before['green_ba']:.3f} -> {after['green_ba']:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
