# Panel Shock Extractor: Beginner Walkthrough
This document is a very detailed, beginner-friendly explanation of:
- [extract_shock_surface.py](/home/anthonyy/links/scratch/reentry/orion/scripts/extract_shock_surface.py)
- [shock_geometry.py](/home/anthonyy/links/scratch/reentry/orion/scripts/shock_geometry.py)
The goal is not just to say "what the code does", but also:
- what the Python syntax means
- what each function is responsible for
- what data goes in and out
- what the important mathematical ideas are
- where the current method is likely to behave strangely
This walkthrough matches the code as it exists right now.
---
## 1. The Big Picture, In Very Simple Words
Imagine this:
- You have a giant 3D CFD result.
- Somewhere inside it is a bow shock.
- You want a computer to trace out the shock surface.
The panel extractor does that like this:
1. It computes a **shock sensor** from the density field.
2. It finds the shock at the **stagnation line** first.
3. Then it moves outward in rings.
4. On each ring, it tests many directions around the body.
5. For each direction, it builds a little search line and asks:
   - "Where is the shock on this line?"
6. It stores the answer as a 3D point.
7. After enough points are collected, it connects them into a surface.
So the code is really a machine for answering this question many times:
> If I stand here and look in the right direction, where is the shock on this little 1D line?

That is the whole method.
---
## 2. Tiny Python Syntax Guide
You said you only know a little bit of the syntax, so here is the "baby version" first.
### 2.1 `def`
Example:
```python
def sample_line(...):
```
This means:
- "I am making a function"
- a function is a reusable chunk of code
- you can think of it like a tool or machine
### 2.2 `return`
Example:
```python
return float(dt), float(dn)
```
This means:
- "This function is done"
- "Here is the result"
### 2.3 `if`
Example:
```python
if candidate is None:
    continue
```
This means:
- "If this condition is true, do the indented block"
### 2.4 `None`
`None` means:
- "nothing"
- "no value"
- "failed to find something"
### 2.5 List
Example:
```python
accepted_rows = []
```
A list is:
- a container that holds many things
- like a row of boxes
### 2.6 Dictionary
Example:
```python
row = {
    "x": float(point[0]),
    "y": float(point[1]),
}
```
A dictionary is:
- a set of labeled boxes
- instead of box 1, box 2, box 3
- you say `"x"`, `"y"`, `"z"`
### 2.7 Tuple
Example:
```python
tuple[float, float]
```
A tuple is:
- a fixed bundle of values
- like returning exactly two things or three things together
### 2.8 `np.asarray(...)`
`np` is `numpy`.

`numpy` is a Python library for working with arrays and math quickly.

An array is:
- like a long line of numbers
- or a table of numbers
- or a block of numbers in 3D
### 2.9 `pv`
`pv` is `pyvista`.

PyVista is:
- a Python tool for working with 3D meshes and VTK files
- useful for reading `flow.vtu`
- useful for sampling/interpolating fields
### 2.10 `Path`
`Path` is a nicer way to work with file paths.

Example:
```python
ROOT / "cases"
```
This means:
- "take the root folder and append `cases` to it"
### 2.11 `@contextmanager`
This is a Python feature for "set something up, do work, then clean it up".

In this file it is used for:
- turning off VTK warnings temporarily
- then turning them back on
### 2.12 `if __name__ == "__main__":`
This means:
- "Only run this part when the file is executed directly"
So this:
```python
if __name__ == "__main__":
    raise SystemExit(main())
```
means:
- if you run the script from the terminal
- call `main()`
---
## 3. Vocabulary Used In This Code
### 3.1 Density
This is the CFD density field, stored as `Density`.
### 3.2 Gradient
A gradient means:
- "how fast something changes"
If density changes very sharply, the gradient is large.
### 3.3 Shock Sensor
The shock sensor in this file is:
- the magnitude of the 3D density gradient
In simpler words:
- "how sharp is the density jump here?"
### 3.4 Stagnation Line
This is the first central line used to find the shock near the nose.

