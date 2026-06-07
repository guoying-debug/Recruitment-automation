from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class CandidateRecord:
    position_id: str
    source: str
    file_name: str
    name: str
    phone: str
    email: str
    education: str
    years_experience: str
    skills: str
    target_role: str
    score: float
    recommendation: str
    summary: str
    agent_status: str = "待解析"
    status: str = "待沟通"
    interview_time: str = ""
    interviewer: str = ""
    offer_salary: str = ""
    offer_join_date: str = ""
    offer_deadline: str = ""
    synced_to_tencent_docs: bool = False
    pushed_to_wecom: bool = False
    updated_at: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> dict:
        return asdict(self)
