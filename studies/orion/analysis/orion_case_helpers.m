function helpers = orion_case_helpers()
helpers.resolve_script_dir = @resolve_script_dir;
helpers.discover_cases = @discover_cases;
helpers.case_selection_menu = @case_selection_menu;
helpers.choose_case_interactively = @choose_case_interactively;
helpers.parse_case_name = @parse_case_name;
helpers.format_case_label = @format_case_label;
helpers.mach_field_name = @mach_field_name;
end


function script_dir = resolve_script_dir()
script_path = mfilename('fullpath');
if isempty(script_path)
    script_dir = pwd;
else
    script_dir = fileparts(script_path);
end
end


function case_names = discover_cases(cases_dir, required_files)
if ischar(required_files) || isstring(required_files)
    required_files = cellstr(required_files);
end

d = dir(cases_dir);
d = d([d.isdir]);
names = {d.name};
mask = ~strcmp(names, '.') & ~strcmp(names, '..') & ...
       ~cellfun(@isempty, regexp(names, '^m[0-9p\.]+', 'once'));

candidate_cases = sort(names(mask));
keep_case = false(size(candidate_cases));
for idx = 1:numel(candidate_cases)
    case_dir = fullfile(cases_dir, candidate_cases{idx});
    keep_case(idx) = all(cellfun(@(name) isfile(fullfile(case_dir, name)), required_files));
end
case_names = candidate_cases(keep_case);
end


function selected = case_selection_menu(all_cases, action_label)
if nargin < 2 || strlength(string(action_label)) == 0
    action_label = "case group";
end

mach_map  = group_by_mach(all_cases);
mach_keys = fieldnames(mach_map);
mach_nums = cellfun(@(key) mach_map.(key).M_val, mach_keys);
[~, si]   = sort(mach_nums);
mach_keys = mach_keys(si);

max_menu_items = 3 * numel(mach_keys) + 4;
menu_labels = cell(max_menu_items, 1);
menu_cases  = cell(max_menu_items, 1);
idx = 0;

fprintf('\nSelect %s:\n\n', char(action_label));

for m = 1:numel(mach_keys)
    mach_info = mach_map.(mach_keys{m});
    mach      = mach_info.label;
    cases     = mach_info.cases;
    aoa_cases = cases(contains(cases, '_aoa'));
    ref_cases = cases(cellfun(@(c) any(contains(c, ...
        {'_coarse', '_medium', '_fine', '_very_fine'})), cases));

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
    {'_coarse', '_medium', '_fine', '_very_fine'})), all_cases));

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


function case_name = choose_case_interactively(cases_dir, required_files, action_label)
if nargin < 3 || strlength(string(action_label)) == 0
    action_label = "plotting";
end

case_names = discover_cases(cases_dir, required_files);
if isempty(case_names)
    if ischar(required_files) || isstring(required_files)
        files_label = strjoin(cellstr(required_files), ', ');
    else
        files_label = strjoin(required_files, ', ');
    end
    error('No case folders with %s found in %s.', files_label, cases_dir);
end

fprintf('\nSelect case for %s:\n\n', char(action_label));
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

tok = regexp(case_name, '^m([0-9p\.]+)_(coarse|medium|fine|very_fine)$', 'tokens', 'once');
if ~isempty(tok)
    info.M_val         = str2double(strrep(tok{1}, 'p', '.'));
    info.mesh_level    = tok{2};
    info.mesh_level(1) = upper(info.mesh_level(1));
    info.is_refinement = true;
    info.label         = sprintf('$M = %.1f$ (%s mesh)', info.M_val, info.mesh_level);
end
end


function case_label = format_case_label(case_name)
info = parse_case_name(case_name);
case_label = info.label;
end


function field_name = mach_field_name(M_val)
field_name = ['m_' regexprep(sprintf('%.12g', M_val), '[^0-9A-Za-z]', '_')];
end


function label = mach_display_name(M_val)
label = ['m' sprintf('%.12g', M_val)];
end