It is aligned with the AoA-adjusted freestream direction, not always global `x`.
### 3.5 AoA
AoA means:
- **angle of attack**
That is how much the body/freestream is tilted in the `x-y` plane.
### 3.6 `dt`
In this panel method:
- `dt` = tangent spacing
That means:
- how far apart neighboring shells are
- and roughly how far apart neighboring rays are intended to be around the surface
### 3.7 `dn`
In this panel method:
- `dn` = normal spacing along each node line
That means:
- how finely the search line is sampled
### 3.8 Ray
A ray is:
- one angular direction around the body
If you stand at the center and turn around in azimuth, each chosen angle is a ray.
### 3.9 Shell
A shell is:
- one outward ring of constant surface radius
Shell 1 is close to stagnation.
Shell 2 is farther out.
Shell 3 farther out again.
### 3.10 Panel
Here "panel" means:
- a local small fitted piece of the surface
The code uses previous shock points on a ray to estimate the local shape.
### 3.11 Predictor-Corrector
This is a two-step method:
1. predict where the shock should be
2. use that provisional answer to make a better corrected prediction
So it is basically:
- first guess
- better guess
---
## 4. Shared Geometry Helper First
Before understanding the panel file, you need the geometry helper.

File:
- [shock_geometry.py](/home/anthonyy/links/scratch/reentry/orion/scripts/shock_geometry.py)
### 4.1 Why This Helper Exists
If AoA is not zero, the "forward direction" is not just global `x`.

So instead of always using:
- `x` = forward
- `y` = pitch direction
- `z` = span direction
the helper builds a rotated coordinate frame:
- `streamwise`
- `pitch_normal`
- `spanwise`
That is the frame the panel extractor works in.
### 4.2 `load_case_aoa_degrees()`
This function:
- tries to read AoA from the generated config file
- or local config
- or case name
This is how the extractor learns whether the case is `aoa0`, `aoa15`, and so on.
### 4.3 `streamwise_basis_from_aoa()`
This is one of the most important helpers.

It returns three unit vectors:
- `streamwise`
- `pitch_normal`
- `spanwise`
For AoA = 15 degrees, for example:
- `streamwise = [cos(15), sin(15), 0]`
- `pitch_normal = [-sin(15), cos(15), 0]`
- `spanwise = [0, 0, 1]`
Important:
- only the `x-y` plane is rotated
- `z` stays as `z`
### 4.4 `frame_coordinates()`
This function converts ordinary 3D Cartesian points into the local AoA-aware frame.

If a point in global space is:
- `[x, y, z]`
it turns it into:
- `[stream_coord, pitch_coord, span_coord]`
This is useful because the code wants to think in:
- "forward"
- "up/down in pitch plane"
- "spanwise left/right"
### 4.5 `perpendicular_radius()`
This function answers:
> How far is this point from the streamwise axis?

That matters because the stagnation region should be found relative to the streamwise axis, not necessarily relative to global `(y=0, z=0)`.
---
## 5. Panel File: Top of File
File:
- [extract_shock_surface.py](/home/anthonyy/links/scratch/reentry/orion/scripts/extract_shock_surface.py)
---
## 6. Lines 1-20: Imports
These lines load the tools the script needs.
### Lines 1-2
```python
#!/usr/bin/env python3
from __future__ import annotations
```
- line 1 says this file should be run with Python 3
- line 2 is a Python typing convenience; you do not need to worry much about it
### Lines 4-8
Standard Python tools:
- `argparse`: read command-line arguments
- `csv`: write CSV files
- `math`: use trig and square roots
- `contextmanager`: make the warning-suppression helper
- `Path`: handle file paths
### Lines 10-12
External libraries:
- `numpy`
- `pyvista`
- `scipy.signal`
`scipy.signal` provides:
- `find_peaks`
- `savgol_filter`
### Lines 14-20
This loads helper functions:
- from `case_cli`
- from `shock_geometry`
So the panel extractor does not have to reinvent:
- case selection
- case path resolution
- AoA-aware basis construction
---
## 7. Lines 22-25: Optional VTK Warning Control
```python
try:
    from vtkmodules.vtkCommonCore import vtkObject
except ImportError:
    vtkObject = None
```
Meaning:
- try to import a VTK object that lets us control warnings
- if that import fails, keep going anyway
So the script can still work even if that specific VTK helper is unavailable.
---
## 8. Lines 27-52: User Settings
This block is extremely important because it holds the "knobs".
### `vtu_name`, `density_scalar`, outputs
These say:
- input file is `flow.vtu`
- the field to use is `Density`
- outputs are `shock_surface.vtp` and `shock_surface.csv`
### `stagnation_shock_node_radius`
This tells the code:
- when looking for the stagnation shock node in the full 3D field
- only trust points close to the streamwise axis first
### `default_dt = 0.10`
This means:
- the default shell/ray tangent spacing is `0.10`
### `default_dn = 0.025`
This means:
- the default node-line sample spacing is `0.025`
This is very fine.
### `surface_sensor_min_fraction = 0.005`
This means:
- after the center peak is found
- the rest of the domain is considered "active" only if its shock sensor is at least `0.5%` of the center peak
This is a way of ignoring extremely weak/noisy parts of the field.
### `surface_mesh_edge_factor = 4.0`
This is a geometry quality control:
- when triangles are built
- if edges are too stretched compared with the local spacing
- skip them
### `savgol_window_points = 9`, `savgol_poly_order = 3`
These control the Savitzky-Golay smoothing.

Savitzky-Golay filter means:
- a 1D smoothing method
- it tries to reduce noise without flattening the curve as brutally as a crude moving average
### `streamwise_padding_factor = 1.0`
This tells the code:
- when building the streamwise search window
- add some extra margin
### `line_peak_height_fraction = 0.05`
This is part of the shock-pick threshold:
- the peak should not be too tiny compared with the strongest thing on the line
### `line_peak_prominence_fraction = 0.02`
Prominence means:
- how much the peak sticks up above its surroundings
So this helps reject little bumps that are not "real enough".
### `panel_half_length_factor = 8.0`
This determines how long a panel-guided node line is.

Bigger value:
- longer search line
Smaller value:
- shorter search line
### `panel_prediction_tolerance_dt_factor = 2.0`
This is the current acceptance rule:
- if the predicted/corrected shock point is too far from where we expected
- reject it
Current tolerance:
- `2 * dt`
### `panel_fit_node_count = 5`
The panel fit uses up to the last 5 previous points on a ray.
### `minimum_azimuth_rays = 12`
Even if the surface is tiny, use at least 12 rays around the body.
### `suppress_vtk_warnings = True`
This just makes the output less noisy.
---
## 9. Lines 54-60: Important Globals
### `SCRIPT_DIR`, `ROOT`, `CASES_DIR`
These are folder paths.

They tell the script where it lives and where the case folders live.
### `LINE_MODE_CENTER = 0`
This label means:
- the stagnation line
### `LINE_MODE_STREAMWISE = 1`
This label means:
- a plain streamwise node line
### `LINE_MODE_PANEL = 2`
This label means:
- a node line whose direction came from the panel model
These codes are written to the CSV so you can later tell which point came from which type of line.
---
## 10. `vtk_warning_mode()` at Lines 63-74
This function is a small helper to temporarily hide VTK warnings.
### What the syntax means
```python
@contextmanager
def vtk_warning_mode(enabled: bool):
```
This says:
- "I am making a special helper"
- it can be used with a `with ...:` block
### Step by step
- If warnings are not being managed, just let the code run.
- Otherwise:
  - remember the old VTK warning setting
  - turn warnings off
  - let the main work happen
  - turn warnings back on afterward
So it is just a tidy cleanup helper.
---
## 11. Case Selection In `main()`
The simplified script no longer has a full command-line settings parser.

Now the rule is:
- if you type case names after the script name, those are the cases
- if you type nothing, the interactive selector opens
Example:
```bash
python3 scripts/extract_shock_surface.py m3_aoa15
```
means:
- run only `m3_aoa15`
If you run:
```bash
python3 scripts/extract_shock_surface.py
```
then:
- the script asks you to choose cases interactively
So the terminal input is now much simpler:
- case names only
- no spacing flags
- no legacy inference flags
---
## 12. `configured_sampling_steps()`
This helper is much simpler than the old spacing logic.

