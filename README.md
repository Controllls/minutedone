# 팀 라이브러리 에이전트 v2

Claude · ChatGPT · Gemini · 로컬 LLM(Ollama) | Notion | Google Sheets

---

## 빠른 시작

```bash
# 1. 패키지 설치
pip install -r requirements.txt

# 2. 환경변수 파일 생성
cp config/.env.template config/.env
# → config/.env 를 텍스트 편집기로 열어 LLM_PROVIDER 및 API 키 입력

# 3. 노트북 실행
jupyter notebook notebooks/setup_and_test.ipynb
```

## LLM 전환 방법

`config/.env` 파일에서 한 줄만 수정하면 됩니다.

| 값 | 설명 |
|---|---|
| `LLM_PROVIDER=claude` | Anthropic Claude (기본값) |
| `LLM_PROVIDER=chatgpt` | OpenAI ChatGPT |
| `LLM_PROVIDER=gemini` | Google Gemini |
| `LLM_PROVIDER=local` | 로컬 LLM (Ollama) |

로컬 LLM 사용 시 추가 준비:
1. [Ollama 설치](https://ollama.com/download)
2. `ollama pull llama3.1`
3. `ollama serve`

## 파일 구조

```
team-library-agent-v2/
├── config/
│   └── .env.template       ← 환경변수 설정 템플릿
├── scripts/
│   ├── llm.py              ← 통합 LLM 래퍼 (핵심)
│   ├── notion.py           ← Notion 연동
│   └── sheets.py           ← Google Sheets 연동
├── notebooks/
│   └── setup_and_test.ipynb ← 설치 테스트 노트북
├── output/                 ← 내보낸 파일 저장 위치
├── requirements.txt
├── README.md
└── team-library-agent-v2-guide.docx  ← 상세 설치 안내서
```

## 상세 안내

`team-library-agent-v2-guide.docx` 파일을 참고하세요.

> ⚠️ `config/.env` 와 `config/service_account.json` 은 절대 Git에 커밋하지 마세요.
