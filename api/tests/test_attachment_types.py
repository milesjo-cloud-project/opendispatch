import pytest

from app.jobs.routes import _attachment_content_type


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/heic", "image/avif", "image/svg+xml"])
def test_accepts_image_media_types_independent_of_extension(mime):
    assert _attachment_content_type("upload.data", mime) == mime


def test_accepts_pdf_and_recovers_image_type_from_extension():
    assert _attachment_content_type("invoice.pdf", "application/pdf") == "application/pdf"
    assert _attachment_content_type("photo.webp", "application/octet-stream") == "image/webp"


def test_rejects_non_image_non_pdf():
    assert _attachment_content_type("script.js", "text/javascript") is None
