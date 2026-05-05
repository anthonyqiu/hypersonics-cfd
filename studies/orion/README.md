# Orion Study

`studies/orion/` is the source-controlled home of the Orion campaign definition.

## Folders

- `study.toml`: the editable case matrix, defaults, aliases, and overrides.
- `geometry/`: canonical geometry inputs used to define the campaign.
- `meshes/`: Orion mesh files used by generated SU2 configs.
- `analysis/`: non-production helpers such as MATLAB plotting and lightweight study notes. See `analysis/README.md`.
- `build/generated-configs/`: rendered SU2 configs for managed cases. Generated at runtime.
- `build/manifests/`: generated batch manifests, especially for shock extraction jobs.
- `build/logs/shock-extraction/`: batch-level SLURM logs for shock extraction submissions.
- `data/cases/`: solver outputs grouped by case name, with per-case solver logs under `logs/solver/`.

## Managed workflow

1. Edit `study.toml`.
2. Render configs with `python3 ../../scripts/setup_cases.py` and follow the prompts.
3. Submit solver runs with `python3 ../../scripts/submit_cases.py`.
4. Submit shock extraction with `python3 ../../scripts/submit_shock_extraction.py`.
5. Export the coarse/refined initial stagnation search-line profile with `python3 ../../scripts/export_initial_search_line.py` when you want to inspect raw vs smoothed `|grad rho|`.
6. Export lighter ParaView-ready flow slices with `python3 ../../scripts/export_flow_slices.py` when you want `xy` and `xz` planes without opening the full 3D field locally.
7. Pull selected results to your laptop with `bash ../../scripts/pull_cluster_results.sh` from a local checkout. By default it writes into `data/cases/`; set `LOCAL_CASES_DIR` only if you want a different destination.

## Notes

- Case aliases such as `m3_fine -> m3_aoa0` are preserved as symlinks in `data/cases/`.
- Generated configs use explicit mesh and case-output paths, so outputs still land in each case folder even though the config files live in `build/generated-configs/`.
- Legacy per-case `config.cfg` and `run.sh` files are removed during staging instead of being archived into the repo.
- Terminated shock-search lines can be exported with `CFD_EXPORT_TERMINATED_SEARCH_LINES=1`; the extractor writes summary/profile CSVs to `data/cases/<case>/search_line_debug/`.
