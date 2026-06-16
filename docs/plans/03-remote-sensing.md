# Remote-Sensing Pipeline — Implementation Plan

**Pipeline:** `pipelines/remote_sensing/` (BRONZE → SILVER: Sentinel-1 GRD + DEM → water mask → surface area → `Observation`)
**Owner track:** Remote Sensing
**Stack:** Google Earth Engine via `geemap` + `xee` + `earthengine-api`; Python; `uv`; orchestrated by Prefect 2.
**Contract version:** emits `Observation` `contract_version: 2` (`docs/contracts/observation-and-abt.md`).
**Status:** Planning. PLANNING ONLY — no application code in this document.

This plan covers everything between a published Sentinel-1 scene in GEE and a persisted `Observation` row plus its companion per-reservoir **blended rating curve / hypsometric** artifact. It is written to be honest about the closed loop ([ADR-0005](../adr/0005-closed-loop-no-live-ground-truth.md)): SAR extraction is one of only two production components between the satellite and a storage number, with **no live ground truth to catch its errors** — so confidence, provenance, and the staged extraction harness ([ADR-0007](../adr/0007-water-extraction-harness.md)) are first-class, not afterthoughts.

---

## 1. Scope & owned requirements

### Owned (this pipeline is the implementer)

| ID | Requirement | This plan covers it in |
| --- | --- | --- |
| **FR-RS-1** | Retrieve latest S1 GRD per AOI; **fixed relative orbit + pass direction** per reservoir (or incidence-angle normalization); AOI sized to FRL max extent; AOI provenance from JRC GSW; versioned GeoJSON → PostGIS with manual override | §5 step 1–2, §6 reservoir config, §7.3 |
| **FR-RS-2** | SAR preprocessing (calibration → γ⁰, speckle filter, **radiometric terrain flattening**, **DEM-based layover/shadow masking**) → binary water mask via **ML extraction** (clustering K-means/GMM/Otsu VH-dominant; path to RF/U-Net); **pluggable & versioned** | §5 steps 3–6, §7.1 extractor interface |
| **FR-RS-3** | True-area via `ee.Image.pixelArea()` / equal-area; per-area **quality/confidence** (cluster separability, mask compactness, layover/shadow fraction) | §5 steps 7–8, §7.2 |
| **FR-RS-4** | Derive volume + level by intersecting extent with **DEM hypsometric curve** (DEM valid only above acquisition waterline) | §5 step 9, §6 hypsometric artifact, §4 (handoff to GT/ABT) |
| **FR-RS-5** | Persist per-acquisition results + water-mask reference; emit downstream trigger | §5 step 10–11, §7.2 Observation schema |
| **FR-RS-6** | Record full provenance (scene IDs, processing params, AOI version) | §5 step 10, every step writes `processing_params` |

### Foundational / accuracy requirements this pipeline materially gates

- **NFR-ACC-1 / AC-2 (foundational gate):** ML-extracted-area→volume/level must agree with bulletins within tolerance (fill-% MAE ≤ 5–10%). The extractor + its co-fit curve are selected here (the harness lives jointly with Data-Engineering ground-truthing — §8.4 of spec / [ADR-0007](../adr/0007-water-extraction-harness.md)). This pipeline produces the **areas and masks** that ground-truthing validates and selects on. See §10.
- **AC-3:** estimation accuracy on holdout — depends on this pipeline's area quality + the blended curve.
- **Constraint §10 (spec):** ice/frozen surface, wind-roughened water, terrain shadow are explicit failure modes — handled in §5 step 5–6 and §9.

### Explicitly NOT in scope (owned elsewhere)

- Ground-truth bulletin ingestion, temporal nearest-match, residual computation, ABT assembly → **Data Engineering** (FR-DE / FR-GT).
- The **empirical** rating-curve fit and final **blended** curve fit-metrics/selection → ground-truthing (FR-GT-4) jointly. This pipeline supplies the **DEM/hypsometric half** of the blend (per [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md)) and the extracted areas; it does not own the empirical regression.
- Forecasting, release-risk, MLflow model serving → **AI/ML**.
- DB schema/migrations for `Reservoir`, `Observation`, `RatingCurve`, PostGIS tables → **DB team** (we write to those tables via the data-access layer).
- Catchment delineation (FR-DE-7) — separate concern even though it shares the DEM.

---

## 2. Upstream dependencies (things we need before/while building)

