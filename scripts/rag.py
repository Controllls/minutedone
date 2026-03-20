"""
============================================================
rag.py
팀 라이브러리 에이전트 v2 - RAG 채팅 모듈
============================================================
회의록을 문서 저장소에 저장하고,
질문이 들어오면 관련 문서를 검색해 LLM에 컨텍스트로 전달합니다.

저장 방식: output/rag_store.json (로컬 JSON)
검색 방식: 키워드 기반 TF-IDF 스코어링 (외부 벡터DB 불필요)
============================================================
"""

import os
import json
import math
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")

import llm

RAG_STORE_PATH = "output/rag_store.json"

_CHAT_SYSTEM = """\
너는 팀 회의록 기반 AI 어시스턴트야.
아래 [참고 문서]는 실제 회의에서 나온 내용이야.
반드시 참고 문서 내용을 바탕으로 답변해.
문서에 없는 내용은 "해당 내용은 회의록에서 찾을 수 없어요."라고 솔직하게 말해.
답변은 간결하고 핵심만 담아줘.
"""

_CHAT_PROMPT = """\
[참고 문서]
{context}

[질문]
{question}
"""


# ============================================================
# 저장소 관리
# ============================================================

def _load_store() -> list[dict]:
    if not os.path.exists(RAG_STORE_PATH):
        return []
    with open(RAG_STORE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_store(docs: list[dict]):
    os.makedirs(os.path.dirname(RAG_STORE_PATH), exist_ok=True)
    with open(RAG_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)


def add_document(text: str, metadata: dict = None) -> int:
    """
    회의록 텍스트를 청크로 나눠 저장소에 추가합니다.
    반환값: 추가된 청크 수
    """
    docs = _load_store()
    chunks = _chunk_text(text)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for chunk in chunks:
        docs.append({
            "id": len(docs),
            "text": chunk,
            "metadata": metadata or {},
            "created_at": now,
        })
    _save_store(docs)
    return len(chunks)


def get_all_documents() -> list[dict]:
    return _load_store()


def clear_store():
    _save_store([])


# ============================================================
# 텍스트 청킹
# ============================================================

def _chunk_text(text: str, max_chars: int = 400, overlap: int = 80) -> list[str]:
    """
    텍스트를 발화 단위 또는 문장 단위로 청킹합니다.
    화자 구분(이름: ...) 패턴이 있으면 발화 단위로 묶어서 자릅니다.
    """
    # 화자 패턴 감지
    speaker_pattern = re.compile(r'^[가-힣A-Za-z]{1,10}:\s', re.MULTILINE)
    if speaker_pattern.search(text):
        # 발화 단위로 분리
        parts = speaker_pattern.split(text)
        speakers = speaker_pattern.findall(text)
        utterances = [s + p for s, p in zip(speakers, parts[1:])]
    else:
        # 줄바꿈 단위
        utterances = [l.strip() for l in text.split('\n') if l.strip()]

    chunks, buf = [], ""
    for utt in utterances:
        if len(buf) + len(utt) > max_chars and buf:
            chunks.append(buf.strip())
            buf = buf[-overlap:] + " " + utt  # 오버랩
        else:
            buf += (" " if buf else "") + utt
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


# ============================================================
# 검색 (키워드 기반 TF-IDF)
# ============================================================

def _tokenize(text: str) -> list[str]:
    """한국어+영어 간단 토크나이징"""
    text = text.lower()
    tokens = re.findall(r'[가-힣]+|[a-z0-9]+', text)
    stopwords = {'이', '그', '저', '것', '수', '를', '을', '이', '가', '은', '는',
                 '에', '의', '로', '으로', '도', '와', '과', '하', '해', '했', '한',
                 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at'}
    return [t for t in tokens if t not in stopwords and len(t) > 1]


def _score(query_tokens: list[str], doc_text: str) -> float:
    doc_tokens = _tokenize(doc_text)
    if not doc_tokens:
        return 0.0
    doc_freq = {}
    for t in doc_tokens:
        doc_freq[t] = doc_freq.get(t, 0) + 1

    tfidf = sum(doc_freq.get(q, 0) / len(doc_tokens) for q in query_tokens)

    # 서브스트링 보너스: 복합어("회의날짜가")가 토큰 분리 없이 들어온 경우도 커버
    doc_lower = doc_text.lower()
    substring_bonus = sum(0.05 for q in query_tokens if len(q) >= 2 and q in doc_lower)

    return (tfidf + substring_bonus) * math.log(1 + len(doc_tokens))


def search(query: str, top_k: int = 4) -> list[dict]:
    """
    질문과 관련도 높은 청크를 top_k개 반환합니다.
    키워드 매칭 결과가 없으면 최신 청크를 fallback으로 반환합니다.
    """
    docs = _load_store()
    if not docs:
        return []
    q_tokens = _tokenize(query)
    scored = [(doc, _score(q_tokens, doc["text"])) for doc in docs]
    scored.sort(key=lambda x: x[1], reverse=True)

    matched = [doc for doc, score in scored[:top_k] if score > 0]
    if matched:
        return matched

    # 키워드 매칭 실패 시 최신 청크 fallback
    return docs[-top_k:]


# ============================================================
# RAG 채팅
# ============================================================

def chat(question: str, history: list[dict] = None) -> tuple[str, list[dict]]:
    """
    질문에 대해 RAG 기반으로 답변합니다.

    Args:
        question: 사용자 질문
        history: 이전 대화 기록 [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        (답변 텍스트, 업데이트된 history)
    """
    history = history or []

    # 1. 관련 문서 검색
    relevant = search(question, top_k=4)

    if relevant:
        context = "\n\n---\n\n".join(
            f"[{doc['metadata'].get('title', '회의록')} | {doc['created_at']}]\n{doc['text']}"
            for doc in relevant
        )
    else:
        context = "저장된 회의록이 없습니다."

    # 2. 프롬프트 구성
    prompt = _CHAT_PROMPT.format(context=context, question=question)

    # 3. 멀티턴 LLM 호출
    reply, updated_history = llm.multi_turn(history, prompt)

    # history에는 원본 질문으로 저장 (프롬프트 아닌)
    updated_history[-2]["content"] = question  # user 메시지를 원본 질문으로 교체

    return reply, updated_history


# ============================================================
# 저장소 상태 확인
# ============================================================

def store_stats() -> dict:
    docs = _load_store()
    return {
        "total_chunks": len(docs),
        "meetings": len({d["metadata"].get("title", "") for d in docs if d.get("metadata")}),
    }
