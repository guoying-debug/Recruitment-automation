from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from app.config import settings
from app.models import CandidateRecord


DEFAULT_COLUMNS = [
    "position_id",
    "source",
    "file_name",
    "name",
    "phone",
    "email",
    "education",
    "years_experience",
    "skills",
    "target_role",
    "score",
    "recommendation",
    "summary",
    "agent_status",
    "status",
    "interview_time",
    "interviewer",
    "offer_salary",
    "offer_join_date",
    "offer_deadline",
    "synced_to_tencent_docs",
    "pushed_to_wecom",
    "updated_at",
]

TEXT_COLUMNS = [
    "position_id",
    "source",
    "file_name",
    "name",
    "phone",
    "email",
    "education",
    "years_experience",
    "skills",
    "target_role",
    "recommendation",
    "summary",
    "agent_status",
    "status",
    "interview_time",
    "interviewer",
    "offer_salary",
    "offer_join_date",
    "offer_deadline",
    "updated_at",
]

JOB_COLUMNS = [
    "position_id",
    "target_role",
    "jd_text",
    "weight_education",
    "weight_experience",
    "weight_skills",
    "weight_role",
    "weight_communication",
]
ROUTE_COLUMNS = ["position_id", "group_name", "webhook_url", "enabled"]

DEFAULT_JOBS = [
    {
        "position_id": "job_ai_hr",
        "target_role": "AI招聘助理",
        "jd_text": "负责招聘流程优化、简历筛选、候选人沟通、数据分析，熟悉 AI 工具与 Excel，具备较强沟通协作能力。",
        "weight_education": 15,
        "weight_experience": 20,
        "weight_skills": 35,
        "weight_role": 15,
        "weight_communication": 15,
    },
    {
        "position_id": "job_data_analyst",
        "target_role": "数据分析师",
        "jd_text": "负责招聘数据分析、报表整理、渠道转化分析，熟悉 SQL、Excel、可视化工具，具备业务沟通能力。",
        "weight_education": 15,
        "weight_experience": 20,
        "weight_skills": 35,
        "weight_role": 15,
        "weight_communication": 15,
    },
]

DEFAULT_ROUTES = [
    {
        "position_id": "job_ai_hr",
        "group_name": "AI招聘群",
        "webhook_url": "",
        "enabled": True,
    },
    {
        "position_id": "job_data_analyst",
        "group_name": "数据分析招聘群",
        "webhook_url": "",
        "enabled": True,
    },
]


class CandidateRepository:
    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or settings.db_path
        self._ensure_store()

    def _ensure_store(self) -> None:
        if not self.csv_path.exists():
            pd.DataFrame(columns=DEFAULT_COLUMNS).to_csv(self.csv_path, index=False, encoding="utf-8-sig")

    def list_all(self) -> pd.DataFrame:
        self._ensure_store()
        df = pd.read_csv(self.csv_path)
        for column in DEFAULT_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        for column in TEXT_COLUMNS:
            if column in df.columns:
                df[column] = df[column].fillna("").astype(str)
        return df[DEFAULT_COLUMNS]

    def upsert(self, record: CandidateRecord) -> None:
        df = self.list_all()
        mask = (df["file_name"] == record.file_name) & (df["phone"].fillna("") == record.phone)
        row = record.to_dict()
        if mask.any():
            for column in DEFAULT_COLUMNS:
                df.loc[mask, column] = row[column]
        else:
            df = pd.concat([df, pd.DataFrame([row], columns=DEFAULT_COLUMNS)], ignore_index=True)
        df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")

    def update_statuses(
        self,
        file_name: str,
        phone: str,
        candidate_status: str,
        interview_time: str = "",
        interviewer: str = "",
        offer_salary: str = "",
        offer_join_date: str = "",
        offer_deadline: str = "",
    ) -> bool:
        df = self.list_all()
        phone_value = phone or ""
        mask = (df["file_name"] == file_name) & (df["phone"].fillna("") == phone_value)
        if not mask.any():
            return False
        df.loc[mask, "status"] = candidate_status
        recommendation = _derive_recommendation_from_status(candidate_status)
        if recommendation:
            df.loc[mask, "recommendation"] = recommendation
        df.loc[mask, "interview_time"] = interview_time
        df.loc[mask, "interviewer"] = interviewer
        df.loc[mask, "offer_salary"] = offer_salary
        df.loc[mask, "offer_join_date"] = offer_join_date
        df.loc[mask, "offer_deadline"] = offer_deadline
        df.loc[mask, "updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")
        return True

    def stats(self) -> dict:
        df = self.list_all()
        if df.empty:
            return {"total": 0, "avg_score": 0, "recommended": 0, "synced": 0}
        return {
            "total": int(len(df)),
            "avg_score": round(float(df["score"].fillna(0).astype(float).mean()), 1),
            "recommended": int((df["recommendation"] == "推荐").sum()),
            "synced": int(df["synced_to_tencent_docs"].fillna(False).astype(bool).sum()),
        }


