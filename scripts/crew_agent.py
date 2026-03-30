# -*- coding: utf-8 -*-
"""
crew_agent.py — crewAI 멀티 에이전트 회의록 추출기
MinuteDone 앱에서 /api/agent/run 으로 호출됩니다.
"""

import os, sys, json, time, uuid, re
from datetime import date, timedelta
from crewai import Agent, Task, Crew, LLM
from crewai.tools import BaseTool

# MinuteDone DB 접근 (scripts/ 폴더 내에서 실행되므로 상대 경로로)
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import db


# ── 날짜 기준표 사전 계산 ──────────────────────────────────────
def _build_date_reference() -> str:
    _WD = ["월", "화", "수", "목", "금", "토", "일"]
    d = date.today()
    mon = d - timedelta(days=d.weekday())

    def table(monday, label):
        return "\n".join(
            f"  {_WD[i]}요일 ({label}): {(monday + timedelta(days=i)).strftime('%Y-%m-%d')}"
            for i in range(7)
        )

    return (
        f"## 날짜 기준표 (계산 금지 — 반드시 이 표만 참조)\n"
        f"기준일(오늘): {d.strftime('%Y-%m-%d')} ({_WD[d.weekday()]})\n"
        f"내일: {(d+timedelta(1)).strftime('%Y-%m-%d')}  모레: {(d+timedelta(2)).strftime('%Y-%m-%d')}\n\n"
        f"이번 주 (월~일):\n{table(mon, '이번 주')}\n\n"
        f"다음 주 (월~일):\n{table(mon+timedelta(weeks=1), '다음 주')}\n\n"
        "## 날짜 변환 규칙 (스스로 계산 금지)\n"
        '- "오늘/오늘 중" → 기준일\n'
        '- "X요일/X요일까지/이번 주 X요일" (다음 주 언급 없음) → 이번 주 표에서 X요일 날짜\n'
        '  ※ 오늘과 같은 요일이면 → 기준일 자체\n'
        '- "다음 주 X요일" → 다음 주 표에서 X요일 날짜\n'
        '- "이번 주 안에/이번 주 내" → 이번 주 금요일\n'
    )


# ── crewAI 로그 파서 ──────────────────────────────────────────
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")  # ANSI 색상 코드 제거

_NOISE_PATTERNS = [
    r"^> (Entering|Finished) new",
    r"^\s*$",
    r"^[═─╭╰╮╯│\s]+$",          # 박스 테두리 줄
    r"^\[DEBUG\]",
    r"^(Traceback|  File )",
    r"^thinking\.\.\.",
    r"^Using tool:",
    r"^Crew Execution (Started|Finished)",
    r"^Task (Started|Completed)",
    r"^Name:\s*$",
    r"^ID:\s*[0-9a-f\-]+$",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS))

_AGENT_NAME_RE = re.compile(r"## Agent:\s*(.+)")
_TASK_RE       = re.compile(r"## Task:\s*(.+)")
_THOUGHT_RE    = re.compile(r"^\s*Thought:\s*(.+)", re.IGNORECASE)
_ACTION_RE     = re.compile(r"^\s*Action:\s*(.+)", re.IGNORECASE)
_ACTION_IN_RE  = re.compile(r"^\s*Action Input:\s*(.+)", re.IGNORECASE)
_OBS_RE        = re.compile(r"^\s*Observation:\s*(.+)", re.IGNORECASE)
_FINAL_RE      = re.compile(r"^\s*Final Answer:\s*(.+)", re.IGNORECASE)
_DELEGATE_RE   = re.compile(r"coworker['\"]?\s*[:\-]\s*['\"]?([^'\",\n]+)", re.IGNORECASE)


def _parse_crew_line(line: str) -> str | None:
    """crewAI verbose 한 줄 → 읽기 쉬운 형태. None이면 무시."""
    # 1. ANSI 색상 코드 제거
    clean = _ANSI_RE.sub("", line).strip()
    if not clean or _NOISE_RE.search(clean):
        return None

    m = _AGENT_NAME_RE.search(clean)
    if m:
        return f"👤 [{m.group(1).strip()}] 시작"

    m = _TASK_RE.search(clean)
    if m:
        return f"📋 태스크: {m.group(1).strip()[:60]}…"

    m = _THOUGHT_RE.match(clean)
    if m:
        return f"💭 {m.group(1).strip()[:80]}…"

    m = _ACTION_RE.match(clean)
    if m:
        return f"⚙️  도구 호출: {m.group(1).strip()}"

    m = _ACTION_IN_RE.match(clean)
    if m:
        return f"   입력: {m.group(1).strip()[:60]}…"

    m = _OBS_RE.match(clean)
    if m:
        return f"📥 결과: {m.group(1).strip()[:80]}…"

    m = _FINAL_RE.match(clean)
    if m:
        return f"✅ 최종: {m.group(1).strip()[:80]}…"

    m = _DELEGATE_RE.search(clean)
    if m:
        return f"🔀 위임 → {m.group(1).strip()}"

    # 박스 안 태스크 설명 줄 (│ 로 시작하는 경우 이미 제거됨)
    # 너무 짧거나 의미없는 줄 무시
    if len(clean) < 5:
        return None
    # 특수문자만 있는 줄 무시
    if re.match(r"^[\W_]+$", clean):
        return None
    return clean


# ── stdout 캡처 래퍼 ──────────────────────────────────────────
class _LogCapture:
    def __init__(self, log_fn, original):
        self._fn = log_fn
        self._orig = original
        self._buf = ""

    def write(self, text):
        self._orig.write(text)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            parsed = _parse_crew_line(line)
            if parsed:
                self._fn(parsed)

    def flush(self):
        self._orig.flush()
        if self._buf.strip():
            parsed = _parse_crew_line(self._buf)
            if parsed:
                self._fn(parsed)
            self._buf = ""

    def isatty(self):
        return False


# ── 툴 정의 ───────────────────────────────────────────────────

class SaveToMinuteDoneTool(BaseTool):
    """pig 전용 — MinuteDone DB + (향후) Google Calendar / Notion DB"""
    name: str = "save_to_minutedone"
    description: str = (
        "Save extracted tasks to MinuteDone database. "
        "Input must be a JSON array string with fields: "
        "task, due_date, assignee, context, source_quote, reason, checklist, task_level, parent_task"
    )

    def _run(self, data: str) -> str:
        try:
            cleaned = data.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            cleaned = cleaned.strip()
            new_tasks = json.loads(cleaned)
            if isinstance(new_tasks, dict):
                new_tasks = [new_tasks]
        except Exception as e:
            return f"ERROR: JSON 파싱 실패 — {e}"

        existing = db.load_events()
        merged = existing + new_tasks
        db.save_events(merged)
        return f"✅ MinuteDone DB 저장 완료: {len(new_tasks)}건 추가 (총 {len(merged)}건)"


class WriteSummaryTool(BaseTool):
    """rabbit 전용 — 회의 요약 마크다운 파일 생성"""
    name: str = "write_summary"
    description: str = (
        "Write meeting summary as a markdown file. "
        "Input: JSON string with keys 'filename' (str) and 'content' (str, markdown text)."
    )

    def _run(self, data: str) -> str:
        try:
            cleaned = data.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            payload = json.loads(cleaned.strip())
            filename = payload.get("filename", f"meeting_{date.today().strftime('%Y%m%d')}.md")
            content  = payload.get("content", "")
        except Exception as e:
            return f"ERROR: 입력 파싱 실패 — {e}"

        out_dir = os.path.join(_HERE, "..", "output", "summaries")
        os.makedirs(out_dir, exist_ok=True)
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"✅ 요약 파일 저장 완료: output/summaries/{filename}"


# ── 메인 실행 함수 ────────────────────────────────────────────
def run_crew(transcript: str, contacts_context: str = None, log_fn=None) -> dict:
    """
    crewAI 팀으로 회의록을 추출해 MinuteDone DB에 저장합니다.
    log_fn: 실시간 로그 콜백 callable(str)
    Returns: {"status": "done"|"error", "count": int, "session_id": str}
    """
    if log_fn is None:
        log_fn = print

    session_id = str(uuid.uuid4())[:8]
    date_ref = _build_date_reference()
    contacts_section = contacts_context.strip() if contacts_context else "인물 정보 없음"

    # 에이전트별 메모리 주입
    cat_memory       = db.build_agent_memory_prompt("cat")
    pig_memory       = db.build_agent_memory_prompt("pig")
    rabbit_memory    = db.build_agent_memory_prompt("rabbit")
    retriever_memory = db.build_agent_memory_prompt("retriever")

    save_tool    = SaveToMinuteDoneTool()
    summary_tool = WriteSummaryTool()
    _task_timers: dict = {}  # task_name -> start_time

    def task_callback(output):
        """태스크 완료 시 DB에 이력 기록 + 간략 로그"""
        task_name = getattr(output, "name", "") or getattr(output, "description", "")[:40]
        agent_name = getattr(output, "agent", "unknown")
        result_text = str(output.raw)[:300] if hasattr(output, "raw") else str(output)[:300]
        start = _task_timers.pop(task_name, None)
        duration = round(time.time() - start, 2) if start else None
        db.log_agent_run(session_id, agent_name, task_name, result_text,
                         status="done", duration_sec=duration)
        dur_str = f" ({duration}s)" if duration else ""
        log_fn(f"✔ 태스크 완료 [{agent_name}]{dur_str}: {task_name[:40]}")

    def step_callback(step):
        """에이전트 스텝 — 위임/도구 호출만 간략 로그 + DB 기록"""
        agent_obj  = getattr(step, "agent", {})
        agent_name = agent_obj.role if hasattr(agent_obj, "role") else str(agent_obj)
        thought = getattr(step, "thought", "") or ""
        action  = getattr(step, "action",  "") or ""

        if thought or action:
            db.log_agent_decision(session_id, str(agent_name),
                                  str(action)[:200], str(thought)[:300])

        # 위임 감지
        if "delegate" in str(action).lower():
            coworker = re.search(r"coworker['\"]?\s*[:\-]\s*['\"]?([^'\",\n]+)", str(action), re.I)
            target = coworker.group(1).strip() if coworker else "?"
            log_fn(f"🔀 [{agent_name}] → {target} 에게 위임")
        # 툴 호출 감지
        elif action and action.strip():
            log_fn(f"⚙️  [{agent_name}] 도구: {str(action).strip()[:60]}")

    # stdout 가로채기
    _orig_out = sys.stdout
    _orig_err = sys.stderr
    sys.stdout = _LogCapture(log_fn, _orig_out)
    sys.stderr = _LogCapture(log_fn, _orig_err)

    try:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        claude = LLM(model="anthropic/claude-sonnet-4-5", api_key=api_key)

        # ── 에이전트 (5명) ──────────────────────────────────────
        wolf = Agent(
            role="팀 총괄 대장",
            goal="회의록 처리 전 과정을 지휘한다. 추출→저장→문서화→알림 순서를 보장한다.",
            backstory="싸가지는 없지만 결과는 낸다. 끝날 때까지 끝난 게 아님.",
            llm=claude, verbose=True, memory=False,
            max_iter=6,
        )
        cat = Agent(
            role="입력 수신 및 업무 추출 담당",
            goal="회의록(STT 결과 포함)에서 모든 업무를 빠짐없이 추출하고 7개 필드를 완성한다",
            backstory=(
                "파일 입력과 STT 결과를 처음 받는 관문. 원문을 절대 놓치지 않음.\n"
                + cat_memory
            ),
            llm=claude, verbose=True, memory=False,
            max_iter=3,
        )
        pig = Agent(
            role="DB 저장 담당",
            goal="추출된 업무를 parent-sub 계층으로 분류하고 MinuteDone DB에 저장한다. 향후 Google Calendar·Notion DB 연동 예정.",
            backstory=(
                "데이터 저장의 최종 책임자. 구조화와 계층 분류가 특기. 저장 1회로 완료한다.\n"
                + pig_memory
            ),
            tools=[save_tool],
            llm=claude, verbose=True, memory=False,
            max_iter=3,
        )
        rabbit = Agent(
            role="문서 생성 담당",
            goal="회의 결과를 마크다운 요약 파일로 작성한다. 향후 Notion 문서 생성 예정.",
            backstory=(
                "정리의 달인. 회의록을 읽기 좋은 문서로 만든다.\n"
                + rabbit_memory
            ),
            tools=[summary_tool],
            llm=claude, verbose=True, memory=False,
            max_iter=3,
        )
        retriever = Agent(
            role="알림 발송 담당",
            goal="처리 결과를 관련자에게 전달한다. 향후 잔디 API·Gmail·Slack 연동 예정.",
            backstory=(
                "연락의 허브. 누구에게 무엇을 보내야 할지 안다.\n"
                + retriever_memory
            ),
            llm=claude, verbose=True, memory=False,
            max_iter=2,
        )

        # ── 태스크 (4단계) ──────────────────────────────────────

        # 1. cat: 회의록 수신 → 업무 추출
        task_extract = Task(
            description=f"""
아래 회의록에서 언급된 **모든 업무**를 빠짐없이 추출하고, 각 업무마다 7개 필드를 모두 채워라.
추출이 끝나면 즉시 JSON 배열로 반환한다. 추가 검토 없이 한 번에 완료한다.

{date_ref}

## 참여자 / 관계자 정보
{contacts_section}

## 추출 필드 (업무마다 전부 필수)
1. task        : 업무 내용 (구체적으로, 동사형)
2. due_date    : 위 날짜 기준표에서 찾아 YYYY-MM-DD로 변환. 스스로 계산 절대 금지. 없으면 "TBD"
3. assignee    : 담당자 실명. 참여자 정보 섹션 참조. 문맥으로 파악.
                 호칭(닉네임)은 실명으로 변환. 팀 전체면 "전체". 특정 불가면 "미정"
4. context     : 이 업무가 왜 나왔는지 배경 한 줄
5. source_quote: 회의록 원문 그대로 발췌 (1~2문장, 생략·요약 금지)
6. reason      : 이 발언을 업무로 판단한 근거 한 문장
7. checklist   : 완료를 위해 확인할 세부 액션 2~4개 (문자열 배열)

## 회의록
{transcript}
""",
            expected_output=(
                "7개 필드가 모두 채워진 업무 목록 JSON 배열. 추가 작업 없이 반환으로 완료."
            ),
        )

        # 2. pig: 계층 분류 + DB 저장
        task_save = Task(
            description=f"""
cat이 추출한 업무 목록을 parent-sub 계층으로 분류하고 save_to_minutedone 툴로 저장하라.
저장 성공 메시지를 받으면 즉시 완료한다. 재시도 금지.

## parent-sub 분류 기준
- task_level  : "parent" 또는 "sub"
- parent_task : parent 업무의 task명, 없으면 null
- 리서치→기획→시안→수정→납품 같은 단계 구조 → 목표=parent, 단계=sub
- parent가 목록에 없으면 새로 추가
- 단발성 독립 업무 → task_level: "sub", parent_task: null
- parent의 due_date = 소속 sub 중 가장 늦은 날짜

## JSON 형식으로 save_to_minutedone 1회 호출
[{{"task":"","due_date":"","assignee":"","context":"","source_quote":"","reason":"","checklist":[],"task_level":"","parent_task":null}}]
""",
            expected_output="'✅ MinuteDone DB 저장 완료: N건 추가 (총 M건)' 메시지. 이 메시지로 완료.",
        )

        # 3. rabbit: 회의 요약 문서 생성
        task_document = Task(
            description=f"""
cat이 추출한 업무 목록과 회의 내용을 바탕으로 회의 요약 마크다운 문서를 작성하고
write_summary 툴로 저장하라.

## 문서 구성
- 제목: 회의 날짜 + 주요 주제
- 참석자
- 주요 논의 내용 (3~5개 bullet)
- 결정 사항
- 추출된 업무 목록 (담당자, 기한 포함)

## 파일명 형식
meeting_YYYYMMDD_요약.md (오늘 날짜: {date.today().strftime('%Y%m%d')})

write_summary 툴 입력: {{"filename": "meeting_YYYYMMDD_요약.md", "content": "마크다운 내용"}}
""",
            expected_output="'✅ 요약 파일 저장 완료: output/summaries/...' 메시지. 이 메시지로 완료.",
        )

        # 4. retriever: 알림 발송 (현재는 발송 대상 목록 반환, 향후 실제 연동)
        task_notify = Task(
            description=f"""
처리된 업무 목록을 검토하고 알림이 필요한 대상과 내용을 정리하라.
현재는 실제 발송 없이 아래 형식으로 알림 계획만 반환한다.
(향후 잔디 API·Gmail·Slack 연동 시 실제 발송 예정)

## 반환 형식
- 알림 대상: [이름, 채널, 내용 요약]
- 긴급 업무 (오늘/내일 마감): 별도 표시
""",
            expected_output="알림 발송 계획 목록. 대상·채널·내용 포함.",
        )

        crew = Crew(
            agents=[cat, pig, rabbit, retriever],
            tasks=[task_extract, task_save, task_document, task_notify],
            manager_agent=wolf,
            process="hierarchical",
            verbose=True,
            memory=False,
            task_callback=task_callback,
            step_callback=step_callback,
            max_iter=12,
        )

        log_fn("=" * 50)
        log_fn("[늑대] 회의록 감지. 팀 가동 시작.")
        log_fn("=" * 50)

        result = crew.kickoff()

        log_fn("=" * 50)
        log_fn(f"[완료] {str(result)[:200]}")
        log_fn("=" * 50)

        # 저장된 건수 계산
        count = len(db.load_events())

        # 세션 완료 후 패턴 학습 저장
        _save_session_memory(session_id, log_fn)

        return {"status": "done", "count": count, "session_id": session_id}

    except Exception as e:
        log_fn(f"[ERROR] {e}")
        db.log_agent_run(session_id, "system", "crew_run", str(e), status="error")
        return {"status": "error", "error": str(e), "session_id": session_id}
    finally:
        sys.stdout = _orig_out
        sys.stderr = _orig_err


def _save_session_memory(session_id: str, log_fn):
    """세션 완료 후 에이전트별 패턴을 agent_memory에 누적 저장합니다."""
    data = db.get_session_runs(session_id)
    runs = data.get("runs", [])
    for run in runs:
        agent = run.get("agent_name") or "unknown"
        duration = run.get("duration_sec")
        task = run.get("task_name", "")[:50]
        if duration:
            db.upsert_agent_memory(agent, "performance",
                                   f"avg_duration:{task}",
                                   f"{duration}초", confidence=0.6)
    log_fn(f"[DB] 에이전트 메모리 {len(runs)}건 업데이트 (session: {session_id})")
