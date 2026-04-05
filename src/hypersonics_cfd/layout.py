from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemplatePaths:
    su2_base: Path
    run_su2_case: Path
    run_shock_extraction_batch: Path


@dataclass(frozen=True)
class StudyPaths:
    repo_root: Path
    study_name: str
    study_root: Path
    study_file: Path
    docs_dir: Path
    geometry_dir: Path
    meshes_dir: Path
    analysis_dir: Path
    archive_dir: Path
    legacy_case_layout_dir: Path
    build_dir: Path
    generated_config_dir: Path
    shock_manifest_dir: Path
    data_root: Path
    cases_dir: Path
    backups_dir: Path
    exports_dir: Path
    templates: TemplatePaths

    def case_path(self, case_name: str) -> Path:
        return self.cases_dir / case_name

    def generated_config_path(self, case_name: str) -> Path:
        return self.generated_config_dir / f"{case_name}.cfg"

    def legacy_case_dir(self, case_name: str) -> Path:
        return self.legacy_case_layout_dir / case_name

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.generated_config_dir,
            self.shock_manifest_dir,
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_study_paths(study_name: str = "orion") -> StudyPaths:
    root = repo_root()
    study_root = root / "studies" / study_name
    if not study_root.exists():
        raise FileNotFoundError(f"Study not found: {study_root}")

    templates = TemplatePaths(
        su2_base=root / "templates" / "su2" / "base.cfg",
        run_su2_case=root / "templates" / "slurm" / "run_su2_case.sh",
        run_shock_extraction_batch=root / "templates" / "slurm" / "run_shock_extraction_batch.sh",
    )
    data_root = study_root / "data"
    return StudyPaths(
        repo_root=root,
        study_name=study_name,
        study_root=study_root,
        study_file=study_root / "study.toml",
        docs_dir=study_root / "docs",
        geometry_dir=study_root / "geometry",
        meshes_dir=study_root / "meshes",
        analysis_dir=study_root / "analysis",
        archive_dir=study_root / "archive",
        legacy_case_layout_dir=study_root / "archive" / "legacy_case_layout",
        build_dir=study_root / "build",
        generated_config_dir=study_root / "build" / "generated-configs",
        shock_manifest_dir=study_root / "build" / "manifests",
        data_root=data_root,
        cases_dir=data_root / "cases",
        backups_dir=data_root / "backups",
        exports_dir=data_root / "exports",
        templates=templates,
    )
