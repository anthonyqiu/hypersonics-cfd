function diagnostics = plot_search_line_diagnostics(case_name)
% Plot the initial stagnation search line and all exported terminated lines.
%
% The x-axis is always n, the local coordinate along each search line. This makes the
% plots directly comparable to the 1D peak-picking logic inside extract_shock_surface.py.

analysis_dir = resolve_script_dir();
study_dir = fileparts(analysis_dir);
cases_dir = fullfile(study_dir, 'data', 'cases');

initial_file = 'initial_search_line_profile.csv';
terminated_profile_file = fullfile('search_line_debug', 'terminated_search_line_profiles.csv');
terminated_summary_file = fullfile('search_line_debug', 'terminated_search_line_summary.csv');

if nargin < 1 || strlength(string(case_name)) == 0
    case_name = choose_case_interactively(cases_dir, initial_file, terminated_profile_file);
    if strlength(string(case_name)) == 0
        fprintf('No case selected. Exiting.\n');
        diagnostics = struct();
        return;
    end
end

case_name = char(case_name);
case_dir = fullfile(cases_dir, case_name);
initial_path = fullfile(case_dir, initial_file);
terminated_profile_path = fullfile(case_dir, terminated_profile_file);
terminated_summary_path = fullfile(case_dir, terminated_summary_file);

if ~isfile(initial_path)
    error(['Initial search-line profile not found: %s\n' ...
        'Run python3 scripts/export_initial_search_line.py first.'], initial_path);
end
if ~isfile(terminated_profile_path)
    error(['Terminated search-line profiles not found: %s\n' ...
        'Run CFD_EXPORT_TERMINATED_SEARCH_LINES=1 python3 scripts/extract_shock_surface.py first.'], ...
        terminated_profile_path);
end

initial_profile = readtable(initial_path, ...
    'Delimiter', ',', 'TextType', 'string', 'VariableNamingRule', 'preserve');
terminated_profiles = readtable(terminated_profile_path, ...
    'Delimiter', ',', 'TextType', 'string', 'VariableNamingRule', 'preserve');
if isfile(terminated_summary_path)
    terminated_summary = readtable(terminated_summary_path, ...
        'Delimiter', ',', 'TextType', 'string', 'VariableNamingRule', 'preserve');
else
    terminated_summary = table();
end

require_columns(initial_profile, [ ...
    "pass_name", "line_coordinate", "shock_sensor_raw", "shock_sensor_smoothed", ...
    "is_selected_peak", "sensor_floor"]);
require_columns(terminated_profiles, [ ...
    "debug_line_id", "reason", "shell_layer", "ray_index", "candidate_n", ...
    "candidate_smoothed", "n", "shock_sensor_raw", "shock_sensor_smoothed"]);

fig = figure('Color', 'w', 'Name', sprintf('%s search-line diagnostics', case_name));
tiledlayout(2, 1, 'TileSpacing', 'compact', 'Padding', 'compact');

plot_initial_search_line_tile(initial_profile);
plot_terminated_search_line_tile(terminated_profiles, initial_profile);

sgtitle(sprintf('%s search-line diagnostics', case_name), 'Interpreter', 'none');

fprintf('\nCase: %s\n', case_name);
fprintf('  Initial profile: %s\n', initial_path);
fprintf('  Terminated profiles: %s\n', terminated_profile_path);
fprintf('  Terminated lines plotted: %d\n', height(terminated_profiles));
if ~isempty(terminated_summary)
    fprintf('  Terminated summary: %s\n', terminated_summary_path);
end

diagnostics = struct();
diagnostics.initial_profile = initial_profile;
diagnostics.terminated_profiles = terminated_profiles;
diagnostics.terminated_summary = terminated_summary;

if ~usejava('desktop')
    drawnow;
end

end


function plot_initial_search_line_tile(profile)
ax = nexttile;
hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on');

pass_names = unique(profile.pass_name, 'stable');
colors = lines(max(numel(pass_names), 1));
legend_handles = gobjects(0);
legend_labels = {};

for pass_idx = 1:numel(pass_names)
    pass_name = pass_names(pass_idx);
    rows = profile(profile.pass_name == pass_name, :);
    color = colors(pass_idx, :);
    muted_color = 0.65 * [1, 1, 1] + 0.35 * color;

    h = plot(ax, rows.line_coordinate, rows.shock_sensor_raw, '-', ...
        'Color', muted_color, 'LineWidth', 0.8);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = sprintf('%s raw', char(pass_name)); %#ok<AGROW>

    h = plot(ax, rows.line_coordinate, rows.shock_sensor_smoothed, '-', ...
        'Color', color, 'LineWidth', 1.6);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = sprintf('%s smoothed', char(pass_name)); %#ok<AGROW>

    peak_mask = logical(rows.is_selected_peak);
    if any(peak_mask)
        h = scatter(ax, rows.line_coordinate(peak_mask), rows.shock_sensor_smoothed(peak_mask), ...
            54, 'o', 'MarkerFaceColor', color, 'MarkerEdgeColor', 'k', 'LineWidth', 0.8);
        legend_handles(end+1) = h; %#ok<AGROW>
        legend_labels{end+1} = sprintf('%s selected peak', char(pass_name)); %#ok<AGROW>
    end
