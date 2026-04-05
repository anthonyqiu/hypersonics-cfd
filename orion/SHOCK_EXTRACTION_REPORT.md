# Shock Extraction Methods Report

This document explains the two current 3D shock-surface extraction methods in this repository:

1. `scripts/extract_shock_surface.py`
2. `scripts/extract_shock_surface_rectangular.py`

It also explains the shared geometry helper:

3. `scripts/shock_geometry.py`

This report is written against the current code snapshot in this repository on `2026-03-29`. The line numbers below match the code at the time this report was written. If the code changes later, the function names and ideas should still be useful, but some exact line references may drift.

---

## 1. High-Level Overview

Both methods are based on the same physical idea:

- Use the **density field** as the primary flow quantity.
- Compute the **3D density gradient** and use its magnitude as a **shock sensor**.
- Search for a shock point on a family of 1D **node lines**.
- Build a surface from the accepted shock points.

The main difference between the methods is how the node lines are organized.

### 1.1 Rectangular Node-Line Method

File: `scripts/extract_shock_surface_rectangular.py`

Core idea:

- Build a structured rectangular grid in the transverse plane of the body.
- For each transverse location, create a **streamwise node line**.
- On each node line, find the first meaningful local peak of the shock sensor.
- Start from the center node line and move outward in **square-shell order**.
- Accept a candidate only if it stays connected to already accepted neighboring shock points.

This method is easier to reason about and debug because the node lines live on a shared structured grid. Its main weakness is that every node line is parallel to the streamwise direction, which may not align well with the true shock normal away from the stagnation region.

### 1.2 Panel / Surface-Coordinate Method

File: `scripts/extract_shock_surface.py`

Core idea:

- Start with the stagnation node line only.
- Then propagate outward in **surface coordinates**:
  - `dt` = tangent spacing between shells / rays
  - `dn` = normal spacing along each node line
- First shell uses streamwise node lines.
- Later shells use a **panel-fit predictor** built from previously accepted shock nodes along each ray.
- Use a predictor-corrector step to better align the node line with the local shock normal.
- Stop when an entire shell has no accepted shock nodes.

This method is more adaptive and more physically aligned with the evolving shock geometry, but it is also more path-dependent and algorithmically more complex.

### 1.3 Shared AoA-Aware Geometry

File: `scripts/shock_geometry.py`

Both methods now use a common AoA-aware coordinate system:

- `streamwise`
- `pitch_normal`
- `spanwise`

That means the stagnation node line is no longer assumed to lie along the global `x` axis. Instead, it is assumed to pass through the origin and align with the case angle of attack.

---

## 2. Shared Geometry Helper

File: `scripts/shock_geometry.py`

This file contains the coordinate-frame logic that both extractors depend on.

### 2.1 File-Level Constants

#### `AOA_LINE_RE` at line 11

- Looks for a line like `AOA = 15.0` inside a config file.
- Used when the code wants to recover the actual AoA from a generated case config.

#### `AOA_NAME_RE` at line 12

- Looks for `_aoa15`, `_aoa24`, etc. in a case folder name.
- Acts as a fallback when the config is missing or does not contain an AoA line.

### 2.2 `parse_case_aoa_from_text()` at lines 15-20

Purpose:

- Scan config text and return the first AoA value found.

Line-by-line breakdown:

- Line 16: iterate through the config text one line at a time.
- Line 17: check whether the line matches `AOA_LINE_RE`.
- Lines 18-19: if a match exists, parse the captured numeric string as a float and return it.
- Line 20: if nothing matched, return `None`.

### 2.3 `parse_case_aoa_from_name()` at lines 23-27

Purpose:

- Recover AoA from the case name if needed.

Line-by-line breakdown:

- Line 24: search the case name for `_aoa...`.
- Lines 25-26: if no match exists, return `None`.
- Line 27: convert the matched token to a float; `p` is converted to `.` first so names like `aoa15p5` would still work.

### 2.4 `load_case_aoa_degrees()` at lines 30-45

Purpose:

- Decide what AoA the extractor should use for a case.

Search order:

1. `config/generated/<case>.cfg`
2. `cases/<case>/config.cfg`
3. AoA parsed from the folder name
4. default to `0.0`

Line-by-line breakdown:

- Lines 31-33: build the candidate config paths.
- Lines 35-40: iterate over those paths and parse the first AoA found in an existing file.
- Lines 42-44: if config parsing failed, try the case name.
- Line 45: if everything fails, return `0.0`.

### 2.5 `streamwise_basis_from_aoa()` at lines 48-56

Purpose:

- Build the local coordinate frame used by both extractors.

Definitions:

- `streamwise`: freestream / stagnation-line direction
- `spanwise`: global `z`
- `pitch_normal`: perpendicular to both, lying in the AoA rotation plane

Line-by-line breakdown:

- Line 49: convert degrees to radians.
- Lines 50-51: build the AoA-rotated streamwise direction and normalize it.
- Line 53: define spanwise as global `z`.
- Lines 54-55: define the pitch-normal direction as `spanwise x streamwise`, then normalize it.
- Line 56: return the three basis vectors.

### 2.6 `frame_coordinates()` at lines 59-66

Purpose:

- Convert global Cartesian points into the AoA-aware local frame.

Interpretation:

- column 0 = streamwise coordinate
- column 1 = pitch-normal coordinate
- column 2 = spanwise coordinate

Line-by-line breakdown:

- Line 65: ensure the input is a float array.
- Line 66: compute the coordinates by dotting the points with the three basis vectors.

### 2.7 `perpendicular_radius()` at lines 69-72

Purpose:

- Measure distance from a point to the streamwise axis.

This is important because the “center” of the shock surface is not always `(y=0, z=0)` in the global frame once AoA is introduced.

Line-by-line breakdown:

- Line 70: ensure the input is a float array.
- Line 71: project every point onto the streamwise axis.
- Line 72: subtract that axial projection and take the norm of the perpendicular remainder.

### 2.8 `point_from_frame()` at lines 75-87

Purpose:

- Convert a local `(stream, pitch, span)` coordinate back into global Cartesian coordinates.

Line-by-line breakdown:

- Lines 83-86: form the global point as a linear combination of the three basis vectors weighted by the input coordinates.

---

## 3. Rectangular Method

File: `scripts/extract_shock_surface.py`

### 3.1 General Idea

This method builds a rectangular pitch/span grid of node lines.

For every transverse grid location:

- the node line runs in the **streamwise direction**
- density gradient magnitude is sampled along that line
- the first meaningful local maximum is treated as the shock candidate

The extraction starts at the center node line and moves outward in square shells. A candidate on an outer shell is only accepted if it is close enough to already accepted adjacent shock points from the inner shells.

This creates a connected shock surface without letting isolated false peaks enter the solution.

### 3.2 File Header and Settings

#### Imports at lines 4-21

These provide:

- CLI parsing
- CSV writing
- math helpers
- filesystem paths
- `numpy`
- `pyvista`
- `scipy.signal` peak finding and Savitzky-Golay smoothing
- shared CLI helpers from `case_cli`
- shared AoA-aware geometry helpers from `shock_geometry`

#### VTK warning import block at lines 23-26

- Tries to import `vtkObject`.
- If unavailable, the extractor still works, but cannot globally silence VTK warnings.

#### Settings block at lines 28-52

Important values:

- `vtu_name` / `density_scalar`: input file and scalar field name
- `output_surface_name` / `output_csv_name`: output names
- `stagnation_shock_node_radius`: radius used when searching for the stagnation-region shock node
- `default_spacing = 0.125`: current default rectangular spacing
- `surface_sensor_min_fraction`: threshold for deciding which parts of the domain are “active”
- `savgol_window_points`, `savgol_poly_order`: smoothing choices for line profiles
- `line_peak_height_fraction`, `line_peak_prominence_fraction`: peak detection thresholds
- `transverse_growth_factor`, `max_transverse_expansions`: used for automatic transverse extent growth

### 3.3 `vtk_warning_mode()` at lines 59-70

Purpose:

- Temporarily disable VTK warnings during derivative computation.

Line-by-line breakdown:

- Lines 60-63: if warnings are not being managed, just yield immediately.
- Line 65: remember the previous global warning setting.
- Line 66: disable VTK warnings.
- Lines 67-69: run the wrapped code.
- Line 70: restore the previous warning setting afterward.

### 3.4 `parse_args()` at lines 73-109

Purpose:

- Define the rectangular extractor CLI.

Key arguments:

- positional `cases`: optional case names
- `--spacing`: common spacing for both `dx` and `dyz`
- `--grid-bins`: legacy fallback if explicit spacing is not provided
- `--dx`: streamwise spacing
- `--dyz`: rectangular transverse spacing

Line-by-line breakdown:

- Lines 74-79: create the parser and human-readable description.
- Lines 80-84: define positional case selection.
- Lines 85-89: define `--spacing`.
- Lines 90-98: define `--grid-bins`.
- Lines 99-103: define `--dx`.
- Lines 104-108: define `--dyz`.
- Line 109: parse and return the arguments.

### 3.5 `resolve_requested_spacing()` at lines 112-136

Purpose:

- Convert CLI/default settings into actual `dx` and `dyz` overrides.

Line-by-line breakdown:

- Lines 113-115: determine the common spacing source and validate positivity.
- Lines 117-123: build `dx_override` with precedence:
  1. explicit `--dx`
  2. `--spacing`
  3. code-level `default_dx`
- Lines 124-129: build `dyz_override` with precedence:
  1. explicit `--dyz`
  2. `--spacing`
  3. code-level `default_dyz`
- Lines 131-134: validate that any explicit values are positive.
- Line 136: return the resolved pair.

### 3.6 `build_square_shells()` at lines 138-169

Purpose:

- Generate the outward square-shell traversal order over the rectangular pitch/span grid.

Line-by-line breakdown:

- Line 139: start with shell 0 containing the grid center.
- Line 140: mark the center as seen.
- Line 141: compute the maximum shell radius needed to reach the grid edge.
- Lines 142-146: compute the current square bounds.
- Lines 148-158: trace the shell perimeter:
  - top edge
  - right edge
  - bottom edge
  - left edge
- Lines 160-166: drop duplicates and preserve only new cells.
- Lines 166-167: add non-empty shells.
- Line 169: return the shell list.

### 3.7 `choose_stagnation_shock_node()` at lines 172-183

Purpose:

- Find the global stagnation-region shock node from the 3D shock-sensor field.

Line-by-line breakdown:

- Line 177: compute perpendicular distance from each mesh point to the streamwise axis.
- Line 178: keep only points inside `stagnation_shock_node_radius`.
- Line 179: collect those indices.
- Lines 180-181: if the radius filter found nothing, fall back to the geometrically closest points.
- Line 182: among those center-region points, choose the one with the strongest shock sensor.
- Line 183: return the stagnation shock node index and its sensor value.

### 3.8 `centered_axis()` at lines 186-188

Purpose:

- Build a symmetric 1D axis around zero with spacing `step`.

Line-by-line breakdown:

- Line 187: compute how many steps are needed to reach `max_abs`.
- Line 188: create `[-count, ..., 0, ..., +count] * step`.

### 3.9 `streamwise_axis()` at lines 191-195

Purpose:

- Build the 1D streamwise sampling axis.

Line-by-line breakdown:

- Lines 192-193: expand the stream range to integer multiples of `dx`.
- Line 194: compute the number of samples.
- Line 195: build the final axis.

### 3.10 `derive_sampling_steps()` at lines 198-216

Purpose:

- Infer `dx` and `dyz` if the user did not specify them.

Line-by-line breakdown:

- Lines 204-207: measure the active shock-region extents in global Cartesian coordinates.
- Lines 209-210: convert those extents into inferred spacings using `grid_bins`.
- Lines 212-213: apply explicit overrides if present.
- Lines 214-215: validate positivity.
- Line 216: return final `dx`, `dyz`.

### 3.11 `build_node_line_axes()` at lines 219-237

Purpose:

- Build the structured rectangular node-line grid in the AoA-aware frame.

Line-by-line breakdown:

