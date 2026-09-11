"""Small, auditable document readers for the supported demonstration formats."""

from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    pass


def extract_document_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".txt", ".csv"}:
            return content.decode("utf-8", errors="replace")
        if suffix == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
        if suffix == ".docx":
            document = Document(BytesIO(content))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        if suffix == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(content)
            plain_parts = [
                part.get_content()
                for part in message.walk()
                if part.get_content_type() == "text/plain" and not part.get_content_disposition()
            ]
            subject = message.get("subject", "")
            sender = message.get("from", "")
            return f"From: {sender}\nSubject: {subject}\n\n" + "\n".join(plain_parts)
    except Exception as exc:
        raise ValueError("The document could not be read. Upload a valid supported file.") from exc
    raise UnsupportedDocumentError("Supported formats are PDF, DOCX, TXT, CSV, and EML.")
