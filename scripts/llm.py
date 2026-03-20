"""
============================================================
llm.py
팀 라이브러리 에이전트 v2 - 통합 LLM 래퍼
============================================================
.env 의 LLM_PROVIDER 값에 따라
Claude / ChatGPT / Gemini / 로컬 LLM(Ollama) 을
동일한 함수 인터페이스로 사용할 수 있습니다.

  LLM_PROVIDER=claude    → Anthropic Claude
  LLM_PROVIDER=chatgpt   → OpenAI ChatGPT
  LLM_PROVIDER=gemini    → Google Gemini
  LLM_PROVIDER=local     → 로컬 LLM (Ollama)

로컬 LLM 사용 전 준비:
  1. Ollama 설치  : https://ollama.com/download
  2. 모델 다운로드: ollama pull llama3.1
  3. 서버 실행    : ollama serve
  4. .env 설정    : LLM_PROVIDER=local
============================================================
"""

import os
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")

PROVIDER = os.getenv("LLM_PROVIDER", "claude").lower()

# 세션 토큰 누적
_usage = {"input": 0, "output": 0, "calls": 0}

def get_usage() -> dict:
    """현재 세션의 누적 토큰 사용량을 반환합니다."""
    return dict(_usage)

def _track(input_tokens: int, output_tokens: int):
    _usage["input"] += input_tokens
    _usage["output"] += output_tokens
    _usage["calls"] += 1


# ============================================================
# 공통 인터페이스
# ============================================================

def chat(prompt: str, system: str = None, max_tokens: int = 1024) -> str:
    """
    단일 메시지를 보내고 텍스트 응답을 반환합니다.
    LLM_PROVIDER 설정에 따라 자동으로 모델이 선택됩니다.
    """
    if PROVIDER == "claude":
        return _claude_chat(prompt, system, max_tokens)
    elif PROVIDER == "chatgpt":
        return _openai_chat(prompt, system, max_tokens)
    elif PROVIDER == "gemini":
        return _gemini_chat(prompt, system, max_tokens)
    elif PROVIDER == "local":
        return _local_chat(prompt, system, max_tokens)
    else:
        raise ValueError(
            f"❌ 알 수 없는 LLM_PROVIDER: '{PROVIDER}'\n"
            "   claude / chatgpt / gemini / local 중 하나를 입력하세요."
        )


def multi_turn(history: list, new_message: str) -> tuple:
    """
    멀티턴 대화를 유지합니다.
    history 형식: [{"role": "user"|"assistant", "content": "..."}]
    반환값: (응답 텍스트, 업데이트된 history)
    """
    if PROVIDER == "claude":
        return _claude_multi_turn(history, new_message)
    elif PROVIDER == "chatgpt":
        return _openai_multi_turn(history, new_message)
    elif PROVIDER == "gemini":
        return _gemini_multi_turn(history, new_message)
    elif PROVIDER == "local":
        return _local_multi_turn(history, new_message)
    else:
        raise ValueError(f"❌ 알 수 없는 LLM_PROVIDER: '{PROVIDER}'")


def current_provider() -> str:
    """현재 설정된 LLM 프로바이더 이름을 반환합니다."""
    return PROVIDER


# ============================================================
# Claude (Anthropic)
# ============================================================

def _claude_chat(prompt, system, max_tokens):
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("❌ ANTHROPIC_API_KEY 가 비어있습니다. config/.env 를 확인하세요.")
    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    _track(msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text


def _claude_multi_turn(history, new_message):
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("❌ ANTHROPIC_API_KEY 가 비어있습니다.")
    client = anthropic.Anthropic(api_key=api_key)
    updated = history + [{"role": "user", "content": new_message}]
    msg = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=1024,
        messages=updated,
    )
    reply = msg.content[0].text
    _track(msg.usage.input_tokens, msg.usage.output_tokens)
    updated.append({"role": "assistant", "content": reply})
    return reply, updated


# ============================================================
# ChatGPT (OpenAI)
# ============================================================

