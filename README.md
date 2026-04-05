# hypersonics-cfd

Reusable workflows for hypersonic CFD campaigns, with study definitions in Git and heavy solver data kept outside normal Git history.

## Repository layout

```text
hypersonics-cfd/
  docs/                     # design notes and migration reports
  scripts/                  # single home for Python workflow code and shell helpers
  studies/
    orion/                  # one concrete campaign
      study.toml            # case matrix and study defaults
      geometry/             # canonical CAD/profile inputs
      meshes/               # study meshes (kept local, not in Git history)
      analysis/             # MATLAB helpers and small study notes
      data/                 # case folders and outputs (ignored by Git)
      build/                # generated configs and manifests (ignored by Git)
    ellipsoids/             # placeholder for the next campaign
  templates/
    su2/                    # shared SU2 config templates
    slurm/                  # shared batch scripts
```

## Design principles

- Keep the active workflow code in `scripts/` so each Python tool has one canonical home.
- Keep study-specific metadata and canonical inputs under `studies/<campaign>/`.
- Keep generated configs under `studies/<campaign>/build/`.
- Keep solver outputs, restart files, logs, and derived artifacts under `studies/<campaign>/data/`.
- Treat meshes and geometry as canonical study inputs, but keep very large binary inputs out of ordinary Git history.
- Delete legacy backups once the managed workflow owns the active layout, instead of preserving duplicate historical copies inside the repo.
- Render runtime configs with explicit case-folder I/O paths so solver outputs always land under `studies/<campaign>/data/cases/<case>/` even though the configs themselves live in `build/`.

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
python3 scripts/submit_shock_extraction.py --study orion --case m6_aoa24
```

Pull selected results directly from the cluster to a local machine:

```bash
bash scripts/pull_cluster_results.sh
```

When run from a local checkout, the script now defaults to `studies/orion/data/cases/`. You can still override the destination with `LOCAL_CASES_DIR`, and override the remote source with `CLUSTER_CASES_DIR` if needed. It is meant to be run from a local checkout or copied to your laptop/WSL environment, not from the cluster login node.

## Documentation

- [Repository redesign report](docs/repository-redesign-report.md)
- [Shock extraction notes](docs/shock-extraction-notes.md)
- [Orion study guide](studies/orion/README.md)
