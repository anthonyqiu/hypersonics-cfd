# Orion Analysis Assets

`analysis/` holds study-specific helper material that supports interpretation of the CFD runs but does not drive the production pipeline.

- `matlab/`: interactive plotting and one-off calculation helpers used during analysis.
- `digitization/`: metadata exported by plot-digitizing tools such as WebPlotDigitizer. In this study, the JSON file records how an Orion profile/reference plot was calibrated so the traced points can be reproduced later.

The digitization files are not solver inputs. They are lightweight provenance for traced reference curves and hand-extracted geometry/profile data.
