from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import pdfplumber
import streamlit as st

from app.config import settings
from app.models import CandidateRecord
from app.services.collector import ResumeCollector
from app.services.file_utils import SUPPORTED_EXTENSIONS, extract_text, rename_resume
from app.services.mailer import StatusMailer
from app.services.notifier import WeComNotifier
from app.services.resume_parser import ResumeParser
from app.services.scoring import JDScorer
from app.services.tencent_docs import TencentDocsClient
from app.storage.repository import CandidateRepository, JobRepository, WeComRouteRepository


st.set_page_config(page_title="招聘自动化 MVP", page_icon="🤖", layout="wide")
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background: #f7f9fc;
        border: 1px solid #e7edf5;
        border-radius: 14px;
        padding: 12px 14px;
    }
    div[data-testid="stExpander"] {
        border: 1px solid #e7edf5;
        border-radius: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

repo = CandidateRepository()
job_repo = JobRepository()
route_repo = WeComRouteRepository()
collector = ResumeCollector()
parser = ResumeParser()
scorer = JDScorer()
notifier = WeComNotifier(route_repo=route_repo)
tencent_docs = TencentDocsClient()
mailer = StatusMailer()

EXPORT_COLUMN_LABELS = {
    "position_id": "岗位ID",
    "source": "来源",
    "file_name": "文件名",
    "name": "姓名",
    "phone": "电话",
    "email": "邮箱",
    "education": "学历",
    "years_experience": "工作年限",
    "skills": "技能",
    "target_role": "岗位名称",
    "score": "匹配评分",
    "recommendation": "推荐结论",
    "summary": "摘要",
    "agent_status": "Agent状态",
    "status": "候选人状态",
    "interview_time": "面试时间",
    "interviewer": "面试官",
    "offer_salary": "Offer薪资",
    "offer_join_date": "预计入职",
    "offer_deadline": "Offer截止",
    "synced_to_tencent_docs": "已同步腾讯文档",
    "pushed_to_wecom": "已推送企业微信",
    "updated_at": "更新时间",
    "dimension_education": "教育背景",
    "dimension_experience": "工作经验",
    "dimension_skills": "核心技能",
    "dimension_role": "岗位匹配",
    "dimension_communication": "沟通协作",
}

JOB_COLUMN_LABELS = {
    "position_id": "岗位ID",
    "target_role": "岗位名称",
    "jd_text": "JD文本",
    "weight_education": "教育背景权重",
    "weight_experience": "工作经验权重",
    "weight_skills": "核心技能权重",
    "weight_role": "岗位匹配权重",
    "weight_communication": "沟通协作权重",
}

ROUTE_COLUMN_LABELS = {
    "position_id": "岗位ID",
    "group_name": "群名称",
    "webhook_url": "Webhook地址",
    "enabled": "是否启用",
}

RECOMMENDATION_LABELS = {
    "recommended": "推荐",
    "recommend": "推荐",
    "strong recommend": "推荐",
    "further interview": "待定",
    "interview": "待定",
    "pending": "待定",
    "hold": "待定",
    "maybe": "待定",
    "not recommended": "不推荐",
    "reject": "不推荐",
    "rejected": "不推荐",
    "no": "不推荐",
    "推荐": "推荐",
    "待定": "待定",
    "不推荐": "不推荐",
    "一面": "一面",
    "二面": "二面",
    "终面": "终面",
    "已录用": "已录用",
}
BOARD_RECOMMENDATION_OPTIONS = ["全部", "推荐", "待定", "一面", "二面", "终面", "已录用", "不推荐"]
POSITIVE_RECOMMENDATIONS = {"推荐", "一面", "二面", "终面", "已录用"}

AGENT_STATUS_OPTIONS = ["待解析", "待评估", "已解析", "已评估"]
CANDIDATE_STATUS_OPTIONS = ["待沟通", "一面", "二面", "终面", "已淘汰", "已录用"]
INTERVIEWER_OPTIONS = ["未分配", "张经理", "李总监", "王主管", "HRBP", "自定义"]
STATUS_COLOR_MAP = {
    "待解析": "#9e9e9e",
    "待评估": "#ff9800",
    "已解析": "#03a9f4",
    "已评估": "#4caf50",
    "待沟通": "#607d8b",
    "一面": "#3f51b5",
    "二面": "#673ab7",
    "终面": "#e91e63",
    "已淘汰": "#f44336",
    "已录用": "#009688",
}
STATUS_TAG_MAP = {
    "待解析": "⚪ 待解析",
    "待评估": "🟠 待评估",
    "已解析": "🔵 已解析",
    "已评估": "🟢 已评估",
    "待沟通": "⚫ 待沟通",
    "一面": "🔷 一面",
    "二面": "🟣 二面",
    "终面": "🌸 终面",
    "已淘汰": "🔴 已淘汰",
    "已录用": "🟢 已录用",
}

DEFAULT_DIMENSION_WEIGHTS = {
    "教育背景": 15.0,
    "工作经验": 20.0,
    "核心技能": 35.0,
    "岗位匹配": 15.0,
    "沟通协作": 15.0,
}
DEGREE_BASE_SCORES = {
    "博士": 15.0,
    "硕士": 14.0,
    "研究生": 14.0,
    "本科": 12.0,
    "大专": 8.0,
}
EXPERIENCE_SCORE_BANDS = [
    (6, 20.0),
    (4, 18.0),
    (2, 14.0),
    (1, 10.0),
    (0, 6.0),
]
COMMUNICATION_KEYWORDS = ["沟通", "协作", "协调", "对接", "推进", "汇报", "跨部门", "招聘"]
ROLE_ALIGNMENT_KEYWORDS = ["招聘", "分析", "AI", "产品", "运营", "销售", "技术", "管理"]


def save_uploaded_files(uploaded_files: list) -> list[Path]:
    saved_paths: list[Path] = []
    for uploaded in uploaded_files:
        target_path = settings.incoming_dir / uploaded.name
        target_path.write_bytes(uploaded.getbuffer())
        saved_paths.append(target_path)
    return saved_paths


def auto_save_uploaded_files(uploaded_files: list) -> list[Path]:
    if "saved_upload_keys" not in st.session_state:
        st.session_state.saved_upload_keys = set()

    newly_saved: list[Path] = []
    for uploaded in uploaded_files:
        upload_key = f"{uploaded.name}:{uploaded.size}"
        if upload_key in st.session_state.saved_upload_keys:
            continue
        target_path = settings.incoming_dir / uploaded.name
        target_path.write_bytes(uploaded.getbuffer())
        st.session_state.saved_upload_keys.add(upload_key)
        newly_saved.append(target_path)
    return newly_saved


def clear_uploaded_resume_files() -> tuple[int, int]:
    removed_incoming = 0
    removed_processed = 0
    for directory in (settings.incoming_dir, get_processed_dir()):
        for path in directory.iterdir():
            if not path.is_file():
                continue
            path.unlink(missing_ok=True)
            if directory == settings.incoming_dir:
                removed_incoming += 1
            else:
                removed_processed += 1
    st.session_state.saved_upload_keys = set()
    st.session_state.resume_uploader_version = st.session_state.get("resume_uploader_version", 0) + 1
    return removed_incoming, removed_processed


def clear_candidate_data() -> int:
    existing_count = len(repo.list_all())
    pd.DataFrame(columns=repo.list_all().columns).to_csv(repo.csv_path, index=False, encoding="utf-8-sig")
    st.session_state.pop("candidate_status_overrides", None)
    return existing_count


def process_resume(
    file_path: Path,
    source: str,
    position_id: str,
    jd_text: str,
    target_role: str,
    weights: dict[str, float] | None = None,
) -> CandidateRecord:
    resume_text = extract_text(file_path)
    parsed = parser.parse(resume_text, target_role)
    try:
        scoring = scorer.score(parsed, jd_text, weights=weights)
    except TypeError:
        scoring = scorer.score(parsed, jd_text)
    scorecard = build_scorecard(parsed, jd_text, weights=weights)
    scoring["score"] = float(scorecard["total_score"])
    scoring["final_match_score"] = float(scorecard["total_score"])
    scoring["total_score"] = float(scorecard["total_score"])
    scoring["dimensions"] = scorecard["dimensions"]
    if not str(scoring.get("recommendation") or "").strip():
        if scorecard["total_score"] >= 80:
            scoring["recommendation"] = "推荐"
        elif scorecard["total_score"] >= 65:
            scoring["recommendation"] = "待定"
        else:
            scoring["recommendation"] = "不推荐"

    renamed_path = rename_resume(
        file_path=file_path,
        name=parsed.get("name", ""),
        phone=parsed.get("phone", ""),
        target_role=parsed.get("target_role", target_role),
    )

    record = CandidateRecord(
        position_id=position_id,
        source=source,
        file_name=renamed_path.name,
        name=parsed.get("name", ""),
        phone=parsed.get("phone", ""),
        email=parsed.get("email", ""),
        education=parsed.get("education", ""),
        years_experience=parsed.get("years_experience", ""),
        skills=parsed.get("skills", ""),
        target_role=parsed.get("target_role", target_role),
        score=float(scoring.get("score", 0)),
        recommendation=scoring.get("recommendation", "待定"),
        summary=scoring.get("reason") or parsed.get("summary", ""),
        agent_status="已评估",
        status="待沟通",
    )
    return record


def get_processed_dir() -> Path:
    processed_dir = getattr(settings, "processed_dir", settings.base_dir / "app" / "processed")
    processed_dir.mkdir(parents=True, exist_ok=True)
    return processed_dir


def archive_processed_resume(file_path: Path) -> Path:
    processed_dir = get_processed_dir()
    if not file_path.exists():
        return processed_dir / file_path.name
    target_path = processed_dir / file_path.name
    if not target_path.exists():
        return file_path.rename(target_path)

    stem = file_path.stem
    suffix = file_path.suffix.lower()
    counter = 1
    while True:
        candidate_path = processed_dir / f"{stem}_{counter}{suffix}"
        if not candidate_path.exists():
            return file_path.rename(candidate_path)
        counter += 1


def sync_record(record: CandidateRecord) -> CandidateRecord:
    try:
        tencent_docs_success = tencent_docs.append_candidate(record)
    except Exception as exc:
        tencent_docs.last_error = f"腾讯文档同步异常：{exc}"
        tencent_docs_success = False
    if tencent_docs_success:
        record.synced_to_tencent_docs = True
    try:
        wecom_success = notifier.push_candidate(record, tencent_docs.file_url())
    except Exception as exc:
        notifier.last_error = f"企业微信推送异常：{exc}"
        wecom_success = False
    if wecom_success:
        record.pushed_to_wecom = True
    repo.upsert(record)
    return record


def export_candidates_csv(df: pd.DataFrame) -> bytes:
    jobs_by_position = {
        str(row.position_id): row._asdict()
        for row in job_repo.list_all().itertuples(index=False)
    }
    export_df = build_candidate_display_df(df, jobs_by_position)
    return export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def normalize_recommendation(value: object) -> str:
    text = str(value or "").strip()
    key = text.lower()
    return RECOMMENDATION_LABELS.get(key, text or "待定")


def format_bool_cn(value: object) -> str:
    text = str(value).strip().lower()
    return "是" if text in {"true", "1", "yes", "y"} else "否"


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def get_job_dimension_weights(job_info: dict[str, object]) -> dict[str, float]:
    column_map = {
        "教育背景": "weight_education",
        "工作经验": "weight_experience",
        "核心技能": "weight_skills",
        "岗位匹配": "weight_role",
        "沟通协作": "weight_communication",
    }
    weights: dict[str, float] = {}
    for dimension_name, column_name in column_map.items():
        try:
            weights[dimension_name] = float(job_info.get(column_name, DEFAULT_DIMENSION_WEIGHTS[dimension_name]))
        except (TypeError, ValueError):
            weights[dimension_name] = float(DEFAULT_DIMENSION_WEIGHTS[dimension_name])
    return weights


def normalize_score_100(score: object) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    if value <= 10:
        value *= 10
    return min(round(value, 1), 100.0)


def extract_keywords(text: str) -> list[str]:
    raw_keywords = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}|[\u4e00-\u9fff]{2,}", text or "")
    stopwords = {"负责", "熟悉", "具备", "较强", "能力", "相关", "工作", "岗位", "进行", "以及"}
    keywords: list[str] = []
    for keyword in raw_keywords:
        normalized = keyword.strip()
        if normalized in stopwords or len(normalized) < 2:
            continue
        if normalized not in keywords:
            keywords.append(normalized)
    return keywords[:8]


