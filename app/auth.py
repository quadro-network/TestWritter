from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_import_token(x_import_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = (settings.import_token or "").strip()
    if not expected:
        return
    if not x_import_token or x_import_token.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Import-Token",
        )
