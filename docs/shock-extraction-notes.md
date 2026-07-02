# Shock Extraction Notes

This repo keeps one supported shock-surface workflow:

- [`scripts/extract_shock_surface.py`](/scratch/anthonyy/hypersonics-cfd/scripts/extract_shock_surface.py)
- [`scripts/submit_workflow.py`](/scratch/anthonyy/hypersonics-cfd/scripts/submit_workflow.py)

The older rectangular shock extractor is intentionally retired and is no longer part of the maintained workflow.

## What the extractor does

At a high level, the panel-guided extractor:

1. Reads a CFD case's flow field, defaulting to `flow_full.vtu`.
2. Uses the density field to build a 3D density-gradient shock sensor.
3. Builds an angle-of-attack-aware coordinate frame.
4. Finds the stagnation shock node first.
5. Marches outward in shells and rays around the body.
6. Uses a panel-style predictor/corrector step to place the next shock node on each ray.
7. Connects the accepted nodes into a triangulated surface.

The main outputs are written into the case folder:

- `shock_surface.csv`
- `shock_surface.vtp`

Set `CFD_FLOW_FILE=flow.vtu` only when you intentionally want to process a half-domain
field before mirroring. The MATLAB plotting helpers assume `shock_surface.csv` is already
in the desired coordinate system and do not apply hidden x-shifts.

For debugging missing panels, set `CFD_EXPORT_TERMINATED_SEARCH_LINES=1` before running the
extractor. Terminated search-line data is written directly inside the case folder:
`terminated_search_line_summary.csv` stores one metadata row per line, and
`terminated_search_line_profiles.csv` stores one profile row per line with arrays as functions
of the local `n` search-line coordinate.

## Geometry and AoA handling

[`scripts/extract_shock_surface.py`](/scratch/anthonyy/hypersonics-cfd/scripts/extract_shock_surface.py) now contains the geometry helpers directly. They are responsible for:

- recovering the case AoA from the generated config or case name
- building the local `streamwise`, `pitch_normal`, and `spanwise` basis
- converting points between global coordinates and the AoA-aware local frame

That means the extractor does not assume the forward direction is always global `x`.

## Batch workflow

The supported batch path is [`scripts/submit_workflow.py`](/scratch/anthonyy/hypersonics-cfd/scripts/submit_workflow.py).
It can dry-run or submit the solver step followed by dependent mirror, slice, and
shock-extraction jobs. The postprocess chain mirrors the half-domain `flow.vtu` into
`flow_full.vtu`, exports the `xy` and `xz` slices, and then runs the shock extractor on the
mirrored field.

## Analysis helpers

[`studies/orion/analysis/plot_shock.m`](/scratch/anthonyy/hypersonics-cfd/studies/orion/analysis/plot_shock.m) is a study-side visualization helper. It can:

- plot a 2D profile extracted from `shock_surface.csv`
- plot the 3D shock surface
- optionally compare refinement-study results against Billig-style reference curves

[`studies/orion/analysis/plot_residuals.m`](/scratch/anthonyy/hypersonics-cfd/studies/orion/analysis/plot_residuals.m) plots selected residual histories from `history.csv`.

These MATLAB scripts are analysis tools, not part of the production solver pipeline.
