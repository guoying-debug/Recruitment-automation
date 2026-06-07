from __future__ import annotations

import email
import imaplib
from datetime import date
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from app.config import settings
from app.services.file_utils import SUPPORTED_EXTENSIONS


class ResumeCollector:
    def collect_local_files(self) -> list[Path]:
        return [
            path
            for path in settings.incoming_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

    def collect_from_imap(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        sender_keyword: str = "",
        subject_keyword: str = "",
        unread_only: bool = False,
    ) -> list[Path]:
        if not settings.imap_enabled:
            return []

        saved_files: list[Path] = []
        with imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port) as mail:
            mail.login(settings.imap_user, settings.imap_password)
            mail.select(settings.imap_folder)
            search_flag = "UNSEEN" if unread_only else "ALL"
            status, messages = mail.search(None, search_flag)
            if status != "OK":
                return []

            for num in messages[0].split():
                _, data = mail.fetch(num, "(RFC822)")
                message = email.message_from_bytes(data[0][1])
                if not self._message_matches(message, start_date, end_date, sender_keyword, subject_keyword):
                    continue
                saved_files.extend(self._save_attachments(message))
        return saved_files

    def _message_matches(
        self,
        message: email.message.Message,
        start_date: date | None,
        end_date: date | None,
        sender_keyword: str,
        subject_keyword: str,
    ) -> bool:
        message_date = self._parse_message_date(message)
        if start_date and (not message_date or message_date < start_date):
            return False
        if end_date and (not message_date or message_date > end_date):
            return False

        sender_text = self._decode_header_value(message.get("From", "")).lower()
        if sender_keyword.strip() and sender_keyword.strip().lower() not in sender_text:
            return False

        subject_text = self._decode_header_value(message.get("Subject", "")).lower()
        if subject_keyword.strip() and subject_keyword.strip().lower() not in subject_text:
            return False
        return True

    def _parse_message_date(self, message: email.message.Message) -> date | None:
        raw_date = message.get("Date", "")
        if not raw_date:
            return None
        try:
            return parsedate_to_datetime(raw_date).date()
        except (TypeError, ValueError, IndexError, OverflowError):
            return None

    def _decode_header_value(self, value: str) -> str:
        parts: list[str] = []
        for decoded, encoding in decode_header(value):
            if isinstance(decoded, bytes):
                parts.append(decoded.decode(encoding or "utf-8", errors="ignore"))
            else:
                parts.append(decoded)
        return "".join(parts)

    def _save_attachments(self, message: email.message.Message) -> list[Path]:
        saved_files: list[Path] = []
        for part in message.walk():
            disposition = part.get("Content-Disposition", "")
            if "attachment" not in disposition:
                continue

            file_name = part.get_filename()
            if not file_name:
                continue
            file_name = self._decode_header_value(file_name)

            path = settings.incoming_dir / file_name
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            path.write_bytes(part.get_payload(decode=True))
            saved_files.append(path)
        return saved_files