Its job is:
- read `default_dt`
- read `default_dn`
- make sure both are positive
- return them
So now there is only one place to control spacing:
- the settings block near the top of the file
That means:
- less logic
- fewer possible combinations
- easier reading
In plain language:
> "Whatever `dt` and `dn` are written in the code settings, use those."
---
## 13. `choose_stagnation_shock_node()`
This function looks through the entire 3D shock sensor and finds the best stagnation-region shock node.
### Step by step
#### Line 136
```python
radius = perpendicular_radius(points, streamwise)
```
This computes:
- distance from each point to the streamwise axis
This is the right "center" notion when AoA is not zero.
#### Lines 137-138
Build a mask and collect points close to the center line.
#### Lines 139-140
If there were no points inside the preferred radius:
- fall back to the nearest few points to the axis
#### Line 141
From those center-region candidates:
- choose the one with the biggest shock sensor
#### Line 142
Return:
- index of that point
- its shock-sensor strength
This is not yet the extracted surface point.
It is just the stagnation shock node used to define the active region and center scale.
---
## 14. `derive_sampling_steps()` at Lines 145-165
This function determines `dt` and `dn` if the user did not explicitly specify them.
### Lower-level logic
#### Line 154
Convert active shock points into the local AoA-aware frame.
#### Lines 155-156
Measure:
- streamwise span
- surface radius span
#### Lines 158-159
Infer:
- `dn` from streamwise span
- `dt` from transverse surface size
This is only a fallback.
#### Lines 161-162
If the user already gave `dt` or `dn`, those win.
#### Lines 163-164
Reject invalid non-positive spacings.
---
## 15. `build_streamwise_window()` at Lines 168-183
This function decides how long the central streamwise search line should be.
### What it returns
- `center`
- `half_length`
So the actual line becomes:
- from `center - half_length`
- to `center + half_length`
in streamwise coordinate
### Why it matters
The code needs a line long enough to:
- start upstream of the shock
- pass through the shock
- keep going downstream
If this line were too short, the code might miss the shock.
---
## 16. `build_surface_azimuth_rays()` at Lines 186-189
This function decides:
- how many angular directions to use around the surface
### Lower-level logic
If the current reference radius is bigger:
- use more rays
If the radius is smaller:
- still use at least 12 rays
The main idea is:
- try to keep the angular arc-length spacing around `dt`
Important caveat:
This makes the ray spacing only approximately `dt` near the chosen reference radius.
It does not make the spacing exactly uniform at every shell.

That is one of the issues you already noticed.
---
## 17. `radial_unit_vector()` at Lines 192-193
This function takes an angle `theta` and returns a unit vector in that transverse direction.

You can think of it like:
- "turn around the body by angle `theta`"
- "which way am I pointing in the pitch/span plane?"
It uses:
- `pitch_normal`
- `spanwise`
and mixes them with:
- `cos(theta)`
- `sin(theta)`
---
## 18. `sample_line()` at Lines 196-231
This is one of the most important low-level functions in the whole file.
### What it really does
It takes a 3D line and asks:
> Sample the flow field along this line. What do density and shock sensor look like along it?
### Inputs
- `gradient_mesh`: the CFD data with the shock sensor already attached
- `line_center`: center point of the node line
- `line_direction`: direction of the node line
- `half_length`: half the total node-line length
- `normal_step`: sample spacing along that node line
### Step by step
#### Lines 203-207
Normalize the direction vector.

This means:
- keep only direction
- remove length scaling
#### Lines 209-211
Choose the number of samples along the line.

It forces an odd count when possible, so there is a clean center sample.
#### Line 212
Build the 1D coordinates along the line.

Example idea:
- `[-L, ..., 0, ..., +L]`
#### Line 213
Turn the 1D line coordinates into actual 3D points.

This is vector math:
- point = center + distance_along_line * direction
#### Line 215
Use PyVista to interpolate the CFD field at all those 3D sample points.