| Dependency | Provided by | What we need | Blocking? |
| --- | --- | --- | --- |
| **GEE auth / data-access layer** | Platform team | Thin, swappable client that initializes `earthengine-api` (service-account or non-commercial credentials from secret store, NFR-SEC-2), exposes `ImageCollection`/`Image` access and `xee.open_dataset`. We code **against this interface**, never `ee.Initialize()` directly, to preserve the openEO/Planetary-Computer/SNAP migration path (§4.4). | Yes (stub acceptable early via a fake returning canned `ee` objects) |
| **DB schema** | DB team | `Reservoir`, `Observation` (per frozen contract), `RatingCurve`, PostGIS geometry columns for AOI + water masks, object-store keys for raster/mask exports. | Partial — can write to local Parquet/GeoTIFF + stub repository until tables land |
| **Reservoir AOI / orbit config** | DB / config team (we author the schema, §6) | Per-reservoir: dam-point seed coords, frozen relative-orbit number, pass direction, AOI GeoJSON version, FRL, live capacity. **This is the cross-team config decision — see §11.** | Yes — pipeline cannot fix acquisition geometry without it |
| **JRC GSW max-extent** | GEE catalog (`JRC/GSW1_4/GlobalSurfaceWater`) | Source for reproducible AOI derivation (FR-RS-1). | No (one-time AOI bootstrap) |
| **DEM** | GEE catalog (`COPERNICUS/DEM/GLO30`, fallback `USGS/SRTMGL1_003`) | Terrain flattening, layover/shadow geometry, hypsometric curve. | Yes for FR-RS-2/4 |
| **Bulletin ground truth** | Data-Engineering / `dataExtractor` | Needed only by the **harness** (extractor selection, DEM-epoch waterline anchor). Not needed for routine extraction. | No (only for AC-2 calibration) |
| **Prefect 2 runtime** | Platform/Data-Eng | Deployment, scheduling (S1 revisit cadence + daily new-scene check, NFR-TIME-1), retries with backoff (NFR-REL-1). | No (functions runnable standalone) |

---

## 3. Downstream consumers (what depends on our output)

| Consumer | Consumes | Contract |
| --- | --- | --- |
| **Data Engineering — ground-truthing (FR-GT)** | `Observation` rows (`surface_area`, `area_confidence`, `extraction_method/version`, mask refs, provenance); the **DEM hypsometric curve points**; the extractor **plugin** (run on matched scenes, FR-GT-2). | `Observation` schema §7.2; extractor interface §7.1; hypsometric handoff §6.3 |
| **Data Engineering — ABT (FR-ABT / FR-DE-3)** | `surface_area`, `area_confidence`, `derived_volume/level`, `extraction_method`, `is_extrapolated` flag → satellite-derived block of the ABT. | ABT contract §2 of `observation-and-abt.md` |
| **AI/ML** | Indirect — via ABT. The forecaster trains on **SAR-derived state** ([ADR-0005](../adr/0005-closed-loop-no-live-ground-truth.md)), so our area→storage values are the training signal. | ABT |
| **Backend API / UI (FR-API-2, FR-UI-1)** | Water-mask GeoJSON + AOI polygons for Leaflet; last-acquisition date / freshness. | GeoJSON export §7.2 |
| **MLflow** | Per-acquisition extraction metrics; harness candidate metrics for extractor selection ([ADR-0007](../adr/0007-water-extraction-harness.md)). | §10 |

---

## 4. Where the rating curve / volume handoff sits (read this before §5 step 9)

Per [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md), the production **rating curve is blended**: empirical fit owns the observed range; the **DEM hypsometric curve owns above-observed-max → FRL** and supplies independent near-FRL geometry. Ownership split:

