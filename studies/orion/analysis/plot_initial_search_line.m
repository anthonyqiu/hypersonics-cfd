function profile = plot_initial_search_line(case_name)
analysis_dir  = resolve_script_dir();
study_dir     = fileparts(analysis_dir);
cases_dir     = fullfile(study_dir, 'data', 'cases');
required_file = 'initial_search_line_profile.csv';

if nargin < 1 || strlength(string(case_name)) == 0
    case_name = choose_case_interactively(cases_dir, required_file);
    if strlength(string(case_name)) == 0
        fprintf('No case selected. Exiting.\n');
        profile = table();
        return;
    end
end

csv_path = fullfile(cases_dir, char(case_name), required_file);
if ~isfile(csv_path)
    error(['Initial search-line profile not found: %s\n' ...
        'Run python3 scripts/export_initial_search_line.py first.'], csv_path);
end

profile = readtable(csv_path, 'TextType', 'string');
required_columns = [ ...
    "pass_name", "line_coordinate", "shock_sensor_raw", "shock_sensor_smoothed", ...
    "valid_mask", "is_selected_peak", "sample_spacing", "savgol_window_points", ...
    "half_length", "selected_peak_coordinate", "selected_peak_value", "sensor_floor"];
missing_columns = required_columns(~ismember(required_columns, string(profile.Properties.VariableNames)));
if ~isempty(missing_columns)
    error('CSV is missing required columns: %s', strjoin(cellstr(missing_columns), ', '));
end

pass_names = unique(profile.pass_name, 'stable');
if isempty(pass_names)
    error('No coarse/refined search-line rows were found in %s.', csv_path);
end

fig = figure('Color', 'w', 'Name', sprintf('%s initial search line', case_name));
tiledlayout(numel(pass_names), 1, 'TileSpacing', 'compact', 'Padding', 'compact');

for pass_idx = 1:numel(pass_names)
    pass_name = pass_names(pass_idx);
    rows = profile(profile.pass_name == pass_name, :);
    nexttile;
    hold on; grid on; box on;

    raw_color      = [0.65, 0.65, 0.65];
    smooth_color   = [0.00, 0.35, 0.90];
    invalid_color  = [0.85, 0.20, 0.10];
    peak_face      = [0.95, 0.60, 0.10];
    threshold_color = [0.20, 0.60, 0.20];

    legend_handles = gobjects(0);
    legend_labels = {};

    h = plot(rows.line_coordinate, rows.shock_sensor_raw, '-', 'Color', raw_color, 'LineWidth', 1.0);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = 'raw'; %#ok<AGROW>

    h = plot(rows.line_coordinate, rows.shock_sensor_smoothed, '-', 'Color', smooth_color, 'LineWidth', 1.6);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = 'smoothed'; %#ok<AGROW>

    h = yline(rows.sensor_floor(1), '--', 'Color', threshold_color, 'LineWidth', 1.0);
    legend_handles(end+1) = h; %#ok<AGROW>
    legend_labels{end+1} = 'sensor floor'; %#ok<AGROW>

    invalid_mask = logical(rows.valid_mask == 0);
    if any(invalid_mask)
        h = plot(rows.line_coordinate(invalid_mask), rows.shock_sensor_raw(invalid_mask), 'x', ...
            'Color', invalid_color, 'LineWidth', 1.0, 'MarkerSize', 6);
        legend_handles(end+1) = h; %#ok<AGROW>
        legend_labels{end+1} = 'invalid sample'; %#ok<AGROW>
    end

    peak_mask = logical(rows.is_selected_peak);
    if any(peak_mask)
        h = scatter(rows.line_coordinate(peak_mask), rows.shock_sensor_smoothed(peak_mask), ...
            60, 'o', 'MarkerFaceColor', peak_face, 'MarkerEdgeColor', 'k', 'LineWidth', 0.8);
        legend_handles(end+1) = h; %#ok<AGROW>
        legend_labels{end+1} = 'selected peak'; %#ok<AGROW>
    end

    spacing = rows.sample_spacing(1);
    window_points = rows.savgol_window_points(1);
    half_length = rows.half_length(1);
    peak_n = rows.selected_peak_coordinate(1);
    peak_value = rows.selected_peak_value(1);

    title(sprintf('%s pass | spacing = %.4f, SG window = %d, half-length = %.4f', ...
        upper(char(pass_name)), spacing, window_points, half_length), 'Interpreter', 'none');
    xlabel('n (search-line coordinate)');
    ylabel('|grad \rho|');
    legend(legend_handles, legend_labels, 'Location', 'best');
    text(0.02, 0.95, sprintf('peak at n = %.4f, value = %.4f', peak_n, peak_value), ...
        'Units', 'normalized', 'VerticalAlignment', 'top', 'Interpreter', 'none');
end

sgtitle(sprintf('%s initial stagnation search line', case_name), 'Interpreter', 'none');

fprintf('\nCase: %s\n', case_name);
for pass_idx = 1:numel(pass_names)
    pass_name = pass_names(pass_idx);
    rows = profile(profile.pass_name == pass_name, :);
    fprintf('  %s pass: spacing = %.4f, SG window = %d, half-length = %.4f, peak n = %.4f, peak value = %.4f\n', ...
        char(pass_name), rows.sample_spacing(1), rows.savgol_window_points(1), ...
        rows.half_length(1), rows.selected_peak_coordinate(1), rows.selected_peak_value(1));
end

if ~usejava('desktop')
    drawnow;
end

end


function case_name = choose_case_interactively(cases_dir, required_file)
case_names = discover_cases(cases_dir, required_file);
if isempty(case_names)
    error(['No case folders with %s found in %s\n' ...
        'Run python3 scripts/export_initial_search_line.py first.'], required_file, cases_dir);
end

fprintf('\nSelect case for initial search-line plotting:\n\n');
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


function case_names = discover_cases(cases_dir, required_file)
d = dir(cases_dir);
d = d([d.isdir]);
names = {d.name};
mask = ~strcmp(names, '.') & ~strcmp(names, '..') & ...
       ~cellfun(@isempty, regexp(names, '^m[0-9p\.]+', 'once'));

candidate_cases = sort(names(mask));
keep_case = cellfun(@(name) isfile(fullfile(cases_dir, name, required_file)), candidate_cases);
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
