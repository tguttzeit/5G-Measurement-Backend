from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Using 'email' field name to maintain fastapi-users compatibility,
    # but it stores usernames, not actual email addresses
    email: Mapped[str] = mapped_column(String(length=255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(length=1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Consecutive wrong `current_password` submissions to POST /auth/change-password.
    # Reset to 0 on successful login, successful self-service change, or superuser-driven change.
    failed_password_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
