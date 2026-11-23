import uuid
from datetime import UTC, datetime

import pytest
from app.core.security import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.ml.inference import inference
from app.models.user import User
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _ensure_model_loaded():
    """Load the active ML model once per test session.

    TestClient without a context manager does not run FastAPI's lifespan, so
    the inference service would otherwise stay unloaded and every transaction
    test would 500.
    """
    if not inference.is_loaded:
        inference.load()
    yield


@pytest.fixture
def client():
    """TestClient wrapped in a context manager so lifespan runs per-test too."""
    with TestClient(app) as c:
        yield c


def _ensure_user(email: str, password: str, role: str) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).first()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


@pytest.fixture
def auth_header():
    user = _ensure_user("t_tx_admin@example.com", "TestPass123!", "admin")
    token = create_access_token(str(user.id), {"role": user.role})
    return {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": uuid.uuid4().hex,
    }


def _payload(
    external_id: str,
    *,
    amount: str = "50.00",
    currency: str = "USD",
    tx_type: str = "card_payment",
    hour: int = 14,
) -> dict:
    return {
        "external_transaction_id": external_id,
        "customer_reference": "CUST-TEST-001",
        "amount": amount,
        "currency": currency,
        "transaction_type": tx_type,
        "merchant_reference": "MERCHANT-TEST-1",
        "occurred_at": datetime(2026, 11, 8, hour, 0, tzinfo=UTC).isoformat(),
        "context": {"country": "US", "device_reference": "DEV-NEW-TEST"},
    }


def test_create_low_risk_transaction(client, auth_header):
    ext = f"TX-LOW-{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/transactions", headers=auth_header, json=_payload(ext))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["external_transaction_id"] == ext
    assert body["risk_band"] in {"low", "medium"}
    assert body["idempotency_key"] == auth_header["Idempotency-Key"]
    assert body["replayed"] is False


def test_create_high_risk_transaction_creates_alert(client, auth_header):
    ext = f"TX-HIGH-{uuid.uuid4().hex[:8]}"
    payload = _payload(ext, amount="12000.00", currency="JPY", tx_type="cash_withdrawal", hour=2)
    r = client.post("/api/v1/transactions", headers=auth_header, json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["risk_band"] == "high"
    assert body["alert_id"] is not None
    assert body["alert_severity"] == "high"


def test_idempotency_replay_returns_same_response(client, auth_header):
    ext = f"TX-IDEM-{uuid.uuid4().hex[:8]}"
    payload = _payload(ext)

    r1 = client.post("/api/v1/transactions", headers=auth_header, json=payload)
    assert r1.status_code == 201, r1.text
    body1 = r1.json()

    r2 = client.post("/api/v1/transactions", headers=auth_header, json=payload)
    assert r2.status_code == 201, r2.text
    body2 = r2.json()

    assert body1["transaction_id"] == body2["transaction_id"]
    assert body1["alert_id"] == body2["alert_id"]
    assert body2["replayed"] is True


def test_idempotency_conflict_different_payload(client, auth_header):
    ext1 = f"TX-CONF-{uuid.uuid4().hex[:8]}"
    ext2 = f"TX-CONF-{uuid.uuid4().hex[:8]}"

    r1 = client.post("/api/v1/transactions", headers=auth_header, json=_payload(ext1))
    assert r1.status_code == 201

    r2 = client.post("/api/v1/transactions", headers=auth_header, json=_payload(ext2))
    assert r2.status_code == 409


def test_missing_idempotency_key_rejected(client):
    user = _ensure_user("t_tx_admin@example.com", "TestPass123!", "admin")
    token = create_access_token(str(user.id), {"role": user.role})
    r = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {token}"},
        json=_payload(f"TX-NOKEY-{uuid.uuid4().hex[:8]}"),
    )
    assert r.status_code == 422


def test_invalid_currency_rejected(client, auth_header):
    payload = _payload(f"TX-BADCUR-{uuid.uuid4().hex[:8]}", currency="XYZ")
    r = client.post("/api/v1/transactions", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_invalid_amount_rejected(client, auth_header):
    payload = _payload(f"TX-BADAMT-{uuid.uuid4().hex[:8]}", amount="-5.00")
    r = client.post("/api/v1/transactions", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_analyst_role_can_create(client):
    user = _ensure_user("t_tx_analyst@example.com", "TestPass123!", "analyst")
    token = create_access_token(str(user.id), {"role": user.role})
    r = client.post(
        "/api/v1/transactions",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": uuid.uuid4().hex,
        },
        json=_payload(f"TX-ANALYST-{uuid.uuid4().hex[:8]}"),
    )
    assert r.status_code == 201


def test_auditor_role_forbidden(client):
    user = _ensure_user("t_tx_auditor@example.com", "TestPass123!", "auditor")
    token = create_access_token(str(user.id), {"role": user.role})
    r = client.post(
        "/api/v1/transactions",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": uuid.uuid4().hex,
        },
        json=_payload(f"TX-AUD-{uuid.uuid4().hex[:8]}"),
    )
    assert r.status_code == 403


def test_list_transactions(client, auth_header):
    r = client.get("/api/v1/transactions", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert body["limit"] == 50