This is a big deal:
- the points do not need to lie on original mesh nodes
- PyVista interpolates values there
#### Lines 216-223
Extract:
- density
- raw shock sensor
- valid-point mask
The valid-point mask tells us whether interpolation actually landed inside the mesh correctly.
#### Lines 225-231
Return a dictionary containing:
- the 3D sample points
- the 1D line coordinate values
- density values
- shock sensor values
- validity mask
This function is the basic "measurement tool" for every node line.
---
## 19. `smooth_line_profile()` at Lines 234-254
This function smooths the shock-sensor values on one sampled line.
### Why smoothing is needed
Raw gradients are noisy.

If you tried to pick peaks directly:
- the code would latch onto little wiggles
- especially on fine meshes
### What happens here
1. Find which samples are valid.
2. Extract the valid contiguous part.
3. If it is long enough:
   - apply Savitzky-Golay smoothing
4. Otherwise:
   - just keep the raw segment
So this function tries to make the line profile less noisy but still preserve peak structure.
---
## 20. `find_first_peak_from_upstream()` at Lines 257-292
This function answers:
> On this node line, where is the first good shock-like peak from upstream?
### Why "from upstream"?
Because for the stagnation line and early streamwise lines, the shock should usually be the first major jump encountered from the upstream side.
### Step by step
#### Lines 262-264
If the line has no valid samples:
- fail immediately
#### Line 266
Smooth the shock-sensor profile.
#### Lines 267-272
Compute:
- valid segment
- local maximum
- threshold height
- threshold prominence
#### Line 274
Ask SciPy to find peaks.
#### Lines 276-277
If peaks exist:
- choose the first one
#### Lines 278-283
If no proper peak exists but fallback is allowed:
- use the biggest value on the line instead
#### Lines 285-291
Return the chosen peak and its metadata.

This metadata includes:
- 3D point
- density
- raw and smoothed shock sensor
- sample index
- coordinate along the node line
---
## 21. `find_peak_near_center()` at Lines 295-330
This is similar to the previous function, but the choice rule is different.

It answers:
> On this node line, which acceptable peak is closest to the center of the line?
### Why do we need a second peak picker?
Because once the panel method predicts a line that should cross the shock near its middle, we no longer necessarily want:
- the first upstream bump
We want:
- the peak nearest the predicted crossing location
That is why the code uses this function for panel-guided node lines.
---
## 22. `panel_history_for_ray()` at Lines 333-338
This function is tiny but important.

It builds the history for one azimuth ray:
- the center row
- plus that ray’s accepted rows so far
So every ray starts from the same stagnation point history.
---
## 23. `fit_panel_model()` at Lines 341-365
This is the heart of the "panel" idea.
### What it is trying to do
Suppose along one ray we already found several shock points.

Each of those points has:
- a streamwise position
- a surface radius
The function tries to fit a simple local line:
```text
stream_coord = slope * radius_surface + intercept
```
This gives us a local guess of how the surface is leaning along that ray.
### Step by step
#### Lines 345-346
If there are fewer than two history points:
- you cannot fit a line
#### Line 348
Use only the most recent few points, up to `panel_fit_node_count`.

This is important because:
- we want a local fit, not a global fit over the whole ray
#### Lines 349-350
Extract:
- radii
- streamwise coordinates
#### Lines 352-354
If all radii are basically the same:
- there is no meaningful fit
#### Line 356
Use `np.polyfit(..., deg=1)` to fit a straight line.

This returns:
- slope
- intercept
#### Line 357
Extrapolate to the target radius.

This gives a predicted streamwise location for the next shell.
#### Lines 358-359
Build a local normal direction in the 2D `(stream, radius)` plane.

This is a subtle but important step.

