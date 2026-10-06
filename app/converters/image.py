"""ImageConverter — image conversion via Pillow.

Handles the details that bite in practice:

- alpha composited onto a background for formats without transparency (JPG, BMP)
- EXIF orientation applied via ``ImageOps.exif_transpose``
- ICO limited to 256x256 (resized, or blocked when ``ico_resize`` is disabled)
- color modes (``P``, ``LA``, ``CMYK``, ...) converted to what the target supports
- atomic output: write to a temp file, then rename

Cancellation: Pillow cannot interrupt a single ``save()``, so cancel takes effect
between jobs. This is documented behavior, not a bug.

v0.1 uses fixed defaults (JPEG quality 90); user-facing options arrive later with
``options_schema()``.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from app.converters.base import BaseConverter, ConversionCancelled, ConversionError
from app.models.conversion_context import ConversionContext
from app.utils.file_utils import atomic_output
from app.utils.format_utils import target_from_output

IMAGE_FORMATS = ["png", "jpg", "webp", "bmp", "tiff", "ico"]

_SAVE_FORMAT = {
    "png": "PNG",
    "jpg": "JPEG",
    "webp": "WEBP",
    "bmp": "BMP",
    "tiff": "TIFF",
    "ico": "ICO",
}

# Targets that cannot store an alpha channel; transparency is composited away.
_OPAQUE_TARGETS = {"jpg", "bmp"}
_ALPHA_MODES = {"RGBA", "LA", "PA"}
_ICO_MAX = (256, 256)


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in _ALPHA_MODES:
        return True
    return image.mode == "P" and "transparency" in image.info


def _parse_color(value, default: tuple[int, int, int] = (255, 255, 255)) -> tuple:
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return tuple(int(c) for c in value)
    text = str(value).strip().lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return default


class ImageConverter(BaseConverter):
    name = "pillow"
    priority = 10

    # ------------------------------------------------------------------ capability
    def supported_pairs(self) -> set[tuple[str, str]]:
        return {
            (src, dst)
            for src in IMAGE_FORMATS
            for dst in IMAGE_FORMATS
            if src != dst
        }

    def is_available(self) -> bool:
        return True  # Pillow is a Python dependency, always importable

    def max_parallel_jobs(self) -> int:
        return 2

    # ------------------------------------------------------------------ validation
    def validate(
        self,
        source_format: str,
        target_format: str,
        source: Path,
        options: dict,
    ) -> list[str]:
        problems: list[str] = []
        if target_format == "ico":
            allow_resize = options.get("ico_resize", True)
            try:
                with Image.open(source) as image:
                    if max(image.size) > max(_ICO_MAX) and not allow_resize:
                        problems.append("ICO images cannot exceed 256x256.")
            except (OSError, ValueError):
                pass
        if not Path(source).exists():
            problems.append("Source file not found.")
        return problems

    def options_schema(self, source_format: str, target_format: str) -> dict:
        schema: dict = {}
        if target_format in ("jpg", "webp"):
            schema["quality"] = {
                "type": "int", "min": 1, "max": 100, "default": 90, "label": "Quality",
            }
        if target_format in ("jpg", "bmp"):
            schema["background"] = {
                "type": "color", "default": "#ffffff",
                "label": "Background (for transparency)",
            }
        if target_format == "ico":
            schema["ico_resize"] = {
                "type": "bool", "default": True,
                "label": "Resize to 256×256 when larger",
            }
        return schema

    # ------------------------------------------------------------------- execution
    def convert(self, context: ConversionContext) -> Path:
        if context.cancelled:
            raise ConversionCancelled()

        # Converters do not receive the target format; it is derived from the output
        # path that preflight resolved.
        target = target_from_output(context.output)
        save_format = _SAVE_FORMAT.get(target)
        if save_format is None:
            raise ConversionError(f"Unsupported image target: {target!r}")
        options = self.effective_options("", target, context.options)

        try:
            with Image.open(context.source) as opened:
                opened.load()
                context.report(15)
                oriented = ImageOps.exif_transpose(opened) or opened
                image = oriented.copy()  # detach from the file handle before it closes
                image = self._prepare(image, target, options)
                context.report(55)

                if context.cancelled:
                    raise ConversionCancelled()

                with atomic_output(context.output) as temp_path:
                    image.save(
                        temp_path, format=save_format, **self._save_kwargs(target, options)
                    )
                context.report(95)
        except ConversionCancelled:
            raise
        except ConversionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
            raise ConversionError(f"Image conversion failed: {exc}") from exc

        return context.output

    # -------------------------------------------------------------------- helpers
    def _save_kwargs(self, target: str, options: dict) -> dict:
        quality = int(options.get("quality", 90))
        if target == "jpg":
            return {"quality": quality, "optimize": True}
        if target == "webp":
            return {"quality": quality, "method": 4}
        return {}

    def _prepare(self, image: Image.Image, target: str, options: dict) -> Image.Image:
        if target == "ico":
            return self._prepare_ico(image, options.get("ico_resize", True))
        if target in _OPAQUE_TARGETS and _has_alpha(image):
            return self._flatten(image, _parse_color(options.get("background")))
        # Normalize modes the target cannot store directly.
        if image.mode == "CMYK":
            return image.convert("RGB")
        if image.mode == "P":
            return image.convert("RGBA") if _has_alpha(image) else image.convert("RGB")
        if image.mode == "LA":
            return image.convert("RGBA")
        return image

    def _prepare_ico(self, image: Image.Image, resize: bool) -> Image.Image:
        # ICO entries are stored as PNG. Some decoders (e.g. GNOME's glycin)
        # reject any embedded PNG that is not RGBA, so always normalize to RGBA.
        if image.mode == "CMYK":
            image = image.convert("RGB")
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        if max(image.size) > max(_ICO_MAX):
            if not resize:
                raise ConversionError("ICO images cannot exceed 256x256.")
            image = image.copy()
            image.thumbnail(_ICO_MAX, Image.Resampling.LANCZOS)
        return image

    def _flatten(self, image: Image.Image, background: tuple) -> Image.Image:
        if image.mode == "P":
            image = image.convert("RGBA")
        elif image.mode not in ("RGBA", "LA"):
            image = image.convert("RGBA")
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (*background, 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")
