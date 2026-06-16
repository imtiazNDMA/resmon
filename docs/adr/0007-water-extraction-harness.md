# Water-extraction harness: joint pipeline selection with staged escalation

## Context

In the closed loop (ADR-0005), SAR water extraction is one of only two production components (with the rating curve) between the satellite and a storage number, with no live ground truth to catch its errors. FR-GT-5 says to select the extraction method "whose derived volume/level best agrees with ground truth" — but deriving volume needs the rating curve, which is itself fit from the extractor's areas (co-dependent). And the deep model (U-Net) can't run at t=0 because no labels exist yet.

## Decision

- **Candidates.** Cold-start unsupervised on VH-dominant backscatter — `Otsu-VH`, `K-means[VV,VH]`, `GMM[VV,VH]` (Otsu is per-scene adaptive, satisfying "not a fixed global threshold"). A **U-Net** is added later, trained on **weak labels** harvested from low-residual / high-confidence unsupervised masks (FR-GT-6) — staged escalation, not a bake-off of equals.
- **Select the pipeline, not the extractor.** Resolve the chicken-and-egg by giving each candidate its **own co-fit blended rating curve** (ADR-0004), so its area→storage map absorbs its own bias, then compare end-to-end `(extractor + its curve)` by **derived fill-% MAE vs bulletins on a walk-forward / leave-one-season-out holdout** (NFR-ACC-1).
- **Robustness is first-class.** Break the metric out by season/regime (monsoon vs winter-ice vs wind-roughened) and prefer the *robust* pipeline, not the lowest-mean one — a method that collapses on winter ice is disqualified for a year-round system.
- **Promotion & lifecycle.** Promote the U-Net only if it beats the incumbent on the same holdout. Track every candidate + metric in MLflow, register the winner, keep extraction pluggable & versioned (FR-RS-2). Per-pixel `area_confidence` drives quality gates and flags wind/shadow/frozen scenes.

## Consequences

- The system is operational from day one on unsupervised extraction; the deep model is an earned upgrade, not a dependency.
- Each extractor carries its own rating curve until one pipeline is promoted — slightly more bookkeeping, but it makes selection an honest end-to-end comparison.
- Rejected: judging masks by intrinsic quality (no ground-truth tie), a single shared curve across extractors (hides per-method bias), and starting with U-Net (no labels).
