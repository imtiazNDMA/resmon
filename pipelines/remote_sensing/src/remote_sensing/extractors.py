"""Water-extraction plugins (FR-RS-2, ADR-0007). Array-based so they run on backscatter
patches (xee-exported in prod, synthetic in tests) without GEE.

Water is specular to SAR → very low VH backscatter, so every method separates a
low-VH water mode from a high-VH land mode. Each is pluggable & versioned via the
registry; the harness selects/promotes one (ADR-0007).

Shared building blocks:

- :func:`otsu_from_histogram` — ONE Otsu implementation used by both the array path
  (``np.histogram`` here) and the live-GEE path (server-side ``ee.Reducer.histogram``
  pulled client-side in ``gee_real``), so per-scene adaptive thresholding is a single
  audited code path.
- Unified separability: every extractor reports the SAME statistic — normalised Fisher
  separation of the water/land VH classes — so ``area_confidence`` is comparable across
  methods. Method-native scores (e.g. Otsu's eta) stay in ``diagnostics``.
- Abstain gate: scenes whose VH histogram has no credible water/land valley
  (wind-roughened, frozen, dry pool → effectively unimodal) yield ``abstained=True``
  instead of a fabricated mask; the pipeline skips persistence for abstained scenes.
- NaN/masked handling: non-finite pixels are removed from the valid mask before any
  histogramming or clustering and can never appear in the output water mask.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

#: Below this unified Fisher separability the water/land partition is not credible.
SEPARABILITY_FLOOR = 0.15
#: Above this valley/peak ratio the VH histogram is effectively unimodal → abstain.
VALLEY_RATIO_MAX = 0.75
#: Fewer valid pixels than this cannot support a per-scene histogram threshold.
MIN_VALID_PIXELS = 32

_HIST_BINS = 256


@dataclass(frozen=True)
class ExtractionResult:
    water_mask: np.ndarray  # bool 2D, valid_mask applied; all-False when abstained
    separability: float  # unified Fisher separation of water/land VH classes, 0–1 (FR-RS-3)
    threshold_used: float | None
    diagnostics: dict = field(default_factory=dict)
    #: True → no confident water/land partition on this scene (unimodal / wind-merged /
    #: too few valid pixels). Callers MUST NOT persist an area from an abstained result.
    abstained: bool = False


def _abstain(
    shape: tuple[int, ...], reason: str, diagnostics: dict | None = None
) -> ExtractionResult:
    diag = {"abstain_reason": reason, **(diagnostics or {})}
    return ExtractionResult(np.zeros(shape, dtype=bool), 0.0, None, diag, abstained=True)


def fisher_separability(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised Fisher separation d/(d+1) between two 1-D samples → [0, 1).

    This is the ONE separability statistic reported by every extractor (comparable
    inputs to ``area_confidence`` regardless of method).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return 0.0
    va, vb = float(a.var()), float(b.var())
    denom = va + vb
    if denom <= 0:
        return 0.0
    d = (float(a.mean()) - float(b.mean())) ** 2 / denom
    return float(d / (d + 1.0))


def otsu_from_histogram(counts: np.ndarray, centers: np.ndarray) -> tuple[float, float]:
    """Otsu threshold + eta (between/total-variance ratio) from histogram counts and bin
    centers. Works on ``np.histogram`` output and on GEE ``ee.Reducer.histogram`` output
    (``histogram``/``bucketMeans`` lists) alike — the single shared Otsu implementation.
    """
    counts = np.asarray(counts, dtype=float)
    centers = np.asarray(centers, dtype=float)
    total = counts.sum()
    if counts.size < 2 or total <= 0:
        raise ValueError("otsu_from_histogram needs a non-empty histogram with >= 2 bins")
    p = counts / total
    omega = np.cumsum(p)  # class-0 probability up to bin k
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b2 = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega))
    sigma_b2 = np.nan_to_num(sigma_b2)
    k = int(sigma_b2.argmax())
    total_var = float(np.sum(p * (centers - mu_t) ** 2))
    eta = float(sigma_b2[k] / total_var) if total_var > 0 else 0.0
    return float(centers[k]), float(min(max(eta, 0.0), 1.0))


def fisher_from_histogram(counts: np.ndarray, centers: np.ndarray, threshold: float) -> float:
    """Unified Fisher separability computed from a histogram split at ``threshold`` —
    the histogram analogue of :func:`fisher_separability` for the server-side GEE path."""
    counts = np.asarray(counts, dtype=float)
    centers = np.asarray(centers, dtype=float)
    lo = centers < threshold
    n_lo, n_hi = counts[lo].sum(), counts[~lo].sum()
    if n_lo <= 0 or n_hi <= 0:
        return 0.0
    m_lo = float((counts[lo] * centers[lo]).sum() / n_lo)
    m_hi = float((counts[~lo] * centers[~lo]).sum() / n_hi)
    v_lo = float((counts[lo] * (centers[lo] - m_lo) ** 2).sum() / n_lo)
    v_hi = float((counts[~lo] * (centers[~lo] - m_hi) ** 2).sum() / n_hi)
    denom = v_lo + v_hi
    if denom <= 0:
        return 0.0
    d = (m_lo - m_hi) ** 2 / denom
    return float(d / (d + 1.0))


def valley_ratio(
    counts: np.ndarray, centers: np.ndarray, threshold: float, *, smooth_bins: int = 5
) -> float:
    """Bimodality check: depth of the histogram valley at ``threshold``.

    Ratio of the minimum (smoothed) count between the two class modes to the lower of
    the two mode peaks. ≈1 → no real valley (unimodal scene: dry pool, wind-merged,
    frozen) → the partition is an artefact and the extractor must abstain; ≈0 → clean
    bimodal water/land scene.
    """
    counts = np.asarray(counts, dtype=float)
    centers = np.asarray(centers, dtype=float)
    if counts.size < 3:
        return 1.0
    kernel = np.ones(smooth_bins) / smooth_bins
    sm = np.convolve(counts, kernel, mode="same")
    lo = centers < threshold
    if not lo.any() or lo.all():
        return 1.0
    i_lo = int(np.argmax(np.where(lo, sm, -np.inf)))
    i_hi = int(np.argmax(np.where(~lo, sm, -np.inf)))
    peak = float(min(sm[i_lo], sm[i_hi]))
    if peak <= 0:
        return 1.0
    valley = float(sm[min(i_lo, i_hi) : max(i_lo, i_hi) + 1].min())
    return float(min(1.0, valley / peak))


class WaterExtractor(ABC):
    name: str
    version: str
    requires_labels: bool = False

    @abstractmethod
    def extract(
        self, vv: np.ndarray, vh: np.ndarray, valid_mask: np.ndarray, *, context: dict
    ) -> ExtractionResult:
        """Return a binary water mask + separability from γ⁰ VV/VH (dB) over valid pixels."""

    def fit(self, patches, labels) -> None:  # no-op for unsupervised cold-start
        return None


class OtsuVH(WaterExtractor):
    """Per-scene adaptive bimodal threshold on the VH histogram (not a fixed global
    threshold). Water = VH below the Otsu cut. Abstains on unimodal scenes."""

    name = "otsu_vh"
    version = "0.2.0"

    def extract(self, vv, vh, valid_mask, *, context):
        valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(vh)
        vals = vh[valid]
        if vals.size < MIN_VALID_PIXELS:
            return _abstain(vh.shape, "too_few_valid_pixels", {"n_valid": int(vals.size)})
        hist, edges = np.histogram(vals, bins=_HIST_BINS)
        centers = (edges[:-1] + edges[1:]) / 2
        threshold, eta = otsu_from_histogram(hist, centers)
        water_vals = vals[vals < threshold]
        land_vals = vals[vals >= threshold]
        vr = valley_ratio(hist, centers, threshold)
        sep = fisher_separability(water_vals, land_vals)
        diag = {
            "bins": _HIST_BINS,
            "otsu_eta": eta,  # method-native score (secondary; separability is unified)
            "valley_ratio": vr,
        }
        if water_vals.size == 0 or land_vals.size == 0:
            return _abstain(vh.shape, "degenerate_partition", diag)
        if vr > VALLEY_RATIO_MAX:
            return _abstain(vh.shape, "unimodal_histogram", diag)
        if sep < SEPARABILITY_FLOOR:
            return _abstain(vh.shape, "low_separability", diag)
        mask = (vh < threshold) & valid  # water = low VH (specular)
        return ExtractionResult(mask, sep, threshold, diag)


class _SklearnExtractor(WaterExtractor):
    requires_labels = False

    def _cluster(self, feats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:  # labels, means_vh
        raise NotImplementedError

    def extract(self, vv, vh, valid_mask, *, context):
        valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(vv) & np.isfinite(vh)
        idx = np.flatnonzero(valid.ravel())
        if idx.size < MIN_VALID_PIXELS:
            return _abstain(
                vh.shape, "too_few_valid_pixels", {"method": self.name, "n_valid": int(idx.size)}
            )
        feats = np.column_stack([vv.ravel()[idx], vh.ravel()[idx]])
        labels, vh_means = self._cluster(feats)
        water_label = int(np.argmin(vh_means))  # lower VH = water
        vh_feat = feats[:, 1]
        water_vals = vh_feat[labels == water_label]
        land_vals = vh_feat[labels != water_label]
        if water_vals.size == 0 or land_vals.size == 0:
            return _abstain(vh.shape, "degenerate_partition", {"method": self.name})
        sep = fisher_separability(water_vals, land_vals)
        # Bimodality gate on the VH histogram at the implied class boundary — a cluster
        # split of a unimodal scene always "separates", so the valley depth is the
        # honest signal (same gate semantics as OtsuVH).
        implied_t = float((water_vals.mean() + land_vals.mean()) / 2.0)
        hist, edges = np.histogram(vh_feat, bins=_HIST_BINS)
        centers = (edges[:-1] + edges[1:]) / 2
        vr = valley_ratio(hist, centers, implied_t)
        diag = {"method": self.name, "valley_ratio": vr, "implied_vh_threshold": implied_t}
        if vr > VALLEY_RATIO_MAX:
            return _abstain(vh.shape, "unimodal_histogram", diag)
        if sep < SEPARABILITY_FLOOR:
            return _abstain(vh.shape, "low_separability", diag)
        flat = np.zeros(vh.size, dtype=bool)
        flat[idx[labels == water_label]] = True
        return ExtractionResult(flat.reshape(vh.shape), sep, None, diag)


class KMeansVVVH(_SklearnExtractor):
    name = "kmeans"
    version = "0.2.0"

    def _cluster(self, feats):
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(feats)
        means_vh = np.array([feats[km.labels_ == c, 1].mean() for c in (0, 1)])
        return km.labels_, means_vh


class GMMVVVH(_SklearnExtractor):
    name = "gmm"
    version = "0.2.0"

    def _cluster(self, feats):
        from sklearn.mixture import GaussianMixture

        gm = GaussianMixture(n_components=2, random_state=0).fit(feats)
        labels = gm.predict(feats)
        means_vh = gm.means_[:, 1]
        return labels, means_vh


_REGISTRY: dict[str, type[WaterExtractor]] = {
    OtsuVH.name: OtsuVH,
    KMeansVVVH.name: KMeansVVVH,
    GMMVVVH.name: GMMVVVH,
}


def get_extractor(name: str) -> WaterExtractor:
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(f"Unknown extractor {name!r}; valid: {sorted(_REGISTRY)}") from None


def available_extractors() -> list[str]:
    return sorted(_REGISTRY)
