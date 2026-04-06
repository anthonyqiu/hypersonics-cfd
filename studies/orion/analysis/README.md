# Orion Analysis Assets

`analysis/` holds study-specific helper material that supports interpretation of the CFD runs but does not drive the production pipeline.

- `plot_residuals.m`, `plot_shock.m`, and `calcs.m`: interactive MATLAB helpers used during analysis.
- `plot_initial_search_line.m`: MATLAB viewer for the coarse/refined stagnation search-line profile exported by `python3 scripts/export_initial_search_line.py`.
- `mesh_refinement_analysis.xlsx`: lightweight study spreadsheet for mesh-refinement review.
