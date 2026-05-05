from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StudyPaths:
    repo_root: Path
    study_name: str
    study_root: Path
    study_file: Path
    meshes_dir: Path
    generated_config_dir: Path
    shock_manifest_dir: Path
    shock_batch_log_dir: Path
    cases_dir: Path
    su2_template: Path
    run_case_script: Path
    run_shock_extraction_script: Path

    def case_path(self, case_name: str) -> Path:
        return self.cases_dir / case_name

    def case_logs_dir(self, case_name: str) -> Path:
        return self.case_path(case_name) / "logs"

    def solver_logs_dir(self, case_name: str) -> Path:
        return self.case_logs_dir(case_name) / "solver"

    def generated_config_path(self, case_name: str) -> Path:
        return self.generated_config_dir / f"{case_name}.cfg"

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.generated_config_dir,
            self.shock_manifest_dir,
            self.shock_batch_log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_case_runtime_dirs(self, case_name: str) -> None:
        self.solver_logs_dir(case_name).mkdir(parents=True, exist_ok=True)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def list_study_names() -> list[str]:
    studies_dir = repo_root() / "studies"
    if not studies_dir.exists():
        return []
    return sorted(
        path.name
        for path in studies_dir.iterdir()
        if path.is_dir() and (path / "study.toml").exists()
    )


def get_study_paths(study_name: str = "orion") -> StudyPaths:
    root = repo_root()
    study_root = root / "studies" / study_name
    if not study_root.exists():
        raise FileNotFoundError(f"Study not found: {study_root}")

    return StudyPaths(
        repo_root=root,
        study_name=study_name,
        study_root=study_root,
        study_file=study_root / "study.toml",
        meshes_dir=study_root / "meshes",
        generated_config_dir=study_root / "build" / "generated-configs",
        shock_manifest_dir=study_root / "build" / "manifests",
        shock_batch_log_dir=study_root / "build" / "logs" / "shock-extraction",
        cases_dir=study_root / "data" / "cases",
        su2_template=root / "templates" / "su2" / "base.cfg",
        run_case_script=root / "templates" / "slurm" / "run_su2_case.sh",
        run_shock_extraction_script=root / "templates" / "slurm" / "run_shock_extraction.sh",
    )


def choose_study_paths_interactively(default: str = "orion") -> StudyPaths:
    study_names = list_study_names()
    if not study_names:
        raise FileNotFoundError("No studies with study.toml were found under studies/")
    if len(study_names) == 1:
        return get_study_paths(study_names[0])

    if default not in study_names:
        default = study_names[0]

    print("\nSelect study:\n")
    for index, study_name in enumerate(study_names, start=1):
        default_suffix = " [default]" if study_name == default else ""
        print(f"  {index}) {study_name}{default_suffix}")
    print("\n  q) Quit\n")

    choice = input(f"Study [1-{len(study_names)}/q, default={default}]: ").strip().lower()
    if choice == "":
        return get_study_paths(default)
    if choice == "q":
        raise SystemExit(0)

    try:
        index = int(choice) - 1
        assert 0 <= index < len(study_names)
    except (ValueError, AssertionError):
        raise SystemExit("Invalid study selection.")

    return get_study_paths(study_names[index])
