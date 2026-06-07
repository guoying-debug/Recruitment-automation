from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.config import settings

DIMENSION_MAX_SCORES = {
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


class JDScorer:
    def score(
        self,
        candidate: dict[str, Any],
        jd_text: str,
        weights: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if settings.llm_api_key:
            try:
                result = self._score_with_llm(candidate, jd_text)
                return self._enrich_score_result(candidate, jd_text, result, weights=weights)
            except Exception:
                pass
        return self._score_with_rules(candidate, jd_text, weights=weights)

    def build_scorecard(
        self,
        candidate: dict[str, Any],
        jd_text: str,
        raw_score: Any | None = None,
        weights: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dimension_weights = _normalize_dimension_weights(weights)
        base_dimensions = self._build_base_dimension_scores(candidate, jd_text)
        weighted_dimensions = _apply_dimension_weights(base_dimensions, dimension_weights)
        base_total = round(sum(weighted_dimensions.values()), 1)
        normalized_raw = _normalize_score_100(raw_score)
        final_score = base_total if base_total > 0 else normalized_raw
        scaled_dimensions = _scale_dimension_scores(weighted_dimensions, dimension_weights, final_score)
        return {
            "total_score": round(sum(dimension_weights.values()), 1),
            "final_match_score": final_score,
            "dimensions": [
                {
                    "name": name,
                    "score": scaled_dimensions[name],
                    "max_score": dimension_weights[name],
                }
                for name in DIMENSION_MAX_SCORES
            ],
        }

    def _score_with_llm(self, candidate: dict[str, Any], jd_text: str) -> dict[str, Any]:
        prompt = f"""
你是招聘初筛助手。请基于候选人信息和 JD 进行 0-100 分制打分，并严格返回 JSON：
score, recommendation, reason

要求：
1. reason 必须使用简体中文输出
2. reason 控制在 50-90 个汉字，适合直接展示给 HR
3. 不要输出英文总结，不要输出 Markdown

候选人信息：
{json.dumps(candidate, ensure_ascii=False)}

JD：
{jd_text[:8000]}
"""
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": "你只返回 JSON，不要输出 Markdown。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        response = requests.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(_extract_json(content))
        return data

    def _score_with_rules(
        self,
        candidate: dict[str, Any],
        jd_text: str,
        weights: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scorecard = self.build_scorecard(candidate, jd_text, weights=weights)
        score = scorecard["final_match_score"]
        if score >= 80:
            recommendation = "推荐"
        elif score >= 65:
            recommendation = "待定"
        else:
            recommendation = "不推荐"

        return {
            "score": float(score),
            "final_match_score": float(score),
            "total_score": 100.0,
            "dimensions": scorecard["dimensions"],
            "recommendation": recommendation,
            "reason": self._build_rule_reason(candidate, scorecard["dimensions"]),
        }

    def _enrich_score_result(
        self,
        candidate: dict[str, Any],
        jd_text: str,
        result: dict[str, Any],
        weights: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scorecard = self.build_scorecard(candidate, jd_text, raw_score=result.get("score"), weights=weights)
        final_score = scorecard["final_match_score"]
        recommendation = str(result.get("recommendation") or "").strip()
        if not recommendation:
            if final_score >= 80:
                recommendation = "推荐"
            elif final_score >= 65:
                recommendation = "待定"
            else:
                recommendation = "不推荐"
        return {
            "score": final_score,
            "final_match_score": final_score,
            "total_score": 100.0,
            "dimensions": scorecard["dimensions"],
            "recommendation": recommendation,
            "reason": self._normalize_reason_text(
                str(result.get("reason") or ""),
                candidate,
                scorecard["dimensions"],
            ),
        }

    def _build_base_dimension_scores(self, candidate: dict[str, Any], jd_text: str) -> dict[str, float]:
        candidate_text = " ".join(
            str(candidate.get(field) or "")
            for field in ["education", "years_experience", "skills", "target_role", "summary"]
        )
        education = str(candidate.get("education") or "")
        years = str(candidate.get("years_experience") or "")
        skills_text = str(candidate.get("skills") or "")
        target_role = str(candidate.get("target_role") or "")

        return {
            "教育背景": self._score_education(education),
            "工作经验": self._score_experience(years),
            "核心技能": self._score_skills(skills_text, jd_text),
            "岗位匹配": self._score_role_alignment(target_role, candidate_text, jd_text),
            "沟通协作": self._score_communication(candidate_text, jd_text),
        }

    def _score_education(self, education: str) -> float:
        score = 6.0
        for degree, base_score in DEGREE_BASE_SCORES.items():
            if degree in education:
                score = max(score, base_score)
        if any(keyword in education for keyword in ["985", "211", "双一流", "省重点"]):
            score += 1.0
        return min(score, DIMENSION_MAX_SCORES["教育背景"])

    def _score_experience(self, years: str) -> float:
        match = re.search(r"(\d+)", years)
        year_count = int(match.group(1)) if match else 0
        for threshold, score in EXPERIENCE_SCORE_BANDS:
            if year_count >= threshold:
                return min(score, DIMENSION_MAX_SCORES["工作经验"])
        return 6.0

    def _score_skills(self, skills_text: str, jd_text: str) -> float:
        jd_keywords = _extract_keywords(jd_text)
        if not jd_keywords:
            return 20.0
        candidate_text = skills_text.lower()
        matched = sum(1 for keyword in jd_keywords if keyword.lower() in candidate_text)
        ratio = matched / len(jd_keywords)
        score = 10.0 + ratio * 25.0
        return min(round(score, 1), DIMENSION_MAX_SCORES["核心技能"])

    def _score_role_alignment(self, target_role: str, candidate_text: str, jd_text: str) -> float:
        score = 6.0
        target_role_lower = target_role.lower()
        candidate_text_lower = candidate_text.lower()
        if target_role_lower and target_role_lower in candidate_text_lower:
            score += 6.0
        keyword_hits = sum(1 for keyword in ROLE_ALIGNMENT_KEYWORDS if keyword.lower() in jd_text.lower() and keyword.lower() in candidate_text_lower)
        score += min(keyword_hits * 1.5, 3.0)
        return min(round(score, 1), DIMENSION_MAX_SCORES["岗位匹配"])

    def _score_communication(self, candidate_text: str, jd_text: str) -> float:
        candidate_text_lower = candidate_text.lower()
        jd_text_lower = jd_text.lower()
        needed = [keyword for keyword in COMMUNICATION_KEYWORDS if keyword.lower() in jd_text_lower]
        if not needed:
            return 10.0
        hits = sum(1 for keyword in needed if keyword.lower() in candidate_text_lower)
        ratio = hits / len(needed)
        score = 6.0 + ratio * 9.0
        return min(round(score, 1), DIMENSION_MAX_SCORES["沟通协作"])

    def _build_rule_reason(self, candidate: dict[str, Any], dimensions: list[dict[str, Any]]) -> str:
        skills = str(candidate.get("skills") or "无明显关键词")
        dimension_parts = [f"{item['name']}{item['score']}/{item['max_score']}" for item in dimensions]
        return f"规则匹配完成，技能信息为 {skills}；维度得分：{'，'.join(dimension_parts)}。"

    def _normalize_reason_text(
        self,
        reason: str,
        candidate: dict[str, Any],
        dimensions: list[dict[str, Any]],
    ) -> str:
        normalized = str(reason or "").strip()
        if _contains_chinese(normalized):
            return normalized
        return self._build_cn_reason(candidate, dimensions)

    def _build_cn_reason(self, candidate: dict[str, Any], dimensions: list[dict[str, Any]]) -> str:
        skills = str(candidate.get("skills") or "")
        years = str(candidate.get("years_experience") or "经验未知")
        top_dimensions = sorted(dimensions, key=lambda item: float(item.get("score", 0)), reverse=True)[:2]
        top_dimension_names = "、".join(str(item.get("name")) for item in top_dimensions if item.get("name")) or "综合匹配"
        skills_text = skills[:40] + "..." if len(skills) > 40 else skills
        if skills_text:
            return f"候选人在{top_dimension_names}方面表现较好，具备{skills_text}等相关能力；当前工作年限为{years}，建议结合岗位实际要求继续评估。"
        return f"候选人在{top_dimension_names}方面表现较好，当前工作年限为{years}，建议结合岗位实际要求继续评估。"


def _extract_json(content: str) -> str:
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("LLM did not return JSON")
    return match.group(0)


def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _normalize_score_100(score: Any) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    if value <= 10:
        value *= 10
    return min(round(value, 1), 100.0)


def _extract_keywords(text: str) -> list[str]:
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


def _normalize_dimension_weights(weights: dict[str, Any] | None) -> dict[str, float]:
    if not weights:
        return {name: float(value) for name, value in DIMENSION_MAX_SCORES.items()}

    normalized: dict[str, float] = {}
    for name, default_value in DIMENSION_MAX_SCORES.items():
        try:
            value = float(weights.get(name, default_value))
        except (TypeError, ValueError):
            value = float(default_value)
        normalized[name] = max(value, 0.0)

    total = sum(normalized.values())
    if total <= 0:
        return {name: float(value) for name, value in DIMENSION_MAX_SCORES.items()}
    if round(total, 1) == 100.0:
        return {name: round(value, 1) for name, value in normalized.items()}
    return {name: round(value * 100.0 / total, 1) for name, value in normalized.items()}


def _apply_dimension_weights(base_dimensions: dict[str, float], dimension_weights: dict[str, float]) -> dict[str, float]:
    weighted_dimensions: dict[str, float] = {}
    for name, default_max_score in DIMENSION_MAX_SCORES.items():
        ratio = base_dimensions.get(name, 0.0) / default_max_score if default_max_score else 0.0
        weighted_dimensions[name] = round(ratio * dimension_weights[name], 1)
    return weighted_dimensions


def _scale_dimension_scores(
    base_dimensions: dict[str, float],
    dimension_weights: dict[str, float],
    target_score: float,
) -> dict[str, float]:
    if target_score <= 0:
        return {name: 0.0 for name in base_dimensions}
    base_total = sum(base_dimensions.values())
    if base_total <= 0:
        return {name: 0.0 for name in base_dimensions}

    scaled: dict[str, float] = {}
    dimension_names = list(base_dimensions.keys())
    running_total = 0.0
    for index, name in enumerate(dimension_names):
        max_score = dimension_weights[name]
        if index == len(dimension_names) - 1:
            score = round(target_score - running_total, 1)
        else:
            score = round(base_dimensions[name] * target_score / base_total, 1)
            running_total += score
        scaled[name] = min(max(score, 0.0), max_score)

    current_total = round(sum(scaled.values()), 1)
    gap = round(target_score - current_total, 1)
    if gap != 0:
        last_name = dimension_names[-1]
        scaled[last_name] = min(max(round(scaled[last_name] + gap, 1), 0.0), dimension_weights[last_name])
    return scaled