- Line 228: map active points into local frame coordinates.
- Lines 229-230: measure streamwise extent.
- Line 231: add streamwise padding.
- Line 232: build the streamwise sample locations.
- Line 233: build the pitch-normal axis.
- Line 234: build the spanwise axis.
- Lines 235-236: identify the grid center indices.
- Line 237: return all axes and center indices.

### 3.12 `sample_node_lines()` at lines 240-279

Purpose:

- Sample the full rectangular node-line grid from the 3D gradient field.

Line-by-line breakdown:

- Lines 249-251: read axis sizes.
- Line 253: allocate one big point cloud for all node-line samples.
- Lines 255-256: precompute the streamwise contribution for all stream locations.
- Lines 257-265: for each transverse grid position:
  - build its local offset
  - add that offset to the streamwise line
  - place those sample points into the large array
- Line 267: interpolate the large array from the gradient mesh.
- Lines 268-269: pull out density and raw shock-sensor values, replacing NaN/Inf.
- Lines 270-273: obtain the valid-point mask.
- Lines 275-279: reshape the arrays into `(ny, nz, nx)` so each rectangular cell owns one 1D streamwise profile.

### 3.13 `smooth_line_profile()` at lines 282-302

Purpose:

- Smooth a single node-line profile with Savitzky-Golay.

Line-by-line breakdown:

- Line 283: allocate an output array.
- Line 284: locate valid sample indices only.
- Lines 285-286: return zeros if the line has no valid data.
- Lines 288-290: isolate the contiguous valid segment.
- Lines 291-293: if the segment is too short to smooth, just copy it.
- Line 295: choose the largest valid odd window length that fits.
- Lines 296-298: if even that is too short, just copy the segment.
- Line 300: choose polynomial order safely.
- Line 301: apply Savitzky-Golay.
- Line 302: return the smoothed result.

### 3.14 `find_first_local_peak()` at lines 305-343

Purpose:

- Given one streamwise node line, choose the first meaningful local shock peak.

Line-by-line breakdown:

- Lines 313-315: reject completely invalid lines.
- Line 317: smooth the raw shock sensor.
- Lines 318-320: isolate the valid segment.
- Line 321: get the strongest local value.
- Lines 322-323: build height and prominence thresholds.
- Line 325: find peaks.
- Line 326: map local peak locations back to absolute indices.
- Lines 328-329: if peaks exist, use the first one from upstream.
- Lines 330-335: otherwise optionally fall back to the global maximum of the segment.
- Lines 337-343: return the chosen peak information.

### 3.15 `has_adjacent_shock()` at lines 346-370

Purpose:

- Enforce local spatial continuity of the extracted shock surface.

Line-by-line breakdown:

- Lines 356-363: search the 8 neighboring rectangular bins for accepted shock points.
- Lines 365-366: if none exist, reject the candidate.
- Lines 368-369: compute distances to those neighboring points.
- Line 370: accept the candidate only if at least one neighbor lies within the allowed radius.

### 3.16 `extract_shock_nodes()` at lines 373-562

Purpose:

- This is the core rectangular shock extractor.

Conceptually, it does:

1. find the center shock point
2. define a sensor floor from that center point
3. move outward shell by shell
4. accept only connected candidates
5. build a surface mesh from accepted points

Line-by-line breakdown:

- Lines 384-390: extract grid sizes, compute actual `dx`, `dyz`, node-line diagonal, and neighbor radius.
- Lines 392-399: find the center node-line peak.
- Lines 400-401: fail if the center line has no shock.
- Lines 403-404: define the sensor floor relative to the center peak.
- Lines 406-408: initialize storage for rows, accepted points, and per-bin indexing.
- Lines 410-417: reconstruct the center shock point in global Cartesian coordinates.
- Lines 418-435: store the center point and its metadata.
- Line 437: initialize the spiral step counter.
- Line 438: build the square-shell traversal.
- Lines 439-490: loop over shells and node lines:
  - find a local peak on each streamwise node line
  - reject missing candidates
  - reconstruct the candidate point in 3D
  - reject it if it is not connected to adjacent accepted bins
  - stage accepted rows for that shell
