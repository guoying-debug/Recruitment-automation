from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import CandidateRecord


class StatusMailer:
    def is_configured(self) -> bool:
        return all(
            [
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_user,
                settings.smtp_password,
                settings.smtp_from,
            ]
        )

    def send_status_email(self, record: CandidateRecord, recipients: list[str]) -> tuple[bool, str]:
        cleaned = [item.strip() for item in recipients if item and item.strip()]
        if not cleaned:
            return False, "请先填写候选人收件邮箱。"
        if not self.is_configured():
            return False, "SMTP 未配置，请先在 .env 中补充邮件配置。"

        message = EmailMessage()
        subject, intro, detail_lines, follow_up = self._build_status_copy(record)
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = ", ".join(cleaned)
        detail_html = "".join(
            [
                (
                    f'<tr><td style="padding: 8px; border: 1px solid #ddd; background: #f7f7f7;">{label}</td>'
                    f'<td style="padding: 8px; border: 1px solid #ddd;">{value}</td></tr>'
                )
                for label, value in detail_lines
            ]
        )
        message.set_content(
            "\n".join(
                [
                    f"{record.name or '候选人'} 您好：",
                    "",
                    intro,
                    "",
                    *[f"{label}：{value}" for label, value in detail_lines],
                    "",
                    follow_up,
                    "",
                    "此邮件由招聘自动化系统自动发送，请勿直接回复。",
                ]
            )
        )
        message.add_alternative(
            f"""
            <html>
              <body style="font-family: Arial, sans-serif; color: #222;">
                <p>{record.name or '候选人'} 您好：</p>
                <p>{intro}</p>
                <table style="border-collapse: collapse; min-width: 520px;">
                  {detail_html}
                </table>
                <p>{follow_up}</p>
                <p style="color: #666;">此邮件由招聘自动化系统自动发送，请勿直接回复。</p>
              </body>
            </html>
            """,
            subtype="html",
        )

        try:
            server_factory = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
            with server_factory(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                if settings.smtp_use_tls and not settings.smtp_use_ssl:
                    server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(message)
        except Exception as exc:
            return False, f"邮件发送失败：{exc}"
        return True, f"已发送到 {', '.join(cleaned)}"

    def _build_status_copy(self, record: CandidateRecord) -> tuple[str, str, list[tuple[str, str]], str]:
        base_details = [
            ("应聘岗位", record.target_role or "未填写"),
            ("当前进度", record.status or "待沟通"),
        ]
        if record.status in {"一面", "二面", "终面"}:
            stage_name = {"一面": "面试邀请", "二面": "复试邀请", "终面": "终面邀请"}[record.status]
            details = base_details + [
                ("面试时间", record.interview_time or "待定"),
                ("面试官", record.interviewer or "待安排"),
            ]
            return (
                f"{stage_name} | {record.target_role or record.name or record.file_name}",
                "感谢您参与本次招聘流程。经过评估，诚邀您进入下一轮面试，具体安排如下：",
                details,
                "请您确认是否可以按时参加。如需调整时间，请尽快与我们联系，我们将协助协调。",
            )
        if record.status == "已淘汰":
            details = base_details
            return (
                f"应聘结果通知 | {record.target_role or record.name or record.file_name}",
                "感谢您投递并参与本次岗位应聘。经过综合评估，很遗憾本轮流程暂不继续推进。",
                details,
                "再次感谢您对本岗位的关注与投入，祝您后续求职顺利，未来如有更合适的机会，我们期待再次与您联系。",
            )
        if record.status == "已录用":
            details = base_details + [
                ("Offer薪资", record.offer_salary or "待定"),
                ("预计入职", record.offer_join_date or "待定"),
                ("确认截止", record.offer_deadline or "待定"),
            ]
            return (
                f"Offer 通知 | {record.target_role or record.name or record.file_name}",
                "恭喜您顺利通过本次招聘流程。我们诚挚邀请您加入，Offer 关键信息如下：",
                details,
                "如您接受本次录用安排，请在截止时间前完成确认。如需进一步沟通细节，也欢迎及时与我们联系。",
            )
        details = base_details
        return (
            f"应聘进度通知 | {record.target_role or record.name or record.file_name}",
            "您好，您的应聘流程状态已有更新，请查收最新信息：",
            details,
            "如有问题，欢迎通过原沟通渠道与我们联系。",
        )
