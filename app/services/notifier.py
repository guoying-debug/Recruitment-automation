from __future__ import annotations

import logging

import requests

from app.config import settings
from app.models import CandidateRecord
from app.storage.repository import WeComRouteRepository

logger = logging.getLogger(__name__)


class WeComNotifier:
    def __init__(self, route_repo: WeComRouteRepository | None = None) -> None:
        self.route_repo = route_repo or WeComRouteRepository()
        self.last_error = ""

    def push_candidate(self, record: CandidateRecord, doc_url: str = "") -> bool:
        webhook_urls = self._resolve_webhooks(record.position_id)
        if not webhook_urls:
            self.last_error = "未配置企业微信机器人 webhook。"
            return False

        lines = [
            "## 新候选人入库通知",
            f"> 岗位ID：`{record.position_id or '未填写'}`",
            f"> 姓名：**{record.name or '未知'}**",
            f"> 手机：{record.phone or '未识别'}",
            f"> 岗位：{record.target_role or '未填写'}",
            f"> 匹配分：<font color=\"info\">{record.score}</font>",
            f"> 结论：<font color=\"comment\">{record.recommendation}</font>",
            f"> Agent状态：{record.agent_status}",
            f"> 候选人状态：{record.status}",
        ]
        if doc_url:
            lines.append(f"> [腾讯文档查看详情]({doc_url})")
        if record.summary:
            lines.append(f"> 摘要：{record.summary[:120]}")

        payload = {"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}}
        success = False
        try:
            for webhook_url in webhook_urls:
                response = requests.post(webhook_url, json=payload, timeout=20)
                response.raise_for_status()
                body = response.json()
                success = success or body.get("errcode") == 0
        except requests.RequestException as e:
            self.last_error = f"企业微信推送失败：{e}"
            return False
        except Exception as e:
            logger.exception("WeCom push failed unexpectedly.")
            self.last_error = f"企业微信推送异常：{e}"
            return False
        self.last_error = ""
        return success

    def _resolve_webhooks(self, position_id: str) -> list[str]:
        routes = self.route_repo.list_by_position(position_id)
        webhook_urls = routes["webhook_url"].tolist() if not routes.empty else []
        if webhook_urls:
            return webhook_urls
        return [settings.wecom_webhook_url] if settings.wecom_webhook_url else []
