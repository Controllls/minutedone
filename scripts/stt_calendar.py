"""
============================================================
stt_calendar.py
팀 라이브러리 에이전트 v2 - STT 녹취록 → 캘린더 + 인사이트
============================================================
STT로 변환된 녹취록 텍스트를 두 가지로 처리합니다.

  [Test 1] 일정 & 액션 아이템 추출 → JSON → Google Calendar 등록
  [Test 2] 인사이트 & 이슈 요약 → Markdown → output/insights.md 저장

사용법:
  # 텍스트 파일을 인자로 넘기기
  python scripts/stt_calendar.py path/to/transcript.txt

  # 스크립트로 import해서 사용
  from stt_calendar import run
  events, markdown = run(transcript_text)

Google Calendar 사전 준비:
  1. config/service_account.json 준비 (Google Cloud 서비스 계정)
  2. 해당 서비스 계정 이메일을 캘린더 '공유 설정'에 편집자로 추가
  3. config/.env 에 GOOGLE_CALENDAR_ID 설정
============================================================
"""

import os
import json
import sys
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")
load_dotenv(dotenv_path="config/calendar.env", override=False)  # 캘린더 전용 설정

import llm    # 기존 LLM 래퍼
import rules  # 회사별 추출 규칙


# ============================================================
# 날짜 헬퍼
# ============================================================

_WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _today_str() -> str:
    """오늘 날짜를 'YYYY-MM-DD (요일)' 형식으로 반환합니다."""
    d = date.today()
    return f"{d.strftime('%Y-%m-%d')} ({_WEEKDAYS_KR[d.weekday()]})"


# ============================================================
# 프롬프트 템플릿
# ============================================================

_DATE_SYSTEM = (
    "너는 회의록에서 날짜 표현을 찾아 실제 날짜로 변환하는 어시스턴트야. "
    "반드시 JSON 객체만 출력하고, 코드블록을 절대 사용하지 마."
)

_DATE_PROMPT = """\
오늘: {today}

아래 회의록에서 언급된 모든 날짜/기간 표현을 찾아 실제 날짜(YYYY-MM-DD)로 변환해줘.

## 출력 형식
{{
  "표현": "YYYY-MM-DD"
}}

- "이번 주 금요일", "다음 주 월요일", "내일", "이번 주 안에" 등 → 오늘({today}) 기준으로 계산
- 날짜 언급이 없으면 빈 객체 {{}} 를 반환해.
- 코드블록 없이 순수 JSON만 출력해.

## 회의록
{transcript}
"""

_CALENDAR_SYSTEM = (
    "너는 회의록에서 업무를 빠짐없이 추출하는 어시스턴트야. "
    "반드시 JSON 배열만 출력하고, 코드블록을 절대 사용하지 마."
)

_CALENDAR_PROMPT = """\
오늘: {today}
{date_map_section}
아래 회의록에서 언급된 업무를 모두 추출해서 JSON 배열로 반환해.
계층 구분 없이 업무를 나열하기만 하면 돼.

각 항목의 필드:
- "task": 업무 내용 (구체적으로)
- "due_date": YYYY-MM-DD 또는 "TBD"
  - 날짜 특정 가능: 위의 날짜 사전 변환 결과를 우선 사용하고, 없으면 오늘({today}) 기준으로 계산
  - TBD: "나중에", "추후", "검토 예정", 날짜 언급 없음
- "assignee": 담당자, 모르면 "미정"
- "context": 이 업무가 나온 배경 한 줄
{rules_section}

코드블록 없이 순수 JSON 배열만 출력해.

## 회의록
{transcript}
{ppt_section}"""

_HIERARCHY_SYSTEM = (
    "너는 업무 목록을 보고 parent-sub 관계를 파악하는 프로젝트 매니저야. "
    "반드시 JSON 배열만 출력하고, 코드블록을 절대 사용하지 마."
)

_HIERARCHY_PROMPT = """\
아래는 회의록에서 추출한 업무 목록이야.
각 업무를 보고 parent-sub 관계를 판단해서 필드를 추가한 뒤 JSON 배열로 반환해.
{rules_section}

## 추가할 필드
- "task_level": "parent" 또는 "sub"
- "parent_task": 이 업무가 속하는 parent 업무의 task 이름, 없으면 null

## 판단 기준
- 여러 업무가 하나의 목표를 완성하기 위한 단계라면 → 그 목표를 parent로 설정하고, 단계들은 sub
- parent가 목록에 없으면 새로 만들어서 추가해도 돼
- 완전히 독립된 업무는 sub, parent_task: null
- parent의 due_date는 소속된 sub 중 가장 늦은 날짜로 맞춰줘

입력 데이터의 모든 필드(task, due_date, assignee, context)를 그대로 유지하면서 두 필드만 추가해.
코드블록 없이 순수 JSON 배열만 출력해.

업무 목록:
{tasks_json}
"""

_INSIGHT_SYSTEM = (
    "너는 기술 스터디의 핵심을 요약하여 기술 블로그 포스팅 초안을 잡는 에이전트야."
)

_INSIGHT_PROMPT = """\
다음 항목에 맞춰 내용을 구조화해줘.

1. 핵심 안건: 오늘 논의된 가장 중요한 주제 3가지
2. 기술적 한계(Issues): 테스트 과정에서 발견된 오류나 한계
3. 새로운 발견(Insights): 피그마 MCP, 커서 활용법 등 새롭게 알게 된 유용한 정보
4. 결론: 회의의 최종 결정 사항

출력 가이드: 노션(Notion)에 그대로 복사할 수 있게 Markdown 형식으로 작성해줘.

회의록 내용:
{transcript}
"""


# ============================================================
# Test 1 — 일정 & 액션 아이템 추출
# ============================================================

def _strip_codeblock(raw: str) -> str:
    """LLM 응답에서 코드블록 마커(```json ... ```)를 제거합니다."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _parse_json(raw: str) -> list:
    """LLM 응답에서 JSON 배열을 파싱합니다. 코드블록이 있으면 제거합니다."""
    return json.loads(_strip_codeblock(raw))


def _extract_date_map(transcript: str) -> dict:
    """회의록에서 날짜 표현 → YYYY-MM-DD 매핑을 추출합니다 (Step 0)."""
    today = _today_str()
    raw = llm.chat(
        _DATE_PROMPT.format(today=today, transcript=transcript),
        system=_DATE_SYSTEM,
        max_tokens=1000,
    )
    try:
        return json.loads(_strip_codeblock(raw))
    except Exception:
        return {}


def _format_date_map(date_map: dict) -> str:
    """날짜 매핑 dict를 프롬프트 주입용 문자열로 변환합니다."""
    if not date_map:
        return ""
    lines = "\n".join(f'- "{k}" → {v}' for k, v in date_map.items())
    return f"\n## 날짜 사전 변환 결과 (반드시 이 날짜 사용)\n{lines}\n"


def extract_calendar_events(transcript: str, company: str = None, ppt_context: str = None) -> list[dict]:
    """
    STT 텍스트에서 일정/액션 아이템을 3단계로 추출합니다.
    0단계: 날짜 표현 사전 추출
    1단계: 업무 나열 (계층 구분 없이)
    2단계: parent-sub 관계 재배치
    company: 회사별 규칙 파일 이름 (config/rules/{company}.md). None이면 환경변수 COMPANY_RULES 사용.
    ppt_context: PPT/문서에서 추출한 텍스트. 프롬프트에 참고 자료로 주입됩니다.
    """
    today = _today_str()
    rule_text = rules.load(company)
    rules_section = f"\n\n## 팀 규칙 (반드시 준수)\n\n{rule_text}" if rule_text else ""
    ppt_section = f"\n## 참고 문서 (PPT/자료)\n\n아래 문서 내용을 업무 추출 시 참고하세요. 회의록에서 언급된 항목과 연결지어 context를 보완할 수 있습니다.\n\n{ppt_context}" if ppt_context else ""

    # 0단계: 날짜 표현 사전 추출
    date_map = _extract_date_map(transcript)
    date_map_section = _format_date_map(date_map)

    # 1단계: 업무 나열
    raw1 = llm.chat(
        _CALENDAR_PROMPT.format(
            today=today,
            transcript=transcript,
            rules_section=rules_section,
            ppt_section=ppt_section,
            date_map_section=date_map_section,
        ),
        system=_CALENDAR_SYSTEM,
        max_tokens=10000,
    )
    tasks = _parse_json(raw1)

    # 2단계: 계층 재배치
    raw2 = llm.chat(
        _HIERARCHY_PROMPT.format(
            tasks_json=json.dumps(tasks, ensure_ascii=False, indent=2),
            rules_section=rules_section,
        ),
        system=_HIERARCHY_SYSTEM,
        max_tokens=10000,
    )
    return _parse_json(raw2)


# ============================================================
# Test 2 — 인사이트 & 이슈 요약
# ============================================================

def extract_insights(transcript: str) -> str:
    """
    STT 텍스트에서 인사이트 & 이슈를 Markdown 형식으로 요약합니다.
    """
    prompt = _INSIGHT_PROMPT.format(transcript=transcript)
    return llm.chat(prompt, system=_INSIGHT_SYSTEM, max_tokens=2048)


# ============================================================
# Task 분류
# ============================================================

_TASK_SYSTEM = (
    "너는 회의록에서 추출된 태스크 데이터를 관리하는 프로젝트 매니저 에이전트야."
)

_TASK_PROMPT = """\
아래 JSON 배열을 입력받아 지정된 뷰 구조에 맞게 분류해줘.

## 분류 규칙

기준일: {today}
본인 이름: {user_name}

1. `전체_업무`: 완료 여부와 상관없이 모든 태스크
2. `오늘_할일`: due_date가 오늘 날짜이거나, due_date가 'TBD'인 태스크
3. `담당_업무`: assignee가 본인 이름 또는 "전체"인 태스크
4. `완료_업무`: status가 "done"인 태스크 (없으면 빈 배열 반환)

## 출력 규칙

- 출력 형식은 반드시 아래 JSON 구조를 따를 것
- 각 태스크에는 원본 필드(task, task_level, parent_task, due_date, assignee, context)를 그대로 유지할 것
- task_level이 없는 경우 "sub"으로 간주, parent_task가 없는 경우 null로 간주
- 뷰는 중복 포함 허용
- status 필드가 없으면 기본값은 "pending"으로 간주

## 출력 포맷

{{
  "views": {{
    "전체_업무": [ ...모든 태스크... ],
    "오늘_할일": [ ...오늘 마감이거나 TBD인 태스크... ],
    "담당_업무": [ ...본인 또는 전체 담당 태스크... ],
    "완료_업무": [ ...status가 done인 태스크... ]
  }}
}}

코드블록 없이 순수 JSON만 출력해.

## 입력 데이터

{events_json}
"""


def classify_tasks(events: list[dict], user_name: str = "전체") -> dict:
    """
    추출된 이벤트 목록을 전체/오늘/담당/완료 뷰로 분류합니다.
    """
    today = _today_str()
    prompt = _TASK_PROMPT.format(
        today=today,
        user_name=user_name,
        events_json=json.dumps(events, ensure_ascii=False, indent=2),
    )
    raw = llm.chat(prompt, system=_TASK_SYSTEM, max_tokens=2048)
    return json.loads(_strip_codeblock(raw))


# ============================================================
# Notion Calendar 등록
# ============================================================

def create_notion_calendar_events(events: list[dict]) -> list[str]:
    """
    추출된 이벤트 목록을 Notion 데이터베이스에 페이지로 생성합니다.
    Notion Calendar가 해당 DB를 바라보고 있으면 자동으로 캘린더에 표시됩니다.
    날짜가 'TBD'인 항목은 스킵합니다.

    필요한 설정:
      - NOTION_TOKEN (config/.env)
      - NOTION_CALENDAR_DB_ID (config/calendar.env)

    Notion DB 필수 속성:
      - 이름(title): 일정 제목
      - 날짜(date):  due_date 매핑
      - 담당자(rich_text): assignee
      - 맥락(rich_text):   context
    """
    import notion

    db_id = os.getenv("NOTION_CALENDAR_DB_ID")
    if not db_id:
        raise ValueError(
            "❌ NOTION_CALENDAR_DB_ID 가 비어있습니다. config/calendar.env 를 확인하세요."
        )

    created_urls = []
    for ev in events:
        due = ev.get("due_date", "TBD")
        if not due or due.upper() == "TBD":
            print(f"  ⏭️  날짜 미정, 스킵: {ev.get('task')}")
            continue

        title = f"[{ev.get('assignee', '미정')}] {ev.get('task', '')}"
        properties = {
            "이름": {
                "title": [{"text": {"content": title}}]
            },
            "날짜": {
                "date": {"start": due}
            },
        }
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": ev.get("context", "")}}]
                },
            }
        ] if ev.get("context") else None

        result = notion.create_page(db_id, properties, children)
        url = result.get("url", "")
        created_urls.append(url)
        print(f"  ✅ 등록: [{ev.get('assignee', '미정')}] {ev.get('task')} ({due})")

    return created_urls


# ============================================================
# 인사이트 파일 저장
# ============================================================

def save_insights(markdown: str, output_path: str = "output/insights.md") -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"  ✅ 저장: {output_path}")
    return output_path


# ============================================================
# 통합 실행
# ============================================================

def run(
    transcript: str,
    skip_calendar: bool = False,
    insights_path: str = "output/insights.md",
) -> tuple[list[dict], str]:
    """
    STT 녹취록을 받아 캘린더 이벤트 등록 + 인사이트 저장까지 실행합니다.

    Args:
        transcript: STT 변환된 회의록 텍스트
        skip_calendar: True면 캘린더 등록 없이 추출만 수행
        insights_path: 인사이트 Markdown 저장 경로

    Returns:
        (events, markdown) 튜플
    """
    print("=" * 55)
    print(f"STT 캘린더 에이전트  |  LLM: {llm.current_provider().upper()}")
    print("=" * 55)

    # ── Test 1 ──────────────────────────────────────────────
    print("\n[Test 1] 일정 & 액션 아이템 추출 중...")
    events = extract_calendar_events(transcript)
    print(f"  → {len(events)}개 항목 추출됨\n")
    print(json.dumps(events, ensure_ascii=False, indent=2))

    if not skip_calendar:
        print("\n  [캘린더 등록 중...]")
        try:
            urls = create_notion_calendar_events(events)
            print(f"  → {len(urls)}개 캘린더 등록 완료")
        except Exception as e:
            print(f"  ⚠️  캘린더 등록 실패 (추출 결과는 유지됩니다): {e}")

    # ── Test 2 ──────────────────────────────────────────────
    print("\n[Test 2] 인사이트 & 이슈 요약 중...")
    markdown = extract_insights(transcript)
    save_insights(markdown, insights_path)
    print("\n--- 추출된 인사이트 ---")
    print(markdown)

    return events, markdown


# ============================================================
# CLI 진입점
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, encoding="utf-8") as f:
            transcript_text = f.read()
        print(f"파일 로드: {path} ({len(transcript_text)}자)\n")
    else:
        print("녹취록 텍스트를 붙여넣고 엔터를 두 번 치세요:")
        lines = []
        while True:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
        transcript_text = "\n".join(lines).strip()

    skip = "--no-calendar" in sys.argv
    run(transcript_text, skip_calendar=skip)
