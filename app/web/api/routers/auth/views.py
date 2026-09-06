"""Authentication routes: register, login, refresh, verify, reset.

The only unauthenticated routes in the service. Everything else declares
``Depends(require_roles(...))``.

Two behaviours are deliberate and should not be "fixed" into friendlier ones:

* login returns the same error for an unknown email and a wrong password —
  distinguishing them turns the endpoint into a user-enumeration oracle;
* password-reset request always reports success, for the same reason.

    codegraph explore "auth views.py create_access_token get_user_by_email"
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.web.api.deps import CurrentUserDep, EmailDep, SessionDep, SettingsDep
from app.web.api.routers.auth.schema import (
    AccessToken,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPair,
    UserRead,
    VerifyEmailRequest,
)
from app.web.core.exceptions import AuthenticationError, ResourceConflictError
from app.web.core.security import (
    TokenType,
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.web.db.models.enums import UserRole, UserStatus
from app.web.db.services import onboarding_service, user_service
from app.web.services.email import EmailMessagePayload
from app.web.utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("app.web.api.auth")


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: SessionDep,
    settings: SettingsDep,
    email_service: EmailDep,
) -> RegisterResponse:
    """Create an organization and its first user, who becomes ``org_admin``."""
    if await user_service.get_user_by_email(session, payload.email) is not None:
        raise ResourceConflictError("An account with that email already exists.")

    slug = payload.organization_slug
    if await user_service.get_organization_by_slug(session, slug) is not None:
        raise ResourceConflictError("An organization with that name already exists.")

    organization = await user_service.create_organization(
        session, name=payload.organization_name, slug=slug, contact_email=payload.email
    )
    user = await user_service.create_user(
        session,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        organization_id=organization.id,
        role=UserRole.ORG_ADMIN,
        full_name=payload.full_name,
    )
    await onboarding_service.get_or_create_state(session, organization.id)

    verify_token = create_purpose_token(
        settings,
        user_id=user.id,
        email=user.email,
        role=user.role,
        organization_id=organization.id,
        token_type=TokenType.EMAIL_VERIFY,
    )
    sent = email_service.send(
        EmailMessagePayload(
            to=user.email,
            subject="Verify your NSE Analytics account",
            body=f"Confirm your address with this token:\n\n{verify_token}\n",
        )
    )
    logger.info("user_registered", user_id=str(user.id), organization_id=str(organization.id))
    return RegisterResponse(
        user=UserRead.model_validate(user),
        organization_id=organization.id,
        verification_email_sent=sent,
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    """Exchange credentials for an access/refresh pair."""
    user = await user_service.get_user_by_email(session, payload.email)
    # Same error either way: never reveal whether the address exists.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise AuthenticationError(
            "Incorrect email or password.", detail=f"login failed for {payload.email}"
        )
    if user.status == UserStatus.DISABLED:
        raise AuthenticationError("This account has been disabled.")

    await user_service.record_login(session, user)
    logger.info("user_logged_in", user_id=str(user.id))
    return TokenPair(
        access_token=create_access_token(
            settings,
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
        ),
        refresh_token=create_refresh_token(
            settings,
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
        ),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=AccessToken)
async def refresh(
    payload: RefreshRequest, session: SessionDep, settings: SettingsDep
) -> AccessToken:
    """Exchange a refresh token for a fresh access token.

    The role is re-read from the database rather than copied from the token, so
    a revoked or downgraded role takes effect on the next refresh.
    """
    claims = decode_token(settings, payload.refresh_token, expected_type=TokenType.REFRESH)
    user = await user_service.get_user_by_id(session, claims.sub)
    if user is None or user.status == UserStatus.DISABLED:
        raise AuthenticationError(detail=f"refresh for missing/disabled user {claims.sub}")

    return AccessToken(
        access_token=create_access_token(
            settings,
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
        ),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest, session: SessionDep, settings: SettingsDep
) -> MessageResponse:
    """Confirm an email address using the token from the verification email."""
    claims = decode_token(settings, payload.token, expected_type=TokenType.EMAIL_VERIFY)
    user = await user_service.get_user_by_id(session, claims.sub)
    if user is None:
        raise AuthenticationError(detail=f"verify for missing user {claims.sub}")

    await user_service.mark_email_verified(session, user)
    logger.info("email_verified", user_id=str(user.id))
    return MessageResponse(message="Email address verified.")


@router.post("/password-reset/request", response_model=MessageResponse)
async def request_password_reset(
    payload: PasswordResetRequest,
    session: SessionDep,
    settings: SettingsDep,
    email_service: EmailDep,
) -> MessageResponse:
    """Send a reset token. Always reports success, whether or not the user exists."""
    user = await user_service.get_user_by_email(session, payload.email)
    if user is not None:
        token = create_purpose_token(
            settings,
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.organization_id,
            token_type=TokenType.PASSWORD_RESET,
            expires_in_hours=1,
        )
        email_service.send(
            EmailMessagePayload(
                to=user.email,
                subject="Reset your NSE Analytics password",
                body=f"Use this token to set a new password:\n\n{token}\n",
            )
        )
        logger.info("password_reset_requested", user_id=str(user.id))

    return MessageResponse(
        message="If an account exists for that address, a reset email has been sent."
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirm, session: SessionDep, settings: SettingsDep
) -> MessageResponse:
    """Set a new password using a reset token."""
    claims = decode_token(settings, payload.token, expected_type=TokenType.PASSWORD_RESET)
    user = await user_service.get_user_by_id(session, claims.sub)
    if user is None:
        raise AuthenticationError(detail=f"reset for missing user {claims.sub}")

    await user_service.set_password(session, user, hash_password(payload.password))
    logger.info("password_reset_completed", user_id=str(user.id))
    return MessageResponse(message="Password updated.")


@router.get("/me", response_model=UserRead)
async def read_me(current_user: CurrentUserDep, session: SessionDep) -> UserRead:
    """The authenticated caller. Open to every role — it returns only their own row."""
    user = await user_service.get_user_by_id(session, current_user.id)
    if user is None:
        raise AuthenticationError(detail=f"token subject {current_user.id} no longer exists")
    return UserRead.model_validate(user)


__all__ = ["router"]
