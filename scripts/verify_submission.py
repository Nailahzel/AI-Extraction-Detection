"""Validate and render the five-page PDF for visual review (development tool)."""

import json
import pymupdf

from modelshield.config import ROOT


def verify():
    path = ROOT / "reports" / "ModelShield-submission.pdf"
    with pymupdf.open(path) as document:
        assert len(document) == 5, f"Expected five pages, got {len(document)}"
        pages = []
        for page in document:
            text = page.get_text()
            assert len(text) > 300, f"Page {page.number+1} is missing content"
            for block in page.get_text("blocks"):
                assert (
                    block[0] >= 20 and block[2] <= page.rect.width - 15
                ), f"Horizontal clipping on page {page.number+1}"
                assert (
                    block[1] >= 15 and block[3] <= page.rect.height - 15
                ), f"Vertical clipping on page {page.number+1}"
            image_path = ROOT / "reports" / f"submission-page-{page.number+1}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(image_path)
            pages.append(
                {
                    "page": page.number + 1,
                    "text_characters": len(text),
                    "images": len(page.get_images()),
                }
            )
        assert (
            pages[-1]["images"] >= 1
        ), "The result page must include actual browser evidence"
    result = {
        "status": "passed",
        "page_count": 5,
        "clipped_text_blocks": 0,
        "pages": pages,
    }
    (ROOT / "reports" / "submission-check.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    verify()
