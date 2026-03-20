"""
============================================================
rules.py
회사/팀별 추출 규칙 문서 로더
============================================================
config/rules/ 폴더의 .md 파일을 읽어서 프롬프트에 주입합니다.

사용법:
  - config/rules/default.md  : 기본 규칙 (항상 적용)
  - config/rules/{회사명}.md : 회사별 규칙 (COMPANY_RULES 환경변수로 선택)

환경변수:
  COMPANY_RULES=tiro        → config/rules/tiro.md 를 추가로 로드
  COMPANY_RULES=             → default.md 만 사용
============================================================
"""

import os
from pathlib import Path

RULES_DIR = Path("config/rules")


def load(company: str = None) -> str:
    """
    규칙 문서를 로드해서 하나의 문자열로 반환합니다.
    company가 지정되면 default + {company}.md 를 합쳐서 반환합니다.
    """
    company = company or os.getenv("COMPANY_RULES", "").strip()

    parts = []

    default_path = RULES_DIR / "default.md"
    if default_path.exists():
        parts.append(default_path.read_text(encoding="utf-8").strip())

    if company:
        company_path = RULES_DIR / f"{company}.md"
        if company_path.exists():
            parts.append(company_path.read_text(encoding="utf-8").strip())
        else:
            print(f"  ⚠️  규칙 파일 없음: {company_path} (default만 사용)")

    return "\n\n---\n\n".join(parts) if parts else ""


def list_available() -> list[str]:
    """사용 가능한 규칙 파일 목록을 반환합니다."""
    if not RULES_DIR.exists():
        return []
    return [f.stem for f in RULES_DIR.glob("*.md")]