If the surface locally follows:
- `stream = m * radius + b`
then the tangent direction in that 2D plane is like:
- `[m, 1]`
and a normal direction is perpendicular to that, which is represented here as:
- `[1, -m]`
Then the code normalizes it.
#### Lines 360-365
Return all the useful panel model pieces in a dictionary.
---
## 24. `build_panel_line()` at Lines 368-386
Now that the code has a panel model, it needs to turn that into a real 3D node line.
### What this means physically
The code knows:
- which ray angle we are on
- what radius we are targeting
- what local normal direction the panel fit suggests
So it creates:
- a 3D point where the line should be centered
- a 3D direction the line should point in
### Step by step
#### Line 376
Get the radial unit vector for the current azimuth.
#### Lines 377-380
Build the 3D line center:
- streamwise piece
- plus radial piece
#### Lines 381-384
Build the 3D line direction:
- streamwise component
- plus radial component
This is the actual "panel-guided normal-ish search line".
#### Line 385
Normalize the direction.
#### Line 386
Return:
- line center
- line direction
---
## 25. `predictor_corrector_candidate()` at Lines 389-430
This is the other big heart of the panel method.
### Why this exists
A panel prediction from old data may be a little off.

So instead of trusting one shot:
1. predict
2. sample
3. get provisional point
4. refine prediction
5. sample again
6. get corrected point
### Step by step
#### Lines 401-403
Fit the first panel model.

If that fails:
- there is no panel candidate
#### Lines 405-409
Build the first node line from the panel model and sample it.

Then pick a peak near the center of that line.
#### Lines 410-411
If even that fails:
- no candidate
#### Lines 413-417
Turn the provisional point into a tiny new history row.

This row only needs:
- `stream_coord`
- `radius_surface`
#### Lines 418-420
Try fitting a corrected panel model that includes the provisional point.

If that fails:
- keep the initial candidate
#### Lines 422-426
Build the corrected line and sample it.
#### Lines 427-428
If corrected sampling fails:
- keep the initial candidate
#### Line 430
Return:
- the corrected candidate
- the absolute line-coordinate distance from center
That second value is used as a crude prediction error measure.
---
## 26. `extract_panel_surface()` at Lines 433-634
This is the main algorithm.

If you understand this function, you understand the whole panel method.
### Inputs
- `gradient_mesh`: CFD data with `ShockSensorRaw`
- `active_points`: points above the sensor threshold
- `dt`: tangent spacing
- `dn`: normal spacing
- frame vectors
### Outputs
- a `PyVista PolyData` shock surface
- a summary dictionary
---
### 26.1 Lines 442-451: Build Global Marching Setup
#### Line 442-444
Build the central streamwise search window.

This is used for:
- stagnation node line
- first shell streamwise lines
#### Line 445
Set the normal sample spacing equal to `dn`.
#### Line 446
Choose panel-line half-length.

It is:
- `panel_half_length_factor * max(dt, dn)`
So the search line length scales with the spacing.
#### Line 447
Prediction tolerance is:
- `2 * dt`
This means:
- if the candidate ends up too far from where the panel expected
- reject it
#### Lines 448-451
Estimate:
- maximum surface radius
- azimuth rays
- total shell cap
Important:
This shell cap is only a safety limit.
The method still really stops when a full shell is empty.
---
### 26.2 Lines 453-456: Storage
The code creates containers for:
- accepted rows
- accepted shock-node points
- a map from `(shell, ray)` to point index
- per-ray history
These are the memory of the method.
---
### 26.3 Lines 458-467: Find the Stagnation Shock Node
#### Lines 458-464
Build and sample the stagnation node line.

Important:
- it is centered on the streamwise axis
- it points exactly in the streamwise direction
- it uses the AoA-aware streamwise vector
#### Line 465
Pick the first upstream peak on that line.
#### Lines 466-467
If that fails:
- the whole method cannot continue
---
### 26.4 Lines 469-489: Store the Center Row
The center peak becomes the first accepted shock point.

The code stores:
- Cartesian coordinates
- streamwise coordinate
- density
- shock sensor
- shell index
- ray index
- line mode
- prediction error
This center row is also used later as the start of every ray history.
---
### 26.5 Lines 491-554: March Outward Shell by Shell
This is the main loop.
#### Line 491
Loop over shell indices.
#### Line 492
Convert shell index into shell radius:
- `shell_radius = shell_index * dt`
#### Line 493
Prepare a temporary list for accepted points in this shell.

That is important:
- the whole shell is evaluated first
- only after that is it committed
#### Lines 494-495
Loop over azimuth rays.