end

if ismember("sensor_floor", string(profile.Properties.VariableNames))
    h = yline(ax, profile.sensor_floor(1), '--', 'Color', [0.15, 0.50, 0.20], 'LineWidth', 1.0);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = 'sensor floor'; %#ok<AGROW>
end

title(ax, 'Initial stagnation search line', 'Interpreter', 'none');
xlabel(ax, 'n (distance along search line)');
ylabel(ax, '|grad \rho|');
legend(ax, legend_handles, legend_labels, 'Location', 'best');
end


function plot_terminated_search_line_tile(profiles, initial_profile)
ax = nexttile;
hold(ax, 'on'); grid(ax, 'on'); box(ax, 'on');

shells = double(profiles.shell_layer);
shell_min = min(shells);
shell_max = max(shells);
color_map = parula(128);

for row_idx = 1:height(profiles)
    n = parse_number_list(profiles.n(row_idx));
    raw_sensor = parse_number_list(profiles.shock_sensor_raw(row_idx));
    smooth_sensor = parse_number_list(profiles.shock_sensor_smoothed(row_idx));
    if isempty(n) || isempty(smooth_sensor)
        continue;
    end

    color = color_for_value(double(profiles.shell_layer(row_idx)), shell_min, shell_max, color_map);
    muted_color = 0.82 * [1, 1, 1] + 0.18 * color;

    if numel(raw_sensor) == numel(n)
        plot(ax, n, raw_sensor, '-', 'Color', muted_color, 'LineWidth', 0.4);
    end
    plot(ax, n, smooth_sensor, '-', 'Color', color, 'LineWidth', 0.75);

    candidate_n = double(profiles.candidate_n(row_idx));
    candidate_value = double(profiles.candidate_smoothed(row_idx));
    if isfinite(candidate_n) && isfinite(candidate_value)
        plot(ax, candidate_n, candidate_value, '.', 'Color', color, 'MarkerSize', 9);
    end
end

if ismember("sensor_floor", string(initial_profile.Properties.VariableNames))
    yline(ax, initial_profile.sensor_floor(1), '--', 'Color', [0.15, 0.50, 0.20], 'LineWidth', 1.0);
end

colormap(ax, color_map);
caxis(ax, [shell_min, shell_max]);
cb = colorbar(ax);
cb.Label.String = 'shell layer';

title(ax, sprintf('Terminated search lines (%d profiles)', height(profiles)), 'Interpreter', 'none');
xlabel(ax, 'n (distance along each terminated search line)');
ylabel(ax, '|grad \rho|');
end


function values = parse_number_list(value)
text = strtrim(string(value));
if ismissing(text) || strlength(text) == 0
    values = [];
    return;
end
values = str2double(split(text, ';'));
values = values(:);
end


function color = color_for_value(value, value_min, value_max, color_map)
if value_max <= value_min
    color = color_map(1, :);
    return;
end
fraction = (value - value_min) / (value_max - value_min);
index = 1 + round(fraction * (size(color_map, 1) - 1));
index = max(1, min(size(color_map, 1), index));
color = color_map(index, :);
end


function require_columns(table_data, required_columns)
missing_columns = required_columns(~ismember(required_columns, string(table_data.Properties.VariableNames)));
if ~isempty(missing_columns)
    error('CSV is missing required columns: %s', strjoin(cellstr(missing_columns), ', '));
end
end


function case_name = choose_case_interactively(cases_dir, initial_file, terminated_profile_file)
case_names = discover_cases(cases_dir, initial_file, terminated_profile_file);
if isempty(case_names)
    error(['No case folders with both %s and %s were found in %s\n' ...
        'Run the initial-line exporter and shock extractor with terminated-line export first.'], ...
        initial_file, terminated_profile_file, cases_dir);
end

fprintf('\nSelect case for search-line diagnostic plotting:\n\n');
for idx = 1:numel(case_names)
    fprintf('  %2d) %s\n', idx, case_names{idx});
end
fprintf('\n  q) Quit\n\n');

choice = strtrim(input(sprintf('Case [1-%d/q]: ', numel(case_names)), 's'));
if strcmpi(choice, 'q')
    case_name = "";
    return;
end

index = str2double(choice);
if isnan(index) || index < 1 || index > numel(case_names)
    error('Invalid case selection.');
end
case_name = string(case_names{index});
end


function case_names = discover_cases(cases_dir, initial_file, terminated_profile_file)
d = dir(cases_dir);
d = d([d.isdir]);
names = {d.name};
mask = ~strcmp(names, '.') & ~strcmp(names, '..') & ...
       ~cellfun(@isempty, regexp(names, '^m[0-9p\.]+', 'once'));

candidate_cases = sort(names(mask));
keep_case = false(size(candidate_cases));
for idx = 1:numel(candidate_cases)
    case_dir = fullfile(cases_dir, candidate_cases{idx});
    keep_case(idx) = isfile(fullfile(case_dir, initial_file)) && ...
        isfile(fullfile(case_dir, terminated_profile_file));
end
case_names = candidate_cases(keep_case);
end


function script_dir = resolve_script_dir()
script_path = mfilename('fullpath');
if isempty(script_path)
    script_dir = pwd;
else
    script_dir = fileparts(script_path);
end
end