- Lines 492-493: stop when a full shell has no accepted shock points.
- Lines 495-500: commit accepted rows from that shell into the global solution.
- Lines 502-511: create `PolyData` and attach point-data arrays.
- Lines 513-541: connect neighboring rectangular cells into triangles, but reject overly stretched elements.
- Lines 543-561: build the summary dictionary returned to the caller.

### 3.17 `choose_transverse_scale()` at lines 565-599

Purpose:

- Automatically expand the pitch/span grid until the extracted shock no longer touches the rectangular boundary.

Line-by-line breakdown:

- Line 575: use a coarse probing grid for the extent test.
- Line 576: derive probe spacings.
- Line 577: start with scale `1.0`.
- Lines 578-598: repeatedly:
  - build a scaled rectangular node-line grid
  - sample it
  - extract a provisional surface
  - inspect whether any accepted points lie on the outer boundary
  - return once the boundary is no longer touched
  - otherwise scale up by `transverse_growth_factor`
- Line 599: if all probe attempts still touch the boundary, return the final scale anyway.

### 3.18 `write_surface_outputs()` at lines 602-652

Purpose:

- Write the extracted surface to both `.vtp` and `.csv`.

Line-by-line breakdown:

- Lines 603-605: define output paths and save the VTK surface file.
- Lines 607-623: open the CSV and write the header.
- Lines 625-633: pull out all point-data arrays.
- Lines 634-650: write one CSV row per accepted shock node.
- Line 652: return both output paths.

### 3.19 `process_case()` at lines 655-719

Purpose:

- End-to-end processing for one case.

Line-by-line breakdown:

- Lines 656-660: resolve the case path and skip missing VTU cases.
- Lines 662-665: read the VTU file and convert cell data to point data if necessary.
- Lines 667-669: ensure `Density` exists.
- Lines 671-672: compute the 3D density gradient.
- Lines 674-675: load AoA and build the local frame.
- Lines 676-680: compute shock-sensor magnitude and store it as `ShockSensorRaw`.
- Lines 682-686: determine the active shock region.
- Line 688: determine actual `dx` and `dyz`.
- Lines 689-691: determine how much to expand the rectangular grid transversely.
- Lines 692-697: build the node-line axes and sample them.
- Lines 698-708: extract the surface.
- Line 709: write the output files.
- Lines 711-719: print the run summary.

### 3.20 `main()` at lines 722-751

Purpose:

- CLI entry point.

Line-by-line breakdown:

- Lines 723-724: parse args and resolve spacing.
- Lines 726-738: print a summary banner and settings.
- Lines 740-742: resolve cases from CLI or interactive selector and deduplicate aliases.
- Lines 745-748: process each selected case.
- Lines 750-751: print completion and return success.

---

## 4. Panel / Surface-Coordinate Method

File: `scripts/extract_shock_surface.py`

### 4.1 General Idea

This method does **not** build a shared rectangular search grid in advance.

Instead:

1. Find the stagnation shock node on a single stagnation node line.
2. Define a family of outward-propagating rays in surface coordinates.
3. March shell by shell:
   - shell spacing = `dt`
   - node-line sample spacing = `dn`
4. Use streamwise node lines on the first shell.
5. Use a panel-fit predictor for later shells.
6. Use a predictor-corrector refinement.
7. Stop when an entire shell contains no accepted shock nodes.

This method is closer to a shock-normal-tracking method than the rectangular one.

### 4.2 File Header and Settings

#### Imports at lines 4-20

Similar role to the rectangular extractor, but this file does not need `point_from_frame` because each node line is built directly as a 3D line from a center point and a direction vector.

#### Settings block at lines 27-52

Important values:

- `default_dt = 0.10`: tangent shell/ray spacing
- `default_dn = 0.025`: normal spacing along each node line
- `panel_half_length_factor = 8.0`: how long the panel-guided node lines should be
- `panel_prediction_tolerance_dt_factor = 2.0`: acceptance rule for panel prediction error, currently `2 * dt`
- `panel_fit_node_count = 5`: number of previous radial nodes used in the panel fit
- `minimum_azimuth_rays = 12`: minimum number of angular rays

