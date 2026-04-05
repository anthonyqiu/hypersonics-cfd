clear; clc; close all;

analysis_dir    = resolve_script_dir();
study_dir       = fileparts(analysis_dir);
cases_dir       = fullfile(study_dir, 'data', 'cases');
geometry_file   = fullfile(study_dir, 'geometry', 'orion_profile_xy.csv');
x_shift_orion   = 0.71;
x_shift_shock   = -0.133080166111 + 0.133080166111;
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

all_cases = discover_cases(cases_dir, required_file);
if isempty(all_cases)
    error(['No case folders with %s found in %s\n' ...
        'Pull shock surface files with pull_cluster_results.sh using option 3, 4, 6, or 7.'], ...
        required_file, cases_dir);
end

%% SHOW MENU
selected = case_selection_menu(all_cases, plot_mode);
if isempty(selected)
    disp('No cases selected. Exiting.');
    return;
end

%% PLOT
switch plot_mode
    case '2D'
        plot_shocks_2d( ...
            selected, cases_dir, geometry_file, x_shift_orion, x_shift_shock, ...
            R_stag, profile_bins_2d, plot_orion_2d);
    case '3D'
        plot_shocks_3d(selected, cases_dir, geometry_file, plot_orion_3d);
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

function selected = case_selection_menu(all_cases, plot_mode)
    mach_map  = group_by_mach(all_cases);
    mach_keys = fieldnames(mach_map);
    mach_nums = cellfun(@(key) mach_map.(key).M_val, mach_keys);
    [~, si]   = sort(mach_nums);
    mach_keys = mach_keys(si);

    max_menu_items = 3 * numel(mach_keys) + 4;
    menu_labels = cell(max_menu_items, 1);
    menu_cases  = cell(max_menu_items, 1);
    idx = 0;

    fprintf('\nSelect %s case group to plot:\n\n', plot_mode);

    for m = 1:numel(mach_keys)
        mach_info = mach_map.(mach_keys{m});
        mach      = mach_info.label;
        cases     = mach_info.cases;
        aoa_cases = cases(contains(cases, '_aoa'));
        ref_cases = cases(cellfun(@(c) any(contains(c, {'_coarse', '_medium', '_fine'})), cases));

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
    all_ref = all_cases(cellfun(@(c) any(contains(c, {'_coarse', '_medium', '_fine'})), all_cases));

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
    fprintf('  %2d) Custom (type case name)\n\n', idx);
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

function plot_shocks_2d(selected, cases_dir, geometry_file, x_shift_orion, x_shift_shock, R_stag, profile_bins, plot_orion)
    figure('Color', 'w');
    hold on; grid on; box on;

    colors = lines(numel(selected));
    plot_billig = is_refinement_selection(selected);

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
        x_profile = x_profile + x_shift_shock;

        info = parse_case_name(case_name);
        col_k = colors(k, :);

        idx = idx + 1;
        h(idx) = plot(x_profile,  r_profile, '-', 'LineWidth', 1.4, 'Color', col_k);
        plot(x_profile, -r_profile, '-', 'LineWidth', 1.4, 'Color', col_k, 'HandleVisibility', 'off');
        leg_text{idx} = sprintf('%s (CFD)', info.label);

        if plot_billig && info.is_refinement && ~isnan(info.M_val)
            mach_field = mach_field_name(info.M_val);
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
            xg    = geo(:, 1) + x_shift_orion;
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

function plot_shocks_3d(selected, cases_dir, geometry_file, plot_orion)
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
        info = parse_case_name(case_name);
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

function info = parse_case_name(case_name)
    info = struct( ...
        'M_val', NaN, ...
        'AOA_val', NaN, ...
        'mesh_level', '', ...
        'is_aoa', false, ...
        'is_refinement', false, ...
        'label', strrep(case_name, '_', '\_'));

    tok = regexp(case_name, '^m([0-9p\.]+)_aoa([0-9\-\.]+)$', 'tokens', 'once');
    if ~isempty(tok)
        info.M_val   = str2double(strrep(tok{1}, 'p', '.'));
        info.AOA_val = str2double(strrep(tok{2}, 'p', '.'));
        info.is_aoa  = true;
        info.label   = sprintf('$M = %.1f$, $\\mathrm{AoA} = %.0f^{\\circ}$', info.M_val, info.AOA_val);
        return;
    end

    tok = regexp(case_name, '^m([0-9p\.]+)_(coarse|medium|fine)$', 'tokens', 'once');
    if ~isempty(tok)
        info.M_val         = str2double(strrep(tok{1}, 'p', '.'));
        info.mesh_level    = tok{2};
        info.mesh_level(1) = upper(info.mesh_level(1));
        info.is_refinement = true;
        info.label         = sprintf('$M = %.1f$ (%s mesh)', info.M_val, info.mesh_level);
    end
end

function tf = is_refinement_selection(cases)
    tf = ~isempty(cases);
    for k = 1:numel(cases)
        info = parse_case_name(cases{k});
        if ~info.is_refinement
            tf = false;
            return;
        end
    end
end

function field_name = mach_field_name(M_val)
    field_name = ['m_' regexprep(sprintf('%.12g', M_val), '[^0-9A-Za-z]', '_')];
end

function label = mach_display_name(M_val)
    label = ['m' sprintf('%.12g', M_val)];
end

function x_out = get_billig(y_in, M_inf, R_stag)
    delta  = 0.143 * R_stag * exp(3.24 / M_inf^2);
    R_curv = 1.143 * R_stag * exp(0.54 / (M_inf - 1)^1.2);
    theta  = asin(1 / M_inf);
    x_out  = R_stag + delta ...
           - R_curv * cot(theta)^2 .* ...
             (sqrt(1 + (y_in.^2 * tan(theta)^2) / R_curv^2) - 1);
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
