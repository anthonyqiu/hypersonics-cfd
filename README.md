# hypersonics-cfd

Reusable workflows for hypersonic CFD campaigns, with study definitions in Git and heavy solver data kept outside normal Git history.

## Repository layout

```text
hypersonics-cfd/
  docs/                     # design notes and migration reports
  scripts/                  # thin command-line entrypoints
  src/hypersonics_cfd/      # reusable Python library code
  studies/
    orion/                  # one concrete campaign
      study.toml            # case matrix and study defaults
      geometry/             # canonical CAD/profile inputs
      meshes/               # study meshes (kept local, not in Git history)
      analysis/             # MATLAB helpers and digitization assets
      archive/              # archived legacy case-local layouts
      docs/                 # current and legacy study docs
      data/                 # cases and backups (ignored by Git)
      build/                # generated configs and manifests (ignored by Git)
    ellipsoids/             # placeholder for the next campaign
  templates/
    su2/                    # shared SU2 config templates
    slurm/                  # shared batch scripts
```

## Design principles

- Keep reusable code under `src/` and user-facing entrypoints under `scripts/`.
- Keep study-specific metadata and canonical inputs under `studies/<campaign>/`.
- Keep generated configs under `studies/<campaign>/build/`.
- Keep solver outputs, restart files, logs, and derived artifacts under `studies/<campaign>/data/`.
- Treat meshes and geometry as canonical study inputs, but keep very large binary inputs out of ordinary Git history.

## Common commands

Preview or stage case configs:

```bash
python3 scripts/setup_cases.py --campaign orion --experiment aoa
python3 scripts/setup_cases.py --campaign orion --case m3_coarse --apply
```

Dry-run solver submissions:

```bash
python3 scripts/submit_cases.py --campaign orion --case m3_coarse
```

Dry-run shock extraction batch submissions:

```bash
python3 scripts/submit_shock_surface.py --study orion --case m6_aoa24
```

Pull selected results directly from the cluster to a local machine:

```bash
bash scripts/pull_cluster_results.sh
```

Edit `LOCAL_CASES_DIR` at the top of the script first. The remote cases path is auto-detected, but you can override `CLUSTER_CASES_DIR` if needed. It is meant to be run from a local checkout or copied to your laptop/WSL environment, not from the cluster login node.

## Documentation

- [Repository redesign report](docs/repository-redesign-report.md)
- [Orion study guide](studies/orion/README.md)
