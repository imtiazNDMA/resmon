# Freeze `Observation` and ABT as the inter-pipeline contracts

## Context

V1 builds all three pipelines (Remote-Sensing, Data-Engineering, ML) concurrently, with SAR on the critical path. The pipelines form a hard dependency chain (RS → DE → ML), so concurrent construction deadlocks unless the seams between them are fixed up front and downstream tracks can develop against stubs.

## Decision

Freeze two schemas as the contract (`contract_version: 1`, in [`docs/contracts/observation-and-abt.md`](../contracts/observation-and-abt.md)): the `Observation` row RS emits, and the `AnalyticalBaseTable` DE emits / ML consumes. Downstream tracks develop immediately against the bulletin CSV plus synthetic `Observation` rows (`extraction_method = 'stub'`) and swap in real SAR output later. Changing a column requires bumping `contract_version`.

Two non-obvious choices are baked in:

- **ABT grain is a continuous daily IST calendar**, not the weekly bulletin cadence — because catchment forcing is native-daily and the forecast horizon is in days. Ground-truth and SAR columns are sparse (populated only on their dates), with `days_since_*` recency columns.
- **The canonical join key is the IST calendar date.** Bulletins are IST, SAR and forcing are UTC; all are mapped to the IST date before joining, to keep point-in-time alignment unambiguous.

## Consequences

- DE and ML are unblocked from day one; a broken GEE credential or slow SAR work cannot stall them.
- The daily grid means most rows have null targets; the forecaster trains on the subset of dates with a storage observation.
- A column change is a coordinated, versioned event — deliberate friction that protects the seam.
