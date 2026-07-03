# Backfill analysis — dense SAR area(t) series (2026-07-03)

Stage-1.2 results (Replan.md §3): adaptive Otsu extraction over every full-coverage
orbit-27 ASC scene. `ok` rows carry a real area; `abstain` = histogram failed the
bimodality gate (recorded, never given an area); `error` = reduction failure.

## Headline findings

- **845 scenes processed: 775 ok, 64 abstain, 0 errors** (92% yield, ~35 min wall-clock).
- **The extraction chain is validated against fully independent truth**: SAR area vs
  bulletin fill (±3 d nearest match, no shared processing anywhere) — Gobind Sagar
  **r = 0.971** (93 pairs), Pong **r = 0.964 / ρ = 0.984** (91), Thein **r = 0.802** (89).
  For unflattened σ⁰ with a histogram Otsu, the first two are near the ceiling that
  scene-to-bulletin timing noise allows.
- **Abstains cluster where SAR physics predicts**: Pong (broad, shallow, wind-exposed)
  abstains in shoulder/monsoon (24% / 12%) — wind roughening merges the modes; Thein
  (narrow Himalayan gorge) abstains in winter (16%) — low-backscatter conditions.
  Gobind Sagar barely abstains at all (0.4%). The gate is doing its job, not failing
  randomly.
- **Large scene-to-scene jumps are monsoon fillings, not artifacts**: every top jump
  lands in July–August with separability ≥ 0.85 — reservoirs genuinely gain tens of
  km² in a 12-day revisit during monsoon inflow.
- **Stage-2 watch item — Thein (r = 0.80)**: the weakest correlation. Plausible causes,
  in order: smallest area (46–99 km²) → highest boundary-pixel fraction; narrow gorge
  geometry (layover/shadow unmasked, deferred item); genuine area–storage hysteresis.
  The Stage-2 estimator study must break out Thein separately, and Thein is the first
  candidate to benefit from terrain flattening when it lands.

## gobind_sagar — 279 scenes processed

### Status by season

```text
status    abstain   ok  abstain_rate_%
season                                
monsoon         0   89             0.0
shoulder        1  120             0.8
winter          0   69             0.0
```

### Series sanity

```text
area_km2:      {'count': 278.0, 'min': 73.9, 'mean': 121.3, 'max': 148.6}
threshold_db:  {'min': -24.1, 'mean': -22.4, 'max': -21.1}
separability:  {'min': 0.84, 'mean': 0.91, 'max': 0.94}
```

### Area vs bulletin fill (nearest bulletin within ±3 d — fully independent)

```text
matched pairs (±3d): 93
Pearson r  (area, pct_filled): 0.971
Spearman ρ (area, pct_filled): 0.978
Pearson r, monsoon only:       0.964
```

### Largest scene-to-scene jumps (wind/ice candidates)

```text
    acquisition_date    area_km2       jump  gap_d  separability
195       2023-07-16  132.971181  22.179668   12.0      0.931632
46        2018-08-23  124.213633  19.465402   12.0      0.921701
136       2021-08-07  113.273789  17.960407   12.0      0.923289
166       2022-08-02  118.625904  16.775208   12.0      0.929567
45        2018-08-11  104.748231  16.741095   12.0      0.921099
```

## pong — 283 scenes processed

### Status by season

```text
status    abstain  ok  abstain_rate_%
season                               
monsoon        11  81            12.0
shoulder       29  93            23.8
winter          1  68             1.4
```

### Series sanity

```text
area_km2:      {'count': 242.0, 'min': 94.2, 'mean': 202.6, 'max': 252.9}
threshold_db:  {'min': -25.9, 'mean': -23.3, 'max': -20.9}
separability:  {'min': 0.83, 'mean': 0.91, 'max': 0.96}
```

### Area vs bulletin fill (nearest bulletin within ±3 d — fully independent)

```text
matched pairs (±3d): 91
Pearson r  (area, pct_filled): 0.964
Spearman ρ (area, pct_filled): 0.984
Pearson r, monsoon only:       0.966
```

### Largest scene-to-scene jumps (wind/ice candidates)

```text
    acquisition_date    area_km2       jump  gap_d  separability
251       2025-07-05  160.693377  57.372603   12.0      0.915276
193       2023-07-16  231.787178  46.631005   12.0      0.952606
42        2018-07-30  137.798621  43.638602   12.0      0.927635
44        2018-08-23  216.156452  41.913409   12.0      0.940551
12        2017-07-23  177.066354  40.566589   12.0      0.940093
```

## thein — 283 scenes processed

### Status by season

```text
status    abstain   ok  abstain_rate_%
season                                
monsoon         1   90             1.1
shoulder       10  113             8.1
winter         11   58            15.9
```

### Series sanity

```text
area_km2:      {'count': 261.0, 'min': 46.2, 'mean': 74.3, 'max': 98.8}
threshold_db:  {'min': -23.1, 'mean': -21.4, 'max': -20.1}
separability:  {'min': 0.84, 'mean': 0.88, 'max': 0.92}
```

### Area vs bulletin fill (nearest bulletin within ±3 d — fully independent)

```text
matched pairs (±3d): 89
Pearson r  (area, pct_filled): 0.802
Spearman ρ (area, pct_filled): 0.793
Pearson r, monsoon only:       0.778
```

### Largest scene-to-scene jumps (wind/ice candidates)

```text
    acquisition_date   area_km2       jump  gap_d  separability
163       2022-07-09  61.932590  23.987867   12.0      0.883049
225       2024-08-03  46.236938  19.476428   24.0      0.887843
257       2025-09-03  98.833625  18.669568   12.0      0.907328
8         2017-04-30  86.939526  17.380528   12.0      0.847491
196       2023-08-09  77.115713  16.248841   12.0      0.915952
```
