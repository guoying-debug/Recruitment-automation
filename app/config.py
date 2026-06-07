from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    incoming_dir: Path = BASE_DIR / "app" / "incoming"
    processed_dir: Path = BASE_DIR / "app" / "processed"
    data_dir: Path = BASE_DIR / "app" / "data"
    db_path: Path = BASE_DIR / "app" / "data" / "candidates.csv"

    llm_api_key: str = _env("LLM_API_KEY", "ZHIPUAI_API_KEY")
    llm_base_url: str = _env(
        "LLM_BASE_URL",
        "ZHIPUAI_BASE_URL",
        default="https://api.deepseek.com",
    )
    llm_model: str = _env("LLM_MODEL", "TEXT_MODEL", default="deepseek-chat")

    wecom_webhook_url: str = os.getenv("WECOM_WEBHOOK_URL", "")

    tencent_docs_access_token: str = os.getenv("TENCENT_DOCS_ACCESS_TOKEN", "")
    tencent_docs_client_id: str = os.getenv("TENCENT_DOCS_CLIENT_ID", "")
    tencent_docs_open_id: str = os.getenv("TENCENT_DOCS_OPEN_ID", "")
    tencent_docs_file_id: str = os.getenv("TENCENT_DOCS_FILE_ID", "")
    tencent_docs_append_rows_url: str = os.getenv("TENCENT_DOCS_APPEND_ROWS_URL", "")
    tencent_docs_file_url: str = os.getenv("TENCENT_DOCS_FILE_URL", "")

    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_user: str = os.getenv("IMAP_USER", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_folder: str = os.getenv("IMAP_FOLDER", "INBOX")
    imap_enabled: bool = os.getenv("IMAP_ENABLED", "false").lower() == "true"

    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    smtp_use_ssl: bool = os.getenv("SMTP_USE_SSL", "false").lower() == "true"


settings = Settings()
settings.incoming_dir.mkdir(parents=True, exist_ok=True)
settings.processed_dir.mkdir(parents=True, exist_ok=True)
settings.data_dir.mkdir(parents=True, exist_ok=True)
