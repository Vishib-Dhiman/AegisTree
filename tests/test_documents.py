import base64

import pytest

from clearsky import documents
from clearsky.documents import format_documents, parse_pdf, text_document


def make_pdf(pages) -> bytes:
    """A minimal valid PDF; each item is one page's text ('' makes a textless 'scanned' page)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_id = len(objs)
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        )
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_scanned_pdf(text_pages=1) -> bytes:
    """A PDF whose last page is only an image (like a scan), after some text pages."""
    import io
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw

    pdf = pdfium.PdfDocument(make_pdf(["Cover page with enough text to count."] * text_pages))
    page = pdf.new_page(612, 792)
    pil = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(pil).text((20, 80), "SCANNED INVOICE 4471", fill="black")
    image = pdfium.PdfImage.new(pdf)
    image.set_bitmap(pdfium.PdfBitmap.from_pil(pil))
    image.set_matrix(pdfium.PdfMatrix().scale(600, 200).translate(6, 500))
    page.insert_obj(image)
    page.gen_content()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_text_is_extracted_with_page_markers():
    doc = parse_pdf("policy.pdf", b64(make_pdf(["Session tokens must use aegis_seal.", "Retries default to 1."])))
    assert doc.pages == 2 and not doc.scanned_pages and not doc.images
    assert "[Page 1]\nSession tokens must use aegis_seal." in doc.text
    assert "[Page 2]\nRetries default to 1." in doc.text


def test_scanned_pages_are_rendered_for_the_vision_model():
    doc = parse_pdf("scan.pdf", b64(make_scanned_pdf()))
    assert doc.pages == 2 and doc.scanned_pages == [2]
    assert len(doc.images) == 1 and base64.b64decode(doc.images[0])[:2] == b"\xff\xd8"  # JPEG
    assert parse_pdf("scan.pdf", b64(make_scanned_pdf()), render_scans=False).images == []


def test_short_and_blank_pages_are_not_mistaken_for_scans():
    doc = parse_pdf("short.pdf", b64(make_pdf(["Title", ""])))
    assert doc.scanned_pages == [] and doc.images == []
    assert "[Page 1]\nTitle" in doc.text


def test_data_url_prefix_is_accepted():
    doc = parse_pdf("a.pdf", "data:application/pdf;base64," + b64(make_pdf(["Some reasonably long page text."])))
    assert doc.pages == 1


@pytest.mark.parametrize("data, message", [
    (b64(b"hello, not a pdf"), "not a PDF"),
    ("!!!not base64!!!", "base64"),
    (b64(b"%PDF-1.4 but broken"), "couldn't be opened"),
])
def test_bad_files_are_rejected_clearly(data, message):
    with pytest.raises(ValueError) as ex:
        parse_pdf("x.pdf", data)
    assert message in str(ex.value)


def test_size_limit(monkeypatch):
    monkeypatch.setattr(documents, "MAX_PDF_BYTES", 100)
    with pytest.raises(ValueError) as ex:
        parse_pdf("big.pdf", b64(make_pdf(["x" * 200])))
    assert "larger than" in str(ex.value)


def test_page_limit(monkeypatch):
    monkeypatch.setattr(documents, "MAX_PAGES", 2)
    doc = parse_pdf("long.pdf", b64(make_pdf([f"Page {i} has plenty of text on it." for i in range(5)])))
    assert doc.pages == 5 and doc.truncated and "[Page 3]" not in doc.text


def test_prompt_block_marks_documents_as_reference_and_shares_budget():
    a = text_document("a.pdf", "[Page 1]\n" + "alpha " * 3000)
    b = text_document("b.pdf", "[Page 1]\nbeta text")
    block = format_documents([a, b], budget=6000)
    assert "not instructions" in block
    assert "=== a.pdf" in block and "text cut to fit" in block
    assert "=== b.pdf" in block and "beta text" in block
    assert len(block) < 6000 + 600
    assert format_documents([]) is None