### 4.3 `vtk_warning_mode()` at lines 63-74

Same purpose and structure as the rectangular extractor:

- temporarily suppress VTK warnings during derivative computation

### 4.4 `parse_args()` at lines 77-113

Purpose:

- Define the panel extractor CLI.

Key arguments:

- positional `cases`
- `--spacing`: common value for both `dt` and `dn`
- `--grid-bins`: legacy fallback for inferred spacing
- `--dt`: tangent spacing
- `--dn`: normal spacing

### 4.5 `resolve_requested_spacing()` at lines 116-128

Purpose:

- Resolve the final `dt` and `dn` overrides.

Line-by-line breakdown:

- Lines 117-119: determine `common_spacing` and validate it.
- Lines 121-122: resolve:
  - `dt_override` from `--dt`, then `--spacing`, then `default_dt`
  - `dn_override` from `--dn`, then `--spacing`, then `default_dn`
- Lines 124-127: validate positivity.
- Line 128: return the pair.

### 4.6 `choose_stagnation_shock_node()` at lines 131-142

Purpose:

- Same role as in the rectangular method: find the strong stagnation-region shock node in the 3D sensor field.

### 4.7 `derive_sampling_steps()` at lines 145-165

Purpose:

- Infer `dt` and `dn` if the user does not specify them.

Interpretation:

- `dn` is inferred from the streamwise span because it controls line sampling along the node line.
- `dt` is inferred from the transverse surface radius because it controls shell / ray spacing.

Line-by-line breakdown:

- Lines 154-156: compute local-frame extents.
- Lines 158-159: infer `dn` and `dt`.
- Lines 161-162: apply explicit overrides.
- Lines 163-164: validate positivity.
- Line 165: return the final pair.

### 4.8 `build_streamwise_window()` at lines 168-183

Purpose:

- Define the normal-search extent for the stagnation-line and first-shell streamwise node lines.

Line-by-line breakdown:

- Lines 175-177: measure streamwise extent in local coordinates.
- Line 178: add padding.
- Lines 179-180: compute full start and stop.
- Lines 181-182: return the line center and half-length.

### 4.9 `build_surface_azimuth_rays()` at lines 186-189

Purpose:

- Decide how many azimuth rays to use around the surface.

Line-by-line breakdown:

- Line 187: prevent degeneracy when `reference_radius < dt`.
- Line 188: choose enough rays so the arc length is approximately `dt`, but never fewer than `minimum_azimuth_rays`.
- Line 189: return uniformly spaced angles.

### 4.10 `radial_unit_vector()` at lines 192-193

Purpose:

- Convert an azimuth angle into a transverse radial direction in the AoA-aware frame.

Interpretation:

- This is the tangent-plane radial direction built from `pitch_normal` and `spanwise`.

### 4.11 `sample_line()` at lines 196-231

Purpose:

- Sample one arbitrary 3D node line.

This is more general than the rectangular method because the node line can point in any direction.

Line-by-line breakdown:

- Lines 203-207: normalize the line direction and reject zero vectors.
- Lines 209-211: choose an odd number of samples so there is a center point if possible.
- Line 212: build the 1D line coordinates along the node line.
- Line 213: convert the line coordinates into actual 3D sample points.
- Line 215: interpolate the gradient mesh at those points.
- Lines 216-223: extract density, shock sensor, and valid mask.
- Lines 225-231: return all line-sample data.

### 4.12 `smooth_line_profile()` at lines 234-254

Purpose:

- Same general role as in the rectangular method: smooth the 1D shock-sensor profile before peak detection.

### 4.13 `find_first_peak_from_upstream()` at lines 257-292

Purpose:

- Find the first meaningful peak on a node line, measured from the upstream end.

Used for:

- stagnation node line
- first shell streamwise node lines

Line-by-line breakdown:

- Lines 262-264: reject invalid lines.
- Line 266: smooth the raw profile.
- Lines 267-272: isolate the valid segment and build thresholds.
- Lines 274-283: choose the first real peak, or optionally the global maximum as fallback.
- Lines 285-291: return the candidate metadata.

