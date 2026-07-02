clear; clc; close all;

helpers       = orion_case_helpers();
analysis_dir  = helpers.resolve_script_dir();
study_dir     = fileparts(analysis_dir);
cases_dir     = fullfile(study_dir, 'data', 'cases');
required_file = 'history.csv';

% Residual fields to plot; names must match history.csv headers.
residual_fields = {'rms[Rho]', 'rms[RhoU]', 'rms[RhoV]', 'rms[RhoE]'};
field_labels    = {'$\rho$', '$\rho u$', '$\rho v$', '$\rho E$'};

set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter',        'latex');
set(groot, 'defaultTextInterpreter',          'latex');

%% DISCOVER AND SELECT CASES
if ~isfolder(cases_dir)
    error(['Cases directory not found: %s\n' ...
        'Run pull_cluster_results.sh first so results land under studies/orion/data/cases.'], cases_dir);
end

all_cases = helpers.discover_cases(cases_dir, required_file);
if isempty(all_cases)
    error(['No case folders with %s found in %s\n' ...
        'Pull history files with pull_cluster_results.sh and try again.'], required_file, cases_dir);
end

selected = helpers.case_selection_menu(all_cases, 'case group');
if isempty(selected)
    disp('No cases selected. Exiting.');
    return;
end

%% PLOT
figure('Color', 'w');
hold on; grid on; box on;
colors      = lines(numel(selected));
line_styles = {'-', '--', ':', '-.'};

h        = gobjects(numel(selected) * numel(residual_fields), 1);
leg_text = cell(numel(selected) * numel(residual_fields), 1);
leg_idx  = 0;

for k = 1:numel(selected)
    case_name = selected{k};
    csv_path  = fullfile(cases_dir, case_name, required_file);

    if ~isfile(csv_path)
        warning('history.csv not found for case: %s', case_name);
        continue;
    end

    fid = fopen(csv_path, 'r');
    header_line = fgetl(fid);
    fclose(fid);

    raw_cols  = strsplit(header_line, ',');
    col_names = strtrim(raw_cols);
    col_names = regexprep(col_names, '^"|"$', '');
    col_names = strtrim(col_names);

    data = readmatrix(csv_path, 'NumHeaderLines', 1);

    iter_col = find(strcmpi(col_names, 'Inner_Iter'), 1);
    if isempty(iter_col)
        iter_col = find(strcmpi(col_names, 'Iteration'), 1);
    end
    if isempty(iter_col)
        iter = (1:size(data, 1)).';
    else
        iter = data(:, iter_col);
    end

    case_label = helpers.format_case_label(case_name);

    for f = 1:numel(residual_fields)
        target  = residual_fields{f};
        col_idx = find(strcmpi(col_names, target), 1);

        if isempty(col_idx)
            warning('Field "%s" not found in %s', target, case_name);
            continue;
        end

        vals = data(:, col_idx);
        ls   = line_styles{mod(f - 1, numel(line_styles)) + 1};

        leg_idx = leg_idx + 1;
        h(leg_idx) = semilogy(iter, 10.^vals, ls, ...
            'Color',     colors(k, :), ...
            'LineWidth', 1.5);
        leg_text{leg_idx} = sprintf('%s - %s', case_label, field_labels{f});
    end
end

if leg_idx == 0
    error('No residual data could be plotted for the selected cases.');
end

valid = isgraphics(h(1:leg_idx));
legend(h(valid), leg_text(valid), 'Location', 'bestoutside', 'FontSize', 11);
xlabel('Inner Iteration', 'FontSize', 14);
ylabel('Residual',        'FontSize', 14);
title('Convergence History', 'FontSize', 16);
set(gca, 'YScale', 'log', 'FontSize', 13);
