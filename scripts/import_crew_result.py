# -*- coding: utf-8 -*-
"""
crewAI 추출 결과를 MinuteDone DB에 추가 저장하는 스크립트
사용: python scripts/import_crew_result.py
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts.db import init_db, load_events, save_events

init_db()

NEW_TASKS = [
    {
        "task": "인스타그램 SV 문구 중 '넓은 상판을 다양하게 활용' 부분을 명사형으로 수정하고 전체적으로 워싱하기",
        "due_date": "TBD",
        "assignee": "수환",
        "context": "인스타그램 SV 피드백 중 다른 문구들은 명사형으로 끝나는데 해당 부분만 문체가 맞지 않아 수정 필요",
        "source_quote": "요것만 한 번 워싱 해주시고 네네. 다른 부분은 괜찮았거든요. 명사형으로 마무리될 수 있게 그리고 한 번 전체적으로 손볼 부분이 있으면 한 번 더 보긴 할게요.",
        "reason": "'워싱 해주시고', '명사형으로 마무리될 수 있게 손볼 부분이 있으면'이라는 표현이 수환에게 수정 작업을 요청하는 명확한 액션 아이템임",
        "checklist": ["'넓은 상판을 다양하게 활용' 문구를 명사형으로 변경", "전체 문구 톤앤매너 일관성 확인", "제품 사진 셀렉과 문구 매칭 여부 검토", "수정본 프로님께 전달"],
        "task_level": "sub",
        "parent_task": None,
        "end_date": None,
    },
    {
        "task": "월요일에 보정본 진행 현황 보고 후 일정 재확정하여 전달하기",
        "due_date": "2026-03-30",
        "assignee": "수환",
        "context": "보정본이 나와야 후속 작업이 가능하므로, 월요일에 보정 진행 현황을 확인하고 전체 일정을 다시 조율해야 함",
        "source_quote": "우선은 월요일날 그 보정된 거 진행 현황 보고 저희가 일정은 바로 한 번 다시 말씀드릴게요.",
        "reason": "'월요일날 진행 현황 보고', '일정은 바로 한 번 다시 말씀드릴게요'라는 표현이 특정 날짜에 수행해야 할 보고 및 일정 공유 업무를 명시함",
        "checklist": ["월요일 보정본 진행 현황 확인", "전체 일정 재산정", "프로님께 일정 공유"],
        "task_level": "sub",
        "parent_task": "보정본 수요일까지 확보하기 (필요시 자체 보정 진행)",
        "end_date": None,
    },
    {
        "task": "작가님에게 보정본 일정 앞당길 수 있는지 확인하기",
        "due_date": "TBD",
        "assignee": "미정",
        "context": "현재 보정본이 다음 주 수요일에 나온다고 했으나 더 빨리 필요한 상황이라 작가님께 일정 조율 가능 여부 확인 필요",
        "source_quote": "확인은 해봐야 돼요. 이게 만약에 작가님 입장에서도 물리적인 시간이 안 된다 이렇게 말씀하시면 사실 저희도 더 당길 수는 없을 수도 있을 것 같아서",
        "reason": "'확인은 해봐야 돼요'라는 표현이 작가님에게 일정 확인이 필요하다는 액션 아이템을 암시함",
        "checklist": ["작가님께 연락", "보정본 일정 앞당김 가능 여부 문의", "불가 시 대안 검토"],
        "task_level": "sub",
        "parent_task": "보정본 수요일까지 확보하기 (필요시 자체 보정 진행)",
        "end_date": None,
    },
    {
        "task": "보정본 수요일까지 확보하기 (필요시 자체 보정 진행)",
        "due_date": "2026-04-01",
        "assignee": "수환",
        "context": "PR팀 사전 요청 건도 있고 후속 작업을 위해 늦어도 수요일까지는 보정본이 필요하며, 작가님 일정이 안 맞으면 자체 보정도 고려",
        "source_quote": "최대한 그래도 수요일까지는 보정본은 받아야 될 것 같긴 해요. 왜냐면 또 막 PR팀에서도 사실 하나 사전 요청하신 것도 하셔가지고",
        "reason": "'수요일까지는 보정본은 받아야 될 것 같긴 해요'라는 표현이 명확한 마감일과 함께 보정본 확보라는 액션 아이템을 제시함",
        "checklist": ["작가님 보정본 수령 여부 확인", "일정 불가 시 자체 보정 진행 결정", "PR팀 요청 건 반영 여부 확인", "수요일까지 최종 보정본 확보"],
        "task_level": "parent",
        "parent_task": None,
        "end_date": None,
    },
    {
        "task": "통화 녹음 내용 정리하여 피드백 사항 내재화하기",
        "due_date": "TBD",
        "assignee": "수환",
        "context": "메일로 피드백을 다시 보내지 않기로 했고, 수환이 통화 내용을 직접 정리해 업무에 반영해야 함",
        "source_quote": "메일은 따로 안 드려도 될 것 같아요. 녹음해서 들으면서 정리하시면 될 것 같아요.",
        "reason": "'녹음해서 들으면서 정리하시면 될 것 같아요'라는 표현이 통화 내용 내재화 업무를 수환에게 지시하는 액션 아이템임",
        "checklist": ["통화 녹음 재청취", "피드백 항목별 정리", "업무 반영 여부 체크"],
        "task_level": "sub",
        "parent_task": None,
        "end_date": None,
    },
]

existing = load_events()
merged = existing + NEW_TASKS
save_events(merged)

print(f"✅ {len(NEW_TASKS)}건 추가 완료 (기존 {len(existing)}건 + 신규 {len(NEW_TASKS)}건 = 총 {len(merged)}건)")
for t in NEW_TASKS:
    print(f"  - [{t['due_date']}] {t['task'][:40]}... / 담당: {t['assignee']}")