- **This pipeline produces:** the **DEM hypsometric `area(elev)` and incremental `volume(elev)` shape**, flooded within the AOI from the **DEM-epoch waterline** up to FRL (§6.3). It does **not** know the absolute storage offset (that comes from the empirical curve's storage at the waterline).
- **Ground-truthing (FR-GT-4) produces:** the empirical fit, the anchor/offset, the overlap validation, and the final `RatingCurve(fit_type='blended')` row.
- **At routine inference,** `derived_volume`/`derived_level` in `Observation` are computed by applying **the latest persisted blended `RatingCurve`** (read-only) to `surface_area`. **Until a curve exists, both are `NULL`** (per the frozen contract — NULL, never silent zero). The `is_extrapolated` flag is set when `surface_area` exceeds the curve's observed-max area.

This keeps the chicken-and-egg ([ADR-0007](../adr/0007-water-extraction-harness.md)) honest: each extractor candidate gets its **own co-fit curve** during selection; in production a single promoted `(extractor + curve)` pair runs.

---

## 5. Algorithm / processing design — step-by-step (SAR → mask → area → Observation)

All server-side heavy lifting stays in GEE (`ee.Image`/`ee.ImageCollection`); only small reductions (areas, histograms, mask GeoTIFF/GeoJSON exports) come back to Python. `xee` is used where an `xarray` view is convenient (e.g. pulling the masked-backscatter array for sklearn-based GMM/RF when not done server-side). Every step appends to a `processing_params` dict that becomes the `Observation.processing_params` jsonb (FR-RS-6).

### Step 0 — Scene discovery & geometry fixing (FR-RS-1)
- Load `COPERNICUS/S1_GRD`, filter: `filterBounds(aoi)`, `filterDate(window)`, `eq('instrumentMode','IW')`, `listContains('transmitterReceiverPolarisation','VV')` and `'VH'`, `eq('resolution_meters', 10)`, `eq('orbitProperties_pass', cfg.pass_direction)`, `eq('relativeOrbitNumber_start', cfg.relative_orbit)`.
- The orbit + pass filter **enforces fixed acquisition geometry per reservoir** so the area time series is physically comparable. If config requests incidence-angle normalization mode instead of a fixed orbit, defer to a documented v2 path (normalize γ⁰ by local incidence angle); v1 default is **fixed orbit/pass** (simpler, the spec's preferred option).
- Group scenes from the same pass into one acquisition (S1 GRD products can be tiled); `scene_ids` becomes a list (FR-RS-6).
- Idempotency: key on `(reservoir_id, acquisition_date_IST)`; skip if `Observation` already exists for that key unless `--reprocess`.
- **Failure handling:** no in-orbit scene in window → emit nothing, log gap, let graceful-degradation (NFR-REL-6) serve last-known state downstream.

### Step 1 — AOI resolution
- Read the **versioned AOI GeoJSON** for the reservoir from config/PostGIS (§6.2). Do NOT re-derive at runtime. (Derivation is the one-time bootstrap, step in §7.3 task T-02.)
- Clip all subsequent ops to this AOI (sized to FRL max extent incl. upstream arms, FR-RS-1).

### Step 2 — Border-noise & thermal-noise handling
- S1 GRD in GEE is already calibrated to σ⁰ (dB) but retains border/low-backscatter artifacts. Apply edge/border-noise mask (drop `< -30 dB` extreme low edges) and keep angle band for terrain flattening.

### Step 3 — Calibration to backscatter (FR-RS-2)
- GEE `COPERNICUS/S1_GRD` bands `VV`,`VH` are σ⁰ in dB. For terrain flattening we need **linear power**, so convert: `pow = 10^(dB/10)`. Record calibration convention in `processing_params`.

### Step 4 — Radiometric terrain flattening → γ⁰ (FR-RS-2, critical Himalayan terrain)
- Use the DEM (`COPERNICUS/DEM/GLO30`) to compute **local incidence angle** and apply **radiometric terrain flattening** to produce **gamma-0 (γ⁰)** backscatter, removing topographic brightness/foreshortening that otherwise corrupts water/land separation on steep slopes.
- Reference implementations: Vollrath et al. "Angular-based radiometric slope correction" (the volumetric model) ported to EE, or `ee` adaptations of the SNAP RTC flow. Pick the **volumetric model** (robust, no external assets). Pin the chosen algorithm + DEM asset id + version in `processing_params`.
- Reproject DEM to the S1 grid; compute slope/aspect → local incidence angle → correction factor; apply to linear power; convert back to dB for the extractor.

### Step 5 — DEM-based layover & shadow masking (FR-RS-2, critical)
- From DEM + S1 viewing geometry (`angle` band, look direction from orbit/pass), compute **layover** (local incidence ≤ 0 relative to range) and **radar shadow** masks.
- Produce a per-pixel `layover_shadow` mask; **exclude those pixels** from extraction and area.
- Compute `layover_shadow_fraction = masked_area / aoi_area` → goes straight into `Observation.layover_shadow_fraction` and **feeds `area_confidence`** (high fraction lowers confidence — a reservoir arm hidden under layover is unmeasured, not empty).

### Step 6 — Speckle filtering (FR-RS-2)
- Apply a refined Lee / Gamma-MAP-style multiplicative-noise filter. Default: **Refined Lee** (7×7) implemented server-side in EE, or a simpler boxcar/focal-median as a fast fallback. Speckle filter is a **plugin parameter** (kernel, window) recorded in `processing_params` — speckle choice interacts with extractor choice and is co-selected in the harness.
- Optionally use a **multitemporal speckle filter** (mean of co-orbit stack) for stability when a per-reservoir stack is available — improves winter-ice/wind robustness (§9).

### Step 7 — Water extraction (FR-RS-2, ML-based, pluggable) → binary mask
- Invoke the configured **extractor plugin** (§7.1). VH-dominant (water is specular → very low VH backscatter), VV as secondary feature.
- v1 cold-start candidates ([ADR-0007](../adr/0007-water-extraction-harness.md)):
  - **`Otsu-VH`** — per-scene adaptive bimodal threshold on VH histogram (satisfies "not a fixed global threshold"). Implemented via EE histogram reduction; refined with a bimodality/edge-sampling (Donchyts) variant to stabilize the histogram on land-dominated AOIs.
  - **`KMeans[VV,VH]`** — k=2 unsupervised cluster, water = low-backscatter cluster.
  - **`GMM[VV,VH]`** — 2-component Gaussian mixture; gives soft posterior → better separability metric.
  - **Path to supervised:** `RandomForest` pixel classifier and **`U-Net`**, trained on **weak labels** harvested from low-residual/high-confidence unsupervised masks (FR-GT-6). RF can run server-side (`ee.Classifier.smileRandomForest`); U-Net runs off-EE on exported `xee` patches (kept behind the same plugin interface).
- Post-process: keep the **connected component containing the dam point**, morphological open/close to remove speckle islands, fill holes. Clip to AOI.
- Output: binary `water_mask` (`ee.Image` 0/1) + soft scores where available.

### Step 8 — Confidence / quality metrics (FR-RS-3)
Compute and combine into `area_confidence ∈ [0,1]`:
- **Cluster separability** — for KMeans/GMM: Otsu between-class variance ratio / GMM component separation (Bhattacharyya or Fisher distance between water & land modes). Low separability (e.g. wind-roughened water raising water backscatter toward land) → low confidence.
- **Mask compactness** — perimeter²/area or boundary-roughness of the water polygon; a fragmented, noisy mask is suspect.
- **Layover/shadow fraction** (step 5) — high fraction caps confidence.
- **Frozen/ice & wind flags** (§9) — set when separability collapses or seasonal context indicates; degrade confidence and tag in `processing_params`.
- Persist component sub-scores in `processing_params` so ground-truthing can break out robustness by regime ([ADR-0007](../adr/0007-water-extraction-harness.md)).

### Step 9 — True surface area (FR-RS-3)
- `area_img = water_mask.multiply(ee.Image.pixelArea())`; `surface_area = area_img.reduceRegion(sum, aoi, scale=10)` → m² → **km²**. NEVER raw pixel counts; `pixelArea()` is true-area (equal-area). Record `scale` and projection.
- Apply the **blended `RatingCurve`** (read-only, §4) → `derived_volume` (BCM), `derived_level` (m). If no curve yet → both NULL. Set `is_extrapolated` if area > curve observed-max area.

### Step 10 — Provenance assembly (FR-RS-6)
Assemble the `Observation` row (§7.2): `scene_ids`, `orbit_relative`, `pass_direction`, `aoi_version`, `extraction_method`, `extraction_version`, full `processing_params` (calibration, terrain-flattening algo + DEM id, speckle kernel, extractor hyperparams, thresholds, confidence sub-scores, ice/wind flags).

### Step 11 — Persist & trigger (FR-RS-5)
- Write water mask raster → object store (key → `water_mask_ref`); export AOI-clipped **GeoJSON** mask for Leaflet (FR-API-2/FR-UI-1).
- Upsert `Observation` via the DB data-access layer (idempotent on `(reservoir_id, acquisition_date)`).
- Emit Prefect downstream trigger → Data-Engineering run (FR-RS-5, §4.3).

---

## 6. Module / directory structure

```
pipelines/remote_sensing/
├── __init__.py
├── config/
│   └── reservoirs.schema.json        # reservoir orbit/AOI config JSON-Schema (§11 cross-team)
├── gee/
│   ├── client.py                     # thin wrapper over platform GEE data-access layer (swappable)
│   ├── collections.py                # asset IDs, band constants (S1_GRD, GLO30, GSW, SRTM)
│   └── export.py                     # raster/GeoJSON export helpers (object store)
├── aoi/
│   ├── derive.py                     # FR-RS-1 JRC GSW max-extent → AOI bootstrap (one-time)
│   └── repository.py                 # versioned AOI GeoJSON ↔ PostGIS read/write
├── preprocess/
│   ├── calibrate.py                  # σ⁰ dB ↔ linear, border/thermal noise
│   ├── terrain_flatten.py            # radiometric terrain flattening → γ⁰ (FR-RS-2)
│   ├── layover_shadow.py             # DEM-based layover/shadow mask (FR-RS-2)
│   └── speckle.py                    # Refined Lee / multitemporal (pluggable param)
├── extract/
│   ├── base.py                       # WaterExtractor ABC — the plugin interface (§7.1)
│   ├── registry.py                   # name+version → extractor lookup (pluggable/versioned)
│   ├── otsu_vh.py                    # cold-start
│   ├── kmeans.py                     # cold-start
│   ├── gmm.py                        # cold-start
│   ├── random_forest.py             # supervised (weak labels)  [staged]
│   └── unet.py                       # supervised (off-EE, xee patches) [staged]
├── confidence.py                     # FR-RS-3 separability/compactness/layover/ice/wind
├── area.py                           # FR-RS-3 pixelArea() true-area + curve apply
├── hypsometry/
│   ├── dem_curve.py                  # FR-RS-4 DEM flood → area(elev)/volume(elev) (ADR-0004 half)
│   └── waterline.py                  # DEM-epoch waterline estimation helper
├── observation.py                    # assemble + validate Observation against contract v2
├── repository.py                     # Observation/RatingCurve read-write via DB access layer
├── flow.py                           # Prefect 2 flow: discover→preprocess→extract→area→persist
└── tests/
    ├── unit/ ...                     # see §9
    ├── integration/ ...
    └── fixtures/                     # canned ee responses, small clipped GeoTIFFs
```

---

## 7. Interfaces / contracts exposed

### 7.1 Water-extraction plugin interface (the pluggable, versioned extractor — FR-RS-2, [ADR-0007](../adr/0007-water-extraction-harness.md))

```python
# extract/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import ee

@dataclass(frozen=True)
class ExtractionResult:
    water_mask: ee.Image          # binary 0/1, AOI-clipped, dam-component only
    soft_score: ee.Image | None   # per-pixel water posterior/score if available (GMM/U-Net)
    separability: float           # cluster/mode separation [0,1] (FR-RS-3)
    threshold_used: float | None  # for Otsu/threshold methods (provenance)
    diagnostics: dict             # method-specific, → processing_params (FR-RS-6)

class WaterExtractor(ABC):
    name: str                     # e.g. "otsu_vh", "kmeans", "gmm", "unet"
    version: str                  # semver of THIS extractor impl (→ extraction_version)
    requires_labels: bool         # False for unsupervised cold-start, True for RF/U-Net

    @abstractmethod
    def extract(
        self,
        backscatter: ee.Image,    # γ⁰ VV+VH, speckle-filtered, terrain-flattened (dB)
        aoi: ee.Geometry,
        dam_point: ee.Geometry,   # seed for connected-component selection
        valid_mask: ee.Image,     # 1 where NOT layover/shadow/border
        *,
        context: dict,            # season/regime hint, reservoir_id, acquisition_date
    ) -> ExtractionResult: ...

    def fit(self, training_patches, labels) -> None:   # no-op for unsupervised
        ...
```
- Discovered via `extract/registry.py` keyed by `(name, version)`; selection + promotion governed by the harness ([ADR-0007](../adr/0007-water-extraction-harness.md)), tracked in MLflow. The flow reads `extraction_method`/`extraction_version` from config so the promoted pipeline is swappable without code change.

### 7.2 `Observation` output schema (frozen contract v2 — emitted)
We emit exactly the `Observation` table from `docs/contracts/observation-and-abt.md` §1. Key columns we are responsible for populating correctly:

| Column | Unit | Null | Source step |
| --- | --- | --- | --- |
| `reservoir_id`, `acquisition_date` (IST) | — | no (PK) | step 0 |
| `surface_area` | km² | no | step 9 (`pixelArea()`) |
| `area_confidence` | 0–1 | no | step 8 |
| `derived_volume` | BCM | yes (NULL until curve) | step 9 |
| `derived_level` | m | yes (NULL until curve) | step 9 |
| `water_mask_ref` | — | no | step 11 |
| `extraction_method`, `extraction_version` | — | no | step 7 |
| `scene_ids` (text[]) | — | no | step 0 |
| `orbit_relative` (int), `pass_direction` (ASC/DESC) | — | no | step 0 (from config) |
| `aoi_version` | — | no | step 1 |
| `layover_shadow_fraction` | 0–1 | no | step 5 |
| `processing_params` (jsonb) | — | no | steps 3–10 |

**Stub rule (honored):** synthetic rows from inverting a rough bulletin curve carry `extraction_method='stub'` so DE/ML can start before real SAR lands and trivially filter them.

### 7.3 Reservoir config schema for orbit/AOI (we author; DB/config team stores — **§11 cross-team decision**)

```jsonc
// config/reservoirs.schema.json (per reservoir)
{
  "reservoir_id": "gobind_sagar",          // stable key, matches Reservoir.id
  "name": "Gobind Sagar (Bhakra Dam)",
  "basin": "Sutlej",
  "dam_point": { "lat": 31.4106, "lon": 76.4332 },   // SEED for AOI derivation + component pick
  "acquisition": {
    "mode": "fixed_orbit",                  // "fixed_orbit" (v1 default) | "incidence_normalized"
    "relative_orbit": 165,                  // FROZEN per reservoir — see §11
    "pass_direction": "DESC",               // "ASC" | "DESC" — FROZEN per reservoir
    "polarisations": ["VV", "VH"]
  },
  "aoi": {
    "geojson_ref": "aoi/gobind_sagar/v3.geojson",  // versioned, → PostGIS
    "aoi_version": "v3",
    "derivation": {                          // FR-RS-1 provenance, JRC GSW bootstrap
      "source": "JRC/GSW1_4/GlobalSurfaceWater",
      "occurrence_threshold_pct": 50,
      "buffer_m": 300,
      "manual_override": false
    }
  },
  "frl_m": 512.06,
  "live_capacity_bcm": 6.229,
  "dem_asset": "COPERNICUS/DEM/GLO30"
}
```
The DB/config team must persist: `relative_orbit`, `pass_direction`, `dam_point`, versioned AOI GeoJSON, `frl_m`, `live_capacity_bcm`, with **manual-override** per reservoir (FR-RS-1). These three frozen-orbit numbers are the gating decision (§11).

### 7.4 DEM hypsometric handoff (to ground-truthing for the blend, [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md))
`hypsometry/dem_curve.py` exposes:
```python
def dem_hypsometric_shape(
    reservoir_id: str, aoi: ee.Geometry, dem: ee.Image,
    frl_m: float, dem_epoch_waterline_m: float,
) -> DemCurveShape:   # area(elev) samples + incremental volume(elev) above waterline
```
Returns **shape only** (no absolute offset), the DEM-epoch waterline used, and the valid range `[waterline_m, FRL]`. Ground-truthing anchors and blends it (FR-GT-4). Persisted into the `RatingCurve` row's DEM-prior component.

---

## 8. Library choices

| Need | Library | Notes |
| --- | --- | --- |
| EE compute / collections | `earthengine-api` (behind platform access layer) | Never `ee.Initialize()` directly — swappable backend (§4.4) |
| EE convenience, viz, export | `geemap` | Mask GeoJSON/GeoTIFF export, map QA |
| EE → xarray | `xee` | Pull masked backscatter patches for off-EE GMM/RF/U-Net + QA |
| Numeric / clustering off-EE | `numpy`, `scikit-learn` | GMM, KMeans cross-checks, separability metrics |
| Geometry / IO | `shapely`, `geopandas`, `rasterio` | AOI handling, mask polygonization, GeoTIFF |
| Schema validation | `pydantic` (Observation model) + `pandera` (tabular gates, NFR-TEST-1) | Validate against frozen contract before write |
| Orchestration | `prefect` (2.x) | Flow, retries+backoff (NFR-REL-1), scheduling |
| Experiment tracking | `mlflow` | Harness candidate metrics, extractor selection ([ADR-0007](../adr/0007-water-extraction-harness.md)) |
| Deep segmentation (staged) | `torch` + `segmentation-models-pytorch` | U-Net only when weak labels exist (FR-GT-6) |
| Env / packaging | `uv` | Lockfile, reproducibility (NFR-MNT-1) |

---

## 9. Failure modes & robustness (ice / wind / shadow — spec §10 constraint)

| Failure | Detection | Mitigation in this pipeline |
| --- | --- | --- |
| **Frozen / ice-covered surface (winter)** | Separability collapse (water mode merges with land), seasonal context (winter months), VH not specular over ice | Set `ice_suspect` flag in `processing_params`; **degrade `area_confidence`**; harness breaks out a **winter-ice regime** metric and disqualifies extractors that collapse on ice ([ADR-0007](../adr/0007-water-extraction-harness.md)). Multitemporal speckle helps. Do not silently report shrunken area. |
| **Wind-roughened water** | VH backscatter of water rises toward land → low cluster separability, larger overlap in GMM | Low confidence + `wind_suspect` flag; prefer VH; widen uncertainty downstream; harness's wind-roughened regime metric. |
| **Terrain shadow / layover** | DEM-geometry mask (step 5) | Exclude pixels, report `layover_shadow_fraction`; cap confidence; fixed orbit/pass keeps the masked region consistent across time so the area series stays comparable. |
| **No in-orbit scene this window** | empty collection (step 0) | Emit nothing; graceful degradation downstream (NFR-REL-6); freshness flag. |
| **Border/thermal noise** | extreme low-dB edge pixels | Border mask (step 2). |
| **GEE quota/availability** | API errors | Prefect retry + exponential backoff (NFR-REL-1); batch within quota; cache scene metadata. |

---

## 10. Testing & validation

**Unit (mockable, no GEE):**
- Calibration dB↔linear round-trip; `pixelArea()` area math on synthetic masks (true-area vs naive pixel-count divergence asserted).
- Confidence metric monotonicity (separability↓ ⇒ confidence↓; layover_fraction↑ ⇒ confidence↓).
- Extractor registry: `(name, version)` resolution; ABC compliance for each extractor.
- `Observation` pydantic/pandera validation against the **frozen contract v2** — column presence, units, null rules (`derived_volume` NULL allowed; `surface_area` not). CI fails on contract drift without a `contract_version` bump.

**Integration (small canned GEE fixtures / `xee` patches):**
- Full flow on a clipped scene → produces a valid `Observation` + mask GeoJSON; idempotent re-run upserts, no duplicate.
- Terrain-flattening + layover/shadow on a steep synthetic DEM tile (regression for the Himalayan case).
- Fixed-orbit filter actually pins `relativeOrbitNumber_start` / pass.

**Validation against ground-truthing (the real accuracy gate — AC-2 / NFR-ACC-1):**
- Run the **[ADR-0007](../adr/0007-water-extraction-harness.md) harness** jointly with Data-Engineering: each cold-start extractor extracts area on bulletin-matched scenes (FR-GT-2), co-fit its own blended curve, score **derived fill-% MAE vs bulletins on walk-forward / leave-one-season-out**, broken out by **monsoon / winter-ice / wind** regime. Select the **robust** pipeline, register in MLflow, keep pluggable. This pipeline owns the extraction + area + DEM-curve-shape half of that loop.
- Backtest hook for AC-12 / NFR-TEST-3: include a near-FRL episode so extraction is exercised at high-water (where AOI sizing to FRL matters most).

**Acceptance mapping:**
- **AC-2 (foundational gate):** our areas + DEM-curve shape feed the matched-pair validation; the selected extractor+curve must hit fill-% MAE ≤ 5–10%. This pipeline is the input side of the gate.
- **AC-3:** estimation accuracy on holdout — bounded by area quality + the blended curve.
- **AC-7 / NFR-TIME-1:** new S1 detected & processed within 24 h (Prefect daily new-scene check + revisit-cadence schedule).
- **AC-12:** pandera data-validation gates + the regression backtest run in CI.

---

## 11. Risks & open decisions

| # | Decision / risk | Owner / who must act | Default if unresolved |
| --- | --- | --- | --- |
| **D1** | **Frozen relative-orbit number + pass direction for each of the 3 pilot reservoirs.** This is the headline cross-team item: it must be chosen (best AOI coverage + acceptable revisit) and **stored in the reservoir config (§7.3) by the DB/config team**. Mixing orbits breaks area-series comparability (FR-RS-1). | RS picks (orbit-coverage analysis); **DB/config team stores** | Pick the descending pass with fullest AOI footprint per reservoir; document per-reservoir. |
| **D2** | `fixed_orbit` vs `incidence_normalized` mode. v1 plan defaults to **fixed_orbit**; incidence normalization deferred to v2. | RS | fixed_orbit |
| **D3** | Terrain-flattening algorithm (volumetric angular slope-correction vs SNAP-RTC port) — affects γ⁰ quality on steep terrain. | RS | Volumetric model (no external assets). |
| **D4** | Speckle filter (Refined Lee vs multitemporal vs focal-median) — co-selected with extractor in harness. | RS + harness | Refined Lee 7×7; multitemporal when stack available. |
| **D5** | DEM-epoch waterline per reservoir (needed for the DEM-curve shape, [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md)). Each has its own error. | RS + ground-truthing | Bulletin level nearest Copernicus GLO-30 epoch (~2011–2015). |
| **D6** | `area_confidence` exact formula weighting (separability vs compactness vs layover vs ice/wind). | RS, tuned against harness regime breakouts | Weighted product, documented in `confidence.py`. |
| **D7** | Object-store backend + `water_mask_ref` URI scheme for raster/mask exports. | DB/platform | Local/object store key; finalize with DB team. |
| **D8** | AOI occurrence threshold + buffer for JRC GSW derivation; **each AOI eyeballed once before freezing** (FR-RS-1). | RS (one-time) | 50% occurrence, ~300 m buffer, manual review. |

---

## 12. Task breakdown (sequenced; T-01…)

| Task | Description | Depends on | Acceptance check |
| --- | --- | --- | --- |
| **T-01** | GEE client wrapper over platform data-access layer; collection/band constants; `uv` env. | Upstream GEE layer (or stub) | `client.py` lists ≥1 S1 scene over a test AOI via the swappable interface; no direct `ee.Initialize`. |
| **T-02** | AOI bootstrap from JRC GSW max-extent → dam-component → buffer → versioned GeoJSON → PostGIS; one-time eyeball review of all 3. | T-01, dam-point config | 3 AOIs persisted, versioned, each visually reviewed; sized past observed high-water. |
| **T-03** | Reservoir orbit/AOI **config schema** (§7.3) + loader; **freeze relative orbit + pass per reservoir (D1)**. | T-02 | Schema validates; 3 reservoirs have frozen orbit/pass; DB/config team has the values. |
| **T-04** | Scene discovery + fixed-orbit/pass filtering + acquisition grouping + idempotency key (step 0). | T-03 | Returns only in-orbit scenes; same key not reprocessed; `scene_ids` captured. |
| **T-05** | Calibration + border/thermal-noise (steps 2–3). | T-04 | dB↔linear round-trip test; edge artifacts removed. |
| **T-06** | **Radiometric terrain flattening → γ⁰** (step 4). | T-05, DEM | Flattened γ⁰ on steep synthetic DEM; topographic brightness reduced vs σ⁰ (regression). |
| **T-07** | **DEM layover/shadow mask** + `layover_shadow_fraction` (step 5). | T-06 | Mask matches expected on synthetic steep tile; fraction in `Observation`. |
| **T-08** | Speckle filter (Refined Lee + multitemporal option) (step 6). | T-06 | Speckle reduced; kernel recorded in `processing_params`. |
| **T-09** | **Extractor plugin interface + registry** + cold-start `Otsu-VH`, `KMeans`, `GMM`; connected-component + morphology (step 7). | T-08 | ABC-compliant; registry resolves `(name,version)`; binary mask, dam-component only. |
| **T-10** | **Confidence/quality** metrics incl. ice/wind/layover flags (step 8). | T-09 | Monotonicity tests; sub-scores in `processing_params`. |
| **T-11** | **True-area** via `pixelArea()` + curve apply + `is_extrapolated` (step 9). | T-09, RatingCurve read | Area in km²; NULL volume/level until curve; never pixel-count. |
| **T-12** | DEM hypsometric **shape** (`area(elev)`/`volume(elev)`) + waterline helper (§7.4, [ADR-0004](../adr/0004-blended-rating-curve-dem-empirical.md)). | T-02, DEM | Shape over [waterline, FRL]; handoff struct to ground-truthing. |
| **T-13** | `Observation` assembly + pydantic/pandera validation against **frozen contract v2**; mask raster + GeoJSON export + `water_mask_ref`. | T-10, T-11 | Valid row; contract test passes; mask exported. |
| **T-14** | Repository upserts (Observation) via DB access layer; idempotent on `(reservoir_id, acquisition_date)`. | T-13, DB schema | Re-run = no duplicate; upsert verified. |
| **T-15** | **Prefect flow** discover→…→persist→downstream trigger; retries+backoff; daily new-scene check + revisit schedule. | T-14 | Flow runs end-to-end on fixture; emits trigger; retries on transient. |
| **T-16** | **Harness integration** ([ADR-0007](../adr/0007-water-extraction-harness.md)): run cold-start candidates on bulletin-matched scenes with Data-Eng, score fill-% MAE by regime, MLflow-track, select+register promoted `(extractor+curve)`. | T-11, T-12, ground-truth pairs | Candidate metrics in MLflow; robust winner selected & registered (AC-2 input). |
| **T-17** | Staged supervised path: RF (`smileRandomForest`) + U-Net on weak labels (FR-GT-6), same plugin interface. | T-16, weak labels | RF/U-Net behind interface; promoted only if it beats incumbent on holdout. |
| **T-18** | Synthetic-stub `Observation` generator (`extraction_method='stub'`) so DE/ML unblock early. | T-13 | Stub rows pass contract validation; filterable. |

---

## 13. Mapping to acceptance criteria

- **AC-1** (pipelines run automatically): T-15 Prefect flow on revisit schedule + daily new-scene check, idempotent, emits downstream trigger.
- **AC-2 (foundational gate)** — our extracted areas, masks, and DEM-curve shape are the input side; the harness (T-16) selects the extractor+blended-curve hitting fill-% MAE ≤ 5–10%, versioned in MLflow.
- **AC-3** — estimation accuracy bounded by area quality (T-10/T-11) + blended curve.
- **AC-7 / NFR-TIME-1** — new S1 processed within 24 h (T-15 schedule), freshness surfaced.
- **AC-12 / NFR-TEST-1/2/3** — pandera gates + contract tests + near-FRL backtest in CI (T-13, §10).
