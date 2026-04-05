# Repository Redesign Report

## Objective

This redesign turns the repository from a single mixed-use `orion/` working folder into a reusable campaign repo with a clear split between:

- reusable workflow code
- campaign metadata and canonical inputs
- generated configs and manifests
- heavy CFD data and derived outputs

The redesign was done on branch `repo-structure-redesign` so the previous layout remains recoverable.

## What changed

### High-level restructuring

- Consolidated the active Python workflow under `scripts/` so there is one canonical home for each tool instead of a wrapper layer plus a second source tree.
- Moved the Orion case matrix to `studies/orion/study.toml`.
- Moved shared templates to `templates/su2/` and `templates/slurm/`.
- Moved Orion geometry into `studies/orion/geometry/`.
- Moved Orion meshes into `studies/orion/meshes/`.
- Moved heavy case data into `studies/orion/data/`.
- Moved generated configs and manifests into `studies/orion/build/`.
- Removed the repository layout's dependence on the compatibility-only `reentry/orion` path.
- Removed the temporary archive/backup layer so the repo only describes the active workflow and active study data layout.

### Functional improvements

- Added a shared path model in `scripts/layout.py`.
- Flattened the study path model so template paths now live directly on `StudyPaths` instead of under a nested `templates` object.
- Made case generation study-aware instead of hard-coding the old `orion/` tree.
- Preserved case aliases such as `m3_fine -> m3_aoa0` as managed symlinks.
- Normalized mesh naming to `coarse.su2` throughout the managed workflow.
- Retired the old rectangular shock extractor so the repo now supports one maintained shock-surface workflow.
- Kept the supported shock extractor implementation directly in `scripts/extract_shock_surface.py` so it is not split across wrapper and library copies.
- Added `scripts/pull_cluster_results.sh` as a direct `ssh/scp` helper that auto-detects the remote case root and copies selected files into local per-case folders without an intermediate export bundle.
- Made shock-batch manifests store case names instead of machine-specific absolute paths.
- Made generated SU2 configs use explicit mesh and case-output paths so solver outputs always land in `studies/<campaign>/data/cases/<case>/` even though configs are stored under `build/`.

## Current folder map

### Repository root

- `docs/`: repo-level documentation, including this report.
- `scripts/`: the single home for the active Python workflow plus shell helpers.
- `studies/`: campaign-specific source-controlled content.
- `templates/`: shared SU2 and SLURM templates.

### `studies/orion/`

- `study.toml`: campaign defaults, profiles, aliases, and overrides.
- `geometry/`: canonical CAD/profile inputs.
- `meshes/`: Orion meshes used by generated configs.
- `analysis/`: helper scripts, plotting assets, and digitization provenance that support interpretation but not production runs.
- `build/generated-configs/`: rendered SU2 configs for each managed case.
- `build/manifests/`: generated batch manifests.
- `data/cases/`: heavy per-case solver outputs and derived artifacts.

## Script inventory

### Active tools in `scripts/`

- `setup_cases.py`: renders managed SU2 configs and maintains case aliases and cleanup.
- `submit_cases.py`: builds or submits SLURM jobs for solver runs.
- `submit_shock_extraction.py`: builds or submits SLURM jobs for the panel shock extractor.
- `extract_shock_surface.py`: runs the supported panel-based 3D shock-surface extractor.
- `check_convergence.py`: checks `history.csv` residuals against a target threshold.
- `pull_cluster_results.sh`: interactive local-machine helper for copying selected result files directly from cluster case folders into local case folders.
- `case_selection.py`: shared case discovery, filtering, deduplication, and path resolution helpers.
- `layout.py`: central study/repo path model.
- `shock_geometry.py`: AoA-aligned coordinate-frame helpers used by the supported extractor.

## Why the new structure is better

### Better separation of concerns

The old layout mixed templates, scripts, generated configs, case outputs, logs, and backups inside one `orion/` folder. That made it hard to tell which files were source, which were products, and which were just local runtime residue.

The new layout gives each category one home:

- workflow code lives in `scripts/`
- shared templates live in `templates/`
- campaign metadata lives in `studies/<campaign>/`
- heavy outputs live in `studies/<campaign>/data/`
- generated configs live in `studies/<campaign>/build/`

### Easier reuse across campaigns

The old repo was effectively a single-study working directory. Reusing logic for a second campaign would have meant either copying the `orion/` folder or pushing more and more special cases into one script tree.

