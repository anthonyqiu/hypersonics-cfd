# Shock Extraction Notes

This repo keeps one supported shock-surface workflow:

- [`scripts/extract_shock_surface.py`](/scratch/anthonyy/hypersonics-cfd/scripts/extract_shock_surface.py)
- [`scripts/submit_shock_extraction.py`](/scratch/anthonyy/hypersonics-cfd/scripts/submit_shock_extraction.py)

The older rectangular shock extractor is intentionally retired and is no longer part of the maintained workflow.

## What the extractor does

At a high level, the panel-guided extractor:

1. Reads a CFD case's `flow.vtu`.
2. Uses the density field to build a 3D density-gradient shock sensor.
3. Builds an angle-of-attack-aware coordinate frame.
4. Finds the stagnation shock node first.
5. Marches outward in shells and rays around the body.
6. Uses a panel-style predictor/corrector step to place the next shock node on each ray.
7. Connects the accepted nodes into a triangulated surface.

The main outputs are written into the case folder:

- `shock_surface.csv`
- `shock_surface.vtp`

## Geometry and AoA handling

[`scripts/extract_shock_surface.py`](/scratch/anthonyy/hypersonics-cfd/scripts/extract_shock_surface.py) now contains the geometry helpers directly. They are responsible for:

- recovering the case AoA from the generated config or case name
- building the local `streamwise`, `pitch_normal`, and `spanwise` basis
- converting points between global coordinates and the AoA-aware local frame

That means the extractor does not assume the forward direction is always global `x`.

## Batch workflow

The shock-extraction batch path is:

1. [`scripts/submit_shock_extraction.py`](/scratch/anthonyy/hypersonics-cfd/scripts/submit_shock_extraction.py) selects eligible cases and prints or submits an `sbatch` command.
2. It writes a case-name manifest in `studies/<study>/build/manifests/`.
3. [`templates/slurm/run_shock_extraction.sh`](/scratch/anthonyy/hypersonics-cfd/templates/slurm/run_shock_extraction.sh) reads that manifest.
4. The wrapper calls [`scripts/extract_shock_surface.py`](/scratch/anthonyy/hypersonics-cfd/scripts/extract_shock_surface.py) once per listed case.

A manifest is only a text file containing case names for one batch job.

## Analysis helpers

[`studies/orion/analysis/plot_shock.m`](/scratch/anthonyy/hypersonics-cfd/studies/orion/analysis/plot_shock.m) is a study-side visualization helper. It can:

- plot a 2D profile extracted from `shock_surface.csv`
- plot the 3D shock surface
- optionally compare refinement-study results against Billig-style reference curves

[`studies/orion/analysis/plot_residuals.m`](/scratch/anthonyy/hypersonics-cfd/studies/orion/analysis/plot_residuals.m) plots selected residual histories from `history.csv`.

These MATLAB scripts are analysis tools, not part of the production solver pipeline.