### 4.14 `find_peak_near_center()` at lines 295-330

Purpose:

- Find the candidate shock peak nearest the center of a panel-guided node line.

Why this exists:

- Once a panel model predicts where the shock should be, we do not want to blindly take the first upstream peak anymore.
- We want the candidate most consistent with the predicted node-line placement.

### 4.15 `panel_history_for_ray()` at lines 333-338

Purpose:

- Build the radial history for one azimuth ray.

Line-by-line breakdown:

- Line 338: prepend the center row to that ray’s accepted history.

This means every ray always has the stagnation node as its first history point.

### 4.16 `fit_panel_model()` at lines 341-365

Purpose:

- Fit a local linear model relating `stream_coord` to `radius_surface` along one ray.

Interpretation:

- It is a local panel approximation in the 2D `(stream, radius)` plane for a given azimuth ray.

Line-by-line breakdown:

- Lines 345-346: need at least two history points.
- Line 348: keep only the last few points, up to `panel_fit_node_count`.
- Lines 349-350: extract radii and streamwise positions.
- Lines 352-354: reject degenerate history with no radial variation.
- Line 356: fit a straight line.
- Line 357: extrapolate the stream coordinate to the target radius.
- Lines 358-359: convert the fitted slope into a local normal direction in `(stream, radius)` space.
- Lines 360-365: return the full panel model.

### 4.17 `build_panel_line()` at lines 368-386

Purpose:

- Convert the fitted panel model into an actual 3D node line.

Line-by-line breakdown:

- Line 376: compute the transverse radial unit vector for the current azimuth.
- Lines 377-380: build the line center in 3D.
- Lines 381-384: build the node-line direction as a combination of streamwise and radial directions.
- Line 385: normalize the direction.
- Line 386: return the node line.

### 4.18 `predictor_corrector_candidate()` at lines 389-430

Purpose:

- Perform one predictor-corrector refinement for panel-guided node lines.

Workflow:

1. build a panel line from historical data
2. sample it
3. find a provisional shock point
4. refit the panel model including that provisional point
5. resample a corrected line
6. choose the corrected shock point

Line-by-line breakdown:

- Lines 401-403: fit a panel model or fail.
- Lines 405-409: sample the predicted line and choose a provisional candidate.
- Lines 410-411: fail if the provisional candidate does not exist.
- Lines 413-417: build a provisional row for the corrected fit.
- Lines 418-420: if a corrected model cannot be built, keep the provisional candidate.
- Lines 422-426: sample the corrected line and choose the corrected candidate.
- Lines 427-428: if corrected sampling fails, keep the provisional candidate.
- Line 430: return the corrected candidate and its prediction error proxy.

### 4.19 `extract_panel_surface()` at lines 433-634

Purpose:

- This is the core panel / surface-coordinate extractor.

Conceptually, it does:

1. define the stagnation node line
2. find the stagnation shock point
3. define azimuth rays
4. move outward shell by shell with spacing `dt`
5. use streamwise lines on shell 1
6. use panel-guided lines on later shells
7. stop when a full shell has no accepted points

Line-by-line breakdown:

- Lines 442-451: build the streamwise search window, set `dn`, compute predictor tolerances, define azimuth rays, and set a conservative shell cap.
- Lines 453-456: initialize storage for accepted points and ray histories.
- Lines 458-467: sample the stagnation node line and require a center shock candidate.
- Lines 469-470: define the sensor floor relative to the center peak.
- Lines 471-489: create the center row and store it.
- Lines 491-552: shell-by-shell outward march:
  - Line 492: shell radius is `shell_index * dt`
  - Lines 494-495: loop over azimuth rays
  - Lines 497-510: shell 1 uses streamwise node lines
  - Lines 512-529: later shells use the panel predictor-corrector
  - Lines 527-528: reject candidates whose prediction error exceeds `2 * dt`
  - Lines 534-550: store accepted candidate metadata
