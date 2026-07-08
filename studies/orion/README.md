# Orion Study

`studies/orion/` is the source-controlled home of the Orion campaign definition.

## Folders

- `study.toml`: the editable case matrix, defaults, and overrides.
- `geometry/`: canonical geometry inputs used to define the campaign.
- `meshes/`: Orion mesh files used by generated SU2 configs. See `meshes/README.md`
  for recorded mesh controls and near-wall spacing notes.
- `analysis/`: non-production helpers such as MATLAB plotting and lightweight study notes. See `analysis/README.md`.
- `build/generated-configs/`: rendered SU2 configs for managed cases. Generated at runtime.
- `data/cases/`: solver outputs grouped by case name, with per-case solver logs under `logs/solver/` and postprocess logs under `logs/postprocess/`.
- `data/obsolete/cases/`: legacy full-mesh case backups kept out of the active workflow.

## Managed workflow

1. Edit `study.toml`.
2. Render configs with `python3 ../../scripts/setup_cases.py` and follow the prompts.
3. Dry-run or submit solver/postprocess jobs with `python3 ../../scripts/submit_workflow.py`.
4. Check case progress with `python3 ../../scripts/workflow_status.py`.
5. Export the coarse/refined initial stagnation search-line profile with `python3 ../../scripts/export_initial_search_line.py` when you want to inspect raw vs smoothed `|grad rho|`.
6. Export lighter ParaView-ready flow slices with `python3 ../../scripts/export_flow_slices.py` when you want `xy` and `xz` planes without opening the full 3D field locally.
7. Compare refinement shock surfaces with `python3 ../../scripts/compare_shock_surfaces.py --study orion`; by default it writes `data/shock_surface_deviation_refinement.csv`.
8. Pull selected results to your laptop with `bash ../../scripts/pull_cluster_results.sh` from a local checkout. By default it writes into `data/cases/`; set `LOCAL_CASES_DIR` only if you want a different destination.

## Notes

- The AoA campaign uses the active `very_fine.su2` symmetric mesh. The refinement
  `m*_very_fine` names are aliases to the corresponding `m*_aoa0` folders, so they
  are not submitted as separate solver runs.
- `geometry/orion_profile_xy.csv` is stored in the active shifted mesh coordinates,
  with the geometric stagnation nose near `x=0`. Keep it aligned with the symmetric
  meshes because plotting and shock extraction do not apply hidden origin shifts.
- Solver walltimes follow mesh level: coarse `04:00:00`, medium `05:00:00`,
  fine `11:00:00`, and very fine `18:00:00`.
  All cases use `CONV_STARTITER=10000` so residual-only convergence cannot stop
  the solver before the flow has had time to develop. Mach 9 cases use adaptive
  CFL from `0.005` up to `0.05`, `CONV_STARTITER=30000`, and `24:00:00`
  solver walltime. `m6_coarse` and `m9_coarse` are excluded from the managed
  case list.
- The postprocess chain is submitted as separate dependent jobs. Mirror, slice,
  and shock-extraction walltimes are configured per mesh level in `study.toml`.
  Current mirror walltimes are `00:15:00` for all mesh levels; submit only on
  partitions that allow
  the configured minimum walltime.
- Postprocess reruns are resumable by output presence: completed `flow_full.vtu`,
  flow slices, and shock-surface files are kept, while the first missing step is rerun.
- Runtime timing rows are appended to `data/cases/<case>/logs/workflow_timings.csv`
  and the aggregate `data/workflow_timings.csv`. Use those measured solver, mirror,
  slice, and shock times to tighten the mesh-level walltime overrides.
- `submit_workflow.py` can run interactively, or non-interactively with flags such as
  `--dry-run --cases m1p5_medium,m1p5_fine --full-workflow`.
- Add the symmetric coarse mesh as `meshes/coarse.su2` before adding `coarse` to the
  refinement mesh levels in `study.toml`.
- Solver jobs run from the case directory, and generated configs use case-local output stems so outputs still land in each case folder even though the config files live in `build/generated-configs/`.
- Legacy per-case `config.cfg` and `run.sh` files are removed during staging instead of being archived into the repo.
- Terminated shock-search lines can be exported with `CFD_EXPORT_TERMINATED_SEARCH_LINES=1`; the extractor writes summary/profile CSVs directly into `data/cases/<case>/`.
