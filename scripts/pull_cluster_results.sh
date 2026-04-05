#!/usr/bin/env bash

set -euo pipefail

# =============================================================================
# CFD Results Collector
# Run this from your LOCAL machine (WSL/macOS/Linux terminal).
# It scans remote case folders, groups them by Mach number, and copies the
# selected outputs into matching local per-case folders.
# =============================================================================

# --- Configure these ---------------------------------------------------------
CLUSTER_USER="${CLUSTER_USER:-anthonyy}"
CLUSTER_HOST="${CLUSTER_HOST:-trillium}"

# Optional override. Leave empty to auto-detect the cluster cases directory.
CLUSTER_CASES_DIR="${CLUSTER_CASES_DIR:-}"

# Edit this for your laptop/WSL destination.
LOCAL_CASES_DIR="${LOCAL_CASES_DIR:-$HOME/cfd-results/orion/cases}"
# -----------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

REMOTE_HOST="${CLUSTER_USER}@${CLUSTER_HOST}"
REMOTE_CASES_DIR=""

declare -a FILES_TO_PULL=()

declare -a SURFACE_FILES=(
    "shock_surface.csv"
    "shock_surface.vtp"
    "shock_surface_panel.csv"
    "shock_surface_panel.vtp"
    "shock_surface_rectangular.csv"
    "shock_surface_rectangular.vtp"
)

declare -a LIGHTWEIGHT_FILES=(
    "history.csv"
    "surface_flow.vtu"
    "density_gradient_y0.vtu"
    "shock.csv"
    "shock_gradient.csv"
    "shock_pressure.csv"
    "${SURFACE_FILES[@]}"
)

declare -a PRIMARY_FILES=(
    "history.csv"
    "flow.vtu"
    "surface_flow.vtu"
    "density_gradient_y0.vtu"
    "shock.csv"
    "shock_gradient.csv"
    "shock_pressure.csv"
    "${SURFACE_FILES[@]}"
)

declare -a REMOTE_CASE_CANDIDATES=(
    "/scratch/${CLUSTER_USER}/hypersonics-cfd/studies/orion/data/cases"
    "/home/${CLUSTER_USER}/links/scratch/hypersonics-cfd/studies/orion/data/cases"
    "/home/${CLUSTER_USER}/links/scratch/reentry/orion/studies/orion/data/cases"
    "/home/${CLUSTER_USER}/links/scratch/reentry/orion/cases"
)

die() {
    echo -e "${RED}$*${RESET}" >&2
    exit 1
}

info() {
    echo -e "${CYAN}$*${RESET}"
}

join_list() {
    local out=""
    local item
    for item in "$@"; do
        [ -n "$out" ] && out+=", "
        out+="$item"
    done
    printf '%s' "$out"
}

run_remote_bash() {
    local script="$1"
    ssh -o LogLevel=ERROR "${REMOTE_HOST}" "bash -lc $(printf '%q' "$script")"
}

resolve_cluster_cases_dir() {
    local -a candidates=()
    local candidate
    local remote_script

    if [ -n "${CLUSTER_CASES_DIR}" ]; then
        candidates+=("${CLUSTER_CASES_DIR}")
    fi

    for candidate in "${REMOTE_CASE_CANDIDATES[@]}"; do
        if [ -z "${CLUSTER_CASES_DIR}" ] || [ "${candidate}" != "${CLUSTER_CASES_DIR}" ]; then
            candidates+=("${candidate}")
        fi
    done

    remote_script="set -euo pipefail; for d in"
    for candidate in "${candidates[@]}"; do
        remote_script+=" $(printf '%q' "$candidate")"
    done
    remote_script+='; do if [ -d "$d" ]; then printf "%s\n" "$d"; exit 0; fi; done; exit 1'

    if ! REMOTE_CASES_DIR="$(run_remote_bash "$remote_script")"; then
        die "Could not resolve the cluster cases directory. Set CLUSTER_CASES_DIR at the top of the script."
    fi
}

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}${BOLD}║       CFD Results Collector          ║${RESET}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════╝${RESET}"
    echo -e "  Cluster: ${REMOTE_HOST}"
    echo -e "  Remote:  ${REMOTE_CASES_DIR}"
    echo -e "  Local:   ${LOCAL_CASES_DIR}"
    echo ""
}

