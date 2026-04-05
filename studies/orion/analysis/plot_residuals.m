clear; clc; close all;

%% ── SETTINGS ────────────────────────────────────────────────────────────────
cases_dir = '../../data/cases';

% Residual fields to plot — must match headers in history.csv (quotes stripped)
% SU2 typically outputs: rms[Rho], rms[RhoU], rms[RhoV], rms[RhoW], rms[RhoE]
residual_fields = {'rms[Rho]', 'rms[RhoU]', 'rms[RhoV]', 'rms[RhoE]'};
field_labels    = {'$\rho$', '$\rho u$', '$\rho v$', '$\rho E$'};
%% ─────────────────────────────────────────────────────────────────────────────

set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter',        'latex');
set(groot, 'defaultTextInterpreter',          'latex');

%% DISCOVER & SELECT CASES
all_cases = discover_cases(cases_dir);
if isempty(all_cases)
    error('No case folders found in %s', cases_dir);
end

selected = case_selection_menu(all_cases);
if isempty(selected)
    disp('No cases selected. Exiting.');
    return;
end

%% PLOT
figure('Color', 'w');
hold on; grid on; box on;
colors     = lines(numel(selected));
line_styles = {'-', '--', ':', '-.'};

h        = gobjects(numel(selected) * numel(residual_fields), 1);
leg_text = cell(numel(selected) * numel(residual_fields), 1);
leg_idx  = 0;

for k = 1:numel(selected)
    case_name = selected{k};
    csv_path  = fullfile(cases_dir, case_name, 'history.csv');
    
    if ~isfile(csv_path)
        warning('history.csv not found for case: %s', case_name);
        continue;
    end
    
    %% Read CSV — strip surrounding quotes from headers
    fid = fopen(csv_path, 'r');
    header_line = fgetl(fid);
    fclose(fid);
    
    % Parse and clean column names
    raw_cols = strsplit(header_line, ',');
    col_names = strtrim(raw_cols);
    col_names = regexprep(col_names, '^"|"$', '');  % strip leading/trailing "
    col_names = strtrim(col_names);
    
    % Read numeric data (skip header row)
    data = readmatrix(csv_path, 'NumHeaderLines', 1);
    
    % Find Inner_Iter column for x-axis
    iter_col = find(strcmpi(col_names, 'Inner_Iter'), 1);
    if isempty(iter_col)
        iter_col = find(strcmpi(col_names, 'Iteration'), 1);
    end
    if isempty(iter_col)
        iter = (1:size(data,1))';
    else
        iter = data(:, iter_col);
    end
    
    % Build case legend label
    tok = regexp(case_name, 'm([0-9p\.]+)_aoa([0-9\-\.]+)', 'tokens');
    if ~isempty(tok)
        M_val   = str2double(strrep(tok{1}{1}, 'p', '.'));
        AOA_val = str2double(strrep(tok{1}{2}, 'p', '.'));
        case_label = sprintf('$M=%.1f$, $%.0f^{\\circ}$', M_val, AOA_val);
    else
        case_label = strrep(case_name, '_', '\_');
    end
    
    %% Plot each residual field
    for f = 1:numel(residual_fields)
        target = residual_fields{f};
        col_idx = find(strcmpi(col_names, target), 1);
        
        if isempty(col_idx)
            warning('Field "%s" not found in %s', target, case_name);
            continue;
        end
        
        vals = data(:, col_idx);   % already log10 values from SU2
        ls   = line_styles{mod(f-1, numel(line_styles)) + 1};
        
        leg_idx = leg_idx + 1;
        h(leg_idx) = semilogy(iter, 10.^vals, ls, ...
            'Color',     colors(k,:), ...
            'LineWidth', 1.5);
        leg_text{leg_idx} = sprintf('%s - %s', case_label, field_labels{f});
    end
end

%% FORMATTING
valid = isgraphics(h(1:leg_idx));
legend(h(valid), leg_text(valid), 'Location', 'bestoutside', 'FontSize', 11);
xlabel('Inner Iteration', 'FontSize', 14);
ylabel('Residual',        'FontSize', 14);
title('Convergence History', 'FontSize', 16);
set(gca, 'YScale', 'log', 'FontSize', 13);


