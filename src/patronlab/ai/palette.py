"""Palette extraction with k-means clustering (unsupervised learning).

Every pixel of the artisan's photo is a point in RGB space; k-means groups them
into k clusters and each cluster center is one palette color. The share of
pixels in each cluster says how dominant that color is.
"""

import base64
import binascii
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, UnidentifiedImageError
from sklearn.cluster import KMeans

SAMPLE_SIZE = 128  # pixels per side after downscaling: fast and representative


class InvalidImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PaletteColor:
    hex: str
    share: float


def decode_image(data_url_or_base64: str, max_bytes: int) -> Image.Image:
    payload = data_url_or_base64.split(",", 1)[-1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidImageError("IMAGE_NOT_BASE64") from error
    if len(raw) > max_bytes:
        raise InvalidImageError("IMAGE_TOO_LARGE")
    try:
        image = Image.open(io.BytesIO(raw))
        # Guard against decompression bombs before decoding every pixel.
        if image.width * image.height > 40_000_000:
            raise InvalidImageError("IMAGE_TOO_LARGE")
        return image.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise InvalidImageError("IMAGE_UNREADABLE") from error


def extract_palette(image: Image.Image, colors: int = 5, seed: int = 0) -> list[PaletteColor]:
    sample = image.copy()
    sample.thumbnail((SAMPLE_SIZE, SAMPLE_SIZE))
    pixels = np.asarray(sample, dtype=np.float64).reshape(-1, 3)
    distinct = len(np.unique(pixels, axis=0))
    k = max(1, min(colors, distinct))

    model = KMeans(n_clusters=k, n_init=4, random_state=seed).fit(pixels)
    counts = np.bincount(model.labels_, minlength=k)
    order = np.argsort(-counts)
    return [
        PaletteColor(
            hex=_to_hex(model.cluster_centers_[i]), share=round(float(counts[i] / counts.sum()), 3)
        )
        for i in order
    ]


def _to_hex(rgb: np.ndarray) -> str:
    r, g, b = (int(round(min(255, max(0, value)))) for value in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"
