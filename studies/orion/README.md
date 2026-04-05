# Orion Study

`studies/orion/` is the source-controlled home of the Orion campaign definition.

## Folders

- `study.toml`: the editable case matrix, defaults, aliases, and overrides.
- `geometry/`: canonical geometry inputs used to define the campaign.
- `meshes/`: Orion mesh files used by generated SU2 configs.
- `analysis/`: non-production helpers such as MATLAB plotting and digitization metadata. See `analysis/README.md`.
- `build/generated-configs/`: rendered SU2 configs for managed cases. Generated at runtime.
- `build/manifests/`: generated batch manifests, especially for shock extraction jobs.
- `data/cases/`: solver outputs grouped by case name.

## Managed workflow

1. Edit `study.toml`.
2. Render configs with `python3 ../../scripts/setup_cases.py --campaign orion --apply`.
3. Submit solver runs with `python3 ../../scripts/submit_cases.py --campaign orion ...`.
4. Submit shock extraction with `python3 ../../scripts/submit_shock_extraction.py --study orion ...`.
5. Pull selected results to your laptop with `bash ../../scripts/pull_cluster_results.sh` from a local checkout after setting `LOCAL_CASES_DIR`.

## Notes

- Case aliases such as `m3_fine -> m3_aoa0` are preserved as symlinks in `data/cases/`.
- Generated configs use explicit mesh and case-output paths, so outputs still land in each case folder even though the config files live in `build/generated-configs/`.
- Legacy per-case `config.cfg` and `run.sh` files are removed during staging instead of being archived into the repo.
