# Orion Analysis Assets

`analysis/` holds study-specific helper material that supports interpretation of the CFD runs but does not drive the production pipeline.

- `plot_residuals.m`, `plot_shock.m`, and `calcs.m`: interactive MATLAB helpers used during analysis.
- `orion_profile_digitization.json`: metadata exported by a plot-digitizing tool such as WebPlotDigitizer. It records how an Orion profile/reference plot was calibrated so the traced points can be reproduced later.
- `mesh_refinement_analysis.xlsx`: lightweight study spreadsheet for mesh-refinement review.

The digitization files are not solver inputs. They are lightweight provenance for traced reference curves and hand-extracted geometry/profile data.
