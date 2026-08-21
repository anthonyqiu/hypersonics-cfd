---
title: Shock-Surface Deviation
aliases:
  - Surface deviation
  - Shock convergence metric
tags:
  - cfd
  - shock-extraction
  - mesh-convergence
  - orion
---

# Shock-Surface Deviation

## Purpose

The refinement study produces one extracted shock surface for each mesh:

1. Coarse
2. Medium
3. Fine
4. Very fine

The surfaces have different points, triangulations, and marching extents. A
point-to-surface distance over the full meshes would penalize a surface simply
because its extractor marched farther. The comparison instead represents each
surface in a body-fixed spherical frame:

$$
R=R(\vartheta,\varphi),
$$

where:

- $R$ is distance from the body stagnation point;
- $\vartheta$ is polar angle measured away from the upstream stagnation axis;
- $\varphi$ is azimuth around that axis.

The primary quantity is the common-support RMS difference normalized by the
Orion characteristic diameter:

$$
\frac{E_{\mathrm{RMS}}}{D},
\qquad D=5\ \mathrm{m}.
$$

> [!important]
> This measures agreement between two extracted surfaces. It is not error
> relative to an exact shock solution.

## Why Common Support Is Necessary

Suppose one extraction reaches $\vartheta=130^\circ$ and another reaches only
$\vartheta=105^\circ$. Comparing the complete surfaces makes the unmatched
outer region look like a large shape error, even if the overlapping portions
agree.

The raw surfaces are not cropped or overwritten. The comparison masks only the
non-overlapping region while calculating the metric.

At each azimuth, every surface has a largest polar angle to which the marching
algorithm succeeded. The common polar limit across all available refinement
surfaces for one Mach number is

$$
\vartheta_{\mathrm{common}}(\varphi)
=
\min_{k\in\{C,M,F,VF\}}
\vartheta_{\max,k}(\varphi).
$$

The valid three-dimensional comparison domain is therefore

$$
0\leq\vartheta\leq\vartheta_{\mathrm{common}}(\varphi),
\qquad 0\leq\varphi<2\pi.
$$

Using one limit for all three adjacent comparisons makes their errors directly
comparable. Put plainly: determine the maximum $\vartheta$ reached by each
surface, then use the minimum of those maxima. The cutoff may vary slightly
with azimuth.

## Algorithm

### 1. Build an azimuth grid

Use a shared periodic grid of 360 azimuth sectors:

$$
\varphi_j=\frac{2\pi j}{360}.
$$

For each extracted ray, calculate its azimuth and maximum polar angle. These
limits are periodically interpolated onto the common azimuth grid.

### 2. Determine the common polar extent

Calculate $\vartheta_{\mathrm{common}}(\varphi_j)$ using every available
refinement level. This same cutoff is used for coarse--medium, medium--fine,
and fine--very-fine.

### 3. Build the common angular grid

Create a polar grid from stagnation to the largest common cutoff. Along every
surface ray, interpolate the radial shock position:

$$
R_A(\vartheta_i,\varphi_j),
\qquad
R_B(\vartheta_i,\varphi_j).
$$

Keep a grid location only when

$$
\vartheta_i\leq\vartheta_{\mathrm{common}}(\varphi_j).
$$

This removes endpoint bias without modifying either extracted surface.

### 4. Calculate local differences

At each retained location,

$$
d_{ij}
=
\left|
R_A(\vartheta_i,\varphi_j)-R_B(\vartheta_i,\varphi_j)
\right|.
$$

Because both surfaces are evaluated along the same body-fixed direction, this
is their radial separation in that direction. It is not a nearest-neighbour
distance.

### 5. Apply solid-angle weighting

Equal increments of $\vartheta$ crowd together near the stagnation axis. The
solid-angle weight is therefore

$$
w_{ij}\propto
\sin(\vartheta_i)\,\Delta\vartheta\,\Delta\varphi.
$$

The mean and RMS differences are

$$
E_{\mathrm{mean}}
=
\frac{\sum w_{ij}d_{ij}}{\sum w_{ij}},
$$

$$
E_{\mathrm{RMS}}
=
\sqrt{
\frac{\sum w_{ij}d_{ij}^2}{\sum w_{ij}}
}.
$$

The script also reports the weighted 95th percentile and maximum. This is an
angular weighting, not the physical area of the triangulated shock surface.