Each ray is one direction around the surface.
---
### 26.6 Lines 497-510: First Shell Logic
The first shell does not use the panel model.

Why?

Because there is not enough history yet.

So for shell 1:
- build a streamwise line at radius `dt`
- sample it
- pick the first upstream peak
This gives a stable first ring.
---
### 26.7 Lines 512-529: Later Shell Logic
For shells 2 and onward:
#### Line 512
Get the ray history:
- center row
- plus previous accepted rows for this ray
#### Lines 513-524
Run the predictor-corrector candidate finder.
#### Lines 525-526
If that fails:
- skip this ray for this shell
#### Lines 527-528
If the prediction error is too big:
- reject the candidate
Current rule:
- reject if error > `2 * dt`
#### Line 529
If the candidate survived, mark this line as a panel-guided line.
---
### 26.8 Lines 531-550: Candidate Row Construction
If a candidate exists:
- convert it into a row dictionary
- store all needed metadata
This includes:
- Cartesian coordinates
- streamwise coordinate
- density
- shock-sensor values
- shell radius
- azimuth angle
- shell index
- ray index
- line index
- line mode
- prediction error
---
### 26.9 Lines 553-554: End Condition
This is the stop rule you asked for.

If the entire shell produced no accepted shock nodes:
- stop the outward march
This is much cleaner than stopping because of one single bad line.
---
### 26.10 Lines 556-563: Commit Accepted Shell
Once the shell is done:
- append accepted points to the global list
- update the `(shell, ray)` index map
- append them to the ray histories
So the next shell can use them for panel fitting.
---
### 26.11 Lines 565-576: Build PolyData
The raw accepted 3D points become a PyVista surface object.

Then the code attaches data arrays:
- `Density`
- `ShockSensor`
- `ShockSensorRaw`
- `RadiusSurface`
- `AzimuthRadians`
- `ShellLayer`
- `RayIndex`
- `LineIndex`
- `LineModeCode`
- `PredictionError`
- `StreamCoord`
This is why ParaView can color the surface by these values later.
---
### 26.12 Lines 578-587: Center Fan Triangles
This creates triangles from:
- the center point
- shell 1 point on ray `i`
- shell 1 point on ray `i+1`
So the central cap is filled in like a fan.
---
### 26.13 Lines 589-616: Shell-to-Shell Surface Triangles
This connects neighboring shells and neighboring rays.

Each quadrilateral patch is split into two triangles.

But first the code checks edge lengths.

If the patch is too stretched:
- do not create the triangles
This prevents really ugly or nonsensical surface elements.
---
### 26.14 Lines 621-633: Summary
The code returns a summary dictionary containing:
- point count
- cell count
- center peak
- sensor floor
- prediction tolerance
- `dt`
- `dn`
- ray count
- max shell layer
- number of panel lines
- number of first-shell streamwise lines
This is what the script prints at the end of a run.
---
## 27. `write_surface_outputs()` at Lines 637-695
This function writes the outputs to disk.
### Step by step
#### Lines 638-640
Create output paths and save the `.vtp` file.
#### Lines 642-660
Open the CSV and write the header.
#### Lines 663-673
Pull all attached point-data arrays from the surface.
#### Lines 675-693
Write one CSV row per surface point.

So the CSV is basically:
- the surface point cloud
- plus all the metadata about how each point was generated
---
## 28. `process_case()` at Lines 698-746
This function handles one whole case from start to finish.
### Step by step
#### Lines 699-703
Resolve the case path and skip if `flow.vtu` does not exist.
#### Lines 705-708
Read the mesh.

If `Density` is stored on cells instead of points:
- convert it to point data
#### Lines 710-712
If `Density` is still missing:
- stop with a clear error
#### Lines 714-715
Compute the 3D density gradient.

This is one of the most expensive steps.
#### Lines 717-718
Load the case AoA and build the local frame.
#### Lines 719-723
Turn the gradient vector into a scalar shock sensor:
- `ShockSensorRaw = ||grad(rho)||`
#### Lines 725-729
Use the center peak to define the active region.

