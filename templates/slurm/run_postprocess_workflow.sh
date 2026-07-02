#!/bin/bash
set -euo pipefail

study_name="${1:-}"
case_name="${2:-}"
flow_file="${3:-flow_full.vtu}"
run_mirror="${4:-1}"
overwrite_mirror="${5:-0}"
run_slices="${6:-1}"
run_shock="${7:-1}"

if [[ -z "$study_name" || -z "$case_name" ]]; then
    echo "Usage: $0 <study-name> <case-name> [flow-file] [run-mirror: 0|1] [overwrite-mirror: 0|1] [run-slices: 0|1] [run-shock: 0|1]" >&2
    exit 2
fi
for flag_name in run_mirror overwrite_mirror run_slices run_shock; do
    flag_value="${!flag_name}"
    if [[ "$flag_value" != "0" && "$flag_value" != "1" ]]; then
        echo "$flag_name must be 0 or 1." >&2
        exit 2
    fi
done

case_path="studies/$study_name/data/cases/$case_name"
if [[ ! -d "$case_path" ]]; then
    echo "Case directory not found: $case_path" >&2
    exit 2
fi
study_root="studies/$study_name"
timing_script="scripts/workflow_timing.py"

complete_file() {
    [[ -s "$1" ]]
}

complete_outputs() {
    local path
    for path in "$@"; do
        complete_file "$path" || return 1
    done
    return 0
}

record_timing() {
    local step="$1"
    local status="$2"
    local elapsed_seconds="$3"
    local note="${4:-}"
    if [[ -f "$timing_script" ]] && command -v python3 >/dev/null 2>&1; then
        python3 "$timing_script" \
            --case-dir "$case_path" \
            --study-root "$study_root" \
            --study "$study_name" \
            --case "$case_name" \
            --step "$step" \
            --status "$status" \
            --elapsed-seconds "$elapsed_seconds" \
            --note "$note" || true
    fi
}

run_timed_step() {
    local step="$1"
    local function_name="$2"
    local start_epoch
    local end_epoch
    local elapsed_seconds
    local step_exit
    TIMING_STEP_STATUS="success"
    TIMING_STEP_NOTE=""

    start_epoch="$(date +%s)"
    set +e
    "$function_name"
    step_exit=$?
    set -e
    end_epoch="$(date +%s)"
    elapsed_seconds="$((end_epoch - start_epoch))"

    if [[ "$step_exit" -ne 0 ]]; then
        TIMING_STEP_STATUS="failure"
    fi
    record_timing "$step" "$TIMING_STEP_STATUS" "$elapsed_seconds" "$TIMING_STEP_NOTE"
    return "$step_exit"
}

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

echo "Node:       ${SLURM_NODELIST:-local}"
echo "CPUs/task:  ${SLURM_CPUS_PER_TASK:-local}"
echo "Study:      $study_name"
echo "Case:       $case_name"
echo "Flow file:  $flow_file"
echo "Mirror:     $run_mirror"
echo "Slices:     $run_slices"
echo "Shock:      $run_shock"
echo "Threads:    $thread_count"

mirror_step() {
    echo
    echo "=== Mirroring half-domain flow ==="
    if complete_file "$case_path/flow_full.vtu" && [[ "$overwrite_mirror" != "1" ]]; then
        echo "Keeping existing $case_path/flow_full.vtu"
        TIMING_STEP_STATUS="skipped"
        TIMING_STEP_NOTE="flow_full.vtu already exists"
    else
        if ! complete_file "$case_path/flow.vtu"; then
            echo "Input flow field not found: $case_path/flow.vtu" >&2
            TIMING_STEP_NOTE="missing flow.vtu"
            return 2
        fi
        partial_name="flow_full.part.vtu"
        partial_path="$case_path/$partial_name"
        final_path="$case_path/flow_full.vtu"
        rm -f "$partial_path"
        python3 scripts/mirror_sym_flow.py "$case_path" \
            --output-name "$partial_name" \
            --overwrite
        mv -f "$partial_path" "$final_path"
        echo "Completed:  $final_path"
    fi
}

slices_step() {
    echo
    echo "=== Exporting flow slices ==="
    if ! complete_file "$case_path/$flow_file"; then
        echo "Input flow field not found: $case_path/$flow_file" >&2
        TIMING_STEP_NOTE="missing $flow_file"
        return 2
    fi
    if complete_outputs "$case_path/flow_slice_xy.vtp" "$case_path/flow_slice_xz.vtp"; then
        echo "Keeping existing flow_slice_xy.vtp and flow_slice_xz.vtp"
        TIMING_STEP_STATUS="skipped"
        TIMING_STEP_NOTE="flow slices already exist"
    else
        CFD_STUDY="$study_name" CFD_CASE="$case_name" CFD_FLOW_FILE="$flow_file" \
            python3 scripts/export_flow_slices.py
    fi
}

shock_step() {
    echo
    echo "=== Extracting shock surface ==="
    if ! complete_file "$case_path/$flow_file"; then
        echo "Input flow field not found: $case_path/$flow_file" >&2
        TIMING_STEP_NOTE="missing $flow_file"
        return 2
    fi
    if complete_outputs "$case_path/shock_surface.csv" "$case_path/shock_surface.vtp"; then
        echo "Keeping existing shock_surface.csv and shock_surface.vtp"
        TIMING_STEP_STATUS="skipped"
        TIMING_STEP_NOTE="shock surface already exists"
    else
        CFD_STUDY="$study_name" CFD_CASE="$case_name" CFD_FLOW_FILE="$flow_file" \
            python3 scripts/extract_shock_surface.py
    fi
}

if [[ "$run_mirror" == "1" ]]; then
    run_timed_step mirror mirror_step
fi

if [[ "$run_slices" == "1" ]]; then
    run_timed_step slices slices_step
fi

if [[ "$run_shock" == "1" ]]; then
    run_timed_step shock shock_step
fi

echo
echo "Postprocess workflow complete."
