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

- Moved reusable Python code from the old `orion/scripts/` folder into `src/hypersonics_cfd/`.
- Added `scripts/` wrappers so the normal user-facing commands still live in one simple place.
- Moved the Orion case matrix to `studies/orion/study.toml`.
- Moved shared templates to `templates/su2/` and `templates/slurm/`.
- Moved Orion geometry into `studies/orion/geometry/`.
- Moved Orion meshes into `studies/orion/meshes/`.
- Moved heavy case data into `studies/orion/data/`.
- Moved generated configs and manifests into `studies/orion/build/`.
- Archived older case-local config/run layouts under `studies/orion/archive/legacy_case_layout/`.
- Archived old path-specific shock-method notes under `studies/orion/docs/legacy/`.
- Removed the compatibility-only `reentry/orion` symlink path.

### Functional improvements

- Added a shared path model in `src/hypersonics_cfd/layout.py`.
- Made case generation study-aware instead of hard-coding the old `orion/` tree.
- Preserved case aliases such as `m3_fine -> m3_aoa0` as managed symlinks.
- Fixed the historical `course.su2` typo by normalizing to `coarse.su2` and leaving a compatibility symlink behind.
- Added `scripts/collect_small_outputs.py` as a standardized way to bundle small derived outputs such as `.vtp` and `.csv` for local transfer.
- Made shock-batch manifests store case names instead of machine-specific absolute paths.

## Current folder map

### Repository root

- `docs/`: repo-level documentation, including this report.
- `scripts/`: thin entrypoints for day-to-day use.
- `src/hypersonics_cfd/`: reusable implementation code.
- `studies/`: campaign-specific source-controlled content.
- `templates/`: shared SU2 and SLURM templates.

### `studies/orion/`

- `study.toml`: campaign defaults, profiles, aliases, overrides, and bundle rules.
- `geometry/`: canonical CAD/profile inputs.
- `meshes/`: Orion meshes used by generated configs.
- `analysis/`: helper scripts that are useful for analysis but not part of the production pipeline.
- `archive/legacy_case_layout/`: archived legacy case-local config/run script copies.
- `docs/`: Orion documentation.
- `docs/legacy/`: older writeups that still reference the old one-folder layout.
- `build/generated-configs/`: rendered SU2 configs for each managed case.
- `build/manifests/`: generated batch manifests.
- `data/cases/`: heavy per-case solver outputs and derived artifacts.
- `data/backups/`: archived case directories.
- `data/exports/`: portable bundles of small outputs for local sync.

## Script inventory

### User-facing commands in `scripts/`

- `setup_cases.py`: renders managed SU2 configs and maintains case aliases and cleanup.
- `submit_cases.py`: builds or submits SLURM jobs for solver runs.
- `submit_shock_surface.py`: builds or submits SLURM jobs for the panel shock extractor.
- `extract_shock_surface.py`: runs the panel-based 3D shock-surface extractor.
- `extract_shock_surface_rectangular.py`: runs the legacy rectangular extractor.
- `check_convergence.py`: checks `history.csv` residuals against a target threshold.
- `export_density_gradient_slice.py`: creates a lightweight density-gradient slice for inspection.
- `collect_small_outputs.py`: copies small outputs into a portable export bundle.

### Reusable modules in `src/hypersonics_cfd/`

- `layout.py`: central study/repo path model.
- `case_selection.py`: case discovery, filtering, deduplication, and path resolution.
- `setup_cases.py`: case-matrix expansion, alias management, config rendering, and staging logic.
- `submit_cases.py`: solver submission logic.
- `submit_shock_surface.py`: shock-batch submission logic.
- `check_convergence.py`: convergence checks.
- `export_density_gradient_slice.py`: slice export logic.
- `artifacts.py`: small-output bundle rules and copy logic.
- `collect_small_outputs.py`: CLI for artifact bundling.
- `shock_geometry.py`: AoA-aligned coordinate-frame helpers.
- `shock/panel.py`: panel-guided shock extractor.
- `shock/rectangular.py`: legacy rectangular extractor.

## Why the new structure is better

### Better separation of concerns

The old layout mixed templates, scripts, generated configs, case outputs, logs, and backups inside one `orion/` folder. That made it hard to tell which files were source, which were products, and which were just local runtime residue.

The new layout gives each category one home:

- source code lives in `src/`
- runnable commands live in `scripts/`
- shared templates live in `templates/`
- campaign metadata lives in `studies/<campaign>/`
- heavy outputs live in `studies/<campaign>/data/`
- generated configs live in `studies/<campaign>/build/`

### Easier reuse across campaigns

The old repo was effectively a single-study working directory. Reusing logic for a second campaign would have meant either copying the `orion/` folder or pushing more and more special cases into one script tree.

The new layout supports multiple campaigns by design:

- reusable code is no longer nested inside `orion/`
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

Heavy outputs and generated runtime content now live in ignored locations.

### Better support for cluster-to-local workflows

Small derived outputs such as `.vtp` and `.csv` are useful to move off-cluster, but they do not need to live in Git. The new `collect_small_outputs.py` command creates a clean export bundle plus manifest under `studies/<campaign>/data/exports/`, which is easier to sync to a laptop than mining case directories ad hoc.

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

- Compiled all Python modules and wrappers with `python3 -m compileall src scripts`.
- Verified `--help` for:
  - `scripts/setup_cases.py`
  - `scripts/submit_cases.py`
  - `scripts/submit_shock_surface.py`
  - `scripts/extract_shock_surface.py`
  - `scripts/extract_shock_surface_rectangular.py`
  - `scripts/check_convergence.py`
  - `scripts/export_density_gradient_slice.py`
  - `scripts/collect_small_outputs.py`
- Ran `scripts/setup_cases.py --campaign orion --case m3_coarse --case m3_fine --apply`.
- Confirmed generated configs now point to `../../meshes/coarse.su2`.
- Confirmed alias preservation for `m3_fine -> m3_aoa0`.
- Dry-ran `scripts/submit_cases.py --campaign orion --case m3_coarse`.
- Dry-ran `scripts/submit_shock_surface.py --study orion --case m3_coarse`.
- Ran `scripts/collect_small_outputs.py` and verified it produced a manifest-backed export bundle.

## Follow-on recommendations

- If the repository ever needs shareable heavy data management, adopt a dedicated data layer such as DVC, object storage, or a formal CGNS export pipeline.
- If more campaigns appear, keep campaign-specific assumptions out of `src/` until they are proven reusable.
- If MATLAB plotting remains important, consider gradually porting selection/grouping logic into Python so analysis tools share the same case discovery layer.
