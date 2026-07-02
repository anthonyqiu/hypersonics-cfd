#!/bin/bash
set -euo pipefail

config_path="${1:-}"
if [[ -z "$config_path" ]]; then
    echo "Usage: $0 <config-path>" >&2
    exit 2
fi

if [[ ! -f "$config_path" ]]; then
    echo "Config not found: $config_path" >&2
    exit 2
fi

ulimit -c 0

module purge
module load StdEnv/2023 gcc openmpi eigen

export SU2_RUN="$HOME/.local/su2-7.5.1/bin"
export PATH="$SU2_RUN:$PATH"
export OMP_NUM_THREADS=1

echo "Nodes:  ${SLURM_NODELIST:-local}"
echo "Tasks:  ${SLURM_NTASKS:-local}"
echo "NPN:    ${SLURM_NTASKS_PER_NODE:-local}"
echo "Config: $config_path"

config_dir="$(cd "$(dirname "$config_path")" && pwd)"
study_root="$(cd "$config_dir/../.." && pwd)"
repo_root="$(cd "$study_root/../.." && pwd)"
timing_script="$repo_root/scripts/workflow_timing.py"

record_timing() {
    local status="$1"
    local elapsed_seconds="$2"
    if [[ -f "$timing_script" ]] && command -v python3 >/dev/null 2>&1; then
        python3 "$timing_script" \
            --case-dir "$PWD" \
            --study-root "$study_root" \
            --step solver \
            --status "$status" \
            --elapsed-seconds "$elapsed_seconds" \
            --note "config=$config_path" || true
    fi
}

start_epoch="$(date +%s)"
solver_status=0
srun --kill-on-bad-exit=1 SU2_CFD "$config_path" || solver_status=$?
end_epoch="$(date +%s)"
elapsed_seconds="$((end_epoch - start_epoch))"

if [[ "$solver_status" -eq 0 ]]; then
    record_timing success "$elapsed_seconds"
else
    record_timing failure "$elapsed_seconds"
fi

exit "$solver_status"
