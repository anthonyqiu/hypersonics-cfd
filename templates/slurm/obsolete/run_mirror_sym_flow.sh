#!/bin/bash
set -euo pipefail

mirror_script="${1:-}"
case_path="${2:-}"
overwrite="${3:-0}"

if [[ -z "$mirror_script" || -z "$case_path" ]]; then
    echo "Usage: $0 <mirror-script> <case-path> [overwrite: 0|1]" >&2
    exit 2
fi
if [[ ! -f "$mirror_script" ]]; then
    echo "Mirroring script not found: $mirror_script" >&2
    exit 2
fi
if [[ ! -f "$case_path/flow.vtu" ]]; then
    echo "Input flow field not found: $case_path/flow.vtu" >&2
    exit 2
fi
if [[ "$overwrite" != "0" && "$overwrite" != "1" ]]; then
    echo "Overwrite must be 0 or 1." >&2
    exit 2
fi
if [[ -e "$case_path/flow_full.vtu" && "$overwrite" != "1" ]]; then
    echo "Output already exists: $case_path/flow_full.vtu" >&2
    exit 2
fi

module purge
module load StdEnv/2023
module load gcc/14.3
module load python/3.11.5
module load scipy-stack/2026a
module load vtk/9.6.0

thread_count="${SLURM_CPUS_PER_TASK:-1}"
export OMP_NUM_THREADS="$thread_count"
export OPENBLAS_NUM_THREADS="$thread_count"
export MKL_NUM_THREADS="$thread_count"
export NUMEXPR_NUM_THREADS="$thread_count"
export VTK_SMP_MAX_THREADS="$thread_count"

partial_name="flow_full.part.vtu"
partial_path="$case_path/$partial_name"
final_path="$case_path/flow_full.vtu"
rm -f "$partial_path"

echo "Node:       ${SLURM_NODELIST:-local}"
echo "CPUs/task:  ${SLURM_CPUS_PER_TASK:-local}"
echo "Memory:     ${SLURM_MEM_PER_NODE:-local} MiB"
echo "Case:       $case_path"
echo "Input:      $case_path/flow.vtu"
echo "Output:     $final_path"
echo "Threads:    $thread_count"

python3 "$mirror_script" "$case_path" \
    --output-name "$partial_name" \
    --overwrite

mv -f "$partial_path" "$final_path"
echo "Completed:  $final_path"
