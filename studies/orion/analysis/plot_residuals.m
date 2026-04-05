clear; clc; close all;

analysis_dir  = resolve_script_dir();
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

all_cases = discover_cases(cases_dir, required_file);
if isempty(all_cases)
    error(['No case folders with %s found in %s\n' ...
        'Pull history files with pull_cluster_results.sh and try again.'], required_file, cases_dir);
end

selected = case_selection_menu(all_cases);
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

    case_label = format_case_label(case_name);

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


function all_cases = discover_cases(cases_dir, required_file)
    d = dir(cases_dir);
    d = d([d.isdir]);
    names = {d.name};
    mask = ~strcmp(names, '.') & ~strcmp(names, '..') & ...
        ~cellfun(@isempty, regexp(names, '^m[0-9p\.]+', 'once'));

    candidate_cases = sort(names(mask));
    keep_case = cellfun(@(name) isfile(fullfile(cases_dir, name, required_file)), candidate_cases);
    all_cases = candidate_cases(keep_case);
end

function selected = case_selection_menu(all_cases)
    mach_map  = group_by_mach(all_cases);
    mach_keys = fieldnames(mach_map);
    mach_nums = cellfun(@(key) mach_map.(key).M_val, mach_keys);
    [~, si]   = sort(mach_nums);
    mach_keys = mach_keys(si);

    max_menu_items = 3 * numel(mach_keys) + 4;
    menu_labels = cell(max_menu_items, 1);
    menu_cases  = cell(max_menu_items, 1);
    idx = 0;

    fprintf('\nSelect case group:\n\n');

    for m = 1:numel(mach_keys)
        mach_info = mach_map.(mach_keys{m});
        mach      = mach_info.label;
        cases     = mach_info.cases;
        aoa_cases = cases(contains(cases, '_aoa'));
        ref_cases = cases(cellfun(@(c) any(contains(c, ...
            {'_coarse', '_medium', '_fine'})), cases));

        fprintf('  -- %s %s\n', upper(mach), repmat('-', 1, max(1, 36 - numel(mach))));

        if ~isempty(aoa_cases)
            idx = idx + 1;
            label = sprintf('%s AoA cases  (%s)', upper(mach), strjoin(aoa_cases, ', '));
            fprintf('  %2d) %s\n', idx, label);
            menu_labels{idx} = label;
            menu_cases{idx}  = aoa_cases;
        end

        if ~isempty(ref_cases)
            idx = idx + 1;
            label = sprintf('%s refinement cases  (%s)', upper(mach), strjoin(ref_cases, ', '));
            fprintf('  %2d) %s\n', idx, label);
            menu_labels{idx} = label;
            menu_cases{idx}  = ref_cases;
        end

        if ~isempty(aoa_cases) && ~isempty(ref_cases)
            idx = idx + 1;
            label = sprintf('All %s cases', upper(mach));
            fprintf('  %2d) %s\n', idx, label);
            menu_labels{idx} = label;
            menu_cases{idx}  = cases;
        end

        fprintf('\n');
    end

    fprintf('  -- Bulk %s\n', repmat('-', 1, 33));
    all_aoa = all_cases(contains(all_cases, '_aoa'));
    all_ref = all_cases(cellfun(@(c) any(contains(c, ...
        {'_coarse', '_medium', '_fine'})), all_cases));

    if ~isempty(all_aoa)
        idx = idx + 1;
        fprintf('  %2d) All AoA cases\n', idx);
        menu_labels{idx} = 'All AoA cases';
        menu_cases{idx}  = all_aoa;
    end

    if ~isempty(all_ref)
        idx = idx + 1;
        fprintf('  %2d) All refinement cases\n', idx);
        menu_labels{idx} = 'All refinement cases';
        menu_cases{idx}  = all_ref;
    end

    idx = idx + 1;
    fprintf('  %2d) Everything\n', idx);
    menu_labels{idx} = 'Everything';
    menu_cases{idx}  = all_cases;

    idx = idx + 1;
    fprintf('  %2d) Custom\n\n', idx);
    menu_labels{idx} = 'CUSTOM';
    menu_cases{idx}  = {};

    menu_labels = menu_labels(1:idx);
    menu_cases  = menu_cases(1:idx);

    choice = input(sprintf('Choice [1-%d]: ', idx));
    if isempty(choice) || choice < 1 || choice > idx
        selected = {};
        return;
    end

    if strcmp(menu_labels{choice}, 'CUSTOM')
        name = input('Enter case folder name: ', 's');
        selected = {strtrim(name)};
    else
        selected = menu_cases{choice};
    end
end

function mach_map = group_by_mach(cases)
    mach_map = struct();
    for k = 1:numel(cases)
        tok = regexp(cases{k}, '^(m[0-9p\.]+)', 'tokens', 'once');
        if isempty(tok)
            continue;
        end

        mach_label = tok{1};
        M_val = str2double(strrep(mach_label(2:end), 'p', '.'));
        if isfinite(M_val)
            mach_field = mach_field_name(M_val);
            mach_label = mach_display_name(M_val);
        else
            mach_field = matlab.lang.makeValidName(mach_label);
        end

        if ~isfield(mach_map, mach_field)
            mach_map.(mach_field) = struct( ...
                'label', mach_label, ...
                'M_val', M_val, ...
                'cases', {{}});
        end
        mach_map.(mach_field).cases{end + 1} = cases{k};
    end
end

function field_name = mach_field_name(M_val)
    field_name = ['m_' regexprep(sprintf('%.12g', M_val), '[^0-9A-Za-z]', '_')];
end

function label = mach_display_name(M_val)
    label = ['m' sprintf('%.12g', M_val)];
end

function case_label = format_case_label(case_name)
    tok = regexp(case_name, '^m([0-9p\.]+)_aoa([0-9\-\.]+)$', 'tokens', 'once');
    if ~isempty(tok)
        M_val   = str2double(strrep(tok{1}, 'p', '.'));
        AOA_val = str2double(strrep(tok{2}, 'p', '.'));
        case_label = sprintf('$M = %.1f$, $%.0f^{\\circ}$', M_val, AOA_val);
        return;
    end

    tok = regexp(case_name, '^m([0-9p\.]+)_(coarse|medium|fine)$', 'tokens', 'once');
    if ~isempty(tok)
        M_val = str2double(strrep(tok{1}, 'p', '.'));
        mesh_label = tok{2};
        mesh_label(1) = upper(mesh_label(1));
        case_label = sprintf('$M = %.1f$ (%s mesh)', M_val, mesh_label);
        return;
    end

    case_label = strrep(case_name, '_', '\_');
end

function analysis_dir = resolve_script_dir()
    full_path = mfilename('fullpath');

    if isempty(full_path)
        stack = dbstack('-completenames');
        if ~isempty(stack)
            full_path = stack(1).file;
        elseif usejava('desktop')
            try
                full_path = matlab.desktop.editor.getActiveFilename;
            catch
                full_path = pwd;
            end
        else
            full_path = pwd;
        end
    end

    if isfolder(full_path)
        analysis_dir = full_path;
    else
        analysis_dir = fileparts(full_path);
    end
end
