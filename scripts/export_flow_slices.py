#!/usr/bin/env python3
from __future__ import annotations

import os
import time
from pathlib import Path

import pyvista as pv

from case_selection import choose_postprocess_cases_interactively, deduplicate_case_names, resolve_case_path
from extract_shock_surface import density_scalar, suppress_vtk_warnings, vtk_warning_mode, vtu_name
from layout import StudyPaths, choose_study_paths_interactively, get_study_paths


SLICE_SPECS = (
    {
        "name": "xy",
        "normal": (0.0, 0.0, 1.0),
        "origin": (0.0, 0.0, 0.0),
        "output": "flow_slice_xy.vtp",
    },
    {
        "name": "xz",
        "normal": (0.0, 1.0, 0.0),
        "origin": (0.0, 0.0, 0.0),
        "output": "flow_slice_xz.vtp",
    },
)


def progress(message: str) -> None:
    print(message, flush=True)


def cases_from_environment(paths: StudyPaths) -> list[str]:
    raw_cases = os.environ.get("CFD_CASES", "").strip()
    single_case = os.environ.get("CFD_CASE", "").strip()
    requested_cases: list[str] = []

    if raw_cases:
        requested_cases.extend(part.strip() for part in raw_cases.replace("\n", ",").split(",") if part.strip())
    if single_case:
        requested_cases.append(single_case)

    if not requested_cases:
        return []

    return deduplicate_case_names(paths.study_root, paths.cases_dir, requested_cases)


def ensure_point_data(mesh: pv.DataSet) -> pv.DataSet:
    """
    Match the practical ParaView workflow: slice a field that has usable point arrays.

    SU2 outputs are usually already point-data VTU files, but this keeps older cell-data files
    usable without requiring a manual Convert Cell Data To Point Data step in ParaView.
    """
    if density_scalar in mesh.point_data:
        return mesh
    if density_scalar in mesh.cell_data:
        progress("  [stage] converting cell data to point data")
        return mesh.cell_data_to_point_data()
    return mesh


def export_case(paths: StudyPaths, case_dir: str) -> int:
    case_start = time.perf_counter()
    case_path = resolve_case_path(paths.study_root, paths.cases_dir, case_dir)
    flow_path = case_path / vtu_name
    if not flow_path.exists():
        progress(f"  [skip] no {vtu_name} in {case_path.name}")
        return 0

    progress(f"  [stage] reading flow field: {flow_path}")
    mesh = pv.read(flow_path)
    mesh = ensure_point_data(mesh)

    written = 0
    for spec in SLICE_SPECS:
        output_path = case_path / str(spec["output"])
        progress(
            f"  [stage] slicing {spec['name']} plane "
            f"(normal={spec['normal']}, origin={spec['origin']})"
        )
        with vtk_warning_mode(suppress_vtk_warnings):
            sliced = mesh.slice(normal=spec["normal"], origin=spec["origin"])
        if sliced.n_points == 0:
            progress(f"  [warn] {spec['name']} slice produced no points")
            continue
        sliced.save(output_path)
        written += 1
        progress(f"  [ok ] wrote {output_path} ({sliced.n_points} pts, {sliced.n_cells} cells)")

    elapsed = time.perf_counter() - case_start
    progress(f"  [time ] total: {elapsed:.1f} s")
    return written


def main() -> int:
    env_study = os.environ.get("CFD_STUDY", "").strip()
    paths = get_study_paths(env_study) if env_study else choose_study_paths_interactively()

    print("\n╔══════════════════════════════════════════════╗")
    print("║   Flow Slice Exporter                       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Study: {paths.study_name}")
    print("Outputs: flow_slice_xy.vtp, flow_slice_xz.vtp")

    cases = cases_from_environment(paths)
    if not cases:
        cases = choose_postprocess_cases_interactively(paths.cases_dir, vtu_name)
        cases = deduplicate_case_names(paths.study_root, paths.cases_dir, cases)
    if not cases:
        return 0

    total_written = 0
    print(f"\nProcessing {len(cases)} case(s)...\n")
    for case in cases:
        print(f"-> {case}")
        total_written += export_case(paths, case)

    print(f"\nDone. Wrote {total_written} slice file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