class JobRepository:
    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or (settings.data_dir / "positions.csv")
        self._ensure_store()

    def _ensure_store(self) -> None:
        if not self.csv_path.exists():
            pd.DataFrame(DEFAULT_JOBS, columns=JOB_COLUMNS).to_csv(self.csv_path, index=False, encoding="utf-8-sig")

    def list_all(self) -> pd.DataFrame:
        self._ensure_store()
        df = pd.read_csv(self.csv_path)
        for column in JOB_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        return df[JOB_COLUMNS].fillna("")

    def upsert(
        self,
        position_id: str,
        target_role: str,
        jd_text: str,
        weight_education: float = 15,
        weight_experience: float = 20,
        weight_skills: float = 35,
        weight_role: float = 15,
        weight_communication: float = 15,
    ) -> None:
        df = self.list_all()
        mask = df["position_id"] == position_id
        row = {
            "position_id": position_id,
            "target_role": target_role,
            "jd_text": jd_text,
            "weight_education": weight_education,
            "weight_experience": weight_experience,
            "weight_skills": weight_skills,
            "weight_role": weight_role,
            "weight_communication": weight_communication,
        }
        if mask.any():
            for column in JOB_COLUMNS:
                df.loc[mask, column] = row[column]
        else:
            df = pd.concat([df, pd.DataFrame([row], columns=JOB_COLUMNS)], ignore_index=True)
        df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")


class WeComRouteRepository:
    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or (settings.data_dir / "wecom_routes.csv")
        self._ensure_store()

    def _ensure_store(self) -> None:
        if not self.csv_path.exists():
            pd.DataFrame(DEFAULT_ROUTES, columns=ROUTE_COLUMNS).to_csv(self.csv_path, index=False, encoding="utf-8-sig")

    def list_all(self) -> pd.DataFrame:
        self._ensure_store()
        df = pd.read_csv(self.csv_path)
        for column in ROUTE_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        return df[ROUTE_COLUMNS].fillna("")

    def list_by_position(self, position_id: str) -> pd.DataFrame:
        df = self.list_all()
        enabled_series = df["enabled"].astype(str).str.lower().isin(["true", "1", "yes", "y"])
        return df[(df["position_id"] == position_id) & enabled_series & (df["webhook_url"].str.strip() != "")]

    def upsert(self, position_id: str, group_name: str, webhook_url: str, enabled: bool = True) -> None:
        df = self.list_all()
        mask = (df["position_id"] == position_id) & (df["group_name"] == group_name)
        row = {
            "position_id": position_id,
            "group_name": group_name,
            "webhook_url": webhook_url,
            "enabled": enabled,
        }
        if mask.any():
            for column in ROUTE_COLUMNS:
                df.loc[mask, column] = row[column]
        else:
            df = pd.concat([df, pd.DataFrame([row], columns=ROUTE_COLUMNS)], ignore_index=True)
        df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")


def _derive_recommendation_from_status(candidate_status: str) -> str:
    mapping = {
        "一面": "一面",
        "二面": "二面",
        "终面": "终面",
        "已淘汰": "不推荐",
        "已录用": "已录用",
    }
    return mapping.get(candidate_status, "")
