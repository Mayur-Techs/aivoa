"""
API integration tests.

Tests that call /api/ai/chat or /api/documents/extract require a live Groq key.
They are skipped automatically in CI (where GROQ_API_KEY is not set) and run
locally when you have a key in your .env file.
"""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _load_env_key() -> str | None:
    """Read GROQ_API_KEY from a .env two levels above this file (repo root)."""
    try:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip()
                if val:
                    os.environ.setdefault("GROQ_API_KEY", val)
                    return val
    except Exception:
        pass
    return None


# Try loading from .env before checking env vars
_load_env_key()
_HAS_GROQ_KEY = bool(os.environ.get("GROQ_API_KEY"))

requires_groq = pytest.mark.skipif(
    not _HAS_GROQ_KEY,
    reason="GROQ_API_KEY not set — skipping live LLM integration tests",
)


def test_local_vite_preflight_is_allowed() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/api/ai/chat",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"


def test_no_groq_key_returns_503() -> None:
    """Without a key the API must return 503, not a silent rules fallback."""
    import unittest.mock as mock
    from app.config import Settings

    no_key_settings = Settings(groq_api_key=None, frontend_origin="http://localhost:5173")
    with mock.patch("app.services.complaint_graph.get_settings", return_value=no_key_settings):
        with TestClient(app) as client:
            response = client.post(
                "/api/ai/chat",
                json={"message": "Test complaint.", "current_complaint": {}},
            )
    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_invalid_document_returns_a_safe_validation_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/extract",
            data={"current_complaint": "{}"},
            files={"file": ("broken.pdf", b"this is not a PDF", "application/pdf")},
        )
    assert response.status_code == 422
    assert "could not be read" in response.json()["detail"]


@requires_groq
def test_chat_then_correction_preserves_intake() -> None:
    with TestClient(app) as client:
        initial = client.post(
            "/api/ai/chat",
            json={
                "message": "Apollo Pharmacy reported discolored capsules in Amoxicillin capsules 500 mg.",
                "current_complaint": {},
            },
        )
        assert initial.status_code == 200
        initial_data = initial.json()
        assert initial_data["complaint"]["product_name"] is not None
        assert initial_data["complaint"]["detailed_complaint_description"]
        assert initial_data["risk_assessment"]["severity"] in {"Major", "Critical"}

        correction = client.post(
            "/api/ai/chat",
            json={
                "message": "Sorry, the batch number is BMX24602 and the affected quantity is 48 capsules.",
                "current_complaint": initial_data["complaint"],
            },
        )
        assert correction.status_code == 200
        updated = correction.json()["complaint"]
        assert updated["product_name"] == initial_data["complaint"]["product_name"]
        assert updated["batch_lot_number"] == "BMX24602"
        assert updated["affected_quantity"] == "48 capsules"
        assert (
            updated["detailed_complaint_description"]
            == initial_data["complaint"]["detailed_complaint_description"]
        )


@requires_groq
def test_eml_upload_extracts_traceability() -> None:
    document = Path(__file__).resolve().parents[2] / "demo-assets" / "metformin-complaint.eml"
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/extract",
            data={"current_complaint": "{}"},
            files={"file": (document.name, document.read_bytes(), "message/rfc822")},
        )
    assert response.status_code == 200
    complaint = response.json()["complaint"]
    assert complaint["product_name"] is not None
    assert complaint["batch_lot_number"] is not None
