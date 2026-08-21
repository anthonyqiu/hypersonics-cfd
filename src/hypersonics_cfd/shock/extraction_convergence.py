from __future__ import annotations

import csv
import sys
import time

from hypersonics_cfd.study import get_study_paths

from .comparison import (
    common_polar_metrics,
    shared_polar_limit,
    stagnation_standoff,
)
from .extraction import extract_prepared_surface, prepare_shock_field
from .io import write_surface_outputs


SETTINGS = {
    "dt0p10_dn0p020": (0.10, 0.020),
    "dt0p10_dn0p010": (0.10, 0.010),
    "dt0p10_dn0p005": (0.10, 0.005),
    "dt0p20_dn0p010": (0.20, 0.010),
    "dt0p05_dn0p010": (0.05, 0.010),
}
COMPARISONS = (
    ("dn", "dt0p10_dn0p020", "dt0p10_dn0p005"),
    ("dn", "dt0p10_dn0p010", "dt0p10_dn0p005"),
    ("dt", "dt0p20_dn0p010", "dt0p05_dn0p010"),
    ("dt", "dt0p10_dn0p010", "dt0p05_dn0p010"),
)


def run_shock_extraction_convergence(case_name="m6_medium", study_name="orion"):
    paths = get_study_paths(study_name)
    case_path = paths.case_path(case_name)
    output_root = case_path / "shock_extraction_convergence"
    output_root.mkdir(parents=True, exist_ok=True)
    prepared = prepare_shock_field(paths, case_path)
    surfaces = {}
    run_rows = []

    for label, (dt, dn) in SETTINGS.items():
        print(f"\n=== {label}: dt={dt:g}, dn={dn:g} ===", flush=True)
        start = time.perf_counter()
        surface, summary = extract_prepared_surface(prepared, dt, dn)
        elapsed = time.perf_counter() - start
        write_surface_outputs(output_root / label, surface)
        surfaces[label] = surface
        run_rows.append(
            {
                "setting": label,
                "dt": dt,
                "dn": dn,
                "standoff": stagnation_standoff(
                    surface, prepared.body_anchor, prepared.streamwise
                ),
                "points": surface.n_points,
                "triangles": surface.n_cells,
                "rays": summary["ray_count"],
                "max_shell": summary["max_shell_layer"],
                "termination_reason": summary["termination_reason"],
                "elapsed_seconds": elapsed,
            }
        )

    with (output_root / "runs.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=run_rows[0])
        writer.writeheader()
        writer.writerows(run_rows)

    sweep_limits = {
        "dn": shared_polar_limit(
            [surfaces[label] for label in SETTINGS if label.startswith("dt0p10_")],
            axis_origin=prepared.body_anchor,
            streamwise=prepared.streamwise,
        ),
        "dt": shared_polar_limit(
            [surfaces[label] for label in SETTINGS if label.endswith("_dn0p010")],
            axis_origin=prepared.body_anchor,
            streamwise=prepared.streamwise,
        ),
    }
    comparison_rows = []
    for sweep, setting, reference in COMPARISONS:
        dt, dn = SETTINGS[setting]
        reference_dt, reference_dn = SETTINGS[reference]
        metrics = common_polar_metrics(
            surfaces[setting],
            surfaces[reference],
            axis_origin=prepared.body_anchor,
            streamwise=prepared.streamwise,
            polar_limit=sweep_limits[sweep],
        )
        comparison_rows.append(
            {
                "sweep": sweep,
                "setting": setting,
                "dt": dt,
                "dn": dn,
                "reference": reference,
                "reference_dt": reference_dt,
                "reference_dn": reference_dn,
                **metrics,
            }
        )

    with (output_root / "comparisons.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=comparison_rows[0])
        writer.writeheader()
        writer.writerows(comparison_rows)

    print(f"\nwrote {output_root / 'runs.csv'}")
    print(f"wrote {output_root / 'comparisons.csv'}")
    return output_root


def main():
    run_shock_extraction_convergence(
        sys.argv[1] if len(sys.argv) > 1 else "m6_medium"
    )
