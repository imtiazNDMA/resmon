"""Water-extraction plugins (FR-RS-2, ADR-0007). Array-based so they run on backscatter
patches (xee-exported in prod, synthetic in tests) without GEE.

Water is specular to SAR → very low VH backscatter, so every method separates a
low-VH water mode from a high-VH land mode. Each is pluggable & versioned via the
registry; the harness selects/promotes one (ADR-0007).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class ExtractionResult:
    water_mask: np.ndarray  # bool 2D, valid_mask applied
    separability: float  # water/land mode separation, 0–1 (FR-RS-3)
    threshold_used: float | None
    diagnostics: dict = field(default_factory=dict)


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


def _fisher(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised Fisher separation between two 1-D samples → [0, 1)."""
    va, vb = a.var(), b.var()
    denom = va + vb
    if denom <= 0:
        return 0.0
    d = (a.mean() - b.mean()) ** 2 / denom
    return float(d / (d + 1.0))


class OtsuVH(WaterExtractor):
    """Per-scene adaptive bimodal threshold on the VH histogram (not a fixed global
    threshold). Water = VH below the Otsu cut."""

    name = "otsu_vh"
    version = "0.1.0"

    def extract(self, vv, vh, valid_mask, *, context):
        vals = vh[valid_mask]
        if vals.size == 0:
            return ExtractionResult(np.zeros_like(vh, dtype=bool), 0.0, None)
        hist, edges = np.histogram(vals, bins=256)
        centers = (edges[:-1] + edges[1:]) / 2
        p = hist / hist.sum()
        omega = np.cumsum(p)  # class-0 probability up to bin k
        mu = np.cumsum(p * centers)
        mu_t = mu[-1]
        with np.errstate(divide="ignore", invalid="ignore"):
            sigma_b2 = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega))
        sigma_b2 = np.nan_to_num(sigma_b2)
        k = int(sigma_b2.argmax())
        threshold = float(centers[k])
        sep = float(sigma_b2.max() / (vals.var() + 1e-9))  # between/total variance ratio
        mask = (vh < threshold) & valid_mask  # water = low VH (specular)
        return ExtractionResult(mask, min(max(sep, 0.0), 1.0), threshold, {"bins": 256})


class _SklearnExtractor(WaterExtractor):
    requires_labels = False

    def _cluster(self, feats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:  # labels, means_vh
        raise NotImplementedError

    def extract(self, vv, vh, valid_mask, *, context):
        idx = np.where(valid_mask.ravel())[0]
        if idx.size == 0:
            return ExtractionResult(np.zeros_like(vh, dtype=bool), 0.0, None)
        feats = np.column_stack([vv.ravel()[idx], vh.ravel()[idx]])
        labels, vh_means = self._cluster(feats)
        water_label = int(np.argmin(vh_means))  # lower VH = water
        vh_feat = feats[:, 1]
        sep = _fisher(vh_feat[labels == water_label], vh_feat[labels != water_label])
        flat = np.zeros(vh.size, dtype=bool)
        flat[idx[labels == water_label]] = True
        return ExtractionResult(flat.reshape(vh.shape), sep, None, {"method": self.name})


class KMeansVVVH(_SklearnExtractor):
    name = "kmeans"
    version = "0.1.0"

    def _cluster(self, feats):
        from sklearn.cluster import KMeans

        km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(feats)
        means_vh = np.array([feats[km.labels_ == c, 1].mean() for c in (0, 1)])
        return km.labels_, means_vh


class GMMVVVH(_SklearnExtractor):
    name = "gmm"
    version = "0.1.0"

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