def _openai_chat(prompt, system, max_tokens):
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("❌ OPENAI_API_KEY 가 비어있습니다. config/.env 를 확인하세요.")
    client = OpenAI(api_key=api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        max_tokens=max_tokens,
        messages=messages,
    )
    _track(resp.usage.prompt_tokens, resp.usage.completion_tokens)
    return resp.choices[0].message.content


def _openai_multi_turn(history, new_message):
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("❌ OPENAI_API_KEY 가 비어있습니다.")
    client = OpenAI(api_key=api_key)
    updated = history + [{"role": "user", "content": new_message}]
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        max_tokens=1024,
        messages=updated,
    )
    reply = resp.choices[0].message.content
    _track(resp.usage.prompt_tokens, resp.usage.completion_tokens)
    updated.append({"role": "assistant", "content": reply})
    return reply, updated


# ============================================================
# Gemini (Google)
# ============================================================

def _gemini_chat(prompt, system, max_tokens):
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("❌ GOOGLE_API_KEY 가 비어있습니다. config/.env 를 확인하세요.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=os.getenv("GEMINI_MODEL", "gemini-1.5-pro"),
        system_instruction=system or "",
    )
    resp = model.generate_content(prompt)
    try:
        _track(resp.usage_metadata.prompt_token_count, resp.usage_metadata.candidates_token_count)
    except Exception:
        pass
    return resp.text


def _gemini_multi_turn(history, new_message):
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("❌ GOOGLE_API_KEY 가 비어있습니다.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-pro"))
    gemini_history = [
        {"role": "user" if m["role"] == "user" else "model", "parts": [m["content"]]}
        for m in history
    ]
    chat_session = model.start_chat(history=gemini_history)
    reply = chat_session.send_message(new_message).text
    updated = history + [
        {"role": "user", "content": new_message},
        {"role": "assistant", "content": reply},
    ]
    return reply, updated


# ============================================================
# 로컬 LLM (Ollama)
# ============================================================

def _local_chat(prompt, system, max_tokens):
    """
    Ollama 로컬 LLM 을 사용합니다.
    사전 준비:
      1. Ollama 설치 : https://ollama.com/download
      2. 모델 다운로드: ollama pull llama3.1
      3. 서버 실행   : ollama serve
    """
    try:
        import ollama
    except ImportError:
        raise ImportError(
            "❌ ollama 패키지가 없습니다. 아래 명령으로 설치하세요:\n"
            "   pip install ollama"
        )

    model = os.getenv("LOCAL_MODEL", "llama3.1")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = ollama.chat(model=model, messages=messages)
        return resp["message"]["content"]
    except Exception as e:
        raise ConnectionError(
            f"❌ Ollama 연결 실패: {e}\n"
            "   'ollama serve' 가 실행 중인지 확인하세요.\n"
            f"   모델({model}) 설치 확인: ollama list"
        )


def _local_multi_turn(history, new_message):
    try:
        import ollama
    except ImportError:
        raise ImportError("❌ ollama 패키지가 없습니다. pip install ollama")

    model = os.getenv("LOCAL_MODEL", "llama3.1")
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": new_message})

    try:
        resp = ollama.chat(model=model, messages=messages)
        reply = resp["message"]["content"]
    except Exception as e:
        raise ConnectionError(
            f"❌ Ollama 연결 실패: {e}\n"
            "   'ollama serve' 를 실행하세요."
        )

    updated = history + [
        {"role": "user", "content": new_message},
        {"role": "assistant", "content": reply},
    ]
    return reply, updated


# ============================================================
# 연결 테스트
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print(f"통합 LLM 연결 테스트 — 현재 프로바이더: {PROVIDER.upper()}")
    print("=" * 50)
    try:
        resp = chat("안녕하세요! 연결 테스트입니다. 한 문장으로 인사해주세요.")
        print(f"✅ 연결 성공!\n응답: {resp}")
    except Exception as e:
        print(f"❌ 연결 실패: {e}")
