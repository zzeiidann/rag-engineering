from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def load_document(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    elif suffix in {".md", ".txt"}:
        text = content.decode("utf-8")
    else:
        raise ValueError("Supported document formats: PDF, Markdown, TXT")
    if not text.strip():
        raise ValueError("Document contains no extractable text; scanned PDFs require OCR")
    return text
