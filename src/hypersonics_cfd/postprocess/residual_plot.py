from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from hypersonics_cfd.study import get_study_paths


FLOW_FIELDS = (
    "rms[Rho]",
    "rms[RhoU]",
    "rms[RhoV]",
    "rms[RhoW]",
    "rms[RhoE]",
)

FLOW_LABELS = (
    r"$\rho$",
    r"$\rho u$",
    r"$\rho v$",
    r"$\rho w$",
    r"$\rho E$",
)

SA_FIELDS = (*FLOW_FIELDS, "rms[nu]")
SA_LABELS = (*FLOW_LABELS, r"$\tilde{\nu}$")
SST_FIELDS = (*FLOW_FIELDS, "rms[k]", "rms[w]")
SST_LABELS = (*FLOW_LABELS, r"$k$", r"$\omega$")


@dataclass
class Segment:
    path: Path
    iteration: np.ndarray
    residuals: np.ndarray
    labels: tuple[str, ...]


def read_history(path: Path) -> Segment:
    with path.open() as file:
        rows = list(csv.reader(file))
    names = [name.strip().strip('"') for name in rows[0]]
    iteration_index = names.index("Inner_Iter")
    fields, labels = (SST_FIELDS, SST_LABELS) if "rms[k]" in names else (SA_FIELDS, SA_LABELS)
    field_indexes = [names.index(field) for field in fields]
    values = np.asarray(rows[1:], dtype=float)
    return Segment(path, values[:, iteration_index], values[:, field_indexes], labels)


def read_solver_log(path: Path) -> Segment:
    rows = []
    for line in path.read_text(errors="ignore").splitlines():
        if re.match(r"^\|\s*\d+\|", line):
            values = [value.strip() for value in line.split("|")[1:-1]]
            rows.append([float(values[0]), *map(float, values[2:-1])])
    if not rows:
        return Segment(path, np.empty(0), np.empty((0, len(SA_LABELS))), SA_LABELS)
    values = np.asarray(rows)
    labels = SST_LABELS if values.shape[1] == 8 else SA_LABELS
    return Segment(path, values[:, 0], values[:, 1:], labels)


def same_start(a: Segment, b: Segment) -> bool:
    if a.residuals.shape[1] != b.residuals.shape[1]:
        return False
    return np.max(np.abs(a.residuals[0] - b.residuals[0])) < 0.002


def load_segments(case_dir: Path) -> list[Segment]:
    paths = [*case_dir.glob("logs/solver/solver_*.out")]
    paths += [*case_dir.glob("checkpoints/*/history.csv")]
    paths += [case_dir / "history.csv"]
    segments = []
    for path in paths:
        segment = read_history(path) if path.name == "history.csv" else read_solver_log(path)
        if len(segment.iteration):
            segments.append(segment)
    unique = []
    for segment in sorted(segments, key=lambda item: len(item.iteration), reverse=True):
        if not any(same_start(segment, existing) for existing in unique):
            unique.append(segment)
    return unique


def continuation_chain(case_dir: Path) -> list[Segment]:
    segments = load_segments(case_dir)
    current = read_history(case_dir / "history.csv")
    chain = [current]
    remaining = [item for item in segments if not same_start(item, current)]
    while remaining:
        distances = [
            np.max(np.abs(item.residuals[-1] - chain[0].residuals[0]))
            for item in remaining
        ]
        index = int(np.argmin(distances))
        if distances[index] >= 0.02:
            break
        chain.insert(0, remaining.pop(index))
    return chain


def plot_residuals(case_dir: Path, output: Path) -> None:
    chain = continuation_chain(case_dir)
    figure, axis = plt.subplots(figsize=(11, 6.5))
    offset = 0.0
    boundaries = []

    for segment in chain:
        iteration = segment.iteration - segment.iteration[0] + offset
        for index, label in enumerate(segment.labels):
            axis.plot(
                iteration,
                segment.residuals[:, index],
                linewidth=1.15,
                color=f"C{index}",
                label=label if segment is chain[0] else None,
            )
        offset = iteration[-1]
        boundaries.append(offset)

    for boundary in boundaries[:-1]:
        axis.axvline(boundary, color="0.45", linestyle="--", linewidth=0.8)

    axis.set_title(case_dir.name.replace("_", " ").upper() + " Residual History")
    axis.set_xlabel("Cumulative iteration")
    axis.set_ylabel(r"$\log_{10}$(RMS residual)")
    axis.grid(alpha=0.25)
    axis.legend(ncol=3)
    figure.tight_layout()
    figure.savefig(output, format="svg", bbox_inches="tight")
    plt.close(figure)

    print(f"Wrote {output}")
    offset = 0
    for segment in chain:
        end = offset + int(segment.iteration[-1] - segment.iteration[0])
        print(f"{offset:>7}-{end:<7} {segment.path.relative_to(case_dir)}")
        offset = end


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("--study", default="orion")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    case_dir = get_study_paths(args.study).case_path(args.case)
    output = args.output or case_dir / "residual_history.svg"
    plot_residuals(case_dir, output)
