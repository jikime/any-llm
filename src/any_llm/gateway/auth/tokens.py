import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from any_llm.gateway.config import GatewayConfig


def _get_secret(config: GatewayConfig) -> str:
    """Resolve JWT signing secret, falling back to master key."""
    if config.jwt_secret:
        return config.jwt_secret
    if config.master_key:
        return config.master_key
    msg = "JWT secret not configured. Set jwt_secret or master_key."
    raise RuntimeError(msg)


def hash_token(token: str) -> str:
    """Hash a token with SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_refresh_token() -> str:
    """Generate a refresh token."""
    return secrets.token_urlsafe(48)


def sign_access_token(
    *,
    user_id: str,
    config: GatewayConfig,
    jti: str,
    expires_minutes: int | None = None,
) -> str:
    """Sign an access token (JWT)."""
    exp_minutes = expires_minutes or config.access_token_exp_minutes
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": user_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
    }
    return jwt.encode(payload, _get_secret(config), algorithm="HS256")


def verify_access_token(token: str, config: GatewayConfig) -> dict[str, Any]:
    """Verify and decode an access token, raising on failure."""
    try:
        payload = jwt.decode(token, _get_secret(config), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("Access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid access token: {exc}") from exc
    return payload
