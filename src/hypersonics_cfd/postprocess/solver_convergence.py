from __future__ import annotations

import csv
import math

from hypersonics_cfd.cases import (
    choose_postprocess_cases_interactively,
    prompt_with_default,
    resolve_case_path,
)
from hypersonics_cfd.study import choose_study_paths_interactively


def main():
    paths = choose_study_paths_interactively()
    threshold = float(prompt_with_default("Residual threshold", "1e-5"))
    cases = choose_postprocess_cases_interactively(
        paths.cases_dir, "history.csv"
    )
    limit = math.log10(threshold)
    failures = 0

    for case in cases:
        case_path = resolve_case_path(
            paths.study_root, paths.cases_dir, case
        )
        with (case_path / "history.csv").open() as file:
            rows = list(csv.reader(file))
        residuals = [
            (name.strip().strip('"'), float(value))
            for name, value in zip(rows[0], rows[-1])
            if name.strip().strip('"').startswith("rms[")
        ]
        failed = [(name, value) for name, value in residuals if value > limit]
        if failed:
            failures += 1
            values = ", ".join(
                f"{name}={value:.3f}" for name, value in failed
            )
            print(f"{case}: FAIL ({values})")
        else:
            print(f"{case}: PASS")

    return failures