print_file_menu() {
    echo -e "${BOLD}Select file type(s) to collect:${RESET}"
    echo ""
    echo -e "  ${YELLOW}1)${RESET} history.csv only"
    echo -e "  ${YELLOW}2)${RESET} flow.vtu only"
    echo -e "  ${YELLOW}3)${RESET} shock surface files (.csv + .vtp)"
    echo -e "  ${YELLOW}4)${RESET} history.csv + shock surface files"
    echo -e "  ${YELLOW}5)${RESET} history.csv + flow.vtu"
    echo -e "  ${YELLOW}6)${RESET} All primary files"
    echo -e "  ${YELLOW}7)${RESET} density_gradient_y0.vtu only"
    echo -e "  ${YELLOW}8)${RESET} All lightweight post-processing files"
    echo ""
}

set_files_to_pull() {
    FILES_TO_PULL=()
    case "$1" in
        1) FILES_TO_PULL=("history.csv") ;;
        2) FILES_TO_PULL=("flow.vtu") ;;
        3) FILES_TO_PULL=("${SURFACE_FILES[@]}") ;;
        4) FILES_TO_PULL=("history.csv" "${SURFACE_FILES[@]}") ;;
        5) FILES_TO_PULL=("history.csv" "flow.vtu") ;;
        6) FILES_TO_PULL=("${PRIMARY_FILES[@]}") ;;
        7) FILES_TO_PULL=("density_gradient_y0.vtu") ;;
        8) FILES_TO_PULL=("${LIGHTWEIGHT_FILES[@]}") ;;
        *) die "Invalid choice." ;;
    esac
}

list_remote_cases() {
    local remote_dir_q
    local remote_script

    printf -v remote_dir_q '%q' "${REMOTE_CASES_DIR}"
    remote_script="shopt -s nullglob; for path in ${remote_dir_q}/m*; do [ -d \"\$path\" ] || continue; basename \"\$path\"; done | LC_ALL=C sort -V"
    run_remote_bash "$remote_script"
}

