# Repository Guide for Agents

## Scope

These instructions apply to the entire repository.

This project manages hypersonic CFD studies, SU2 case generation, Slurm
workflows, post-processing, shock-surface extraction, and convergence analysis.
Prefer small, transparent changes that preserve the scientific meaning of the
existing workflow.

## Read First

Before changing behavior, read the relevant source and these guides:

- `README.md`: repository layout and common commands.
- `docs/system-tutorial.md`: end-to-end workflow and case lifecycle.
- `docs/shock-extraction-notes.md`: extraction algorithm and terminology.
- `docs/shock-surface-deviation.md`: intended surface-comparison methodology.
- `studies/orion/README.md`: current Orion campaign settings and diagnostics.

Treat executable source and tests as the final authority when documentation has
fallen behind. Update the affected documentation when behavior changes.

## Architecture

```text
scripts/                    Thin user-facing entry points
src/hypersonics_cfd/        Reusable implementation
  workflow/                 Case setup, submission, status, timing, Slurm helpers
  postprocess/              Residuals, convergence, mirroring, slices, wall y+
  shock/                    Frames, sensors, extraction, comparison, diagnostics
studies/<study>/study.toml  Case matrix, defaults, aliases, and overrides
templates/su2/              Shared SU2 configuration templates
templates/slurm/            Shared batch scripts
tests/                      Unit tests for scientific and geometric behavior
```

Keep Python files in `scripts/` as minimal entry points. Put shared logic in
`src/hypersonics_cfd/`. Do not revive or import tools from `scripts/obsolete/`.

## Source-Control Boundaries

Commit source, tests, templates, lightweight documentation, and study metadata.
Do not commit generated or heavy runtime products:

- `studies/*/data/`
- `studies/*/build/`
- SU2 meshes under `studies/*/meshes/*.su2`
- `*.vtu`, `*.dat`, solver logs, restart files, plots, and derived case output

Do not delete, replace, or regenerate solver results unless the user explicitly
requests it. Existing case data and checkpoints may represent days of compute.

## Study and Case Rules

- Define campaign settings in `studies/<study>/study.toml` rather than embedding
  case-specific values in Python.
- Settings resolve in this order: defaults, Mach profile, generated case values,
  then matching overrides. Later overrides win.
- Orion very-fine refinement names are aliases of the corresponding AoA-zero
  cases. Do not submit the aliased simulation twice.
- Preserve coordinate metadata on extracted shock surfaces: `BodyAnchor`,
  `StreamwiseBasis`, `NormalBasis`, `SpanwiseBasis`, `ShellLayer`, and `RayIndex`.
- A turbulence-model restart must use compatible restart variables. Do not start
  an SST case from an SA restart merely to save time.
- Chained continuations must archive `history.csv`, `flow.vtu`, and
  `restart_flow.dat` with the cumulative iteration and CFL before the next run.

## Scientific Invariants

### Shock extraction

The extractor uses `|grad rho|` as its shock sensor. It seeds the stagnation
shock from an initial search line, marches in surface panels, samples local
normal search lines, and accepts peaks using strength, continuity, and marching
direction. Keep geometry transforms in `shock/frame.py`, sensor operations in
`shock/sensor.py`, and extraction orchestration in `shock/extraction.py`.

Changes to peak selection, smoothing, `dt`, `dn`, coordinate frames, or
termination criteria can alter the scientific result. Add focused tests and run
the fixed-flow-field extractor convergence study when changing those areas.

### Shock-surface deviation

Current comparison behavior is defined in `shock/comparison.py`:

1. Determine the common polar-angle extent at every azimuth.
2. Crop both triangulated surfaces to that shared support.
3. Sample triangle centroids and use triangle areas as weights.
4. Measure closest-point distance to the continuous opposite surface in both
   directions.
5. Combine both directions into symmetric mean, RMS, percentile, and maximum
   metrics normalized by the characteristic diameter.
6. Report stagnation stand-off difference separately.

Do not replace physical triangle-area weighting with spherical `sin(theta)`
weighting. Do not compare unmatched extraction tails. Refinement comparisons
include adjacent levels and coarse-to-very-fine; `is_adjacent` distinguishes
them.

### Solver convergence

Residual reduction alone is not the only acceptance criterion. For difficult
Mach 9 cases, preserve checkpoints and assess whether the flow field and the
shock-surface quantities of interest are stable with further iterations. Never
describe a case as converged solely because it reached a walltime or a small
CFL.

## Common Commands

Run commands from the repository root.

```bash
python3 scripts/setup_cases.py
python3 scripts/submit_workflow.py
python3 scripts/workflow_status.py
python3 scripts/plot_residuals.py m9_aoa32
python3 scripts/extract_shock_surface.py
python3 scripts/compare_shock_surfaces.py
python3 scripts/shock_extraction_convergence.py m6_medium
```

Use non-interactive flags for reproducible workflow checks:

```bash
python3 scripts/submit_workflow.py \
  --dry-run \
  --cases m3_medium,m3_fine \
  --full-workflow
```

Default to `--dry-run`. Use `--submit` only when the user explicitly asks to
submit jobs. Before submission, inspect the selected cases, restart setting,
CFL, walltime, dependencies, and intended checkpoint source.

Keep expensive PyVista/SU2 work in Slurm jobs. Lightweight metadata inspection,
small CSV processing, config rendering, and unit tests are appropriate on a
login node.

## Implementation Style

- Prefer direct, readable functions and the existing module boundaries.
- Keep entry-point scripts barebones; avoid duplicated implementation there.
- Do not add defensive error handling, abstractions, or comments unless they
  clarify a real failure mode or non-obvious scientific operation.
- Use structured readers for TOML, CSV, and mesh data.
- Preserve existing names and output formats unless the requested change
  requires a migration.
- Keep edits ASCII unless a file already requires scientific Unicode notation.
- Do not modify unrelated user changes in a dirty working tree.

## Verification

Run the smallest relevant checks during development and the full unit suite
before committing shared scientific or workflow changes:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts tests
git diff --check
```

For additional file types:

```bash
python3 -c 'import tomllib; tomllib.load(open("studies/orion/study.toml", "rb"))'
bash -n templates/slurm/<changed-script>.sh
```

When editing study generation or SU2 templates, render representative SA and
SST cases and inspect the resulting settings. When editing submission logic,
run a non-interactive dry run and verify the complete dependency chain without
calling `sbatch`.

Tests involving synthetic surfaces should verify known geometry, common-support
cropping, area weighting, symmetry, and stand-off distance independently where
possible.

## Git Workflow

- Inspect `git status` before editing and preserve unrelated changes.
- Do not use destructive reset or checkout commands on user work.
- Commit generated source changes only after verification.
- Push or merge only when explicitly requested.
- After pushing, confirm the local branch is clean and synchronized with its
  remote tracking branch.
