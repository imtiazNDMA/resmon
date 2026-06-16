# Reservoir Monitoring & Analytics Platform

Disaster-management platform that monitors reservoirs from Sentinel-1 SAR + DEM and predicts the likelihood of a water release, to give downstream communities early flood warning. This glossary fixes the language; the full spec lives in `requirements.md`.

## Language

**Release event**:
The physical spillway/sluice discharge this platform warns about. It is *never directly observed* in the v1 data — weekly bulletins only show the storage decrement a week later. Always inferred, never measured.
_Avoid_: spill (informal), discharge (ambiguous with routine outflow)

**Release episode**:
A *derived, weakly-labelled* training/validation unit: a near-FRL peak followed by drawdown beyond the seasonal rule curve, reconstructed from the storage time series. The unit AC-5 backtests against. There are ~3 in the v1 dataset.

**Release-risk**:
The user-facing indicator — a transparent function of the forecast trajectory crossing reservoir-specific FRL/threshold bands, net of the rule curve. A *layer over the forecast*, not a separately-trained classifier (see ADR-0001). Expressed as a discrete level: Low / Watch / Warning / Imminent.

**Routine operational release**:
Year-round drawdown for irrigation/hydropower, *below* FRL, following the rule curve. Expected behaviour and an outflow term — explicitly NOT what release-risk alerts on. Conflating it with a release event causes both missed warnings and alarm fatigue.

**Rule curve**:
A reservoir's seasonal target-level schedule — the reference that separates routine operational release from a flood/emergency release event. Official BBMB curves are not published; v1 uses the bulletin **Normal Storage** column as a proxy (see ADR-0002). A climatological average, not an operational target — it may understate deliberate pre-monsoon flood-cushion drawdown.

**Forecast**:
The 1–14 day level/volume/fill-% prediction with intervals. The platform's *validated* layer (walk-forward, skill-vs-baseline). Release-risk inherits its skill and uncertainty.

**Ground truth**:
Official bulletin gauge readings (level, live storage, pct_filled) over ~11 years (2015-07 → 2026-04). A *historical bootstrap corpus only* — there are no current/future bulletins, so it trains and backtests the system but is never available in production (closed loop, ADR-0005). Records level/volume, never surface area — so validation is always *indirect*, through the rating curve.

**Estimation bridge**:
The model that maps SAR-extracted `surface_area → storage/level`, fit from ~11 years of paired (SAR area, bulletin storage). It is the *sole* production path to storage once bulletins stop — the thing that lets remote sensing replace bulletins. Realized as the [[blended rating curve]], not a neural net (the mapping is smooth and low-dimensional). The user's phrase "deep learning" refers to *this bridge*; genuine neural nets belong in SAR water segmentation, not here.
_Avoid_: "the deep learning model" (ambiguous — name the bridge or the segmentation model specifically)

**Closed loop**:
The production operating mode: SAR + DEM + forcing → models, with no bulletin/ground-truth input ever again. Accuracy is fixed by historical backtest; live monitoring is internal-consistency/drift only (ADR-0005).

**Rating curve**:
The per-reservoir calibrated mapping area↔storage(BCM)↔level(m), fit empirically from matched (extracted-area, bulletin) pairs. Owns nearly the full operating range for the pilot fleet, since the history reaches near-FRL.

**Hypsometric curve (DEM-derived)**:
The DEM-derived area–elevation–volume relationship, valid only above the DEM's acquisition-epoch waterline. In v1 it is *blended* into the rating curve (ADR-0004): it supplies independent geometry above the observed fill maximum up to FRL (the near-FRL release zone) and cross-checks the empirical fit in the overlap; the empirical fit owns the observed range.

**Blended rating curve**:
The single persisted curve combining the ground-truth-anchored empirical fit (observed range) with DEM-derived geometry (above observed max → FRL). `RatingCurve.fit_type = 'blended'`. Records both valid ranges and the DEM-epoch waterline.
