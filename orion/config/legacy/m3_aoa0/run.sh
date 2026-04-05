#!/bin/bash
#SBATCH --job-name=m1p5_aoa0
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=64
#SBATCH --cpus-per-task=1
#SBATCH --mem=0
#SBATCH --time=24:00:00
#SBATCH --output=orion_%j.out
#SBATCH --error=orion_%j.err
#SBATCH --account=def-jphickey

ulimit -c 0

module purge
module load StdEnv/2023 gcc openmpi eigen

export SU2_RUN="$HOME/.local/su2-7.5.1/bin"
export PATH="$SU2_RUN:$PATH"
export OMP_NUM_THREADS=1

cd "$SCRATCH/reentry/orion/cases/m3_aoa0"
echo "Nodes: $SLURM_NODELIST Tasks:
$SLURM_NTASKS NPN: $SLURM_NTASKS_PER_NODE"

srun --kill-on-bad-exit=1 SU2_CFD config.cfg
