clear; clc; close all;

helpers         = orion_case_helpers();
analysis_dir    = helpers.resolve_script_dir();
study_dir       = fileparts(analysis_dir);
cases_dir       = fullfile(study_dir, 'data', 'cases');
geometry_file   = fullfile(study_dir, 'geometry', 'orion_profile_xy.csv');
R_stag          = 6;
plot_orion_2d   = true;
plot_orion_3d   = false;
profile_bins_2d = 120;
required_file   = 'shock_surface.csv';

set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter',        'latex');
set(groot, 'defaultTextInterpreter',          'latex');

%% SELECT PLOT MODE
plot_mode = dimension_selection_menu();

%% DISCOVER CASES
if ~isfolder(cases_dir)
    error(['Cases directory not found: %s\n' ...
        'Run pull_cluster_results.sh first so results land under studies/orion/data/cases.'], cases_dir);
end

all_cases = helpers.discover_cases(cases_dir, required_file);
if isempty(all_cases)
    error(['No case folders with %s found in %s\n' ...
        'Pull shock surface files with pull_cluster_results.sh using option 3, 4, 6, or 7.'], ...
        required_file, cases_dir);
end

%% SHOW MENU
selected = helpers.case_selection_menu(all_cases, sprintf('%s case group to plot', plot_mode));
if isempty(selected)
    disp('No cases selected. Exiting.');
    return;
end

%% PLOT
switch plot_mode
    case '2D'
        plot_shocks_2d( ...
            selected, cases_dir, geometry_file, R_stag, profile_bins_2d, plot_orion_2d, helpers);
    case '3D'
        plot_shocks_3d(selected, cases_dir, geometry_file, plot_orion_3d, helpers);
    otherwise
        error('Unsupported plot mode: %s', plot_mode);
end


function plot_mode = dimension_selection_menu()
    fprintf('\nPlot shocks in:\n\n');
    fprintf('   1) 2D profile from shock_surface.csv\n');
    fprintf('   2) 3D shock surface from shock_surface.csv\n\n');

    choice = strtrim(input('Dimension [1-2]: ', 's'));
    switch lower(choice)
        case {'1', '2d', '2-d'}
            plot_mode = '2D';
        case {'2', '3d', '3-d'}
            plot_mode = '3D';
        otherwise
            error('Invalid dimension choice.');
    end
end

function plot_shocks_2d(selected, cases_dir, geometry_file, R_stag, profile_bins, plot_orion, helpers)
    figure('Color', 'w');
    hold on; grid on; box on;

    colors = lines(numel(selected));
    plot_billig = is_refinement_selection(selected, helpers);

    max_curves = 2 * numel(selected) + 1;
    h        = gobjects(max_curves, 1);
    leg_text = repmat({''}, max_curves, 1);
    idx = 0;
    billig_ranges = struct();

    for k = 1:numel(selected)
        case_name = selected{k};
        csv_path  = fullfile(cases_dir, case_name, 'shock_surface.csv');

        if ~isfile(csv_path)
            warning('shock_surface.csv not found for case: %s', case_name);
            continue;
        end

        surface_data = load_shock_surface(csv_path);
        [x_profile, r_profile] = extract_surface_profile(surface_data, profile_bins);

        info = helpers.parse_case_name(case_name);
        col_k = colors(k, :);

        idx = idx + 1;
        h(idx) = plot(x_profile,  r_profile, '-', 'LineWidth', 1.4, 'Color', col_k);
        plot(x_profile, -r_profile, '-', 'LineWidth', 1.4, 'Color', col_k, 'HandleVisibility', 'off');
        leg_text{idx} = sprintf('%s (CFD)', info.label);

        if plot_billig && info.is_refinement && ~isnan(info.M_val)
            mach_field = helpers.mach_field_name(info.M_val);
            r_max = max(r_profile);
            if ~isfield(billig_ranges, mach_field)
                billig_ranges.(mach_field) = struct('M_val', info.M_val, 'r_max', r_max);
            else
                billig_ranges.(mach_field).r_max = max(billig_ranges.(mach_field).r_max, r_max);
            end
        end
    end

    if plot_billig
        billig_fields = fieldnames(billig_ranges);
        billig_mach   = zeros(numel(billig_fields), 1);
        for b = 1:numel(billig_fields)
            billig_mach(b) = billig_ranges.(billig_fields{b}).M_val;
        end
        [~, order]    = sort(billig_mach);
        billig_fields = billig_fields(order);

        for b = 1:numel(billig_fields)
            billig_info = billig_ranges.(billig_fields{b});
            y_billig = linspace(-billig_info.r_max, billig_info.r_max, 400).';
            x_billig = get_billig(y_billig, billig_info.M_val, R_stag);
            x_billig = -x_billig + R_stag;

            idx = idx + 1;
            h(idx) = plot(x_billig, y_billig, 'k--', 'LineWidth', 1.5);
            leg_text{idx} = sprintf('$M = %.1f$ (Billig''s)', billig_info.M_val);
        end
    end

    if plot_orion
        try
            geo   = readmatrix(geometry_file);
            xg    = geo(:, 1);
            yg    = geo(:, 2);
            cx    = mean(xg);
            cy    = mean(yg);
            theta = atan2(yg - cy, xg - cx);
            [~, idx_sort] = sort(theta);
            xg = xg(idx_sort);
            yg = yg(idx_sort);
            xg = [xg; xg(1)];
            yg = [yg; yg(1)];

            idx = idx + 1;
            h(idx) = plot(xg, yg, 'k-', 'LineWidth', 2.0);
            leg_text{idx} = 'Orion';
        catch ME
            warning(ME.identifier, '%s', ME.message);
        end
    end

    if idx == 0
        error('No 2D shock data could be plotted for the selected cases.');
    end

    h        = h(1:idx);
    leg_text = leg_text(1:idx);

    xlabel('$x$ (m)', 'FontSize', 14);
    ylabel('$\pm r$ (m)', 'FontSize', 14);
    title('2D Shock Profiles From Shock Surface', 'FontSize', 16);
    axis equal;
    legend(h, leg_text, 'Location', 'bestoutside', 'FontSize', 12);
    set(gca, 'FontSize', 13);