This throws away weak parts of the field.
#### Lines 731-733
Determine final `dt` and `dn`.
#### Lines 734-736
Run the actual panel extraction.
#### Lines 737-746
Write outputs and print the summary.
---
## 29. `main()` at Lines 749-781
This is the terminal entry point.
### Step by step
#### Lines 750-751
Read user inputs and spacing.
#### Lines 753-768
Print a header and tell the user what settings are being used.
#### Lines 770-772
Choose cases either:
- from the command line
- or via interactive selector
Then deduplicate aliases.
#### Lines 775-778
Process each chosen case.
#### Lines 780-781
Print `Done.` and exit.
---
## 30. One Full Run In Human Language
If you run:
```bash
python3 scripts/extract_shock_surface.py m3_aoa15
```
here is the story:
1. The script reads the arguments.
2. It finds the case folder.
3. It opens `flow.vtu`.
4. It computes `grad(Density)`.
5. It computes `ShockSensorRaw = |grad(Density)|`.
6. It reads AoA and builds the rotated `streamwise / pitch_normal / spanwise` frame.
7. It finds the strongest central shock-like point in the 3D field.
8. It uses that point to define what part of the domain is "active enough".
9. It decides `dt` and `dn`.
10. It builds the stagnation node line and finds the shock on it.
11. It moves to shell 1 and tries streamwise lines around the body.
12. It stores successful shell-1 shock points.
13. For shell 2 and beyond, it uses the previous ray history to predict a better line direction.
14. It samples that predicted line.
15. It corrects the prediction once.
16. It accepts the corrected shock point only if it is consistent enough.
17. It repeats shell by shell.
18. When an entire shell produces no points, it stops.
19. It builds triangles between neighboring accepted points.
20. It writes `.vtp` and `.csv`.
That is the whole machine.
---
## 31. Where The Current Weirdness Probably Comes From
Since you are trying to understand the code well enough to improve it, here are the most likely trouble spots.
### 31.1 `dt` Is Uniform In Parameter Space, Not True Surface Distance
At line 492:
```python
shell_radius = float(shell_index) * dt
```
This means:
- shells are evenly spaced in the method's surface-radius parameter
It does **not** mean:
- accepted shock points will be evenly spaced in actual 3D distance
That is why some areas can look uneven even when `dt` is constant.
### 31.2 Fixed Azimuth Ray Set
At lines 448-450, the code builds one ray set using a reference radius.

That means:
- angular spacing is fixed
- arc-length spacing changes with shell radius
So the tangent spacing is only approximately controlled.
### 31.3 Path Dependence
The panel fit uses previous points on a ray.

That means:
- if early points are a little wrong
- later lines can inherit that error
### 31.4 Peak Picking Still Relies On Heuristics
Even after smoothing, the code still uses:
- height threshold
- prominence threshold
- first-peak or center-near-peak rules
These are smart heuristics, but still heuristics.
---
## 32. If You Want To Read The Code In The Best Order
If you are studying the code manually, this is the order I would recommend:
1. [shock_geometry.py](/home/anthonyy/links/scratch/reentry/orion/scripts/shock_geometry.py)
2. `extract_shock_surface.py` settings block
3. `sample_line()`
4. `find_first_peak_from_upstream()`
5. `find_peak_near_center()`
6. `fit_panel_model()`
7. `build_panel_line()`
8. `predictor_corrector_candidate()`
9. `extract_panel_surface()`
10. `process_case()`
11. `main()`
That order gives the cleanest learning path.
---
## 33. Final Simple Summary
If I had to explain the panel method to a toddler in one paragraph:
> We look for the shock by drawing lots of tiny lines in 3D. First we find the shock right at the front. Then we step outward in little rings. At each new place, we try to point the next tiny line in the direction we think the shock is bending. We sample the CFD values on that line, find the best bump, and save that point. When a whole ring has no more good bump, we stop. Then we connect all the saved points into a surface.

If you want, I can also make a second file called something like:
- `PANEL_CODE_WALKTHROUGH_WITH_COMMENTS.md`
where I literally copy small chunks of the code and explain each chunk immediately underneath it like a textbook.
