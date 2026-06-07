from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.config import settings


class ResumeParser:
    def parse(self, resume_text: str, target_role: str) -> dict[str, Any]:
        if settings.llm_api_key:
            try:
                return self._parse_with_llm(resume_text, target_role)
            except Exception:
                pass
        return self._parse_with_regex(resume_text, target_role)

    def _parse_with_llm(self, resume_text: str, target_role: str) -> dict[str, Any]:
        prompt = f"""
你是招聘简历解析助手。请从简历文本中提取字段，并严格返回 JSON：
name, phone, email, education, years_experience, skills, summary, target_role

岗位：{target_role}
简历文本：
{resume_text[:12000]}
"""
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": "你只返回 JSON，不要输出 Markdown。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
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
        return json.loads(_extract_json(content))

    def _parse_with_regex(self, resume_text: str, target_role: str) -> dict[str, Any]:
        phone_match = re.search(r"(?<!\d)(1[3-9]\d{9})(?!\d)", resume_text)
        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", resume_text)
        name = self._guess_name(resume_text)
        skills = self._guess_skills(resume_text)
        years = self._guess_years(resume_text)
        education = self._guess_education(resume_text)
        return {
            "name": name,
            "phone": phone_match.group(1) if phone_match else "",
            "email": email_match.group(0) if email_match else "",
            "education": education,
            "years_experience": years,
            "skills": skills,
            "summary": resume_text[:180].replace("\n", " "),
            "target_role": target_role,
        }

    def _guess_name(self, resume_text: str) -> str:
        first_lines = [line.strip() for line in resume_text.splitlines()[:8] if line.strip()]
        for line in first_lines:
            if 1 < len(line) <= 8 and re.fullmatch(r"[\u4e00-\u9fa5a-zA-Z·]+", line):
                return line
        return first_lines[0][:8] if first_lines else "未知候选人"

    def _guess_skills(self, resume_text: str) -> str:
        keywords = [
            "Python",
            "Java",
            "SQL",
            "Excel",
            "招聘",
            "AI",
            "机器学习",
            "数据分析",
            "产品",
            "运营",
        ]
        found = [keyword for keyword in keywords if keyword.lower() in resume_text.lower()]
        return ", ".join(found[:6])

    def _guess_years(self, resume_text: str) -> str:
        match = re.search(r"(\d+)\s*年", resume_text)
        return f"{match.group(1)}年" if match else "未知"

    def _guess_education(self, resume_text: str) -> str:
        for item in ["博士", "硕士", "本科", "大专", "高中"]:
            if item in resume_text:
                return item
        return "未知"


def _extract_json(content: str) -> str:
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("LLM did not return JSON")
    return match.group(0)