def normalize_dimension_weights(weights: dict[str, float] | None) -> dict[str, float]:
    if not weights:
        return dict(DEFAULT_DIMENSION_WEIGHTS)
    normalized: dict[str, float] = {}
    for name, default_value in DEFAULT_DIMENSION_WEIGHTS.items():
        try:
            value = float(weights.get(name, default_value))
        except (TypeError, ValueError):
            value = float(default_value)
        normalized[name] = max(value, 0.0)
    total = sum(normalized.values())
    if total <= 0:
        return dict(DEFAULT_DIMENSION_WEIGHTS)
    if round(total, 1) == 100.0:
        return {name: round(value, 1) for name, value in normalized.items()}
    return {name: round(value * 100.0 / total, 1) for name, value in normalized.items()}


def score_education(education: str) -> float:
    score = 6.0
    for degree, base_score in DEGREE_BASE_SCORES.items():
        if degree in education:
            score = max(score, base_score)
    if any(keyword in education for keyword in ["985", "211", "双一流", "省重点"]):
        score += 1.0
    return min(score, DEFAULT_DIMENSION_WEIGHTS["教育背景"])


def score_experience(years: str) -> float:
    match = re.search(r"(\d+)", years)
    year_count = int(match.group(1)) if match else 0
    for threshold, score in EXPERIENCE_SCORE_BANDS:
        if year_count >= threshold:
            return min(score, DEFAULT_DIMENSION_WEIGHTS["工作经验"])
    return 6.0


