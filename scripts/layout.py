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
    cases_dir: Path
    su2_template: Path
    run_case_script: Path
    run_shock_extraction_script: Path

    def case_path(self, case_name: str) -> Path:
        return self.cases_dir / case_name

    def generated_config_path(self, case_name: str) -> Path:
        return self.generated_config_dir / f"{case_name}.cfg"

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.generated_config_dir,
            self.shock_manifest_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
        cases_dir=study_root / "data" / "cases",
        su2_template=root / "templates" / "su2" / "base.cfg",
        run_case_script=root / "templates" / "slurm" / "run_su2_case.sh",
        run_shock_extraction_script=root / "templates" / "slurm" / "run_shock_extraction.sh",
    )
