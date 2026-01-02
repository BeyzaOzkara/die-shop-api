# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services.auth_service import (
    verify_password,
    create_access_token,
    hash_password
)
from ..config import settings
from ..deps import get_current_user

import re
from unidecode import unidecode  # pip install Unidecode

def slug_username(name: str, surname: str) -> str:
    base = f"{name}.{surname}".strip().lower()
    base = unidecode(base)  # türkçe karakterleri düzelt: ş->s, ğ->g
    base = re.sub(r"[^a-z0-9._-]+", "", base)
    base = re.sub(r"\.+", ".", base).strip(".")
    return base[:50] or "user"

def generate_unique_username(db: Session, name: str, surname: str) -> str:
    base = slug_username(name, surname)
    candidate = base
    i = 2
    while db.query(User).filter(User.username == candidate).first():
        suffix = f"-{i}"
        candidate = (base[: (50 - len(suffix))] + suffix)
        i += 1
    return candidate

router = APIRouter(prefix="/auth", tags=["Auth"])


# =========================
# LOGIN
# =========================

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        expires_minutes=settings.JWT_EXPIRES_MINUTES,
    )

    return TokenResponse(access_token=token)


# =========================
# SIGNUP
# =========================

class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    email: str | None = None   # ✅ opsiyonel, validasyon yok


class SignupResponse(TokenResponse):
    generated_username: str


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    username = generate_unique_username(db, payload.name, payload.surname)

    user = User(
        username=username,
        name=payload.name.strip(),
        surname=payload.surname.strip(),
        email=payload.email.strip() if payload.email and payload.email.strip() else None,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=True,  # ✅ bu ekrandan kayıt olan herkes admin
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        subject=str(user.id),
        secret_key=settings.JWT_SECRET_KEY,
        expires_minutes=settings.JWT_EXPIRES_MINUTES,
    )

    return SignupResponse(access_token=token, generated_username=username)


# =========================
# ME
# =========================

class UserMe(BaseModel):
    id: int
    username: str
    name: str
    surname: str
    email: str | None
    is_admin: bool
    is_active: bool


@router.get("/me", response_model=UserMe)
def me(user: User = Depends(get_current_user)):
    return UserMe(
        id=user.id,
        username=user.username,
        name=user.name,
        surname=user.surname,
        email=user.email,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )