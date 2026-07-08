clear; clc; close all;

helpers      = orion_case_helpers();
analysis_dir = helpers.resolve_script_dir();
study_dir    = fileparts(analysis_dir);
csv_path     = fullfile(study_dir, 'data', 'shock_surface_deviation_refinement.csv');
metric_name  = 'symmetric_rms_over_D';
mesh_levels  = {'coarse', 'medium', 'fine', 'very_fine'};

set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter',        'latex');
set(groot, 'defaultTextInterpreter',          'latex');

if ~isfile(csv_path)
    error(['Surface-deviation CSV not found: %s\n' ...
        'Run: python3 scripts/compare_shock_surfaces.py --study orion'], csv_path);
end

opts = detectImportOptions(csv_path, 'FileType', 'text', 'TextType', 'string');
text_vars = {'mach', 'case_a', 'mesh_level_a', 'case_b', ...
    'mesh_level_b', 'comparison', 'is_adjacent', 'status'};
opts = setvartype(opts, text_vars, 'string');
T = readtable(csv_path, opts);
if isempty(T)
    error('Surface-deviation CSV is empty: %s', csv_path);
end

ok = string(T.status) == "ok";
T = T(ok, :);
if isempty(T)
    error('No successful surface-deviation comparisons found in %s.', csv_path);
end

mach_values = unique(string(T.mach), 'stable');
colors = lines(numel(mach_values));

%% Adjacent refinement differences
figure('Color', 'w');
hold on; grid on; box on;

adjacent_labels = {'coarse-medium', 'medium-fine', 'fine-very\_fine'};
x = 1:numel(adjacent_labels);

for m = 1:numel(mach_values)
    mach = mach_values(m);
    Tm = T(string(T.mach) == mach & string(T.is_adjacent) == "true", :);
    y = nan(size(x));

    for k = 1:numel(adjacent_labels)
        row = Tm(string(Tm.comparison) == strrep(adjacent_labels{k}, '\_', '_'), :);
        if ~isempty(row)
            y(k) = row.(metric_name)(1);
        end
    end

    if any(isfinite(y))
        plot(x, y, '-o', 'Color', colors(m, :), 'LineWidth', 1.6, ...
            'MarkerFaceColor', colors(m, :), 'DisplayName', mach_label(mach));
    end
end

set(gca, 'XTick', x, 'XTickLabel', adjacent_labels, 'FontSize', 12);
xlabel('Adjacent refinement pair', 'FontSize', 14);
ylabel('$E_{\mathrm{RMS}} / D$', 'FontSize', 14);
title('Adjacent Shock-Surface Deviation', 'FontSize', 16);
legend('Location', 'bestoutside', 'FontSize', 11);

%% Full pairwise matrix
figure('Color', 'w');
tiledlayout(numel(mach_values), 1, 'TileSpacing', 'compact', 'Padding', 'compact');

for m = 1:numel(mach_values)
    mach = mach_values(m);
    Tm = T(string(T.mach) == mach, :);
    matrix = nan(numel(mesh_levels));

    for r = 1:height(Tm)
        ia = find(strcmp(mesh_levels, char(Tm.mesh_level_a(r))), 1);
        ib = find(strcmp(mesh_levels, char(Tm.mesh_level_b(r))), 1);
        if isempty(ia) || isempty(ib)
            continue;
        end
        value = Tm.(metric_name)(r);
        matrix(ia, ib) = value;
        matrix(ib, ia) = value;
    end
    matrix(1:numel(mesh_levels)+1:end) = 0;

    nexttile;
    imagesc(matrix);
    axis equal tight;
    colorbar;
    title(sprintf('%s Pairwise Shock-Surface Deviation', mach_label(mach)), 'FontSize', 14);
    set(gca, ...
        'XTick', 1:numel(mesh_levels), ...
        'YTick', 1:numel(mesh_levels), ...
        'XTickLabel', display_mesh_levels(mesh_levels), ...
        'YTickLabel', display_mesh_levels(mesh_levels), ...
        'FontSize', 11);
    xtickangle(30);
end

function label = mach_label(mach)
clean = strrep(char(mach), 'p', '.');
label = sprintf('$M = %s$', clean);
end

function labels = display_mesh_levels(levels)
labels = strrep(levels, '_', '\_');
end
