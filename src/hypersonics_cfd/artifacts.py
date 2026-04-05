from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from .case_selection import CASE_NAME_RE
from .layout import StudyPaths


DEFAULT_SMALL_OUTPUT_PATTERNS = (
    "history.csv",
    "shock.csv",
    "shock_gradient.csv",
    "shock_pressure.csv",
    "shock_surface.csv",
    "shock_surface.vtp",
    "shock_surface_panel.csv",
    "shock_surface_panel.vtp",
    "shock_surface_rectangular.csv",
    "shock_surface_rectangular.vtp",
)


def load_small_output_patterns(study_file: Path) -> tuple[str, ...]:
    if not study_file.exists():
        return DEFAULT_SMALL_OUTPUT_PATTERNS

    with study_file.open("rb") as handle:
        matrix = tomllib.load(handle)

    patterns = matrix.get("artifacts", {}).get("small_outputs", {}).get("include", [])
    cleaned = tuple(str(pattern).strip() for pattern in patterns if str(pattern).strip())
    return cleaned or DEFAULT_SMALL_OUTPUT_PATTERNS


def discover_case_names(cases_dir: Path, requested_cases: list[str]) -> list[str]:
    if requested_cases:
        return requested_cases
    if not cases_dir.exists():
        return []
    return sorted(path.name for path in cases_dir.iterdir() if path.is_dir() and CASE_NAME_RE.match(path.name))


def collect_small_outputs(
    paths: StudyPaths,
    requested_cases: list[str],
    *,
    destination: Path | None = None,
    clean: bool = False,
) -> dict[str, int | Path]:
    destination = destination or (paths.exports_dir / "small_outputs")
    if clean and destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    patterns = load_small_output_patterns(paths.study_file)
    case_names = discover_case_names(paths.cases_dir, requested_cases)
    copied = 0
    matched_files: list[Path] = []

    for case_name in case_names:
        case_dir = paths.case_path(case_name)
        if not case_dir.exists():
            continue
        for pattern in patterns:
            for file_path in sorted(case_dir.glob(pattern)):
                if not file_path.is_file():
                    continue
                rel_path = file_path.relative_to(paths.cases_dir)
                target = destination / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, target)
                copied += 1
                matched_files.append(rel_path)

    manifest_path = destination / "MANIFEST.txt"
    manifest_lines = [str(path) for path in sorted(matched_files)]
    manifest_path.write_text("\n".join(manifest_lines) + ("\n" if manifest_lines else ""), encoding="utf-8")
    return {
        "case_count": len(case_names),
        "file_count": copied,
        "destination": destination,
        "manifest_path": manifest_path,
    }
