#!/bin/bash
set -euo pipefail

python_exe="${1:-}"
second_arg="${2:-}"
third_arg="${3:-}"

if [[ -z "$python_exe" || -z "$second_arg" ]]; then
    echo "Usage: $0 <python-executable> [<extract-script>] <case-manifest>" >&2
    exit 2
fi

default_root_dir="${SLURM_SUBMIT_DIR:-$PWD}"
default_extract_script="$default_root_dir/scripts/extract_shock_surface.py"

if [[ -n "$third_arg" && "$second_arg" == *.py ]]; then
    extract_script="$second_arg"
    manifest_path="$third_arg"
    shift 3 || true
else
    extract_script="$default_extract_script"
    manifest_path="$second_arg"
    shift 2 || true
fi

if [[ ! -f "$manifest_path" ]]; then
    echo "Case manifest not found: $manifest_path" >&2
    exit 2
fi

root_dir="$default_root_dir"

if [[ ! -x "$python_exe" ]]; then
    echo "Python executable not found or not executable: $python_exe" >&2
    exit 2
fi

if [[ ! -f "$extract_script" ]]; then
    echo "Shock extraction script not found: $extract_script" >&2
    exit 2
fi

study_name="$(basename "$(dirname "$(dirname "$(dirname "$manifest_path")")")")"

echo "Nodes:      ${SLURM_NODELIST:-local}"
echo "Tasks:      ${SLURM_NTASKS:-local}"
echo "CPUs/task:  ${SLURM_CPUS_PER_TASK:-local}"
echo "Python:     $python_exe"
echo "Manifest:   $manifest_path"
echo "Study:      $study_name"

cd "$root_dir"

case_count=0
while IFS= read -r case_path || [[ -n "$case_path" ]]; do
    [[ -z "$case_path" ]] && continue
    case_count=$((case_count + 1))
    echo
    echo "=== Extracting $case_path ==="
    CFD_STUDY="$study_name" CFD_CASE="$case_path" "$python_exe" "$extract_script"
done < "$manifest_path"

echo
echo "Completed $case_count case(s)."