The new layout supports multiple campaigns by design:

- shared workflow code is no longer nested inside `orion/`
- campaign-specific inputs are isolated under `studies/<campaign>/`
- a second study can reuse the same scripts without inheriting Orion-specific paths

### Cleaner Git history

The previous repo tracked generated configs, heavy case artifacts, scheduler logs, and Python cache files. That makes Git slow, noisy, and hard to use as a source-of-truth tool.

The redesign keeps Git focused on:

- code
- templates
- study metadata
- lightweight documentation
- small canonical geometry inputs

Heavy outputs and generated runtime content now live in ignored locations, without a second in-repo archive layer to keep clean manually.

### Better support for cluster-to-local workflows

Small derived outputs such as `.vtp` and `.csv` are useful to move off-cluster, but they do not need an intermediate staging area inside the repo. The new `pull_cluster_results.sh` helper copies files directly into local per-case folders, including `.vtp` shock-surface outputs, so case context stays obvious and there is no extra export-bundle workflow to maintain.

## Research and design justification

There is no single universal “CFD database repo” standard, but the redesigned layout follows recurring patterns from official solver docs and research-data guidance:

- CFD workflows are usually case-centric.
  OpenFOAM organizes work around case directories, and SU2 revolves around a config-driven case setup.
  Sources:
  https://www.openfoam.com/documentation/guides/latest/doc/openfoam-guide-case-structure.html
  https://su2code.github.io/docs_v7/Configuration-File/

- Reproducible research projects usually separate code, data, and outputs.
  The Turing Way recommends clear folder structure, metadata, and research compendia; Cookiecutter Data Science uses the same principle in a practical project template.
  Sources:
  https://book.the-turing-way.org/reproducible-research/rdm/rdm-storage/
  https://book.the-turing-way.org/reproducible-research/rdm/rdm-metadata/
  https://book.the-turing-way.org/reproducible-research/compendia
  https://cookiecutter-data-science.drivendata.org/using-the-template/

- Large binary/generated data should stay out of ordinary Git history.
  GitHub recommends avoiding large generated files in normal repositories, and DVC documents the pattern of keeping metadata in Git while data lives externally or in dedicated storage.
  Sources:
  https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github
  https://doc.dvc.org/user-guide/data-management/importing-external-data

- Long-term CFD data exchange benefits from standardized data models.
  CGNS exists specifically for portable CFD data storage and interchange.
  Source:
  https://cgns.org/general/overview.html

These sources support the core design decision used here: keep the repo as the workflow and metadata layer, and keep the heavy CFD database as campaign-organized local data.

## Verification performed

- Compiled the consolidated Python workflow with `python3 -m compileall scripts`.
- Verified `--help` for:
  - `scripts/setup_cases.py`
  - `scripts/submit_cases.py`
  - `scripts/submit_shock_extraction.py`
  - `scripts/extract_shock_surface.py`
  - `scripts/check_convergence.py`
- Ran `scripts/setup_cases.py --campaign orion --case m3_coarse --case m3_fine --apply`.
- Confirmed generated configs now point to `../../meshes/coarse.su2`.
- Confirmed generated configs now point to explicit mesh and case-output paths.
- Confirmed alias preservation for `m3_fine -> m3_aoa0`.
- Dry-ran `scripts/submit_cases.py --campaign orion --case m3_coarse --resubmit`.
- Dry-ran `scripts/submit_shock_extraction.py --study orion --case m3_coarse --rerun`.
- Ran `scripts/check_convergence.py --study orion m3_coarse` and `m1.5_coarse`.
- Ran `scripts/extract_shock_surface.py --study orion m3_coarse`.
- Checked `templates/slurm/run_shock_extraction.sh` and `templates/slurm/run_su2_case.sh` usage output.
- Verified `scripts/pull_cluster_results.sh` with `bash -n`; a live `ssh/scp` session was not exercised here because host-trust setup is local-machine specific.

## Follow-on recommendations

- If the repository ever needs shareable heavy data management, adopt a dedicated data layer such as DVC, object storage, or a formal CGNS export pipeline.
- If more campaigns appear, keep campaign-specific assumptions out of the shared helpers in `scripts/` until they are proven reusable.
- If MATLAB plotting remains important, consider gradually porting selection/grouping logic into Python so analysis tools share the same case discovery layer.
