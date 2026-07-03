# Sentinel-1 scene inventory — 2026-07-03

Stage-1.1 recon (Replan.md §3). Full coverage = scene footprint contains the
entire JRC-GSW-derived AOI (the production-series requirement, B2).

## Gobind Sagar (`gobind_sagar`) — AOI 140 km²

Scenes intersecting AOI: **830** · fully covering: **523**

### Scenes per orbit/pass

```text
                  scenes  full_coverage       first        last
orbit pass                                                     
27    ASCENDING      291            279  2015-10-26  2026-06-25
136   DESCENDING     252            244  2015-03-08  2026-06-26
34    DESCENDING     287              0  2015-03-01  2026-06-26
```

**Recommended orbit: 27 ASCENDING** (279 full-coverage scenes)

### Scenes per year × platform

```text
platform  S1A  S1C  S1D
year                   
2015        3    0    0
2016       23    0    0
2017       86    0    0
2018       86    0    0
2019       67    0    0
2020       91    0    0
2021       90    0    0
2022       77    0    0
2023       82    0    0
2024       80    0    0
2025       90    3    0
2026       49    0    3
```

### Cadence on recommended orbit (full-coverage scenes)

```text
          scenes  median_gap_d  p90_gap_d  max_gap_d
S1A+S1B    148.0          12.0       12.0      468.0
S1A only    90.0          12.0       12.0       24.0
S1A+S1C     41.0          12.0       12.0       12.0
```

### Bulletin → nearest full-coverage scene offset

Recommended orbit only:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          151.0           19.9           46.4           72.8           81.5
non-monsoon       44.0           25.0           54.5           86.4           95.5
```

Any fully-covering orbit:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          151.0           37.7           71.5           81.5           82.8
non-monsoon       44.0           50.0           86.4           97.7           97.7
```

## Pong Dam (`pong`) — AOI 251 km²

Scenes intersecting AOI: **885** · fully covering: **730**

### Scenes per orbit/pass

```text
                  scenes  full_coverage       first        last
orbit pass                                                     
27    ASCENDING      285            283  2015-10-26  2026-06-25
136   DESCENDING     251            246  2015-01-31  2026-06-26
34    DESCENDING     349            201  2015-03-01  2026-06-26
```

**Recommended orbit: 27 ASCENDING** (283 full-coverage scenes)

### Scenes per year × platform

```text
platform  S1A  S1C  S1D
year                   
2015        5    0    0
2016       15    0    0
2017      104    0    0
2018      114    0    0
2019       85    0    0
2020       94    0    0
2021       90    0    0
2022       77    0    0
2023       82    0    0
2024       80    0    0
2025       90    3    0
2026       44    0    2
```

### Cadence on recommended orbit (full-coverage scenes)

```text
          scenes  median_gap_d  p90_gap_d  max_gap_d
S1A+S1B    146.0          12.0       12.0       24.0
S1A only    90.0          12.0       12.0       24.0
S1A+S1C     47.0          12.0       12.0       12.0
```

### Bulletin → nearest full-coverage scene offset

Recommended orbit only:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          150.0           20.7           46.0           73.3           82.0
non-monsoon       44.0           25.0           54.5           86.4           95.5
```

Any fully-covering orbit:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          150.0           42.7           77.3           84.7           84.7
non-monsoon       44.0           56.8           95.5           97.7           97.7
```

## Thein Dam (`thein`) — AOI 104 km²

Scenes intersecting AOI: **849** · fully covering: **553**

### Scenes per orbit/pass

```text
                  scenes  full_coverage       first        last
orbit pass                                                     
27    ASCENDING      284            283  2015-10-26  2026-06-25
34    DESCENDING     280            270  2015-03-01  2026-06-26
100   ASCENDING      285              0  2015-11-12  2026-06-30
```

**Recommended orbit: 27 ASCENDING** (283 full-coverage scenes)

### Scenes per year × platform

```text
platform  S1A  S1C  S1D
year                   
2015        4    0    0
2016        8    0    0
2017       86    0    0
2018       87    0    0
2019       80    0    0
2020       88    0    0
2021       90    0    0
2022       88    0    0
2023       91    0    0
2024       89    0    0
2025       89    2    0
2026       44    0    3
```

### Cadence on recommended orbit (full-coverage scenes)

```text
          scenes  median_gap_d  p90_gap_d  max_gap_d
S1A+S1B    147.0          12.0       12.0      468.0
S1A only    90.0          12.0       12.0       24.0
S1A+S1C     46.0          12.0       12.0       12.0
```

### Bulletin → nearest full-coverage scene offset

Recommended orbit only:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          150.0           20.0           46.0           73.3           82.0
non-monsoon       44.0           22.7           54.5           86.4           95.5
```

Any fully-covering orbit:

```text
             bulletins  within_1d_pct  within_3d_pct  within_5d_pct  within_7d_pct
monsoon          150.0           25.3           52.7           84.7           84.7
non-monsoon       44.0           31.8           65.9           95.5           97.7
```