end

function plot_shocks_3d(selected, cases_dir, geometry_file, plot_orion, helpers)
    figure('Color', 'w');
    hold on; grid on; box on;

    colors = lines(numel(selected));
    max_objects = numel(selected) + 1;
    h        = gobjects(max_objects, 1);
    leg_text = repmat({''}, max_objects, 1);
    idx = 0;
    xyz_limits = empty_limits_3d();

    if isscalar(selected)
        point_size = 14;
        point_alpha = 0.58;
    else
        point_size = 9;
        point_alpha = 0.44;
    end

    for k = 1:numel(selected)
        case_name = selected{k};
        csv_path  = fullfile(cases_dir, case_name, 'shock_surface.csv');

        if ~isfile(csv_path)
            warning('shock_surface.csv not found for case: %s', case_name);
            continue;
        end

        surface_data = load_shock_surface(csv_path);
        info = helpers.parse_case_name(case_name);
        col_k = colors(k, :);
        xyz_limits = expand_limits_3d(xyz_limits, surface_data.x, surface_data.y, surface_data.z);

        idx = idx + 1;
        h(idx) = scatter3(surface_data.x, surface_data.y, surface_data.z, point_size, ...
            repmat(col_k, numel(surface_data.x), 1), ...
            'filled', ...
            'MarkerFaceAlpha', point_alpha, ...
            'MarkerEdgeAlpha', 0.10);
        leg_text{idx} = info.label;
    end

    if plot_orion
        try
            [Xg, Yg, Zg] = make_orion_surface(geometry_file);
            xyz_limits = expand_limits_3d(xyz_limits, Xg, Yg, Zg);
            idx = idx + 1;
            h(idx) = surf(Xg, Yg, Zg, ...
                'FaceColor', [0.20, 0.20, 0.20], ...
                'FaceAlpha', 0.16, ...
                'EdgeColor', 'none');
            leg_text{idx} = 'Orion';
        catch ME
            warning(ME.identifier, '%s', ME.message);
        end
    end

    if idx == 0
        error('No 3D shock data could be plotted for the selected cases.');
    end

    h        = h(1:idx);
    leg_text = leg_text(1:idx);

    xlabel('$x$ (m)', 'FontSize', 14);
    ylabel('$y$ (m)', 'FontSize', 14);
    zlabel('$z$ (m)', 'FontSize', 14);
    title('3D Shock Points', 'FontSize', 16);
    apply_cube_axes_3d(gca, xyz_limits, 0.06);
    view(3);
    rotate3d on;
    camlight('headlight');
    lighting gouraud;
    legend(h, leg_text, 'Location', 'bestoutside', 'FontSize', 12);
    set(gca, 'FontSize', 13);
end

