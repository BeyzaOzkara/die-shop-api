import os
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import User
from .services.auth_service import hash_password

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin123")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Admin")
ADMIN_SURNAME = os.getenv("ADMIN_SURNAME", "User")

def main():
    db: Session = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if existing:
            print("Admin already exists:", ADMIN_USERNAME)
            return

        user = User(
            username=ADMIN_USERNAME,
            name=ADMIN_NAME,
            surname=ADMIN_SURNAME,
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            is_admin=True,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print("Admin created:", ADMIN_USERNAME)
    finally:
        db.close()

if __name__ == "__main__":
    main()
