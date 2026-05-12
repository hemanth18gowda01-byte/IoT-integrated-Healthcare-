from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.models import User, UserRole, PatientProfile, HospitalProfile, PharmacyProfile

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    role: UserRole = UserRole.patient


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    full_name: str


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    # Check duplicate
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=data.role,
        is_verified=True,  # Auto-verify for now; add email verification later
    )
    db.add(user)
    db.flush()

    # Create role-specific profile
    if data.role == UserRole.patient:
        profile = PatientProfile(user_id=user.id)
        db.add(profile)
    elif data.role == UserRole.hospital:
        profile = HospitalProfile(user_id=user.id, name=data.full_name)
        db.add(profile)
    elif data.role in (UserRole.pharmacy, UserRole.blood_bank):
        profile = PharmacyProfile(
            user_id=user.id,
            name=data.full_name,
            is_blood_bank=(data.role == UserRole.blood_bank)
        )
        db.add(profile)

    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        full_name=user.full_name,
    )


@router.get("/me")
def get_me(db: Session = Depends(get_db), token: str = Depends(lambda: None)):
    """Get current user info. Frontend calls this on app load."""
    from fastapi import Request
    pass  # Handled in /api/patient/profile endpoint