### 6. Report stand-off separately

The stagnation stand-off distance is

$$
\Delta=R(0,\varphi).
$$

The value is independent of azimuth at the seed node. The script reports both
stand-off values and

$$
\frac{|\Delta_A-\Delta_B|}{D}.
$$

Stand-off is kept separate because the angular weight gives the single
stagnation node little influence on the surface RMS.

## Refinement Comparisons

Only consecutive mesh levels are compared:

| Order | Comparison |
|---|---|
| 1 | Coarse--Medium |
| 2 | Medium--Fine |
| 3 | Fine--Very fine |

The desired convergence trend is

$$
E_{F,VF}<E_{M,F}<E_{C,M}.
$$

If that trend does not occur, check extractor sensitivity and CFD convergence
before interpreting the result as physical mesh dependence.

## Shock-Extraction Convergence Study

CFD mesh convergence and shock-extraction convergence are different questions. Hold
one CFD field fixed and vary only:

- `dn`: spacing along each local search line;
- `dt`: spacing between marched shell layers.

Run:

```bash
python3 scripts/shock_extraction_convergence.py m6_medium
```

The flow field is read and differentiated once. Five extraction settings are
then evaluated:

| Sweep | Settings |
|---|---|
| `dn` | 0.020, 0.010, 0.005 m at `dt=0.10 m` |
| `dt` | 0.20, 0.10, 0.05 m at `dn=0.010 m` |

Outputs:

```text
studies/orion/data/cases/m6_medium/shock_extraction_convergence/
├── dt0p05_dn0p010/
├── dt0p10_dn0p005/
├── dt0p10_dn0p010/
├── dt0p10_dn0p020/
├── dt0p20_dn0p010/
├── comparisons.csv
└── runs.csv
```

`runs.csv` records stand-off, surface size, termination, and runtime.
`comparisons.csv` records each coarser setting against the finest setting in
the same one-parameter sweep.

Extractor-induced changes should be much smaller than the CFD
fine--very-fine change. If they are comparable, the extraction settings are
not yet fine enough for a CFD mesh-convergence claim.

## Running the Refinement Comparison

```bash
python3 scripts/compare_shock_surfaces.py
```

Output:

```text
studies/orion/data/shock_surface_deviation_refinement.csv
```

Plot in MATLAB:

```matlab
plot_shock_surface_deviation
```

## TikZ: Common Polar Support

> [!note]
> Obsidian needs a TikZ rendering plugin such as TikZJax to render this block.

```latex
\documentclass[tikz,border=6pt]{standalone}
\usetikzlibrary{arrows.meta}
\begin{document}
\begin{tikzpicture}[>=Latex, font=\sffamily]
  \coordinate (O) at (0,0);
  \draw[->] (O) -- (5.4,0) node[right] {upstream axis};
  \draw[very thick, blue!70!black]
    plot[smooth] coordinates {(1.7,0) (2.1,0.7) (2.3,1.5) (2.1,2.3) (1.6,3.0)};
  \draw[very thick, red!75!black]
    plot[smooth] coordinates {(1.9,0) (2.3,0.7) (2.5,1.5) (2.3,2.3)};

  \draw[dashed,->] (O) -- (2.3,2.3);
  \draw[->] (0.8,0) arc[start angle=0,end angle=45,radius=0.8];
  \node at (1.2,0.45) {$\vartheta$};
  \draw[<->, thick] (2.1,2.1) -- (2.3,2.3)
    node[midway,right] {$d_{ij}$};

  \node[blue!70!black, above left] at (1.6,3.0) {$S_A$};
  \node[red!75!black, right] at (2.3,2.3) {$S_B$};
  \node[align=center] at (3.4,-0.8)
    {Compare $R_A$ and $R_B$ only up to\\
     $\vartheta_{\mathrm{common}}(\varphi)$.};
\end{tikzpicture}
\end{document}
```

## Interpretation Checklist

- [ ] Same Mach number, angle of attack, coordinate origin, and units.
- [ ] Raw surfaces retained; trimming applied only in the metric.
- [ ] Common-support RMS and stand-off difference both inspected.
- [ ] Adjacent-pair differences decrease with refinement.
- [ ] Extractor sensitivity is smaller than CFD mesh sensitivity.
- [ ] A large maximum has been checked for a local defect.
