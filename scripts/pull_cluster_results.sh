#!/usr/bin/env bash

CLUSTER_USER="${CLUSTER_USER:-anthonyy}"
CLUSTER_HOST="${CLUSTER_HOST:-trillium}"
CLUSTER_CASES_DIR="${CLUSTER_CASES_DIR:-/scratch/${CLUSTER_USER}/hypersonics-cfd/studies/orion/data/cases}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_CASES_DIR="${LOCAL_CASES_DIR:-${REPO_ROOT}/studies/orion/data/cases}"

cases="${1:-}"
preset="${2:-light}"

if [ -z "$cases" ]; then
    ssh "${CLUSTER_USER}@${CLUSTER_HOST}" find "$CLUSTER_CASES_DIR" -mindepth 1 -maxdepth 1 -type d | sed 's|.*/||' | sort -V
    read -r -p "Cases, separated by commas: " cases
    read -r -p "Preset [light]: " selected_preset
    preset="${selected_preset:-light}"
fi

case "$preset" in
    history) files=("history.csv") ;;
    flow) files=("flow_full.vtu") ;;
    shock) files=("shock_surface.csv" "shock_surface.vtp") ;;
    slices) files=("flow_slice_xy.vtp" "flow_slice_xz.vtp") ;;
    yplus) files=("orion_yplus.vtp" "yplus_summary.csv") ;;
    diagnostics) files=("initial_search_line_profile.csv" "terminated_search_line_summary.csv" "terminated_search_line_profiles.csv") ;;
    timing) files=("logs/workflow_timings.csv") ;;
    light) files=("history.csv" "surface_flow.vtu" "shock_surface.csv" "shock_surface.vtp" "flow_slice_xy.vtp" "flow_slice_xz.vtp" "orion_yplus.vtp" "yplus_summary.csv" "logs/workflow_timings.csv") ;;
    all) files=("history.csv" "flow.vtu" "flow_full.vtu" "surface_flow.vtu" "shock_surface.csv" "shock_surface.vtp" "flow_slice_xy.vtp" "flow_slice_xz.vtp" "orion_yplus.vtp" "yplus_summary.csv" "logs/workflow_timings.csv") ;;
    *) IFS=',' read -ra files <<< "$preset" ;;
esac

IFS=',' read -ra case_names <<< "$cases"
for case_name in "${case_names[@]}"; do
    case_name="${case_name// /}"
    for file_name in "${files[@]}"; do
        destination="${LOCAL_CASES_DIR}/${case_name}/${file_name}"
        mkdir -p "$(dirname "$destination")"
        scp "${CLUSTER_USER}@${CLUSTER_HOST}:${CLUSTER_CASES_DIR}/${case_name}/${file_name}" "$destination"
    done
done
