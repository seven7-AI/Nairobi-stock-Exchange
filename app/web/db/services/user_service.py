"""User and organization persistence.

Queries and writes only — no business rules, no role checks. Authorization
already happened at the router.

    codegraph explore "get_user_by_email create_user auth views.py"
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.db.models.enums import UserRole, UserStatus
from app.web.db.models.organization import Organization
from app.web.db.models.user import User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def list_users_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    limit: int,
    created_before: datetime | None = None,
) -> list[User]:
    stmt = select(User).where(User.organization_id == organization_id)
    if created_before is not None:
        stmt = stmt.where(User.created_at < created_before)
    stmt = stmt.order_by(User.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    hashed_password: str,
    organization_id: uuid.UUID,
    role: UserRole,
    full_name: str | None = None,
    status: UserStatus = UserStatus.PENDING_VERIFICATION,
) -> User:
    user = User(
        email=email.lower(),
        hashed_password=hashed_password,
        organization_id=organization_id,
        role=role,
        full_name=full_name,
        status=status,
    )
    session.add(user)
    await session.flush()
    return user


async def mark_email_verified(session: AsyncSession, user: User) -> User:
    user.is_email_verified = True
    user.status = UserStatus.ACTIVE
    await session.flush()
    return user


async def record_login(session: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.now(tz=UTC)
    await session.flush()


async def set_password(session: AsyncSession, user: User, hashed_password: str) -> User:
    user.hashed_password = hashed_password
    await session.flush()
    return user


async def set_role(session: AsyncSession, user: User, role: UserRole) -> User:
    user.role = role
    await session.flush()
    return user


async def set_status(session: AsyncSession, user: User, status: UserStatus) -> User:
    user.status = status
    await session.flush()
    return user


# --- organizations ----------------------------------------------------------
async def get_organization(
    session: AsyncSession, organization_id: uuid.UUID
) -> Organization | None:
    return await session.get(Organization, organization_id)


async def get_organization_by_slug(session: AsyncSession, slug: str) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def list_organizations(
    session: AsyncSession, *, limit: int, created_before: datetime | None = None
) -> list[Organization]:
    stmt = select(Organization)
    if created_before is not None:
        stmt = stmt.where(Organization.created_at < created_before)
    stmt = stmt.order_by(Organization.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_organization(
    session: AsyncSession, *, name: str, slug: str, contact_email: str | None = None
) -> Organization:
    organization = Organization(name=name, slug=slug, contact_email=contact_email)
    session.add(organization)
    await session.flush()
    return organization


__all__ = [
    "create_organization",
    "create_user",
    "get_organization",
    "get_organization_by_slug",
    "get_user_by_email",
    "get_user_by_id",
    "list_organizations",
    "list_users_for_organization",
    "mark_email_verified",
    "record_login",
    "set_password",
    "set_role",
    "set_status",
]
