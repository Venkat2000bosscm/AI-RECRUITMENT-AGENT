from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


def current_user(x_user_id: int | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    """Demo identity via X-User-Id header. Replace with SSO/OIDC in production."""
    user = db.get(User, x_user_id) if x_user_id else db.scalars(select(User).where(User.role == "recruiter")).first()
    if user is None:
        raise HTTPException(401, "Unknown user")
    return user