function surface_data = load_shock_surface(csv_path)
    tbl = readtable(csv_path, 'VariableNamingRule', 'preserve');
    variable_names = string(tbl.Properties.VariableNames);
    required_xyz = ["x", "y", "z"];

    if ~all(ismember(required_xyz, variable_names))
        error('shock_surface.csv must contain x, y, and z columns.');
    end

    if ismember("radius_yz", variable_names)
        radius = double(tbl.radius_yz);
    else
        radius = hypot(double(tbl.y), double(tbl.z));
    end

    surface_data = struct( ...
        'x', double(tbl.x), ...
        'y', double(tbl.y), ...
        'z', double(tbl.z), ...
        'radius', radius);
end

function [x_profile, r_profile] = extract_surface_profile(surface_data, num_bins)
    x = surface_data.x(:);
    r = surface_data.radius(:);
    valid = isfinite(x) & isfinite(r);
    x = x(valid);
    r = r(valid);

    if isempty(x)
        error('shock_surface.csv did not contain any valid points.');
    end

    if max(x) == min(x)
        x_profile = x(1);
        r_profile = max(r);
        return;
    end

    num_bins = max(24, min(num_bins, numel(x)));
    edges = linspace(min(x), max(x), num_bins + 1);
    bin_idx = discretize(x, edges);
    valid = ~isnan(bin_idx);
    x = x(valid);
    r = r(valid);
    bin_idx = bin_idx(valid);

    x_profile = accumarray(bin_idx, x, [num_bins, 1], @mean, NaN);
    r_profile = accumarray(bin_idx, r, [num_bins, 1], @max, NaN);

    valid = isfinite(x_profile) & isfinite(r_profile);
    x_profile = x_profile(valid);
    r_profile = r_profile(valid);
end

function [Xg, Yg, Zg] = make_orion_surface(geometry_file)
    geo = readmatrix(geometry_file);
    x = geo(:, 1);
    r = abs(geo(:, 2));

    [x_unique, ~, ic] = uniquetol(x, 1e-9, 'DataScale', 1);
    r_profile = accumarray(ic, r, [], @max);
    [x_profile, order] = sort(x_unique);
    r_profile = r_profile(order);

    theta = linspace(0, 2 * pi, 120);
    [theta_grid, x_grid] = meshgrid(theta, x_profile);
    r_grid = repmat(r_profile(:), 1, numel(theta));

    Xg = x_grid;
    Yg = r_grid .* cos(theta_grid);
    Zg = r_grid .* sin(theta_grid);
end

function limits = empty_limits_3d()
    limits = [Inf, -Inf; Inf, -Inf; Inf, -Inf];
end

function limits = expand_limits_3d(limits, x, y, z)
    values = {x(:), y(:), z(:)};
    for k = 1:3
        v = values{k};
        v = v(isfinite(v));
        if isempty(v)
            continue;
        end
        limits(k, 1) = min(limits(k, 1), min(v));
        limits(k, 2) = max(limits(k, 2), max(v));
    end
end

function apply_cube_axes_3d(ax, limits, padding_fraction)
    if nargin < 3
        padding_fraction = 0.05;
    end

    if any(~isfinite(limits(:)))
        axis(ax, 'equal');
        pbaspect(ax, [1, 1, 1]);
        return;
    end

    centers = mean(limits, 2);
    spans = limits(:, 2) - limits(:, 1);
    max_span = max(spans);
    if ~(isfinite(max_span) && max_span > 0)
        max_span = 1;
    end

    half_span = 0.5 * max_span * (1 + padding_fraction);
    xlim(ax, centers(1) + [-half_span, half_span]);
    ylim(ax, centers(2) + [-half_span, half_span]);
    zlim(ax, centers(3) + [-half_span, half_span]);

    daspect(ax, [1, 1, 1]);
    pbaspect(ax, [1, 1, 1]);
end

function tf = is_refinement_selection(cases, helpers)
    tf = ~isempty(cases);
    for k = 1:numel(cases)
        info = helpers.parse_case_name(cases{k});
        if ~info.is_refinement
            tf = false;
            return;
        end
    end
end

function x_out = get_billig(y_in, M_inf, R_stag)
    delta  = 0.143 * R_stag * exp(3.24 / M_inf^2);
    R_curv = 1.143 * R_stag * exp(0.54 / (M_inf - 1)^1.2);
    theta  = asin(1 / M_inf);
    x_out  = R_stag + delta ...
           - R_curv * cot(theta)^2 .* ...
             (sqrt(1 + (y_in.^2 * tan(theta)^2) / R_curv^2) - 1);
end
