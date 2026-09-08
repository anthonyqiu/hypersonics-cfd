#!/bin/bash
set -euo pipefail

case_dir="$1"
base_iteration="${2:-}"
state_file="$case_dir/cumulative_iteration.txt"

if [[ -z "$base_iteration" ]]; then
    base_iteration="$(cat "$state_file")"
fi

local_iteration="$(tail -n 1 "$case_dir/history.csv" | cut -d, -f3 | tr -d ' ')"
total_iteration="$((base_iteration + local_iteration))"
checkpoint_dir="$case_dir/checkpoints/iter_${total_iteration}_cfl0p005"

mkdir -p "$checkpoint_dir"
cp --reflink=auto "$case_dir/history.csv" "$case_dir/flow.vtu" "$case_dir/restart_flow.dat" "$checkpoint_dir/"
printf '%s\n' "$total_iteration" > "$state_file"
printf '%s\n' "$checkpoint_dir"
