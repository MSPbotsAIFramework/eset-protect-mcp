"""Non-credential service configuration (SOP §1.2, §9).

No credential field belongs here -- credentials are read per-request from
Headers (see server.py / auth.py), never from the environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080


settings = Settings()
