# Blended rating curve: empirical fit anchored, DEM owns above-observed-max

## Context

V1 builds the DEM hypsometric curve (not deferred). But a DEM only captures terrain *above* the water surface at its own acquisition epoch — Copernicus GLO-30 is a ~2011–2015 composite, so below that epoch's waterline the reservoir bed is submerged and invisible. A naively flooded DEM curve is therefore valid only from the DEM-epoch waterline up to FRL, while the empirical curve (fit from bulletin `(level, storage, area)` pairs) is valid across the observed range (~10–100% for all three pilots). The two overlap in the upper-middle.

## Decision

Produce a single **blended** rating curve (`RatingCurve.fit_type = 'blended'`) per reservoir:

1. **DEM:** Copernicus GLO-30. Estimate the DEM-epoch waterline from the bulletin level nearest the DEM epoch.
2. **Shape:** flood the DEM within the AOI from the waterline to FRL → `area(elev)`, integrate → incremental `volume(elev)` above the waterline.
3. **Anchor:** the DEM supplies *shape*; the *absolute* offset is the empirical curve's storage at the waterline. The DEM never supplies submerged volume.
4. **Overlap (waterline → observed max):** DEM-vs-empirical agreement is a validation metric; on divergence beyond tolerance, trust the empirical curve (ground-truth-anchored) and flag.
5. **Above observed max → FRL:** the DEM curve is the *primary* extrapolator — independent near-FRL geometry instead of blind empirical extrapolation.

Persist both valid ranges and the DEM-epoch waterline with the curve.

## Consequences

- The DEM earns its v1 keep specifically in the near-FRL release zone, while ground truth governs the bulk range.
- Requires estimating each DEM-epoch waterline — a per-reservoir step with its own error, recorded with the curve.
- Rejected alternatives: pure-empirical (blind above observed max, the release zone) and pure-DEM (no submerged volume, no ground-truth anchor).
