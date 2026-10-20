from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from django.conf import settings

from ai.exceptions import GoogleProviderError

from .client import get_genai_client

logger = logging.getLogger(__name__)

PRODUCT_LOCK = (
    "Preserve the actual product exactly as shown in the reference photos. "
    "Do not change the product shape, label, colour, logo, packaging, or variant. "
    "Do not invent specifications, dimensions, colours, packaging, variants, or claims. "
    "Only create or edit the background, lighting, and scene around the product. "
    "Do not invent product claims, prices, or on-image text that is not in the prompt."
)


class NanoBananaProvider:
    def generate_image(
        self,
        prompt: str,
        *,
        reference_images: list[str | Path] | None = None,
        aspect_ratio: str = "9:16",
        system_lock: str | None = None,
    ) -> bytes:
        try:
            from google.genai import types

            client = get_genai_client()
            contents: list = []
            for path in reference_images or []:
                file_path = Path(path)
                mime, _ = mimetypes.guess_type(str(file_path))
                contents.append(
                    types.Part.from_bytes(
                        data=file_path.read_bytes(),
                        mime_type=mime or "image/jpeg",
                    )
                )
            lock = PRODUCT_LOCK if system_lock is None else system_lock
            contents.append(f"{lock}\n\n{prompt}" if lock else prompt)
            response = client.models.generate_content(
                model=settings.NANO_BANANA_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                ),
            )
            for part in getattr(response, "parts", []) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    data = inline.data
                    return data if isinstance(data, bytes) else bytes(data)
                as_image = getattr(part, "as_image", None)
                if callable(as_image):
                    image = as_image()
                    if image is not None and getattr(image, "image_bytes", None):
                        return image.image_bytes
            raise GoogleProviderError("Image generation returned no image.")
        except GoogleProviderError:
            raise
        except Exception as exc:
            logger.exception("Nano Banana request failed")
            raise GoogleProviderError(
                "Image generation failed.",
                retryable=True,
            ) from exc
