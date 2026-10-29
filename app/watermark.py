
"""
SNAP Records — Recipient Watermarking

Generates personalised copies of JPG, PNG and PDF files.

Each copy contains:
- SNAP Records branding
- Recipient identifier
- Unique download/copy identifier

Original files are never modified.
"""

from io import BytesIO
from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


SUPPORTED_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}

MAX_IMAGE_PIXELS = 30_000_000
MAX_PDF_PAGES = 100
MAX_PDF_FILE_SIZE = 25 * 1024 * 1024

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# ============================================================
# Watermark Text
# ============================================================

def build_watermark_text(recipient_id, download_id):
    """
    Build text to embed into a downloaded copy.

    The complete 16-character Copy ID is included so the
    corresponding download can be found in PostgreSQL.
    """

    return (
        f"SNAP Records | "
        f"User: {str(recipient_id)[:8]} | "
        f"Copy: {download_id}"
    )


# ============================================================
# Image Watermarking
# ============================================================

def watermark_image(path, recipient_id, download_id):
    """
    Apply visible watermarks to JPG and PNG images.

    The image is processed in memory.
    The original file remains unchanged.
    """

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Image does not exist: {path}"
        )

    try:
        with Image.open(path) as source:
            image_format = source.format

            if image_format not in ("JPEG", "PNG"):
                raise ValueError(
                    "Unsupported image format"
                )

            if (
                source.width * source.height
                > MAX_IMAGE_PIXELS
            ):
                raise ValueError(
                    "Image exceeds maximum pixel count"
                )

            image = ImageOps.exif_transpose(source)
            image = image.convert("RGBA")

    except UnidentifiedImageError as exc:
        raise ValueError(
            "Invalid or corrupted image"
        ) from exc

    # Create transparent watermark layer
    overlay = Image.new(
        "RGBA",
        image.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(overlay)

    watermark_text = build_watermark_text(
        recipient_id,
        download_id,
    )

    font = ImageFont.load_default()

    # Position watermarks repeatedly across the image
    spacing_x = 420
    spacing_y = 135

    for y in range(25, image.height, spacing_y):
        for x in range(20, image.width, spacing_x):

            draw.text(
                (x, y),
                watermark_text,
                font=font,
                fill=(255, 255, 255, 145),
                stroke_width=1,
                stroke_fill=(0, 0, 0, 110),
            )

    result = Image.alpha_composite(
        image,
        overlay,
    )

    output = BytesIO()

    # Preserve the original image format
    if image_format == "PNG":

        result.save(
            output,
            format="PNG",
        )

        mime_type = "image/png"
        extension = ".png"

    else:

        # JPEG does not support alpha transparency
        result.convert("RGB").save(
            output,
            format="JPEG",
            quality=90,
            optimize=True,
        )

        mime_type = "image/jpeg"
        extension = ".jpg"

    output.seek(0)

    return output, mime_type, extension


# ============================================================
# PDF Watermarking
# ============================================================

def watermark_pdf(path, recipient_id, download_id):
    """
    Apply a visible watermark to every PDF page.

    The watermark has low opacity to preserve readability.
    """

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(
            f"PDF does not exist: {path}"
        )

    if path.stat().st_size > MAX_PDF_FILE_SIZE:
        raise ValueError(
            "PDF exceeds maximum permitted size"
        )

    reader = PdfReader(str(path), strict=False)

    if reader.is_encrypted:
        raise ValueError(
            "Encrypted PDF files are not supported"
        )

    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(
            "PDF has too many pages"
        )

    writer = PdfWriter()

    watermark_text = build_watermark_text(
        recipient_id,
        download_id,
    )

    for page in reader.pages:

        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        if width <= 0 or height <= 0:
            raise ValueError(
                "Invalid PDF page dimensions"
            )

        # Generate transparent PDF overlay
        buffer = BytesIO()

        pdf = canvas.Canvas(
            buffer,
            pagesize=(width, height),
        )

        pdf.setFillColorRGB(
            0.35,
            0.35,
            0.35,
        )

        # Low opacity for improved readability
        pdf.setFillAlpha(0.15)
        pdf.setFont("Helvetica", 10)

        # Repeat watermark across each page
        for y in range(45, int(height), 160):
            for x in range(35, int(width), 360):

                pdf.drawString(
                    x,
                    y,
                    watermark_text,
                )

        pdf.save()

        buffer.seek(0)

        overlay_reader = PdfReader(buffer)

        page.merge_page(
            overlay_reader.pages[0]
        )

        writer.add_page(page)

    output = BytesIO()

    writer.write(output)
    output.seek(0)

    return output, "application/pdf", ".pdf"


# ============================================================
# Main Watermark Function
# ============================================================

def create_watermarked_copy(
    path,
    mime_type,
    recipient_id,
    download_id,
):
    """
    Create a personalised downloadable copy.

    Parameters:
        path: Original file path
        mime_type: MIME type of the original file
        recipient_id: SNAP user ID
        download_id: Unique download identifier

    Returns:
        (BytesIO, mime_type, extension)

    Raises:
        FileNotFoundError
        ValueError
    """

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Original file not found: {path}"
        )

    if mime_type not in SUPPORTED_TYPES:
        raise ValueError(
            f"Unsupported watermark format: {mime_type}"
        )

    if mime_type in (
        "image/jpeg",
        "image/png",
    ):

        return watermark_image(
            path,
            recipient_id,
            download_id,
        )

    if mime_type == "application/pdf":

        return watermark_pdf(
            path,
            recipient_id,
            download_id,
        )

    raise ValueError(
        "Unable to watermark this file"
    )
