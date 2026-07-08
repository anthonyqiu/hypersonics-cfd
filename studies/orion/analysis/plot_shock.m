clear; clc; close all;

helpers         = orion_case_helpers();
analysis_dir    = helpers.resolve_script_dir();
study_dir       = fileparts(analysis_dir);
cases_dir       = fullfile(study_dir, 'data', 'cases');
geometry_file   = fullfile(study_dir, 'geometry', 'orion_profile_xy.csv');
plot_orion_2d   = true;
plot_orion_3d   = true;
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
        plot_shocks_2d(selected, cases_dir, geometry_file, plot_orion_2d, helpers);
    case '3D'
        plot_shocks_3d(selected, cases_dir, geometry_file, plot_orion_3d, helpers);
    otherwise
        error('Unsupported plot mode: %s', plot_mode);
end


function plot_mode = dimension_selection_menu()
    fprintf('\nPlot shocks in:\n\n');
    fprintf('   1) 2D y = 0 symmetry-plane profile from shock_surface.csv\n');
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

function plot_shocks_2d(selected, cases_dir, geometry_file, plot_orion, helpers)
    figure('Color', 'w');
    hold on; grid on; box on;

    colors = lines(numel(selected));

    max_curves = numel(selected) + 1;
    h        = gobjects(max_curves, 1);
    leg_text = repmat({''}, max_curves, 1);
    idx = 0;
    shock_count = 0;

    for k = 1:numel(selected)
        case_name = selected{k};
        csv_path  = fullfile(cases_dir, case_name, 'shock_surface.csv');

        if ~isfile(csv_path)
            warning('shock_surface.csv not found for case: %s', case_name);
            continue;
        end

        surface_data = load_shock_surface(csv_path);
        [x_profile, z_profile, y_tolerance] = extract_y0_profile(surface_data);

        info = helpers.parse_case_name(case_name);
        col_k = colors(k, :);

        idx = idx + 1;
        h(idx) = plot(x_profile, z_profile, '-', ...
            'LineWidth', 1.5, ...
            'Marker', '.', ...
            'MarkerSize', 8, ...
            'Color', col_k);
        leg_text{idx} = sprintf('%s (CFD)', info.label);
        shock_count = shock_count + 1;

        if y_tolerance > 1e-9
            fprintf('%s: used |y| <= %.3g m for the symmetry-plane profile.\n', ...
                case_name, y_tolerance);
        end
    end

    if plot_orion
        try
            [xg, zg] = load_orion_profile_2d(geometry_file);

            idx = idx + 1;
            h(idx) = plot(xg, zg, 'k-', 'LineWidth', 2.0);
            leg_text{idx} = 'Orion';
        catch ME
            warning(ME.identifier, '%s', ME.message);
        end
    end

    if shock_count == 0
        error('No 2D shock data could be plotted for the selected cases.');
    end

    h        = h(1:idx);
    leg_text = leg_text(1:idx);

    xlabel('$x$ (m)', 'FontSize', 14);
    ylabel('$z$ at $y=0$ (m)', 'FontSize', 14);
    title('Shock and Orion Profiles on the $y = 0$ Plane', 'FontSize', 16);
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
    shock_count = 0;
    xyz_limits = empty_limits_3d();

    if isscalar(selected)
        point_size = 10;
        point_alpha = 0.50;
    else
        point_size = 6;
        point_alpha = 0.28;
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
        shock_count = shock_count + 1;
    end

    if plot_orion
        try
            [Xg, Yg, Zg] = make_orion_surface(geometry_file);
            xyz_limits = expand_limits_3d(xyz_limits, Xg, Yg, Zg);
            idx = idx + 1;
            h(idx) = surf(Xg, Yg, Zg, ...
                'FaceColor', [0.42, 0.42, 0.42], ...
                'FaceAlpha', 0.42, ...
                'EdgeColor', [0.18, 0.18, 0.18], ...
                'EdgeAlpha', 0.08);
            leg_text{idx} = 'Orion';

            [x_body, z_body] = load_orion_profile_2d(geometry_file);
            plot3(x_body, zeros(size(x_body)), z_body, ...
                'k-', 'LineWidth', 1.6, 'HandleVisibility', 'off');
            plot3(x_body, z_body, zeros(size(x_body)), ...
                'k-', 'LineWidth', 1.0, 'HandleVisibility', 'off');
        catch ME
            warning(ME.identifier, '%s', ME.message);
        end
    end

    if shock_count == 0
        error('No 3D shock data could be plotted for the selected cases.');
    end

    h        = h(1:idx);
    leg_text = leg_text(1:idx);

    xlabel('$x$ (m)', 'FontSize', 14);
    ylabel('$y$ (m)', 'FontSize', 14);
    zlabel('$z$ (m)', 'FontSize', 14);
    title('3D Shock Surface Points and Orion Body', 'FontSize', 16);
    apply_cube_axes_3d(gca, xyz_limits, 0.06);
    view(45, 22);
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

function [x_profile, z_profile, y_tolerance] = extract_y0_profile(surface_data)
    x = surface_data.x(:);
    y = surface_data.y(:);
    z = surface_data.z(:);
    valid = isfinite(x) & isfinite(y) & isfinite(z);
    x = x(valid);
    y = y(valid);
    z = z(valid);

    if isempty(x)
        error('shock_surface.csv did not contain any valid points.');
    end

    y_tolerance = 1e-9;
    mask = abs(y) <= y_tolerance;

    if nnz(mask) < 3
        sorted_abs_y = sort(abs(y));
        target_count = min(numel(sorted_abs_y), max(3, ceil(0.002 * numel(sorted_abs_y))));
        y_tolerance = max(y_tolerance, sorted_abs_y(target_count));
        mask = abs(y) <= y_tolerance;
    end

    if nnz(mask) < 3
        error('Could not find enough shock-surface points near y = 0.');
    end

    x_profile = x(mask);
    z_profile = z(mask);

    [z_profile, order] = sort(z_profile);
    x_profile = x_profile(order);
end

function [x_profile, z_profile] = load_orion_profile_2d(geometry_file)
    geo = readmatrix(geometry_file);
    if size(geo, 2) < 2
        error('Orion profile file must contain at least two columns: x and profile coordinate.');
    end

    x_profile = geo(:, 1);
    z_profile = geo(:, 2);
    valid = isfinite(x_profile) & isfinite(z_profile);
    x_profile = x_profile(valid);
    z_profile = z_profile(valid);

    if isempty(x_profile)
        error('Orion profile file did not contain valid profile points.');
    end

    if x_profile(1) ~= x_profile(end) || z_profile(1) ~= z_profile(end)
        x_profile = [x_profile; x_profile(1)];
        z_profile = [z_profile; z_profile(1)];
    end
end

function [Xg, Yg, Zg] = make_orion_surface(geometry_file)
    [x, profile_coordinate] = load_orion_profile_2d(geometry_file);
    r = abs(profile_coordinate);

    valid = isfinite(x) & isfinite(r);
    x = x(valid);
    r = r(valid);
    if isempty(x)
        error('Orion profile file did not contain valid points for revolution.');
    end

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