case_mach_prefix() {
    local case_name="$1"
    if [[ "${case_name}" =~ ^(m[0-9]+(\.[0-9]+)?)_ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
        return 0
    fi
    return 1
}

is_aoa_case() {
    [[ "$1" == *_aoa* ]]
}

is_refinement_case() {
    [[ "$1" =~ _(coarse|medium|fine)$ ]]
}

copy_file() {
    local case_name="$1"
    local file_name="$2"
    local local_dir="$3"

    if scp -q "${REMOTE_HOST}:${REMOTE_CASES_DIR}/${case_name}/${file_name}" "${local_dir}/${file_name}" 2>/dev/null; then
        echo -e "    ${GREEN}OK${RESET} ${file_name}"
        return 0
    fi

    echo -e "    ${RED}--${RESET} ${file_name} not found"
    return 1
}

pull_files() {
    local cases=("$@")
    local case_name
    local file_name
    local local_dir
    local found=0
    local missing=0

    echo ""
    for case_name in "${cases[@]}"; do
        [ -z "${case_name}" ] && continue
        local_dir="${LOCAL_CASES_DIR}/${case_name}"
        echo -e "${CYAN}-> ${case_name}${RESET}"
        mkdir -p "${local_dir}"

        for file_name in "${FILES_TO_PULL[@]}"; do
            if copy_file "${case_name}" "${file_name}" "${local_dir}"; then
                ((found += 1))
            else
                ((missing += 1))
            fi
        done
    done

    echo ""
    echo -e "${BOLD}----------------------------------------${RESET}"
    echo -e "  ${GREEN}Transferred: ${found} file(s)${RESET}"
    if [ "${missing}" -gt 0 ]; then
        echo -e "  ${RED}Missing:     ${missing} file(s)${RESET}"
    fi
    echo -e "${BOLD}----------------------------------------${RESET}"
    echo ""
}

resolve_cluster_cases_dir
mkdir -p "${LOCAL_CASES_DIR}"
print_header
print_file_menu
read -r -p "File type [1-8]: " file_choice
echo ""
set_files_to_pull "${file_choice}"

info "Scanning cluster for case folders..."
mapfile -t ALL_CASES < <(list_remote_cases)

if [ ${#ALL_CASES[@]} -eq 0 ]; then
    die "Could not fetch case folders from the cluster."
fi

declare -A MACH_SEEN=()
declare -a MACH_NUMBERS=()
declare -a MENU_CASES=()
declare -a MENU_LABELS=()

for case_name in "${ALL_CASES[@]}"; do
    mach="$(case_mach_prefix "${case_name}" || true)"
    [ -z "${mach}" ] && continue
    if [ -z "${MACH_SEEN[$mach]+x}" ]; then
        MACH_SEEN[$mach]=1
        MACH_NUMBERS+=("${mach}")
    fi
done

mapfile -t MACH_NUMBERS < <(printf '%s\n' "${MACH_NUMBERS[@]}" | LC_ALL=C sort -V)

idx=0

echo ""
echo -e "${BOLD}Select case group:${RESET}"
echo ""

for mach in "${MACH_NUMBERS[@]}"; do
    aoa_cases=()
    ref_cases=()
    all_mach_cases=()

    for case_name in "${ALL_CASES[@]}"; do
        if [[ "${case_name}" == ${mach}_* ]]; then
            all_mach_cases+=("${case_name}")
            if is_aoa_case "${case_name}"; then
                aoa_cases+=("${case_name}")
            elif is_refinement_case "${case_name}"; then
                ref_cases+=("${case_name}")
            fi
        fi
    done

    echo -e "  ${CYAN}── ${mach^^} ────────────────────────────────${RESET}"

    if [ ${#aoa_cases[@]} -gt 0 ]; then
        ((idx += 1))
        label="${mach^^} AoA cases"
        details="$(join_list "${aoa_cases[@]}")"
        echo -e "  ${YELLOW}${idx})${RESET} ${label}  (${details})"
        MENU_LABELS+=("${label}")
        MENU_CASES+=("${aoa_cases[*]}")
    fi

    if [ ${#ref_cases[@]} -gt 0 ]; then
        ((idx += 1))
        label="${mach^^} refinement cases"
        details="$(join_list "${ref_cases[@]}")"
        echo -e "  ${YELLOW}${idx})${RESET} ${label}  (${details})"
        MENU_LABELS+=("${label}")
        MENU_CASES+=("${ref_cases[*]}")
    fi

    if [ ${#all_mach_cases[@]} -gt 0 ] && [ ${#aoa_cases[@]} -gt 0 ] && [ ${#ref_cases[@]} -gt 0 ]; then
        ((idx += 1))
        label="All ${mach^^} cases"
        echo -e "  ${YELLOW}${idx})${RESET} ${label}"
        MENU_LABELS+=("${label}")
        MENU_CASES+=("${all_mach_cases[*]}")
    fi

    echo ""
done

all_aoa=()
all_ref=()
for case_name in "${ALL_CASES[@]}"; do
    is_aoa_case "${case_name}" && all_aoa+=("${case_name}")
    is_refinement_case "${case_name}" && all_ref+=("${case_name}")
done

echo -e "  ${CYAN}── Bulk ─────────────────────────────────${RESET}"

if [ ${#all_aoa[@]} -gt 0 ]; then
    ((idx += 1))
    echo -e "  ${YELLOW}${idx})${RESET} All AoA cases"
    MENU_LABELS+=("All AoA cases")
    MENU_CASES+=("${all_aoa[*]}")
fi

if [ ${#all_ref[@]} -gt 0 ]; then
    ((idx += 1))
    echo -e "  ${YELLOW}${idx})${RESET} All refinement cases"
    MENU_LABELS+=("All refinement cases")
    MENU_CASES+=("${all_ref[*]}")
fi

((idx += 1))
echo -e "  ${YELLOW}${idx})${RESET} Everything"
MENU_LABELS+=("Everything")
MENU_CASES+=("${ALL_CASES[*]}")

((idx += 1))
echo -e "  ${YELLOW}${idx})${RESET} Custom case name(s)"
MENU_LABELS+=("CUSTOM")
MENU_CASES+=("")

echo ""
echo -e "  ${YELLOW}q)${RESET} Quit"
echo ""

read -r -p "Case group [1-${idx}/q]: " case_choice
echo ""

if [[ "${case_choice}" == "q" || "${case_choice}" == "Q" ]]; then
    echo "Bye!"
    exit 0
fi

if ! [[ "${case_choice}" =~ ^[0-9]+$ ]] || [ "${case_choice}" -lt 1 ] || [ "${case_choice}" -gt "${idx}" ]; then
    die "Invalid choice."
fi

selected_label="${MENU_LABELS[$((case_choice - 1))]}"
selected_cases="${MENU_CASES[$((case_choice - 1))]}"

if [ "${selected_label}" = "CUSTOM" ]; then
    read -r -p "Enter case name(s), separated by spaces or commas: " custom_cases
    custom_cases="${custom_cases//,/ }"
    selected_cases="${custom_cases}"
fi

read -r -a CASES <<< "${selected_cases}"
pull_files "${CASES[@]}"
