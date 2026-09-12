from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


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
        assert initial_data["complaint"]["product_name"] == "Amoxicillin capsules"
        assert initial_data["complaint"]["detailed_complaint_description"]
        assert initial_data["risk_assessment"]["severity"] == "Major"

        correction = client.post(
            "/api/ai/chat",
            json={
                "message": "Sorry, the batch number is BMX24602 and the affected quantity is 48 capsules.",
                "current_complaint": initial_data["complaint"],
            },
        )
        assert correction.status_code == 200
        updated = correction.json()["complaint"]
        assert updated["product_name"] == "Amoxicillin capsules"
        assert updated["batch_lot_number"] == "BMX24602"
        assert updated["affected_quantity"] == "48 capsules"
        assert updated["detailed_complaint_description"] == initial_data["complaint"]["detailed_complaint_description"]


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
    assert complaint["product_name"] == "Metformin Hydrochloride API"
    assert complaint["product_strength_grade"].lower() == "ip/bp"
    assert complaint["batch_lot_number"] == "MFH260712A"
    assert complaint["affected_quantity"] == "48 kg (2 HDPE drums)"


def test_invalid_document_returns_a_safe_validation_error() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/extract",
            data={"current_complaint": "{}"},
            files={"file": ("broken.pdf", b"this is not a PDF", "application/pdf")},
        )
    assert response.status_code == 422
    assert response.json()["detail"] == "The document could not be read. Upload a valid supported file."
