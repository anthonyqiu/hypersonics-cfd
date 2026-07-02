# Orion Mesh Notes

The active Orion workflow assumes symmetric meshes. Legacy full-domain meshes are
kept with `_full` names and are not used by the current case-generation workflow.

## Recorded Mesh Controls

These values record the mesh-generation controls used for the Orion refinement
sets. The first cell spacing is held fixed across the refinement levels.

| Mesh | First cell spacing [m] | Surface average element size [m] | Refinement-zone average element size [m] | Farfield average element size [m] |
| --- | ---: | ---: | ---: | ---: |
| Coarse | 1.00e-6 | 0.0225 | 0.18 | 11.25 |
| Medium | 1.00e-6 | 0.015 | 0.12 | 7.5 |
| Fine | 1.00e-6 | 0.01 | 0.08 | 10 |
| Very fine | 1.00e-6 | 0.008 | 0.064 | 8 |

## Near-Wall Spacing Note

Keeping the first cell spacing fixed at `1.00e-6 m` is acceptable for a shock
structure convergence study if the resulting wall `y+` remains sufficiently small.
For wall-resolved calculations, use `y+ < 1` as the practical check.

Because the first layer height is fixed, the mesh refinement is not fully
self-similar in the strict grid-convergence sense. This is usually defensible
when the target quantity is shock shape, shock location, or stand-off distance,
but wall heat flux, skin friction, and other boundary-layer quantities should be
checked with a dedicated near-wall refinement/y-plus assessment.
