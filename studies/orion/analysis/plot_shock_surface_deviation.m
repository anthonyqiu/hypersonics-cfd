clear; clc; close all;

helpers      = orion_case_helpers();
analysis_dir = helpers.resolve_script_dir();
study_dir    = fileparts(analysis_dir);
csv_path     = fullfile(study_dir, 'data', 'shock_surface_deviation_refinement.csv');
metric_name  = 'common_rms_over_D';

set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter',        'latex');
set(groot, 'defaultTextInterpreter',          'latex');

if ~isfile(csv_path)
    error(['Surface-deviation CSV not found: %s\n' ...
        'Run: python3 scripts/compare_shock_surfaces.py'], csv_path);
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

comparison_labels = {'coarse-medium', 'medium-fine', 'fine-very\_fine'};
x = 1:numel(comparison_labels);

for m = 1:numel(mach_values)
    mach = mach_values(m);
    Tm = T(string(T.mach) == mach, :);
    y = nan(size(x));

    for k = 1:numel(comparison_labels)
        row = Tm(string(Tm.comparison) == strrep(comparison_labels{k}, '\_', '_'), :);
        if ~isempty(row)
            y(k) = row.(metric_name)(1);
        end
    end

    if any(isfinite(y))
        plot(x, y, '-o', 'Color', colors(m, :), 'LineWidth', 1.6, ...
            'MarkerFaceColor', colors(m, :), 'DisplayName', mach_label(mach));
    end
end

set(gca, 'XTick', x, 'XTickLabel', comparison_labels, 'FontSize', 12);
xlabel('Adjacent refinement pair', 'FontSize', 14);
ylabel('$E_{\mathrm{RMS}} / D$', 'FontSize', 14);
title('Common-Support Shock-Surface Deviation', 'FontSize', 16);
legend('Location', 'bestoutside', 'FontSize', 11);

%% Adjacent stand-off-distance differences
figure('Color', 'w');
hold on; grid on; box on;

for m = 1:numel(mach_values)
    mach = mach_values(m);
    Tm = T(string(T.mach) == mach, :);
    y = nan(size(x));

    for k = 1:numel(comparison_labels)
        row = Tm(string(Tm.comparison) == strrep(comparison_labels{k}, '\_', '_'), :);
        if ~isempty(row)
            y(k) = row.standoff_difference_over_D(1);
        end
    end

    if any(isfinite(y))
        plot(x, y, '-o', 'Color', colors(m, :), 'LineWidth', 1.6, ...
            'MarkerFaceColor', colors(m, :), 'DisplayName', mach_label(mach));
    end
end

set(gca, 'XTick', x, 'XTickLabel', comparison_labels, 'FontSize', 12);
xlabel('Adjacent refinement pair', 'FontSize', 14);
ylabel('$|\Delta_A-\Delta_B| / D$', 'FontSize', 14);
title('Stagnation Stand-Off Difference', 'FontSize', 16);
legend('Location', 'bestoutside', 'FontSize', 11);

function label = mach_label(mach)
clean = strrep(char(mach), 'p', '.');
label = sprintf('$M = %s$', clean);
end