%% ══════════════════════════════════════════════════════════════════════════════
%%  HELPERS
%% ══════════════════════════════════════════════════════════════════════════════

function all_cases = discover_cases(cases_dir)
d = dir(cases_dir);
d = d([d.isdir]);
names = {d.name};
mask = ~strcmp(names, '.') & ~strcmp(names, '..') & ...
    ~cellfun(@isempty, regexp(names, '^m\d+'));
all_cases = sort(names(mask));
end

function selected = case_selection_menu(all_cases)
mach_map  = group_by_mach(all_cases);
mach_keys = fieldnames(mach_map);
% Sort by Mach number numerically
mach_nums = cellfun(@(m) str2double(m(2:end)), mach_keys);
[~, si]   = sort(mach_nums);
mach_keys = mach_keys(si);

menu_labels = {};
menu_cases  = {};
idx = 0;

fprintf('\nSelect case group:\n\n');

for m = 1:numel(mach_keys)
    mach      = mach_keys{m};
    cases     = mach_map.(mach);
    aoa_cases = cases(contains(cases, '_aoa'));
    ref_cases = cases(cellfun(@(c) any(contains(c, ...
        {'_coarse','_medium','_fine'})), cases));
    
    fprintf('  -- %s %s\n', upper(mach), repmat('-', 1, max(1,36-numel(mach))));
    
    if ~isempty(aoa_cases)
        idx = idx + 1;
        label = sprintf('%s AoA cases  (%s)', upper(mach), strjoin(aoa_cases, ', '));
        fprintf('  %2d) %s\n', idx, label);
        menu_labels{end+1} = label;
        menu_cases{end+1}  = aoa_cases;
    end
    if ~isempty(ref_cases)
        idx = idx + 1;
        label = sprintf('%s refinement cases  (%s)', upper(mach), strjoin(ref_cases, ', '));
        fprintf('  %2d) %s\n', idx, label);
        menu_labels{end+1} = label;
        menu_cases{end+1}  = ref_cases;
    end
    if ~isempty(aoa_cases) && ~isempty(ref_cases)
        idx = idx + 1;
        label = sprintf('All %s cases', upper(mach));
        fprintf('  %2d) %s\n', idx, label);
        menu_labels{end+1} = label;
        menu_cases{end+1}  = cases;
    end
    fprintf('\n');
end

fprintf('  -- Bulk %s\n', repmat('-', 1, 33));
all_aoa = all_cases(contains(all_cases, '_aoa'));
all_ref = all_cases(cellfun(@(c) any(contains(c, ...
    {'_coarse','_medium','_fine'})), all_cases));

if ~isempty(all_aoa)
    idx = idx + 1;
    fprintf('  %2d) All AoA cases\n', idx);
    menu_labels{end+1} = 'All AoA cases';
    menu_cases{end+1}  = all_aoa;
end
if ~isempty(all_ref)
    idx = idx + 1;
    fprintf('  %2d) All refinement cases\n', idx);
    menu_labels{end+1} = 'All refinement cases';
    menu_cases{end+1}  = all_ref;
end
idx = idx + 1;
fprintf('  %2d) Everything\n', idx);
menu_labels{end+1} = 'Everything';
menu_cases{end+1}  = all_cases;

idx = idx + 1;
fprintf('  %2d) Custom\n\n', idx);
menu_labels{end+1} = 'CUSTOM';
menu_cases{end+1}  = {};

choice = input(sprintf('Choice [1-%d]: ', idx));
if isempty(choice) || choice < 1 || choice > idx
    selected = {}; return;
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
    tok = regexp(cases{k}, '^(m\d+)', 'tokens');
    if isempty(tok), continue; end
    mach = tok{1}{1};
    if ~isfield(mach_map, mach)
        mach_map.(mach) = {};
    end
    mach_map.(mach){end+1} = cases{k};
end
end
