from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse
from typing import Any

import requests

from app.config import settings
from app.models import CandidateRecord
from app.storage.repository import CandidateRepository

logger = logging.getLogger(__name__)


class TencentDocsClient:
    def __init__(self) -> None:
        self.repo = CandidateRepository()
        self.last_error = ""

    def append_candidate(self, record: CandidateRecord) -> bool:
        if not self._is_configured():
            self.last_error = "腾讯文档配置不完整。"
            return False

        payload = self._build_payload(record)
        try:
            response = requests.post(
                self._batch_update_url(),
                headers={
                    "Access-Token": settings.tencent_docs_access_token,
                    "Client-Id": settings.tencent_docs_client_id,
                    "Open-Id": settings.tencent_docs_open_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as e:
            self.last_error = f"腾讯文档网络请求失败：{e}"
            return False
        except Exception as e:
            logger.exception("Tencent Docs sync failed unexpectedly.")
            self.last_error = f"腾讯文档同步异常：{e}"
            return False
        updated_cells = body.get("responses", [{}])[0].get("updateRangeResponse", {}).get("updatedCells")
        is_success = isinstance(updated_cells, int) and updated_cells > 0
        if body.get("code") not in (None, 0):
            self.last_error = body.get("message", "腾讯文档接口返回错误。")
            return False
        if body.get("message") not in (None, "", "ok", "OK", "success", "Success"):
            self.last_error = body.get("message", "腾讯文档接口返回失败。")
            return False
        if not is_success:
            self.last_error = "腾讯文档返回 updatedCells=0，未写入任何单元格。请检查应用权限是否包含 scope.sheet / scope.sheet.editable。"
            return False
        self.last_error = ""
        return True

    def file_url(self) -> str:
        return settings.tencent_docs_file_url

    def _build_payload(self, record: CandidateRecord) -> dict[str, Any]:
        row_number = len(self.repo.list_all()) + 2
        cell_range = f"A{row_number}:L{row_number}"
        return {
            "requests": [
                {
                    "updateRangeRequest": {
                        "sheetId": self._sheet_id(),
                        "range": cell_range,
                        "values": [
                            [
                                record.name,
                                record.phone,
                                record.email,
                                record.position_id,
                                record.target_role,
                                record.source,
                                record.score,
                                record.recommendation,
                                record.status,
                                record.file_name,
                                record.updated_at,
                                record.summary,
                            ]
                        ],
                    }
                }
            ]
        }

    def _is_configured(self) -> bool:
        return all(
            [
                settings.tencent_docs_access_token,
                settings.tencent_docs_client_id,
                settings.tencent_docs_open_id,
                self._batch_update_url(),
                self._sheet_id(),
            ]
        )

    def _batch_update_url(self) -> str:
        if settings.tencent_docs_append_rows_url:
            return settings.tencent_docs_append_rows_url
        if not settings.tencent_docs_file_id:
            return ""
        return f"https://docs.qq.com/openapi/spreadsheet/v3/files/{settings.tencent_docs_file_id}/batchUpdate"

    def _sheet_id(self) -> str:
        parsed = urlparse(settings.tencent_docs_file_url)
        query = parse_qs(parsed.query)
        return query.get("tab", [""])[0]
