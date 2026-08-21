from __future__ import annotations

import os

import pyvista as pv

from hypersonics_cfd.cases import (
    cases_from_environment,
    choose_postprocess_cases_interactively,
    deduplicate_case_names,
    resolve_case_path,
)
from hypersonics_cfd.shock.extraction import vtu_name
from hypersonics_cfd.study import (
    choose_study_paths_interactively,
    get_study_paths,
)


SLICES = (
    ((0.0, 0.0, 1.0), (0.0, 0.0, 0.0), "flow_slice_xy.vtp"),
    ((0.0, 1.0, 0.0), (0.0, 1.0e-9, 0.0), "flow_slice_xz.vtp"),
)


def export_case(paths, case):
    case_path = resolve_case_path(
        paths.study_root, paths.cases_dir, case
    )
    mesh = pv.read(case_path / vtu_name)
    for normal, origin, filename in SLICES:
        sliced = mesh.slice(normal=normal, origin=origin)
        sliced.save(case_path / filename)
        print(f"wrote {case_path / filename}", flush=True)


def main():
    study = os.environ.get("CFD_STUDY", "").strip()
    paths = (
        get_study_paths(study)
        if study
        else choose_study_paths_interactively()
    )
    cases = cases_from_environment(paths)
    if not cases:
        cases = choose_postprocess_cases_interactively(
            paths.cases_dir, vtu_name
        )
    cases = deduplicate_case_names(
        paths.study_root, paths.cases_dir, cases
    )
    for case in cases:
        export_case(paths, case)
