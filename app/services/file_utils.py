from __future__ import annotations

import re
from pathlib import Path

import docx
import pdfplumber


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix == ".txt":
        return file_path.read_text(encoding="utf-8", errors="ignore")
    return ""


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value).strip("_")
    return value or "unknown_resume"


def rename_resume(file_path: Path, name: str, phone: str, target_role: str) -> Path:
    stem = sanitize_filename("_".join(filter(None, [name, phone, target_role])))
    new_path = file_path.with_name(f"{stem}{file_path.suffix.lower()}")
    if new_path == file_path:
        return file_path
    if new_path.exists():
        return file_path
    return file_path.rename(new_path)


def archive_resume(file_path: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_path.name
    if not target_path.exists():
        return file_path.rename(target_path)

    stem = file_path.stem
    suffix = file_path.suffix.lower()
    counter = 1
    while True:
        candidate_path = target_dir / f"{stem}_{counter}{suffix}"
        if not candidate_path.exists():
            return file_path.rename(candidate_path)
        counter += 1


def _extract_pdf(file_path: Path) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _extract_docx(file_path: Path) -> str:
    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
