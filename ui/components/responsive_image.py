"""Aspect-ratio-safe image rendering for announcement previews."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


def prepare_responsive_image(
    image_bytes: bytes,
    *,
    max_width: int,
    max_height: int,
) -> Image.Image | None:
    """Return a bounded image without stretching or changing its ratio."""

    if not image_bytes:
        return None

    try:
        with Image.open(
            BytesIO(image_bytes)
        ) as source:
            corrected = ImageOps.exif_transpose(
                source
            )
            prepared = corrected.copy()

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        return None

    resampling = getattr(
        Image,
        "Resampling",
        Image,
    ).LANCZOS

    # thumbnail() never enlarges and always preserves aspect ratio.
    prepared.thumbnail(
        (
            max(1, int(max_width)),
            max(1, int(max_height)),
        ),
        resampling,
    )

    return prepared


def render_responsive_image(
    image_bytes: bytes,
    *,
    caption: str | None = None,
    max_width: int = 900,
    max_height: int = 440,
    fill_container: bool = False,
) -> None:
    """Display a centered, bounded image using its natural aspect ratio."""

    import streamlit as st

    prepared = prepare_responsive_image(
        image_bytes,
        max_width=max_width,
        max_height=max_height,
    )

    if prepared is None:
        st.warning(
            "The announcement image could not be displayed."
        )
        return

    if fill_container:
        st.image(
            prepared,
            caption=caption,
            width="stretch",
        )
        return

    image_column, spacer = st.columns(
        [
            max(prepared.width, 1),
            max(max_width - prepared.width, 1),
        ],
        gap="small",
        vertical_alignment="top",
    )

    with image_column:
        st.image(
            prepared,
            caption=caption,
            width=prepared.width,
        )