- Lines 553-554: stop when an entire shell has no accepted shock nodes.
- Lines 556-563: commit all accepted rows from the shell and update ray histories.
- Lines 565-576: build the `PolyData` and attach point-data arrays.
- Lines 578-587: create center fan triangles between the center node and shell 1.
- Lines 589-616: connect neighboring shells and neighboring rays with triangles, subject to an edge-length quality check.
- Lines 621-633: build the summary dictionary.

### 4.20 `write_surface_outputs()` at lines 637-695

Purpose:

- Write the panel surface to `.vtp` and `.csv`.

Compared with the rectangular method, the CSV stores panel-specific metadata such as:

- `stream_coord`
- `radius_surface`
- `azimuth_radians`
- `ray_index`
- `line_mode_code`
- `prediction_error`

### 4.21 `process_case()` at lines 698-746

Purpose:

- End-to-end processing for one case.

Line-by-line breakdown:

- Lines 699-703: resolve the case and skip missing VTUs.
- Lines 705-708: read the mesh and convert cell data to point data if needed.
- Lines 710-712: ensure `Density` exists.
- Lines 714-715: compute the 3D density gradient.
- Lines 717-718: load AoA and build the local frame.
- Lines 719-723: compute `ShockSensorRaw`.
- Lines 725-729: determine the active shock region.
- Lines 731-733: determine `dt` and `dn`.
- Lines 734-736: run the panel extractor.
- Line 737: write outputs.
- Lines 739-746: print the run summary.

### 4.22 `main()` at lines 749-781

Purpose:

- CLI entry point for the panel extractor.

Structure is the same as the rectangular method:

- parse args
- resolve spacing
- print settings
- select cases
- run each case

---

## 5. Comparison of the Two Methods

### 5.1 Rectangular Method Strengths

- Easier to debug
- Structured and predictable
- Strong local continuity enforcement
- Shared grid makes downstream meshing straightforward

### 5.2 Rectangular Method Weaknesses

- Node lines are always streamwise
- Less aligned with the actual shock normal away from stagnation
- Can appear blocky if `dyz` is too coarse

### 5.3 Panel Method Strengths

- Uses surface coordinates directly
- Node lines can rotate toward the estimated shock normal
- More physically adaptive away from stagnation
- `dt` and `dn` have a clearer geometric meaning

### 5.4 Panel Method Weaknesses

- More path-dependent
- More complex
- More expensive when `dn` is very fine
- More sensitive to missing or noisy radial history

---

## 6. Current Outputs Written by Each Method

### 6.1 Rectangular Method

- `shock_surface.vtp`
- `shock_surface.csv`

CSV columns:

- `x`
- `y`
- `z`
- `density`
- `shock_sensor`
- `shock_sensor_raw`
- `radius_yz`
- `spiral_step`
- `shell_layer`
- `line_index`
- `bin_i`
- `bin_j`

### 6.2 Panel Method

- `shock_surface.vtp`
- `shock_surface.csv`

CSV columns:

- `x`
- `y`
- `z`
- `stream_coord`
- `density`
- `shock_sensor`
- `shock_sensor_raw`
- `radius_surface`
- `azimuth_radians`
- `shell_layer`
- `ray_index`
- `line_index`
- `line_mode_code`
- `prediction_error`

---

## 7. Current Default Settings Summary

### 7.1 Rectangular Method

From `scripts/extract_shock_surface_rectangular.py`:

- `default_spacing = 0.125`
- `surface_sensor_min_fraction = 0.005`
- `savgol_window_points = 9`
- `savgol_poly_order = 3`

### 7.2 Panel Method

From `scripts/extract_shock_surface.py`:

- `default_dt = 0.10`
- `default_dn = 0.025`
- `panel_fit_node_count = 5`
- `panel_prediction_tolerance_dt_factor = 2.0`
- `savgol_window_points = 9`
- `savgol_poly_order = 3`

---

## 8. Short Practical Interpretation

If you want a simple mental model:

- The **rectangular method** says:
  “Lay down a rectangular family of streamwise lines, find the shock on each one, and only keep points that stay connected.”

- The **panel method** says:
  “Start at stagnation, move outward in surface coordinates, and keep rotating the next node line toward the locally predicted shock normal.”

The rectangular method is the more robust baseline.

The panel method is the more ambitious geometry-aware method.