def score_skills(skills_text: str, jd_text: str) -> float:
    jd_keywords = extract_keywords(jd_text)
    if not jd_keywords:
        return 20.0
    candidate_text = skills_text.lower()
    matched = sum(1 for keyword in jd_keywords if keyword.lower() in candidate_text)
    ratio = matched / len(jd_keywords)
    score = 10.0 + ratio * 25.0
    return min(round(score, 1), DEFAULT_DIMENSION_WEIGHTS["核心技能"])


def score_role_alignment(target_role: str, candidate_text: str, jd_text: str) -> float:
    score = 6.0
    target_role_lower = target_role.lower()
    candidate_text_lower = candidate_text.lower()
    if target_role_lower and target_role_lower in candidate_text_lower:
        score += 6.0
    keyword_hits = sum(
        1 for keyword in ROLE_ALIGNMENT_KEYWORDS if keyword.lower() in jd_text.lower() and keyword.lower() in candidate_text_lower
    )
    score += min(keyword_hits * 1.5, 3.0)
    return min(round(score, 1), DEFAULT_DIMENSION_WEIGHTS["岗位匹配"])


def score_communication(candidate_text: str, jd_text: str) -> float:
    candidate_text_lower = candidate_text.lower()
    jd_text_lower = jd_text.lower()
    needed = [keyword for keyword in COMMUNICATION_KEYWORDS if keyword.lower() in jd_text_lower]
    if not needed:
        return 10.0
    hits = sum(1 for keyword in needed if keyword.lower() in candidate_text_lower)
    ratio = hits / len(needed)
    score = 6.0 + ratio * 9.0
    return min(round(score, 1), DEFAULT_DIMENSION_WEIGHTS["沟通协作"])


def build_scorecard(
    candidate: dict[str, object],
    jd_text: str,
    raw_score: object = None,
    weights: dict[str, float] | None = None,
) -> dict[str, object]:
    dimension_weights = normalize_dimension_weights(weights)
    candidate_text = " ".join(
        str(candidate.get(field) or "")
        for field in ["education", "years_experience", "skills", "target_role", "summary"]
    )
    base_dimensions = {
        "教育背景": score_education(str(candidate.get("education") or "")),
        "工作经验": score_experience(str(candidate.get("years_experience") or "")),
        "核心技能": score_skills(str(candidate.get("skills") or ""), jd_text),
        "岗位匹配": score_role_alignment(str(candidate.get("target_role") or ""), candidate_text, jd_text),
        "沟通协作": score_communication(candidate_text, jd_text),
    }
    weighted_dimensions = {
        name: round(
            (base_dimensions.get(name, 0.0) / DEFAULT_DIMENSION_WEIGHTS[name]) * dimension_weights[name],
            1,
        )
        for name in DEFAULT_DIMENSION_WEIGHTS
    }
    final_score = round(sum(weighted_dimensions.values()), 1)
    dimensions = [
        {
            "name": name,
            "score": weighted_dimensions[name],
            "max_score": dimension_weights[name],
        }
        for name in DEFAULT_DIMENSION_WEIGHTS
    ]
    return {
        "total_score": round(sum(weighted_dimensions.values()), 1),
        "max_total_score": round(sum(dimension_weights.values()), 1),
        "final_match_score": final_score,
        "dimensions": dimensions,
    }


def build_candidate_scorecard(row: dict[str, object], jobs_by_position: dict[str, dict[str, object]]) -> dict[str, object]:
    job_info = jobs_by_position.get(str(row.get("position_id") or ""), {})
    candidate = {
        "education": row.get("education", ""),
        "years_experience": row.get("years_experience", ""),
        "skills": row.get("skills", ""),
        "target_role": row.get("target_role", ""),
        "summary": row.get("summary", ""),
    }
    return build_scorecard(
        candidate,
        str(job_info.get("jd_text") or ""),
        raw_score=row.get("score"),
        weights=get_job_dimension_weights(job_info),
    )


def format_dimension_score(scorecard: dict[str, object], dimension_name: str) -> str:
    for item in scorecard.get("dimensions", []):
        if item.get("name") == dimension_name:
            return f"{float(item.get('score', 0)):.1f}/{float(item.get('max_score', 0)):.0f}"
    return "-"


def build_candidate_display_df(df: pd.DataFrame, jobs_by_position: dict[str, dict[str, object]]) -> pd.DataFrame:
    display_df = df.copy()
    scorecards = [build_candidate_scorecard(row, jobs_by_position) for row in display_df.to_dict(orient="records")]
    display_df["score"] = [
        f"{float(card.get('total_score', 0)):.1f}/{float(card.get('max_total_score', 100)):.0f}"
        for card in scorecards
    ]
    display_df["dimension_education"] = [format_dimension_score(card, "教育背景") for card in scorecards]
    display_df["dimension_experience"] = [format_dimension_score(card, "工作经验") for card in scorecards]
    display_df["dimension_skills"] = [format_dimension_score(card, "核心技能") for card in scorecards]
    display_df["dimension_role"] = [format_dimension_score(card, "岗位匹配") for card in scorecards]
    display_df["dimension_communication"] = [format_dimension_score(card, "沟通协作") for card in scorecards]
    if "recommendation" in display_df.columns:
        display_df["recommendation"] = display_df["recommendation"].map(normalize_recommendation)
    if "agent_status" in display_df.columns:
        display_df["agent_status"] = display_df.apply(
            lambda row: STATUS_TAG_MAP.get(derive_agent_status(row.to_dict()), derive_agent_status(row.to_dict())),
            axis=1,
        )
    if "status" in display_df.columns:
        display_df["status"] = display_df["status"].map(lambda x: STATUS_TAG_MAP.get(str(x), str(x)))
    for column in ["synced_to_tencent_docs", "pushed_to_wecom"]:
        if column in display_df.columns:
            display_df[column] = display_df[column].map(format_bool_cn)
    return display_df.rename(columns=EXPORT_COLUMN_LABELS)


def build_job_display_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=JOB_COLUMN_LABELS)


def build_route_display_df(df: pd.DataFrame) -> pd.DataFrame:
    display_df = df.copy()
    if "enabled" in display_df.columns:
        display_df["enabled"] = display_df["enabled"].map(format_bool_cn)
    return display_df.rename(columns=ROUTE_COLUMN_LABELS)


def build_candidate_option(row: dict[str, object]) -> str:
    return f"{row.get('name') or '未知'} | {row.get('phone') or '无电话'} | {row.get('file_name') or '无文件名'}"


def derive_agent_status(row: dict[str, object]) -> str:
    current = str(row.get("agent_status") or "").strip()
    if current in AGENT_STATUS_OPTIONS:
        return current
    if str(row.get("recommendation") or "").strip() or str(row.get("score") or "").strip() not in {"", "0", "0.0"}:
        return "已评估"
    parsed_fields = [
        row.get("name"),
        row.get("phone"),
        row.get("email"),
        row.get("education"),
        row.get("years_experience"),
        row.get("skills"),
        row.get("summary"),
    ]
    if any(str(value or "").strip() for value in parsed_fields):
        return "已解析"
    return "待解析"


