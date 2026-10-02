# kp_tuning

Agent skill and scripts for tuning karttapullautin's vegetation and open-land parameters for a
LiDAR region against orienteering maps — the reusable part of `../optimize_params/` (mapant-bayern).

- `SKILL.md` — the procedure (batch-effect check → references → search per tile group → optional
  seam matching → comparison viewer → delivery). Registered for Claude Code as
  `.claude/skills/kp-tuning` (a symlink to this folder).
- `scripts/` — the tools; each has its usage in its docstring.
- `reference/` — method details and pitfalls, Bavaria's results, Bavaria's optima as search seeds.
- `config/region.example.yaml` — the config every script reads.
- `patches/kp-hardlink.patch` — needed for karttapullautin builds used in the search.

Tested end to end on a small Bavarian configuration (3 sites, 1 border block, a 2 km² area):
header survey of all 71,979 tiles, point sample, batch-effect report, references, registration,
green and yellow search, set choice, evaluation, inis, seam matching, area render (checked against
a production batch run: same features, ≤ 0.5 % vertex difference), PMTiles and viewer.
