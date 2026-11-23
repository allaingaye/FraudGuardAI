from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from fastapi.testclient import TestClient


def _ensure_user(email: str, password: str, role: str) -> None:
    db = SessionLocal()
    try:
        if not db.query(User).filter_by(email=email).first():
            db.add(
                User(email=email, password_hash=hash_password(password), role=role, is_active=True)
            )
            db.commit()
    finally:
        db.close()


def test_login_success_and_me():
    _ensure_user("t_admin@example.com", "TestPass123!", "admin")
    client = TestClient(app)

    r = client.post(
        "/api/v1/auth/login", json={"email": "t_admin@example.com", "password": "TestPass123!"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["role"] == "admin"

    token = body["access_token"]
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["email"] == "t_admin@example.com"


def test_login_wrong_password():
    _ensure_user("t_analyst@example.com", "RightPass123!", "analyst")
    client = TestClient(app)
    r = client.post(
        "/api/v1/auth/login", json={"email": "t_analyst@example.com", "password": "WrongPass123!"}
    )
    assert r.status_code == 401


def test_me_without_token_is_401():
    client = TestClient(app)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
