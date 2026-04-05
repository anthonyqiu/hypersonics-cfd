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

srun --kill-on-bad-exit=1 SU2_CFD "$config_path"
