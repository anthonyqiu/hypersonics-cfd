# hypersonics-cfd

Reusable workflows for hypersonic CFD campaigns, with study definitions in Git and heavy solver data kept outside normal Git history.

## Repository layout

```text
hypersonics-cfd/
  docs/                     # design notes and migration reports
  scripts/                  # thin command entry points and retired tools under obsolete/
  src/hypersonics_cfd/      # reusable workflow, post-processing, and shock modules
    shock/                  # frames, sensors, extraction, comparison, and diagnostics
    postprocess/            # convergence, mirroring, slices, and wall y+
    workflow/               # case setup, submission, status, timing, and Slurm helpers
  studies/
    orion/                  # one concrete campaign
      study.toml            # case matrix and study defaults
      geometry/             # canonical CAD/profile inputs
      meshes/               # study meshes (kept local, not in Git history)
      analysis/             # MATLAB helpers and small study notes
      data/                 # case folders and outputs (ignored by Git)
      build/                # generated configs and other runtime products (ignored by Git)
    ellipsoids/             # placeholder for the next campaign
  templates/
    su2/                    # shared SU2 config templates
    slurm/                  # shared batch scripts
```

## Design principles

- Keep reusable implementation in the `hypersonics_cfd` package and keep
  `scripts/` as stable, short command entry points.
- Keep study-specific metadata and canonical inputs under `studies/<campaign>/`.
- Keep generated configs under `studies/<campaign>/build/`.
- Keep active solver outputs, restart files, per-case solver logs, and derived artifacts under `studies/<campaign>/data/cases/`.
- Treat meshes and geometry as canonical study inputs, but keep very large binary inputs out of ordinary Git history.
- Keep obsolete case backups grouped under `studies/<campaign>/data/obsolete/cases/` instead of mixing them into the active case folder.
- Submit solver jobs from the case directory and use case-local SU2 output names so solver outputs land under `studies/<campaign>/data/cases/<case>/` even though generated configs live in `build/`.
- Keep solver and postprocess logs next to the case data that produced them.
- Keep active case names clean: symmetric cases are the only supported convention; old backups live under `data/obsolete/`.

## Common commands

Preview or stage case configs:

```bash
python3 scripts/setup_cases.py
```

Dry-run the end-to-end symmetric workflow (solver -> wall y+ -> mirror -> slices -> shock extraction):

```bash
python3 scripts/submit_workflow.py
```

Dry-run or submit specific cases without prompts:

```bash
python3 scripts/submit_workflow.py --dry-run --cases m1p5_medium,m1p5_fine --full-workflow
python3 scripts/submit_workflow.py --submit --cases m1p5_medium --solver --yplus --mirror --slices --shock
```

Check managed workflow status:

```bash
python3 scripts/workflow_status.py
python3 scripts/workflow_status.py --cases m1p5_medium,m1p5_fine,m1p5_aoa0
```

Run the interactive shock extractor directly:

```bash
python3 scripts/extract_shock_surface.py
```

Run post-processing against a mirrored symmetric flow field:

```bash
CFD_CASE=m9_aoa0 python3 scripts/extract_shock_surface.py
```

Export terminated shock search lines while running the extractor:

```bash
CFD_EXPORT_TERMINATED_SEARCH_LINES=1 CFD_CASE=m9_aoa0 python3 scripts/extract_shock_surface.py
```

Check convergence interactively:

```bash
python3 scripts/check_convergence.py
```

Export the coarse/refined initial stagnation search-line profile for smoothing diagnostics:

```bash
python3 scripts/export_initial_search_line.py
```

Plot the initial profile and terminated search-line profiles in MATLAB:

```matlab
plot_search_line_diagnostics
```

Export ParaView-ready `xy` and `xz` flow slices on the cluster:

```bash
python3 scripts/export_flow_slices.py
```

Extract the full Orion wall surface colored by y+ and write summary statistics:

```bash
python3 scripts/extract_yplus_surface.py --study orion --cases m6_aoa0
```

Compare adjacent refinement-study shock surfaces over their shared polar-angle domain:

```bash
python3 scripts/compare_shock_surfaces.py
```

Run an extractor-spacing study on one fixed flow field. The five trial surfaces
and two summary tables are written under the case's `shock_extraction_convergence/`
folder, leaving the production shock surface untouched:

```bash
python3 scripts/shock_extraction_convergence.py m6_medium
```

Pull selected results directly from the cluster to a local machine:

```bash
bash scripts/pull_cluster_results.sh
```

When run from a local checkout, the script now defaults to `studies/orion/data/cases/`. You can still override the destination with `LOCAL_CASES_DIR`, and override the remote source with `CLUSTER_CASES_DIR` if needed. It is meant to be run from a local checkout or copied to your laptop/WSL environment, not from the cluster login node.

## Documentation

- [System tutorial](docs/system-tutorial.md)
- [Repository redesign report](docs/repository-redesign-report.md)
- [Shock extraction notes](docs/shock-extraction-notes.md)
- [Shock-surface deviation method](docs/shock-surface-deviation.md)
- [Orion study guide](studies/orion/README.md)