def save_candidate_status(
    selected_candidate: dict[str, object],
    candidate_status: str,
    interview_time: str,
    interviewer: str,
    offer_salary: str = "",
    offer_join_date: str = "",
    offer_deadline: str = "",
) -> bool:
    updated = repo.update_statuses(
        file_name=str(selected_candidate.get("file_name") or ""),
        phone=str(selected_candidate.get("phone") or ""),
        candidate_status=candidate_status,
        interview_time=interview_time.strip(),
        interviewer=interviewer.strip(),
        offer_salary=offer_salary.strip(),
        offer_join_date=offer_join_date.strip(),
        offer_deadline=offer_deadline.strip(),
    )
    if updated:
        candidate_key = build_candidate_identity(selected_candidate)
        if "candidate_status_overrides" not in st.session_state:
            st.session_state.candidate_status_overrides = {}
        st.session_state.candidate_status_overrides[candidate_key] = {
            "status": candidate_status,
            "recommendation": derive_recommendation_from_status(candidate_status) or str(selected_candidate.get("recommendation") or ""),
            "interview_time": interview_time.strip(),
            "interviewer": interviewer.strip(),
            "offer_salary": offer_salary.strip(),
            "offer_join_date": offer_join_date.strip(),
            "offer_deadline": offer_deadline.strip(),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    return updated


def build_candidate_identity(row: dict[str, object]) -> str:
    return f"{row.get('file_name') or ''}::{row.get('phone') or ''}"


def derive_recommendation_from_status(candidate_status: str) -> str:
    mapping = {
        "一面": "一面",
        "二面": "二面",
        "终面": "终面",
        "已淘汰": "不推荐",
        "已录用": "已录用",
    }
    return mapping.get(candidate_status, "")


def derive_recommendation_from_score(score: object) -> str:
    normalized_score = normalize_score_100(score)
    if normalized_score >= 80:
        return "推荐"
    if normalized_score >= 65:
        return "待定"
    return "不推荐"


def build_record_from_row(
    row: dict[str, object],
    *,
    score: float | None = None,
    recommendation: str | None = None,
    target_role: str | None = None,
) -> CandidateRecord:
    return CandidateRecord(
        position_id=str(row.get("position_id") or ""),
        source=str(row.get("source") or ""),
        file_name=str(row.get("file_name") or ""),
        name=str(row.get("name") or ""),
        phone=str(row.get("phone") or ""),
        email=str(row.get("email") or ""),
        education=str(row.get("education") or ""),
        years_experience=str(row.get("years_experience") or ""),
        skills=str(row.get("skills") or ""),
        target_role=target_role if target_role is not None else str(row.get("target_role") or ""),
        score=float(score if score is not None else row.get("score") or 0),
        recommendation=recommendation if recommendation is not None else str(row.get("recommendation") or "待定"),
        summary=str(row.get("summary") or ""),
        agent_status=str(row.get("agent_status") or "待解析"),
        status=str(row.get("status") or "待沟通"),
        interview_time=str(row.get("interview_time") or ""),
        interviewer=str(row.get("interviewer") or ""),
        offer_salary=str(row.get("offer_salary") or ""),
        offer_join_date=str(row.get("offer_join_date") or ""),
        offer_deadline=str(row.get("offer_deadline") or ""),
        synced_to_tencent_docs=parse_bool(row.get("synced_to_tencent_docs")),
        pushed_to_wecom=parse_bool(row.get("pushed_to_wecom")),
        updated_at=str(row.get("updated_at") or ""),
    )


def recalculate_candidates_for_job(job_info: dict[str, object]) -> int:
    position_id = str(job_info.get("position_id") or "")
    jd_text = str(job_info.get("jd_text") or "")
    target_role = str(job_info.get("target_role") or "")
    weights = get_job_dimension_weights(job_info)
    candidates_df = repo.list_all()
    if candidates_df.empty:
        return 0

    job_candidates_df = candidates_df[candidates_df["position_id"].astype(str) == position_id].copy()
    if job_candidates_df.empty:
        return 0

    overrides = st.session_state.get("candidate_status_overrides", {}).copy()
    updated_count = 0
    status_locked_recommendations = {"一面", "二面", "终面", "已录用"}
    for row in job_candidates_df.to_dict(orient="records"):
        scorecard = build_scorecard(
            {
                "education": row.get("education", ""),
                "years_experience": row.get("years_experience", ""),
                "skills": row.get("skills", ""),
                "target_role": target_role or row.get("target_role", ""),
                "summary": row.get("summary", ""),
            },
            jd_text,
            raw_score=row.get("score"),
            weights=weights,
        )
        new_score = float(scorecard["final_match_score"])
        current_status = str(row.get("status") or "")
        if current_status in status_locked_recommendations:
            new_recommendation = current_status
        elif current_status == "已淘汰":
            new_recommendation = "不推荐"
        else:
            new_recommendation = derive_recommendation_from_score(new_score)

        repo.upsert(
            build_record_from_row(
                row,
                score=new_score,
                recommendation=new_recommendation,
                target_role=target_role or str(row.get("target_role") or ""),
            )
        )
        overrides.pop(build_candidate_identity(row), None)
        updated_count += 1

    st.session_state.candidate_status_overrides = overrides
    return updated_count


def apply_candidate_status_overrides(df: pd.DataFrame) -> pd.DataFrame:
    overrides = st.session_state.get("candidate_status_overrides", {})
    if df.empty or not overrides:
        return df
    updated_df = df.copy()
    for index, row in updated_df.iterrows():
        candidate_key = build_candidate_identity(row.to_dict())
        override = overrides.get(candidate_key)
        if not override:
            continue
        updated_df.at[index, "status"] = override.get("status", row.get("status", ""))
        updated_df.at[index, "recommendation"] = override.get("recommendation", row.get("recommendation", ""))
        updated_df.at[index, "interview_time"] = override.get("interview_time", row.get("interview_time", ""))
        updated_df.at[index, "interviewer"] = override.get("interviewer", row.get("interviewer", ""))
        updated_df.at[index, "offer_salary"] = override.get("offer_salary", row.get("offer_salary", ""))
        updated_df.at[index, "offer_join_date"] = override.get("offer_join_date", row.get("offer_join_date", ""))
        updated_df.at[index, "offer_deadline"] = override.get("offer_deadline", row.get("offer_deadline", ""))
        updated_df.at[index, "updated_at"] = override.get("updated_at", row.get("updated_at", ""))
    return updated_df


def resolve_resume_path(candidate: dict[str, object]) -> Path | None:
    file_name = str(candidate.get("file_name") or "").strip()
    if not file_name:
        return None
    for directory in (settings.incoming_dir, get_processed_dir()):
        candidate_path = directory / file_name
        if candidate_path.exists():
            return candidate_path
    return None


@st.cache_data(show_spinner=False)
def load_resume_text(file_path_str: str) -> str:
    file_path = Path(file_path_str)
    if not file_path.exists() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return ""
    return extract_text(file_path)


@st.cache_data(show_spinner=False)
def load_pdf_preview_images(file_path_str: str) -> list[bytes]:
    file_path = Path(file_path_str)
    if not file_path.exists() or file_path.suffix.lower() != ".pdf":
        return []

    image_bytes_list: list[bytes] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_image = page.to_image(resolution=144).original
            buffer = io.BytesIO()
            page_image.save(buffer, format="PNG")
            image_bytes_list.append(buffer.getvalue())
    return image_bytes_list


def render_resume_preview(resume_path: Path | None) -> None:
    if not resume_path or not resume_path.exists():
        st.info("未找到该候选人的简历文件。")
        return

    st.caption(f"简历文件：{resume_path.name}")
    if resume_path.suffix.lower() == ".pdf":
        preview_images = load_pdf_preview_images(str(resume_path))
        if preview_images:
            st.caption("PDF 在线预览")
            for page_index, image_bytes in enumerate(preview_images, start=1):
                st.image(image_bytes, caption=f"第 {page_index} 页", use_container_width=True)
            return
        st.warning("PDF 原样预览加载失败，已切换为文本预览。")

    resume_text = load_resume_text(str(resume_path))
    if resume_text.strip():
        if resume_path.suffix.lower() in {".docx", ".txt"}:
            st.caption("Word/TXT 文本预览")
        st.text_area("简历内容预览", value=resume_text, height=720, disabled=True)
    else:
        st.info("该简历暂不支持在线预览内容。")


def parse_datetime_value(value: object) -> tuple[date, time]:
    text = str(value or "").strip()
    if not text:
        return date.today(), time(9, 0)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date(), parsed.time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    return date.today(), time(9, 0)


st.title("招聘工作台")
st.caption("面向 HR 的岗位配置、简历处理与候选人跟进工作台")

jobs_df = job_repo.list_all()
job_options = {
    f"{row.position_id} | {row.target_role}": row._asdict()
    for row in jobs_df.itertuples(index=False)
}
jobs_by_position = {
    str(row.position_id): row._asdict()
    for row in jobs_df.itertuples(index=False)
}
selected_job_label = st.selectbox("当前岗位", options=list(job_options.keys()), index=0)
selected_job = job_options[selected_job_label]

df = repo.list_all()
df = apply_candidate_status_overrides(df)
board_df = df[df["position_id"].astype(str) == str(selected_job["position_id"])].copy() if not df.empty else df.copy()
board_recommendations = (
    board_df["recommendation"].map(normalize_recommendation) if not board_df.empty else pd.Series(dtype=str)
)
board_stats = {
    "total": int(len(board_df)),
    "recommended": int(board_recommendations.isin(POSITIVE_RECOMMENDATIONS).sum()) if not board_df.empty else 0,
    "synced": int(board_df["synced_to_tencent_docs"].astype(str).str.lower().isin(["true", "1", "yes", "y"]).sum())
    if not board_df.empty
    else 0,
}

hero_col1, hero_col2, hero_col3, hero_col4 = st.columns([1.4, 1, 1, 1])
hero_col1.markdown(
    f"### {selected_job['target_role']}\n"
    f"岗位 ID：`{selected_job['position_id']}`"
)
hero_col2.metric("候选人数", board_stats["total"])
hero_col3.metric("推荐人数", board_stats["recommended"])
hero_col4.metric("已同步腾讯文档", board_stats["synced"])

tab_process, tab_config, tab_board = st.tabs(["简历处理", "岗位配置", "候选人看板"])

with tab_config:
    st.subheader("岗位配置")
    config_col1, config_col2 = st.columns([1.5, 1])
    with config_col1:
        position_id = st.text_input("岗位ID", value=selected_job["position_id"], key="config_position_id")
        target_role = st.text_input("岗位名称", value=selected_job["target_role"], key="config_target_role")
        jd_text = st.text_area("JD 文本", value=selected_job["jd_text"], height=240, key="config_jd_text")
    with config_col2:
        st.markdown("#### 能力权重")
        default_job_weights = get_job_dimension_weights(selected_job)
        weight_education = st.slider(
            "教育背景",
            min_value=0,
            max_value=100,
            value=int(default_job_weights["教育背景"]),
            key="weight_education",
        )
        weight_experience = st.slider(
            "工作经验",
            min_value=0,
            max_value=100,
            value=int(default_job_weights["工作经验"]),
            key="weight_experience",
        )
        weight_skills = st.slider(
            "核心技能",
            min_value=0,
            max_value=100,
            value=int(default_job_weights["核心技能"]),
            key="weight_skills",
        )
        weight_role = st.slider(
            "岗位匹配",
            min_value=0,
            max_value=100,
            value=int(default_job_weights["岗位匹配"]),
            key="weight_role",
        )
        weight_communication = st.slider(
            "沟通协作",
            min_value=0,
            max_value=100,
            value=int(default_job_weights["沟通协作"]),
            key="weight_communication",
        )

    selected_job_weights = {
        "教育背景": float(weight_education),
        "工作经验": float(weight_experience),
        "核心技能": float(weight_skills),
        "岗位匹配": float(weight_role),
        "沟通协作": float(weight_communication),
    }
    weight_total = sum(selected_job_weights.values())
    normalized_job_weights = normalize_dimension_weights(selected_job_weights)
    if weight_total <= 0:
        st.warning("当前能力权重合计为 0，请至少为一个维度设置大于 0 的权重。")
    elif round(weight_total, 1) != 100.0:
        st.info(
            "当前能力权重合计为 "
            f"{weight_total:.1f}，保存时会自动归一化为 100："
            f" 教育背景 {normalized_job_weights['教育背景']:.1f}，"
            f"工作经验 {normalized_job_weights['工作经验']:.1f}，"
            f"核心技能 {normalized_job_weights['核心技能']:.1f}，"
            f"岗位匹配 {normalized_job_weights['岗位匹配']:.1f}，"
            f"沟通协作 {normalized_job_weights['沟通协作']:.1f}"
        )
    else:
        st.success("当前能力权重合计：100")

    save_job_col1, save_job_col2, save_job_col3 = st.columns([1, 1, 1.2])
    with save_job_col1:
        if st.button("保存岗位配置", use_container_width=True, key="save_job_config"):
            if not position_id.strip() or not target_role.strip() or not jd_text.strip():
                st.error("岗位ID、岗位名称和 JD 不能为空。")
            elif weight_total <= 0:
                st.error("能力权重总和必须大于 0。")
            else:
                job_repo.upsert(
                    position_id.strip(),
                    target_role.strip(),
                    jd_text.strip(),
                    weight_education=normalized_job_weights["教育背景"],
                    weight_experience=normalized_job_weights["工作经验"],
                    weight_skills=normalized_job_weights["核心技能"],
                    weight_role=normalized_job_weights["岗位匹配"],
                    weight_communication=normalized_job_weights["沟通协作"],
                )
                st.success("岗位配置已保存，系统已自动归一化为 100 分。")
    with save_job_col2:
        if st.button("按当前岗位权重重算候选人分数", use_container_width=True, key="recalculate_job_scores"):
            if not position_id.strip() or not target_role.strip() or not jd_text.strip():
                st.error("请先完善岗位ID、岗位名称和 JD。")
            elif weight_total <= 0:
                st.error("能力权重总和必须大于 0。")
            else:
                current_job = {
                    "position_id": position_id.strip(),
                    "target_role": target_role.strip(),
                    "jd_text": jd_text.strip(),
                    "weight_education": normalized_job_weights["教育背景"],
                    "weight_experience": normalized_job_weights["工作经验"],
                    "weight_skills": normalized_job_weights["核心技能"],
                    "weight_role": normalized_job_weights["岗位匹配"],
                    "weight_communication": normalized_job_weights["沟通协作"],
                }
                job_repo.upsert(
                    current_job["position_id"],
                    current_job["target_role"],
                    current_job["jd_text"],
                    weight_education=current_job["weight_education"],
                    weight_experience=current_job["weight_experience"],
                    weight_skills=current_job["weight_skills"],
                    weight_role=current_job["weight_role"],
                    weight_communication=current_job["weight_communication"],
                )
                recalculated_count = recalculate_candidates_for_job(current_job)
                st.success(f"已按当前岗位权重重算 {recalculated_count} 位候选人的分数。")
                st.rerun()
    with save_job_col3:
        with st.expander("查看配置说明", expanded=False):
            st.markdown(
                """
                - 简历目录：`app/incoming`
                - 数据文件：`app/data/candidates.csv`
                - 岗位库：`app/data/positions.csv`
                - 外部接口：通过 `.env` 配置
                """
            )

    st.divider()
    st.subheader("企业微信群路由")
    route_col1, route_col2, route_col3 = st.columns([1, 1.4, 0.8])
    route_col1.text_input("群名称", value=f"{target_role}-招聘群", key="route_group_name")
    route_col2.text_input("Webhook URL", value="", key="route_webhook")
    route_col3.checkbox("启用该路由", value=True, key="route_enabled")
    if st.button("保存群路由", use_container_width=True, key="save_route"):
        route_group_name = str(st.session_state.get("route_group_name") or "")
        route_webhook = str(st.session_state.get("route_webhook") or "")
        route_enabled = bool(st.session_state.get("route_enabled"))
        if not position_id.strip() or not route_group_name.strip() or not route_webhook.strip():
            st.error("岗位ID、群名称和 Webhook URL 不能为空。")
        else:
            route_repo.upsert(
                position_id=position_id.strip(),
                group_name=route_group_name.strip(),
                webhook_url=route_webhook.strip(),
                enabled=route_enabled,
            )
            st.success("企业微信群路由已保存。")

    with st.expander("查看岗位库与路由表", expanded=False):
        st.markdown("#### 岗位库")
        st.dataframe(build_job_display_df(job_repo.list_all()), use_container_width=True)
        st.markdown("#### 群路由表")
        st.dataframe(build_route_display_df(route_repo.list_all()), use_container_width=True)

with tab_process:
    st.subheader("简历处理")
    process_col1, process_col2 = st.columns([1.4, 1])
    with process_col1:
        uploader_key = f"resume_uploader_{st.session_state.get('resume_uploader_version', 0)}"
        uploaded_files = st.file_uploader(
            "上传简历文件",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            key=uploader_key,
        )
        auto_saved = auto_save_uploaded_files(uploaded_files or [])
        if auto_saved:
            st.success(f"已自动保存 {len(auto_saved)} 份简历到 incoming 目录。")

        local_files = collector.collect_local_files()
        st.caption(f"待处理文件数：{len(local_files)}")
        if local_files:
            st.dataframe(
                pd.DataFrame({"文件名": [path.name for path in local_files]}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("当前没有待处理简历。")

        clear_resume_col1, clear_resume_col2 = st.columns(2)
        with clear_resume_col1:
            if st.button("清空已上传简历", use_container_width=True, key="clear_uploaded_resumes"):
                removed_incoming, removed_processed = clear_uploaded_resume_files()
                st.success(f"已清空简历文件：incoming {removed_incoming} 份，processed {removed_processed} 份。")
                st.rerun()
        with clear_resume_col2:
            if st.button("清空候选人数据", use_container_width=True, key="clear_candidate_data"):
                removed_records = clear_candidate_data()
                st.success(f"已清空候选人数据，共删除 {removed_records} 条记录。")
                st.rerun()
        st.caption("清空已上传简历会删除 incoming 和 processed 目录中的文件；清空候选人数据会重置 candidates.csv。")

    with process_col2:
        st.markdown("#### 当前处理岗位")
        st.write(f"岗位：{target_role}")
        st.write(f"岗位 ID：{position_id}")
        st.write("能力权重合计：100（系统自动归一化）")

        st.markdown("#### 邮箱导入筛选")
        default_end_date = date.today()
        default_start_date = default_end_date - timedelta(days=7)
        mail_date_col1, mail_date_col2 = st.columns(2)
        with mail_date_col1:
            mail_start_date = st.date_input("开始日期", value=default_start_date, key="mail_start_date")
        with mail_date_col2:
            mail_end_date = st.date_input("结束日期", value=default_end_date, key="mail_end_date")
        mail_sender = st.text_input(
            "发件人关键词",
            value="",
            placeholder="例如：boss、zhipin、hr@company.com",
            key="mail_sender_keyword",
        )
        mail_subject = st.text_input(
            "主题关键词",
            value="",
            placeholder="例如：简历、候选人、AI招聘助理",
            key="mail_subject_keyword",
        )
        mail_unread_only = st.checkbox("仅拉取未读邮件", value=False, key="mail_unread_only")

        if st.button("按筛选条件导入邮箱附件", use_container_width=True, key="pull_from_mail"):
            if mail_start_date > mail_end_date:
                st.error("开始日期不能晚于结束日期。")
            else:
                files = collector.collect_from_imap(
                    start_date=mail_start_date,
                    end_date=mail_end_date,
                    sender_keyword=mail_sender,
                    subject_keyword=mail_subject,
                    unread_only=mail_unread_only,
                )
                st.success(f"已从邮箱导入 {len(files)} 份简历。")

        if st.button("批量处理并同步", type="primary", use_container_width=True, key="process_all_resumes"):
            if not jd_text.strip():
                st.error("请先填写 JD。")
            else:
                processed: list[CandidateRecord] = []
                progress = st.progress(0)
                for idx, file_path in enumerate(local_files, start=1):
                    record = process_resume(
                        file_path,
                        source="本地/邮件/导出文件",
                        position_id=position_id.strip(),
                        jd_text=jd_text,
                        target_role=target_role,
                        weights=normalized_job_weights,
                    )
                    archived_path = archive_processed_resume(settings.incoming_dir / record.file_name)
                    record.file_name = archived_path.name
                    processed.append(sync_record(record))
                    progress.progress(idx / max(len(local_files), 1))
                st.success(f"已处理并同步 {len(processed)} 份简历。")

with tab_board:
    st.subheader("候选人看板")
    if board_df.empty:
        st.info("当前岗位还没有候选人数据，先去“简历处理”上传或采集简历。")
    else:
        board_filter_col1, board_filter_col2, board_filter_col3 = st.columns([1, 1, 1.3])
        recommendation_filter = board_filter_col1.selectbox(
            "推荐结论",
            options=BOARD_RECOMMENDATION_OPTIONS,
            key="board_recommendation_filter",
        )
        status_filter = board_filter_col2.selectbox(
            "候选人状态",
            options=["全部"] + CANDIDATE_STATUS_OPTIONS,
            key="board_status_filter",
        )
        keyword = board_filter_col3.text_input(
            "搜索姓名 / 电话 / 文件名",
            value="",
            key="board_keyword_filter",
        ).strip()

        filtered_board_df = board_df.copy()
        if recommendation_filter != "全部":
            filtered_board_df = filtered_board_df[
                filtered_board_df["recommendation"].map(normalize_recommendation) == recommendation_filter
            ]
        if status_filter != "全部":
            filtered_board_df = filtered_board_df[filtered_board_df["status"].astype(str) == status_filter]
        if keyword:
            keyword_lower = keyword.lower()
            keyword_mask = (
                filtered_board_df["name"].astype(str).str.lower().str.contains(keyword_lower, na=False)
                | filtered_board_df["phone"].astype(str).str.lower().str.contains(keyword_lower, na=False)
                | filtered_board_df["file_name"].astype(str).str.lower().str.contains(keyword_lower, na=False)
            )
            filtered_board_df = filtered_board_df[keyword_mask]

        st.markdown("#### 候选人列表")
        if filtered_board_df.empty:
            st.info("当前筛选条件下没有候选人。")
        else:
            board_display_df = build_candidate_display_df(
                filtered_board_df.sort_values(by="updated_at", ascending=False),
                jobs_by_position,
            )
            board_display_columns = [
                "姓名",
                "岗位名称",
                "匹配评分",
                "推荐结论",
                "候选人状态",
                "更新时间",
            ]
            st.dataframe(
                board_display_df[board_display_columns],
                use_container_width=True,
                hide_index=True,
            )

            list_action_col1, list_action_col2 = st.columns([1, 1.2])
            with list_action_col1:
                export_df = filtered_board_df.sort_values(by="updated_at", ascending=False)
                csv_bytes = export_candidates_csv(export_df)
                st.download_button(
                    "导出当前列表 CSV",
                    csv_bytes,
                    file_name=f"{selected_job['position_id']}_candidates.csv",
                    use_container_width=True,
                )
            with list_action_col2:
                with st.expander("查看推荐结论分布", expanded=False):
                    chart_df = (
                        filtered_board_df["recommendation"]
                        .map(normalize_recommendation)
                        .value_counts()
                        .rename_axis("推荐结论")
                        .reset_index(name="数量")
                    )
                    st.bar_chart(chart_df.set_index("推荐结论"))

            st.divider()
            st.markdown("#### 候选人详情")
            candidate_rows = filtered_board_df.sort_values(by="updated_at", ascending=False).to_dict(orient="records")
            candidate_options = {build_candidate_option(row): row for row in candidate_rows}
            selected_candidate_label = st.selectbox(
                "选择候选人",
                options=list(candidate_options.keys()),
                key="candidate_detail_select",
            )
            selected_candidate = candidate_options[selected_candidate_label]
            selected_candidate_key = build_candidate_identity(selected_candidate)
            selected_resume_path = resolve_resume_path(selected_candidate)
            agent_status_value = derive_agent_status(selected_candidate)
            selected_scorecard = build_candidate_scorecard(selected_candidate, jobs_by_position)

            detail_top_left, detail_top_right = st.columns([1.1, 0.9])
            with detail_top_left:
                st.markdown("##### 基本信息")
                base_info_col1, base_info_col2 = st.columns(2)
                base_info_col1.write(f"姓名：{selected_candidate.get('name') or '未知'}")
                base_info_col1.write(f"电话：{selected_candidate.get('phone') or '-'}")
                base_info_col1.write(f"邮箱：{selected_candidate.get('email') or '-'}")
                base_info_col2.write(f"学历：{selected_candidate.get('education') or '-'}")
                base_info_col2.write(f"年限：{selected_candidate.get('years_experience') or '-'}")
                base_info_col2.write(f"文件：{selected_candidate.get('file_name') or '-'}")

                with st.expander("查看摘要", expanded=True):
                    st.write(str(selected_candidate.get("summary") or "暂无摘要"))

            with detail_top_right:
                st.markdown("##### 评分信息")
                detail_metric_col1, detail_metric_col2 = st.columns(2)
                detail_metric_col1.metric(
                    "匹配评分",
                    f"{float(selected_scorecard.get('total_score', 0)):.1f}/{float(selected_scorecard.get('max_total_score', 100)):.0f}",
                )
                detail_metric_col2.metric(
                    "推荐结论",
                    normalize_recommendation(selected_candidate.get("recommendation")),
                )
                dimension_df = pd.DataFrame(
                    [
                        {
                            "能力维度": item.get("name"),
                            "得分": f"{float(item.get('score', 0)):.1f}",
                            "维度满分": f"{float(item.get('max_score', 0)):.0f}",
                        }
                        for item in selected_scorecard.get("dimensions", [])
                    ]
                )
                st.dataframe(dimension_df, use_container_width=True, hide_index=True)

            detail_tab1, detail_tab2 = st.tabs(["候选人信息", "简历在线查看"])
            with detail_tab1:
                candidate_detail_df = pd.DataFrame(
                    [
                        {
                            "字段": "姓名",
                            "内容": selected_candidate.get("name") or "-",
                        },
                        {"字段": "电话", "内容": selected_candidate.get("phone") or "-"},
                        {"字段": "邮箱", "内容": selected_candidate.get("email") or "-"},
                        {"字段": "学历", "内容": selected_candidate.get("education") or "-"},
                        {"字段": "工作年限", "内容": selected_candidate.get("years_experience") or "-"},
                        {"字段": "技能", "内容": selected_candidate.get("skills") or "-"},
                        {"字段": "岗位名称", "内容": selected_candidate.get("target_role") or "-"},
                        {
                            "字段": "匹配评分",
                            "内容": f"{float(selected_scorecard.get('total_score', 0)):.1f}/{float(selected_scorecard.get('max_total_score', 100)):.0f}",
                        },
                        {"字段": "推荐结论", "内容": normalize_recommendation(selected_candidate.get("recommendation"))},
                        {"字段": "候选人状态", "内容": selected_candidate.get("status") or "-"},
                        {"字段": "面试时间", "内容": selected_candidate.get("interview_time") or "-"},
                        {"字段": "面试官", "内容": selected_candidate.get("interviewer") or "-"},
                        {"字段": "更新时间", "内容": selected_candidate.get("updated_at") or "-"},
                        {"字段": "摘要", "内容": selected_candidate.get("summary") or "暂无摘要"},
                    ]
                )
                st.dataframe(candidate_detail_df, use_container_width=True, hide_index=True)

            with detail_tab2:
                if selected_resume_path and selected_resume_path.exists():
                    st.download_button(
                        "下载原始简历",
                        data=selected_resume_path.read_bytes(),
                        file_name=selected_resume_path.name,
                        use_container_width=True,
                    )
                render_resume_preview(selected_resume_path)

            st.markdown("#### 状态推进")
            process_left, process_right = st.columns([1, 1])
            with process_left:
                action_col1, action_col2 = st.columns(2)
                with action_col1:
                    st.text_input("Agent状态（系统自动）", value=agent_status_value, disabled=True, key="agent_status_view")
                with action_col2:
                    candidate_status_value = st.selectbox(
                        "候选人状态",
                        options=CANDIDATE_STATUS_OPTIONS,
                        index=CANDIDATE_STATUS_OPTIONS.index(selected_candidate.get("status"))
                        if selected_candidate.get("status") in CANDIDATE_STATUS_OPTIONS
                        else 0,
                        key=f"candidate_status_select_{selected_candidate_key}",
                    )

                default_interview_date, default_interview_clock = parse_datetime_value(selected_candidate.get("interview_time"))
                interview_col1, interview_col2 = st.columns(2)
                with interview_col1:
                    interview_date_value = st.date_input(
                        "面试日期",
                        value=default_interview_date,
                        key=f"interview_date_{selected_candidate_key}",
                    )
                with interview_col2:
                    interview_clock_value = st.time_input(
                        "面试时间",
                        value=default_interview_clock,
                        step=1800,
                        key=f"interview_clock_{selected_candidate_key}",
                    )
                interview_time_value = datetime.combine(interview_date_value, interview_clock_value).strftime("%Y-%m-%d %H:%M")

                interviewer_col1, interviewer_col2 = st.columns(2)
                interviewer_current = str(selected_candidate.get("interviewer") or "")
                interviewer_select_default = interviewer_current if interviewer_current in INTERVIEWER_OPTIONS[:-1] else "自定义"
                with interviewer_col1:
                    interviewer_select = st.selectbox(
                        "面试官",
                        options=INTERVIEWER_OPTIONS,
                        index=INTERVIEWER_OPTIONS.index(interviewer_select_default),
                        key=f"interviewer_select_{selected_candidate_key}",
                    )
                with interviewer_col2:
                    interviewer_custom = st.text_input(
                        "自定义面试官",
                        value="" if interviewer_select != "自定义" else interviewer_current,
                        placeholder="例如：张经理 / 李总监",
                        disabled=interviewer_select != "自定义",
                        key=f"interviewer_custom_{selected_candidate_key}",
                    )
                interviewer_value = interviewer_custom.strip() if interviewer_select == "自定义" else interviewer_select

            with process_right:
                offer_salary_value = str(selected_candidate.get("offer_salary") or "")
                offer_join_date_value = str(selected_candidate.get("offer_join_date") or "")
                offer_deadline_value = str(selected_candidate.get("offer_deadline") or "")
                if candidate_status_value == "已录用":
                    offer_col1, offer_col2, offer_col3 = st.columns(3)
                    with offer_col1:
                        offer_salary_value = st.text_input(
                            "Offer薪资",
                            value=offer_salary_value,
                            placeholder="例如：18K*14",
                            key=f"offer_salary_{selected_candidate_key}",
                        )
                    with offer_col2:
                        offer_join_date_value = st.text_input(
                            "预计入职",
                            value=offer_join_date_value,
                            placeholder="例如：2026-07-01",
                            key=f"offer_join_date_{selected_candidate_key}",
                        )
                    with offer_col3:
                        offer_deadline_value = st.text_input(
                            "Offer截止",
                            value=offer_deadline_value,
                            placeholder="例如：2026-06-15",
                            key=f"offer_deadline_{selected_candidate_key}",
                        )

                mail_to_default = str(selected_candidate.get("email") or "")
                mail_to_value = st.text_input(
                    "候选人通知邮箱",
                    value=mail_to_default,
                    help="默认使用候选人邮箱，支持多个邮箱，多个邮箱用英文逗号分隔。",
                    key=f"mail_to_value_{selected_candidate_key}",
                )

                current_interview_time = str(selected_candidate.get("interview_time") or "").strip()
                current_interviewer = str(selected_candidate.get("interviewer") or "").strip()
                current_offer_salary = str(selected_candidate.get("offer_salary") or "").strip()
                current_offer_join_date = str(selected_candidate.get("offer_join_date") or "").strip()
                current_offer_deadline = str(selected_candidate.get("offer_deadline") or "").strip()
                status_fields_changed = any(
                    [
                        candidate_status_value != str(selected_candidate.get("status") or ""),
                        interview_time_value != current_interview_time,
                        interviewer_value != current_interviewer,
                        offer_salary_value.strip() != current_offer_salary,
                        offer_join_date_value.strip() != current_offer_join_date,
                        offer_deadline_value.strip() != current_offer_deadline,
                    ]
                )

                if status_fields_changed:
                    updated = save_candidate_status(
                        selected_candidate,
                        candidate_status_value,
                        interview_time_value,
                        interviewer_value,
                        offer_salary_value,
                        offer_join_date_value,
                        offer_deadline_value,
                    )
                    if updated:
                        st.success("候选人状态信息已自动保存。")
                        st.rerun()
                    else:
                        st.error("未找到该候选人，状态信息保存失败。")

                st.caption("修改候选人状态、面试时间、面试官或 Offer 信息后会自动保存。")

                if st.button("发送候选人通知邮件", use_container_width=True, key=f"send_status_email_btn_{selected_candidate_key}"):
                        email_record = CandidateRecord(
                            position_id=str(selected_candidate.get("position_id") or ""),
                            source=str(selected_candidate.get("source") or ""),
                            file_name=str(selected_candidate.get("file_name") or ""),
                            name=str(selected_candidate.get("name") or ""),
                            phone=str(selected_candidate.get("phone") or ""),
                            email=str(selected_candidate.get("email") or ""),
                            education=str(selected_candidate.get("education") or ""),
                            years_experience=str(selected_candidate.get("years_experience") or ""),
                            skills=str(selected_candidate.get("skills") or ""),
                            target_role=str(selected_candidate.get("target_role") or ""),
                            score=float(selected_scorecard.get("total_score", 0)),
                            recommendation=str(selected_candidate.get("recommendation") or "待定"),
                            summary=str(selected_candidate.get("summary") or ""),
                            agent_status=agent_status_value,
                            status=candidate_status_value,
                            interview_time=interview_time_value,
                            interviewer=interviewer_value,
                            offer_salary=offer_salary_value,
                            offer_join_date=offer_join_date_value,
                            offer_deadline=offer_deadline_value,
                            synced_to_tencent_docs=str(selected_candidate.get("synced_to_tencent_docs")).lower()
                            in {"true", "1", "yes", "y"},
                            pushed_to_wecom=str(selected_candidate.get("pushed_to_wecom")).lower() in {"true", "1", "yes", "y"},
                            updated_at=str(selected_candidate.get("updated_at") or ""),
                        )
                        recipients = [item.strip() for item in mail_to_value.split(",")] if mail_to_value else []
                        ok, msg = mailer.send_status_email(email_record, recipients)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
