"""
============================================================
sheets.py
팀 라이브러리 에이전트 v2 - Google Sheets 연결 모듈
============================================================
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv(dotenv_path="config/.env")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_worksheet(worksheet_index: int = 0, service_account_path: str = "config/service_account.json"):
    creds = Credentials.from_service_account_file(service_account_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError("❌ GOOGLE_SHEET_ID 가 비어있습니다.")
    return gc.open_by_key(sheet_id).get_worksheet(worksheet_index)


def read_all(worksheet) -> list[list]:
    return worksheet.get_all_values()


def append_row(worksheet, row: list) -> None:
    worksheet.append_row(row)


if __name__ == "__main__":
    ws = get_worksheet()
    data = read_all(ws)
    print(f"✅ Sheets 연결 성공! {len(data)}행")
