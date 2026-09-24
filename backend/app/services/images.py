"""Bounded, verified image uploads; extensions alone are never trusted."""

import warnings
from dataclasses import dataclass
from io import BytesIO

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.errors import ServiceError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
FORMATS = {"image/jpeg": ("JPEG", "jpg"), "image/png": ("PNG", "png"), "image/webp": ("WEBP", "webp")}


@dataclass(frozen=True)
class ImageData:
    data: bytes
    content_type: str
    extension: str


def validate_image(data: bytes, content_type: str, max_bytes: int = MAX_IMAGE_BYTES) -> ImageData:
    if content_type not in FORMATS:
        raise ServiceError("Use a JPEG, PNG, or WebP image.", 415)
    if len(data) > max_bytes:
        raise ServiceError(f"Each image must be no larger than {max_bytes // (1024 * 1024)} MiB.", 413)
    if not data:
        raise ServiceError("Each image must be nonempty.", 400)
    expected_format, extension = FORMATS[content_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                if picture.format != expected_format:
                    raise ServiceError("The image content does not match its declared file type.", 400)
                if picture.width * picture.height > MAX_IMAGE_PIXELS:
                    raise ServiceError("Use an image with at most 20 megapixels.", 400)
                if getattr(picture, "n_frames", 1) != 1:
                    raise ServiceError("Use a still image, not an animated image.", 400)
                picture.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ServiceError("The image is damaged or could not be decoded. Select a different photograph.", 400) from None
    return ImageData(data, content_type, extension)


async def read_upload(upload: UploadFile, max_bytes: int = MAX_IMAGE_BYTES) -> ImageData:
    # Limit the read even when Content-Length is absent or dishonest.
    data = await upload.read(max_bytes + 1)
    return validate_image(data, upload.content_type or "", max_bytes)
