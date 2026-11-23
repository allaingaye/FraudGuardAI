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
    if not inference.is_loaded:
        inference.load()
    yield


@pytest.fixture
def client():
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


def _token(email: str, password: str, role: str) -> str:
    user = _ensure_user(email, password, role)
    return create_access_token(str(user.id), {"role": user.role})


@pytest.fixture
def admin_headers():
    return {
        "Authorization": f"Bearer {_token('t_alerts_admin@example.com', 'TestPass123!', 'admin')}"
    }


@pytest.fixture
def analyst_headers():
    return {
        "Authorization": f"Bearer {_token('t_alerts_analyst@example.com', 'TestPass123!', 'analyst')}"
    }


@pytest.fixture
def auditor_headers():
    return {
        "Authorization": f"Bearer {_token('t_alerts_auditor@example.com', 'TestPass123!', 'auditor')}"
    }


def _create_high_risk_tx(client, headers) -> dict:
    payload = {
        "external_transaction_id": f"TX-ALERT-{uuid.uuid4().hex[:8]}",
        "customer_reference": "CUST-ALERT-001",
        "amount": "12000.00",
        "currency": "JPY",
        "transaction_type": "cash_withdrawal",
        "merchant_reference": "ATM-TEST",
        "occurred_at": datetime(2026, 11, 8, 2, 0, tzinfo=UTC).isoformat(),
        "context": {"country": "JP", "device_reference": "DEV-UNKNOWN"},
    }
    r = client.post(
        "/api/v1/transactions",
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        json=payload,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["alert_id"] is not None
    return body


def test_list_alerts_requires_auth(client):
    assert client.get("/api/v1/alerts").status_code == 401


def test_list_alerts_ok(client, admin_headers):
    r = client.get("/api/v1/alerts", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "total" in body


def test_get_alert_detail(client, admin_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r = client.get(f"/api/v1/alerts/{tx['alert_id']}", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert"]["id"] == tx["alert_id"]
    assert body["alert"]["severity"] == "high"
    assert body["transaction"]["external_transaction_id"] == tx["external_transaction_id"]
    assert body["prediction"]["risk_band"] == "high"
    assert isinstance(body["reviews"], list)


def test_get_alert_not_found(client, admin_headers):
    assert client.get(f"/api/v1/alerts/{uuid.uuid4()}", headers=admin_headers).status_code == 404


def test_update_alert_assign_and_status(client, admin_headers, analyst_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    db = SessionLocal()
    try:
        analyst = db.query(User).filter_by(email="t_alerts_analyst@example.com").first()
        analyst_id = str(analyst.id)
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/alerts/{tx['alert_id']}",
        headers={**analyst_headers, "X-Request-ID": "req-update-1"},
        json={"status": "in_review", "assigned_to": analyst_id, "reason": "Assigning to self"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert"]["status"] == "in_review"
    assert body["alert"]["assigned_to"] == analyst_id


def test_update_alert_invalid_transition(client, admin_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r1 = client.patch(
        f"/api/v1/alerts/{tx['alert_id']}",
        headers=admin_headers,
        json={"status": "in_review", "reason": "Starting review"},
    )
    assert r1.status_code == 200

    r2 = client.patch(
        f"/api/v1/alerts/{tx['alert_id']}",
        headers=admin_headers,
        json={"status": "open", "reason": "Trying to go back"},
    )
    assert r2.status_code == 409


def test_auditor_cannot_update_alert(client, admin_headers, auditor_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r = client.patch(
        f"/api/v1/alerts/{tx['alert_id']}",
        headers=auditor_headers,
        json={"status": "in_review", "reason": "Auditor trying to change"},
    )
    assert r.status_code == 403


def test_submit_review_resolves_alert(client, admin_headers, analyst_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r = client.post(
        f"/api/v1/alerts/{tx['alert_id']}/reviews",
        headers={**analyst_headers, "X-Request-ID": "req-review-1"},
        json={"disposition": "confirmed_fraud", "notes": "Verified with customer call"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["alert"]["status"] == "resolved"
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["disposition"] == "confirmed_fraud"


def test_submit_review_twice_conflict(client, admin_headers, analyst_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r1 = client.post(
        f"/api/v1/alerts/{tx['alert_id']}/reviews",
        headers=analyst_headers,
        json={"disposition": "legitimate", "notes": "Customer confirmed"},
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/api/v1/alerts/{tx['alert_id']}/reviews",
        headers=analyst_headers,
        json={"disposition": "confirmed_fraud", "notes": "Changed my mind"},
    )
    assert r2.status_code == 409


def test_admin_cannot_submit_review(client, admin_headers):
    tx = _create_high_risk_tx(client, admin_headers)
    r = client.post(
        f"/api/v1/alerts/{tx['alert_id']}/reviews",
        headers=admin_headers,
        json={"disposition": "legitimate", "notes": "Admin trying to review"},
    )
    assert r.status_code == 403


def test_alert_audit_trail(client, admin_headers, analyst_headers):
    from app.models.audit import AuditLog

    tx = _create_high_risk_tx(client, admin_headers)
    alert_id = tx["alert_id"]

    client.patch(
        f"/api/v1/alerts/{alert_id}",
        headers=admin_headers,
        json={"status": "in_review", "reason": "Start investigation"},
    )
    client.post(
        f"/api/v1/alerts/{alert_id}/reviews",
        headers=analyst_headers,
        json={"disposition": "legitimate", "notes": "False positive — customer confirmed"},
    )

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.entity_id == alert_id)
            .filter(AuditLog.action.in_(["alert.updated", "alert.reviewed"]))
            .all()
        )
        actions = {r.action for r in rows}
        assert "alert.updated" in actions
        assert "alert.reviewed" in actions
    finally:
        db.close()
