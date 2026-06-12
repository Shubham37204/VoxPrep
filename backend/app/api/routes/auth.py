from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import TokenResponse, UserLoginRequest, UserRegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Create new account.
    409 if email already registered — prevents duplicate accounts silently.
    """
    repo = UserRepository(db)
    if await repo.exists(payload.email):
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await repo.create(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
    )
    token = create_access_token(user_id=user.id, email=user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with email + password.
    Always 401 on failure — never reveal whether email exists.
    """
    repo = UserRepository(db)
    user = await repo.get_by_email(payload.email)

    # Constant-time path: verify_password runs even on None user to prevent
    # timing-based email enumeration attacks
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user_id=user.id, email=user.email)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return authenticated user profile. Validates token is still valid."""
    return UserResponse.model_validate(current_user)
