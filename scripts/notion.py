"""
============================================================
notion.py
팀 라이브러리 에이전트 v2 - Notion 연결 모듈
============================================================
"""

import os
from notion_client import Client
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")


def get_client() -> Client:
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("❌ NOTION_TOKEN 이 비어있습니다. config/.env 를 확인하세요.")
    return Client(auth=token)


def get_page_text(page_id: str) -> str:
    """페이지 ID로 본문 텍스트를 추출합니다 (중첩 블록 포함)."""
    notion = get_client()

    def _extract_blocks(block_id: str, depth: int = 0) -> list[str]:
        results = notion.blocks.children.list(block_id=block_id).get("results", [])
        lines = []
        for block in results:
            btype = block.get("type")
            rich = block.get(btype, {}).get("rich_text", [])
            line = "".join(r.get("plain_text", "") for r in rich)
            if line:
                indent = "  " * depth
                lines.append(indent + line)
            if block.get("has_children"):
                lines.extend(_extract_blocks(block["id"], depth + 1))
        return lines

    return "\n".join(_extract_blocks(page_id))


def _get_page_title(page: dict) -> str:
    """Notion 페이지 객체에서 제목을 추출합니다."""
    props = page.get("properties", {})
    # title 타입 속성 우선 탐색
    for prop in props.values():
        if prop.get("type") == "title":
            rich = prop.get("title", [])
            title = "".join(r.get("plain_text", "") for r in rich)
            if title:
                return title
    return "제목 없음"


def query_database(database_id: str, filter_obj: dict = None) -> list[dict]:
    notion = get_client()
    params = {"database_id": database_id}
    if filter_obj:
        params["filter"] = filter_obj
    return notion.databases.query(**params).get("results", [])


def get_meetings_for_rag(database_id: str) -> list[dict]:
    """
    회의록 데이터베이스의 모든 페이지를 읽어 RAG 입력 형태로 반환합니다.

    반환값:
        [{"page_id": str, "title": str, "created_time": str, "text": str}, ...]
    """
    notion = get_client()
    meetings = []

    # 페이지네이션 처리
    cursor = None
    while True:
        params = {"database_id": database_id}
        if cursor:
            params["start_cursor"] = cursor
        resp = notion.databases.query(**params)
        pages = resp.get("results", [])

        for page in pages:
            page_id = page["id"]
            title = _get_page_title(page)
            created_time = page.get("created_time", "")[:10]  # YYYY-MM-DD
            text = get_page_text(page_id)
            if text.strip():
                meetings.append({
                    "page_id": page_id,
                    "title": title,
                    "created_time": created_time,
                    "text": text,
                })

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    return meetings


def create_page(database_id: str, properties: dict, children: list = None) -> dict:
    notion = get_client()
    params = {"parent": {"database_id": database_id}, "properties": properties}
    if children:
        params["children"] = children
    return notion.pages.create(**params)


def save_page_to_file(page_id: str, output_path: str) -> str:
    """Notion 페이지 텍스트를 로컬 .txt 파일로 저장합니다."""
    text = get_page_text(page_id)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"✅ 저장 완료: {output_path}")
    return output_path


if __name__ == "__main__":
    notion = get_client()
    me = notion.users.me()
    print(f"✅ Notion 연결 성공! 사용자: {me.get('name', '알 수 없음')}")
