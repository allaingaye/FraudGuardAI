"""Seed demo users. Run: docker compose exec backend python -m app.utils.seed"""

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User
from sqlalchemy import select

DEMO_USERS = [
    {"email": "admin@fraudguard.example.com", "password": "AdminPass123!", "role": "admin"},
    {"email": "analyst@fraudguard.example.com", "password": "AnalystPass123!", "role": "analyst"},
    {"email": "auditor@fraudguard.example.com", "password": "AuditorPass123!", "role": "auditor"},
]


def seed() -> None:
    db = SessionLocal()
    try:
        for spec in DEMO_USERS:
            existing = db.scalar(select(User).where(User.email == spec["email"]))
            if existing:
                print(f"skip existing: {spec['email']}")
                continue
            db.add(
                User(
                    email=spec["email"],
                    password_hash=hash_password(spec["password"]),
                    role=spec["role"],
                    is_active=True,
                )
            )
            print(f"created: {spec['email']} ({spec['role']})")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
