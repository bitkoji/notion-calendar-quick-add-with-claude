"""Parse natural-language events with Claude and add them to a Notion calendar (database).

Claude is called through the Claude Code CLI (`claude -p`), so no API key is needed;
it runs on your Claude Pro/Max subscription login (run `claude`, then /login).

자연어로 입력한 일정을 Claude로 해석해 Notion 캘린더(데이터베이스)에 추가합니다.
Claude 호출은 Claude Code CLI(`claude -p`)를 통해 이뤄지므로 API 키 없이
Claude Pro/Max 구독 로그인(`claude` 실행 후 /login)으로 동작합니다.

Usage / 사용법:
    py notion_cal.py "Team meeting tomorrow 3 PM for 1 hour"
    py notion_cal.py                  # interactive mode / 대화형 모드
    py notion_cal.py -y "..."         # add without confirming / 확인 없이 바로 추가
    py notion_cal.py --dry-run "..."  # show the parse only, no Notion changes / 해석 결과만 확인
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from messages import tr

# When launched by the Chrome extension (Native Messaging) the working directory may differ,
# so read the .env next to this script.
# 크롬 확장(Native Messaging)에서 실행될 때는 작업 폴더가 다를 수 있으므로 스크립트 옆의 .env를 읽는다
load_dotenv(Path(__file__).resolve().parent / ".env")

# Empty = Claude Code's default model (e.g. opus, sonnet)
# 비우면 Claude Code 기본 모델 사용 (예: opus, sonnet)
MODEL = os.getenv("CLAUDE_MODEL", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Seoul")
# First day of the week: sunday … saturday (default monday). Used for "this week" in the popup
# and for phrases like "this week" / "next week".
# 한 주의 시작: sunday … saturday (기본 monday). 팝업의 이번 주와 "이번 주"·"다음 주" 해석에 쓴다.
WEEK_START = os.getenv("WEEK_START", "") or "monday"
# Python weekday(): Monday = 0 … Sunday = 6
WEEK_START_DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "일정 제목 (간결하게)"},
                    "all_day": {"type": "boolean", "description": "시간 없이 하루 종일 일정이면 true"},
                    "start": {
                        "type": "string",
                        "description": "all_day면 YYYY-MM-DD, 아니면 YYYY-MM-DDTHH:MM:SS+HH:MM (타임존 오프셋 포함)",
                    },
                    "end": {
                        "type": "string",
                        "description": "종료 시각/날짜. 형식은 start와 동일. 알 수 없으면 빈 문자열",
                    },
                    "location": {
                        "type": "string",
                        "description": "사용자가 말한 장소를 그대로 (예: 'ML206', '강남역', '성수동 블루보틀'). 없으면 빈 문자열",
                    },
                    "description": {"type": "string", "description": "장소 외의 메모·준비물 등. 없으면 빈 문자열"},
                    "ampm_unclear": {
                        "type": "boolean",
                        "description": "1~12시 숫자만 있고 오전/오후를 알 수 없으면 true (사용자에게 다시 묻는다). 종일 일정이나 분명하면 false",
                    },
                    "missing": {
                        "type": "array",
                        "description": "사용자에게 물어볼, 말하지 않은 정보. 아래 규칙 참고. 없으면 빈 배열",
                        "items": {"type": "string", "enum": ["date", "time", "location"]},
                    },
                    "repeat": {
                        "type": "object",
                        "description": "반복 일정. start는 첫 번째 일정. 반복이 아니면 freq='none'",
                        "properties": {
                            "freq": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
                            "interval": {"type": "integer", "description": "몇 일/주/달마다 ('격주'=2). 기본 1"},
                            "count": {"type": "integer", "description": "모두 몇 번인지 ('4주 동안' 매주=4, '5번'=5). 모르면 0"},
                            "until": {"type": "string", "description": "마지막 날짜 YYYY-MM-DD ('12월까지'=12월 마지막 날). 모르면 빈 문자열"},
                        },
                        "required": ["freq", "interval", "count", "until"],
                        "additionalProperties": False,
                    },
                },
                "required": ["title", "all_day", "start", "end", "location", "description", "ampm_unclear", "missing", "repeat"],
                "additionalProperties": False,
            },
        },
        "cancellations": {
            "type": "array",
            "description": "취소(삭제)하려는 기존 일정을 찾기 위한 조건",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "일정 제목에서 찾을 핵심 단어 하나 (예: '치과', '팀 회의'). 그 기간 일정 전부면 빈 문자열",
                    },
                    "date_from": {"type": "string", "description": "검색 시작 날짜 YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "검색 끝 날짜 YYYY-MM-DD (하루면 date_from과 같게)"},
                    "time": {
                        "type": "string",
                        "description": "시각을 말했으면 그 일정의 시작 시각 HH:MM 24시간제 ('오전 1시 일정 삭제' → '01:00'). 아니면 빈 문자열",
                    },
                },
                "required": ["keyword", "date_from", "date_to", "time"],
                "additionalProperties": False,
            },
        },
        "moves": {
            "type": "array",
            "description": "기존 일정의 날짜·시간·제목·장소 변경. 새 시각은 프로그램이 원래 일정 기준으로 계산하므로 '변경 내용'만 적는다",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "옮길 일정 제목의 핵심 단어"},
                    "date_from": {"type": "string", "description": "옮길 일정의 현재 날짜 검색 시작 YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "옮길 일정의 현재 날짜 검색 끝 YYYY-MM-DD"},
                    "time": {
                        "type": "string",
                        "description": "옮길 일정의 현재 시작 시각을 말했으면 HH:MM 24시간제 ('3시 회의 4시로' → '15:00'). 아니면 빈 문자열",
                    },
                    "new_date": {"type": "string", "description": "옮길 날짜 YYYY-MM-DD ('목요일로' 처럼 날짜를 지정할 때). 아니면 빈 문자열"},
                    "new_time": {"type": "string", "description": "새 시작 시각 HH:MM ('3시로' 처럼 시각을 지정할 때). 아니면 빈 문자열"},
                    "shift_days": {"type": "integer", "description": "상대 이동 일수 ('다음날로'=1, '하루 당겨'=-1). 없으면 0"},
                    "shift_minutes": {"type": "integer", "description": "상대 이동 분 ('1시간 뒤로'=60, '30분 당겨'=-30). 없으면 0"},
                    "new_duration_minutes": {"type": "integer", "description": "소요 시간을 바꿀 때 새 길이(분). 유지하면 0"},
                    "new_title": {"type": "string", "description": "제목을 바꿀 때 새 제목. 유지하면 빈 문자열"},
                    "new_location": {"type": "string", "description": "장소를 바꿀 때 사용자가 쓴 새 장소 그대로. 유지하면 빈 문자열"},
                    "ampm_unclear": {
                        "type": "boolean",
                        "description": "new_time이 1~12시 숫자만 있고 오전/오후를 알 수 없으면 true. 아니면 false",
                    },
                },
                "required": [
                    "keyword", "date_from", "date_to", "time", "new_date", "new_time",
                    "shift_days", "shift_minutes", "new_duration_minutes", "new_title", "new_location", "ampm_unclear",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["events", "cancellations", "moves"],
    "additionalProperties": False,
}


WEEKDAYS = "월화수목금토일"


def describe_event(ev: dict) -> str:
    """One-line summary shown to Claude: '11/18(수) 15:00~16:00 팀 회의'

    Claude에게 보여줄 한 줄 요약
    """
    tz = ZoneInfo(TIMEZONE)
    this_year = datetime.now(tz).year
    # Add the year when it isn't this year, so Claude doesn't guess the wrong one
    # 올해가 아니면 연도를 붙인다 (Claude가 연도를 잘못 짐작하지 않도록)
    year = lambda d: "" if d.year == this_year else f"{d.year}/"  # noqa: E731
    if ev["all_day"]:
        d = date.fromisoformat(ev["start"][:10])
        when = f"{year(d)}{d.month}/{d.day}({WEEKDAYS[d.weekday()]}) 종일"
        if ev["end"]:
            e = date.fromisoformat(ev["end"][:10])
            when += f"~{year(e)}{e.month}/{e.day}"
    else:
        s = datetime.fromisoformat(ev["start"]).astimezone(tz)
        when = f"{year(s)}{s.month}/{s.day}({WEEKDAYS[s.weekday()]}) {s:%H:%M}"
        if ev["end"]:
            when += f"~{datetime.fromisoformat(ev['end']).astimezone(tz):%H:%M}"
    return f"{when} {ev['title']}"


def describe_created(created: str) -> str:
    """Notion's created_time (UTC) → '11/17 14:03' in the local timezone
    노션 created_time(UTC) → 로컬 타임존 '11/17 14:03'
    """
    dt = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(ZoneInfo(TIMEZONE))
    return f"{dt.month}/{dt.day} {dt:%H:%M}"


def week_range(day: date) -> tuple[date, date]:
    """First and last day of the week containing `day`, by WEEK_START.

    WEEK_START 기준으로 `day`가 속한 주의 첫날과 마지막 날.
    """
    first = day - timedelta(days=(day.weekday() - WEEK_START_DAYS.get(WEEK_START, 0)) % 7)
    return first, first + timedelta(days=6)


def system_prompt(existing: list[dict] | None = None) -> str:
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekdays = WEEKDAYS
    first, last = week_range(now.date())
    day = lambda d: f"{d.isoformat()}({weekdays[d.weekday()]})"  # noqa: E731
    context = ""
    if existing is not None:
        lines = "\n".join(
            f"- {describe_event(ev)}" + (f" [추가한 시각 {describe_created(ev['created'])}]" if ev.get("created") else "")
            for ev in existing
        ) or "- (없음)"
        context = (
            "\n캘린더에 이미 있는 일정(최근 1주 ~ 앞으로 60일, 그리고 최근에 추가한 일정):\n" + lines + "\n"
            "취소·변경 요청은 이 목록에서 사용자가 말한 일정을 골라, 그 일정의 실제 날짜로 date_from/date_to를 정하고 "
            "제목에 실제로 들어 있는 단어로 keyword를 쓴다.\n"
            "'방금 추가한', '아까 넣은', '마지막으로 추가한' 일정은 [추가한 시각]이 가장 늦은 일정이다 "
            "('방금 추가한 일정 2개'면 가장 늦은 2개). 일정마다 cancellations/moves 항목을 하나씩 만든다.\n"
        )
    return (
        "너는 사용자의 자연어 문장에서 캘린더 일정 추가·취소·변경 요청을 추출하는 도우미다.\n"
        f"현재 시각: {now.isoformat(timespec='minutes')} ({weekdays[now.weekday()]}요일), 타임존: {TIMEZONE}.\n"
        "규칙:\n"
        "- '내일', '다음 주 금요일', '모레 저녁' 같은 상대 표현은 현재 시각 기준으로 정확한 날짜로 바꾼다.\n"
        f"- 한 주는 {weekdays[first.weekday()]}요일에 시작한다. '이번 주'는 {day(first)} ~ {day(last)}, "
        "'다음 주'는 그다음 7일, '지난 주'(지난주)는 그 앞 7일이다.\n"
        "- 시간 언급이 없으면 all_day=true로 하고 날짜만 쓴다.\n"
        "- 너는 일정을 맡아 관리하는 비서다. 일정에 필요한데 사용자가 말하지 않은 정보는 missing에 넣어 사용자에게 묻는다:\n"
        "  · date: 날짜(요일·'내일' 같은 표현 포함)를 전혀 말하지 않았으면. 이때 start에는 오늘 날짜를 임시로 쓴다. 반복 일정은 넣지 않는다.\n"
        "  · time: 시각을 말하지 않았는데 시험·회의·약속·수업·진료·면접처럼 보통 정해진 시각이 있는 일정이면. "
        "여행·휴가·생일·기념일·마감·공휴일처럼 원래 하루 종일인 일정이면 넣지 않는다.\n"
        "  · location: 장소를 말하지 않았는데 약속·회의·진료·면접·모임·식사처럼 보통 가는 곳이 있는 일정이면. "
        "온라인·전화·개인 할 일·마감·생일·기념일이면 넣지 않는다.\n"
        "- '아침'=09:00, '점심'=12:00, '오후'만 있으면 14:00, '저녁'=19:00 정도로 합리적으로 추정한다.\n"
        "- '3시', '7시 반'처럼 1~12시 숫자만 있고 오전/오후·아침/점심/저녁·새벽/밤 같은 단서가 없으면 "
        "ampm_unclear=true로 하고, 시각은 더 그럴듯한 쪽으로 채운다 (사용자가 나중에 고른다). "
        "'15시'처럼 24시간제이거나 단서가 있으면 false.\n"
        "- 소요 시간이 언급되면 end를 계산하고, 없으면 시간 일정은 1시간으로 가정한다. 종일 일정의 end는 여러 날일 때만 쓴다.\n"
        "- 한 문장에 여러 일정이 있으면 모두 events에 담는다. 일정이 없으면 빈 배열을 반환한다.\n"
        "- 제목은 핵심만 짧게. 장소(강의실 번호·건물·가게·주소 등)는 사용자가 쓴 표현 그대로 location에, "
        "그 외 메모·준비물은 description에 넣는다. 장소를 제목에 중복해 넣지 않는다.\n"
        "- '매일', '매주 화요일', '격주', '매달 15일'처럼 반복하는 일정은 하나만 만들고 repeat에 적는다. start는 첫 번째 일정이다. "
        "'매주 화·목'처럼 요일이 여럿이면 요일마다 일정을 하나씩 만든다. 횟수·기간을 말하지 않으면 count=0, until=''로 둔다 "
        "(프로그램이 앞으로 3개월로 정한다). 반복이 아니면 freq='none', interval=1, count=0, until=''.\n"
        "취소 규칙:\n"
        "- '취소', '삭제', '지워', '빼줘', '안 가' 등 기존 일정을 없애려는 요청은 events가 아니라 cancellations에 담는다.\n"
        "- keyword는 제목에 들어 있을 법한 가장 짧은 핵심 단어 하나로 쓴다 (예: '내일 치과 예약 취소' → '치과').\n"
        "  '내일 일정 전부 취소'처럼 특정 일정이 아니면 빈 문자열.\n"
        "- 날짜가 언급되면 그 날짜(또는 기간)를, 없으면 date_from=오늘, date_to=오늘부터 1년 뒤로 한다.\n"
        "- 시각을 말하면('내일 오전 1시 일정 삭제', '3시 회의 옮겨') time에 그 일정의 시작 시각을 쓴다. "
        "프로그램이 그 시각에 시작하는 일정만 고른다.\n"
        "변경 규칙:\n"
        "- '옮겨', '미뤄', '당겨', '변경', '바꿔', '연기' 등 기존 일정의 날짜·시간·제목·장소를 바꾸는 요청은 moves에만 담는다. "
        "이때 cancellations와 events에는 아무것도 넣지 않는다.\n"
        "- 제목을 바꾸면 new_title에 새 제목, 장소를 바꾸면 new_location에 새 장소를 쓴다 "
        "('팀 회의 장소 2층 회의실로 바꿔' → new_location='2층 회의실'). 바꾸지 않는 것은 빈 문자열.\n"
        "  날짜·시간은 그대로 두는 변경이면 new_date·new_time은 빈 문자열, shift는 0으로 둔다.\n"
        "- 원래 일정 기준의 상대 변경('다음날로', '하루 뒤로', '1시간 뒤로', '30분 당겨')은 shift_days/shift_minutes로,\n"
        "  절대 지정('목요일로', '3시로', '금요일 오후 2시로')은 new_date/new_time으로 쓴다. 쓰지 않는 값은 0 또는 빈 문자열.\n"
        "- 새 시각을 직접 계산해 넣지 말 것. 프로그램이 원래 일정의 실제 시간에서 계산한다."
        + context
    )


def find_claude() -> str:
    path = shutil.which("claude")
    # A process started by Chrome may have a different PATH, so also check the default install location
    # 크롬이 실행한 프로세스는 PATH가 다를 수 있어 기본 설치 위치도 확인
    if not path:
        default = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
        path = str(default) if default.exists() else None
    if not path:
        raise RuntimeError(tr("claude.notFound"))
    return path


def parse_request(text: str, notion: "Notion | None" = None) -> dict:
    """Sentence → {"events": [to add], "cancellations": [delete conditions], "moves": [reschedule conditions]}

    If `notion` is given, upcoming events are shown to Claude so it can pick the right one.

    자연어 문장 → {"events": [추가], "cancellations": [취소 조건], "moves": [변경 조건]}
    notion이 주어지면 다가오는 일정 목록을 Claude에게 함께 보여줘 어떤 일정을 말하는지 정확히 고르게 한다.
    """
    existing = None
    if notion is not None:
        today = datetime.now(ZoneInfo(TIMEZONE)).date()
        existing = notion.find_events((today - timedelta(days=7)).isoformat(), (today + timedelta(days=60)).isoformat())[:100]
        # Also the most recently created events, whatever their date ("delete the one I just added")
        # 날짜와 관계없이 최근에 만든 일정도 함께 ("방금 추가한 일정 삭제")
        seen = {ev["id"] for ev in existing}
        existing += [ev for ev in notion.recently_created() if ev["id"] not in seen]
    out = ask_claude(system_prompt(existing), EVENT_SCHEMA, text)
    for ev in out["events"]:
        validate_event(ev)
        if ev["repeat"]["until"]:
            date.fromisoformat(ev["repeat"]["until"])
    out["events"] = expand_repeats(out["events"])
    for c in out["cancellations"] + out["moves"]:
        if c["time"]:
            datetime.strptime(c["time"], "%H:%M")
        date.fromisoformat(c["date_from"])
        date.fromisoformat(c["date_to"])
    for m in out["moves"]:
        if m["new_date"]:
            date.fromisoformat(m["new_date"])
        if m["new_time"]:
            datetime.strptime(m["new_time"], "%H:%M")
    return out


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "understood": {"type": "boolean", "description": "날짜·시각·장소 중 하나라도, 또는 '없음'·'종일'을 알아들었으면 true. 관계없는 말이면 false"},
        "date": {"type": "string", "description": "말한 날짜 YYYY-MM-DD. 말하지 않았으면 빈 문자열"},
        "all_day": {"type": "boolean", "description": "'종일', '하루 종일', '시간 없이'면 true"},
        "time": {"type": "string", "description": "말한 시작 시각 HH:MM 24시간제. 말하지 않았거나 all_day면 빈 문자열"},
        "duration_minutes": {"type": "integer", "description": "소요 시간(분). '3시부터 5시까지'=120, '2시간'=120. 말하지 않으면 60"},
        "location": {"type": "string", "description": "말한 장소 그대로. 말하지 않았거나 '없음'이면 빈 문자열"},
        "no_location": {"type": "boolean", "description": "장소가 없다·필요 없다·안 정해졌다고 했으면 true. 장소를 말하지 않았을 뿐이면 false"},
    },
    "required": ["understood", "date", "all_day", "time", "duration_minutes", "location", "no_location"],
    "additionalProperties": False,
}


def parse_answer(text: str, title: str = "", asked: list[str] | None = None) -> dict:
    """Read the user's answer to a question about an event (its date, time and/or place).
    Returns {"date": "YYYY-MM-DD" | "", "all_day": bool, "time": "HH:MM" | "", "duration_minutes": int,
    "location": str, "no_location": bool}; raises if the answer isn't about any of them.

    일정에 대해 물은 것(날짜·시간·장소)에 대한 사용자의 답을 읽는다.
    {"date", "all_day", "time", "duration_minutes", "location", "no_location"}을 돌려주고, 관계없는 말이면 오류를 낸다.
    """
    now = datetime.now(ZoneInfo(TIMEZONE))
    first, last = week_range(now.date())
    names = {"date": "날짜", "time": "시간", "location": "장소"}
    asked_text = ", ".join(names[a] for a in (asked or []) if a in names) or "날짜·시간·장소"
    system = (
        "너는 일정을 관리하는 비서다. 일정에 대해 사용자에게 물은 질문의 답을 읽는다.\n"
        f"일정 제목: {title or '(없음)'} / 물은 것: {asked_text}\n"
        f"현재 시각: {now.isoformat(timespec='minutes')} ({WEEKDAYS[now.weekday()]}요일), 타임존: {TIMEZONE}. "
        f"한 주는 {WEEKDAYS[first.weekday()]}요일에 시작하고 이번 주는 {first.isoformat()} ~ {last.isoformat()}.\n"
        "규칙:\n"
        "- 답에 들어 있는 것만 채운다. 말하지 않은 칸은 빈 문자열(길이는 60).\n"
        "- '내일', '다음 주 화요일' 같은 날짜는 현재 시각 기준 YYYY-MM-DD로 바꾼다.\n"
        "- '오후 3시'=15:00, '아침 9시'=09:00, '저녁 7시 반'=19:30. '3시'처럼 오전/오후가 없으면 "
        "일정 제목을 보고 더 그럴듯한 쪽으로 정한다 (시험·회의·수업·진료는 보통 낮 시간).\n"
        "- '3시부터 5시까지', '2시간'처럼 길이를 말하면 duration_minutes에.\n"
        "- '종일', '하루 종일'이면 all_day=true. 장소는 사용자가 쓴 표현 그대로.\n"
        "- '없음', '안 정해짐', '모름'도 알아들은 답이다 (understood=true, 그 칸은 비움). 장소에 대해 그렇게 말했으면 no_location=true.\n"
        "- 일정과 관계없는 말이면 understood=false."
    )
    out = ask_claude(system, ANSWER_SCHEMA, text)
    if not out["understood"]:
        raise RuntimeError(tr("answer.notUnderstood"))
    if out["date"]:
        date.fromisoformat(out["date"])
    if out["all_day"]:
        out["time"] = ""
    elif out["time"]:
        datetime.strptime(out["time"], "%H:%M")
    minutes = out["duration_minutes"]
    return {
        "date": out["date"],
        "all_day": bool(out["all_day"]),
        "time": out["time"],
        "duration_minutes": minutes if 0 < minutes <= 24 * 60 else 60,
        "location": out["location"].strip()[:2000],
        "no_location": bool(out["no_location"]) and not out["location"].strip(),
    }


def apply_answer(ev: dict, ans: dict, own: bool = True) -> None:
    """Apply a parse_answer() result to an event to add, and update its "missing" list.
    The date is only applied to the event itself (own), not to other occurrences of a repeating event.
    Each question stays until it's answered, so answering only the time still leaves the date/place
    to ask; the place question also ends when the user says there's none.

    parse_answer() 결과를 추가할 일정에 적용하고 "missing"을 고친다.
    날짜는 그 일정에만(own) 적용하고 반복 일정의 다른 일정에는 적용하지 않는다.
    질문은 답할 때까지 남는다: 시간만 답하면 날짜·장소는 계속 묻는다. 장소는 "없음"이라고 해도 끝난다.
    """
    missing = list(ev.get("missing", []))
    tz = ZoneInfo(TIMEZONE)
    if own and ans["date"]:
        old = local_date(ev["start"])
        shift = date.fromisoformat(ans["date"]) - old
        if ev["all_day"]:
            ev["start"] = ans["date"]
            ev["end"] = (date.fromisoformat(ev["end"][:10]) + shift).isoformat() if ev["end"] else ""
        else:
            # Same wall-clock time on the new day / 새 날짜의 같은 시각
            st = datetime.fromisoformat(ev["start"]).astimezone(tz)
            new_st = datetime(*(local_date(ev["start"]) + shift).timetuple()[:3], st.hour, st.minute, tzinfo=tz)
            length = datetime.fromisoformat(ev["end"]) - datetime.fromisoformat(ev["start"]) if ev["end"] else None
            ev["start"] = new_st.isoformat()
            ev["end"] = (new_st + length).isoformat() if length else ""
        missing = [m for m in missing if m != "date"]
    day = local_date(ev["start"]).isoformat()
    if ans["all_day"]:
        ev.update(all_day=True, start=day, end="")
        missing = [m for m in missing if m != "time"]
    elif ans["time"]:
        ev.update(time_on(day, ans))
        ev["ampm_unclear"] = False
        missing = [m for m in missing if m != "time"]
    if ans["location"]:
        ev["location"] = ans["location"]
    if ans["location"] or ans.get("no_location"):
        missing = [m for m in missing if m != "location"]
    ev["missing"] = missing


def ask_claude(system: str, schema: dict, text: str) -> dict:
    """Run `claude -p` with a system prompt and a JSON schema, and return the structured output.

    시스템 프롬프트와 JSON 스키마로 `claude -p`를 실행해 구조화된 결과를 돌려준다.
    """
    cmd = [
        find_claude(), "-p",
        "--system-prompt", system,
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--output-format", "json",
        # Text parsing only, no file/command tools
        # 파일/명령 도구 없이 텍스트 해석만
        "--tools", "",
        # Don't load MCP servers
        # MCP 서버 로드 안 함
        "--strict-mcp-config",
        # Don't load user/project settings or hooks
        # 사용자/프로젝트 설정·hook 로드 안 함
        "--setting-sources", "",
        "--no-session-persistence",
        "--effort", "low",
    ]
    if MODEL:
        cmd += ["--model", MODEL]

    env = os.environ.copy()
    # Remove the API key: if present, usage is billed to the API instead of the subscription
    # API 키가 있으면 구독 대신 API로 과금되므로 제거
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        proc = subprocess.run(
            cmd, input=text, capture_output=True, text=True, encoding="utf-8",
            env=env, cwd=tempfile.gettempdir(), timeout=180,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(tr("claude.timeout"))

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout).strip()[:500]
        raise RuntimeError(tr("claude.runFailed", detail=detail or tr("unknown")))

    if result.get("is_error") or result.get("structured_output") is None:
        msg = str(result.get("result") or result.get("subtype") or tr("unknown"))
        if "login" in msg.lower() or result.get("api_error_status") == 401:
            msg += "\n→ " + tr("claude.loginHint")
        raise RuntimeError(tr("claude.error", detail=msg))
    return result["structured_output"]


def validate_event(ev: dict) -> None:
    """Check that the date strings from Claude are in a format Notion accepts.

    Claude가 준 날짜 문자열이 Notion이 받을 수 있는 형식인지 확인한다.
    """
    for key in ("start", "end"):
        value = ev[key]
        if not value:
            continue
        if ev["all_day"]:
            date.fromisoformat(value)
        else:
            dt = datetime.fromisoformat(value)
            # If the offset is missing, attach the configured timezone
            # 오프셋이 빠졌으면 설정된 타임존을 붙인다
            if dt.tzinfo is None:
                ev[key] = dt.replace(tzinfo=ZoneInfo(TIMEZONE)).isoformat()


# Repeating events: at most this many from one event, and 3 months when no end is given
# 반복 일정: 일정 하나에서 최대 이만큼, 끝을 말하지 않으면 3개월
MAX_REPEAT = 60
DEFAULT_REPEAT_MONTHS = 3


def _add_months(d: date, n: int) -> date | None:
    """The same day n months later, or None if that month has no such day (e.g. the 31st).

    n달 뒤의 같은 날. 그 달에 그날이 없으면(예: 31일) None.
    """
    y, m = divmod(d.month - 1 + n, 12)
    try:
        return d.replace(year=d.year + y, month=m + 1)
    except ValueError:
        return None


def expand_repeats(events: list[dict]) -> list[dict]:
    """Turn each repeating event into its occurrences (Notion's API has no repeating events).
    Times keep the local wall clock, so a daylight saving change doesn't shift them.
    Occurrences of one event share "series" (its index) and carry "series_n"/"series_total".

    반복 일정을 하나하나의 일정으로 펼친다 (노션 API에는 반복 일정이 없다).
    시각은 로컬 벽시계 기준이라 서머타임이 바뀌어도 밀리지 않는다.
    같은 반복에서 나온 일정은 "series"(원래 순서)가 같고 "series_n"/"series_total"이 붙는다.
    """
    tz = ZoneInfo(TIMEZONE)
    out: list[dict] = []
    for index, ev in enumerate(events):
        rep = ev.pop("repeat", None) or {}
        freq = rep.get("freq", "none")
        if freq not in ("daily", "weekly", "monthly"):
            out.append(ev)
            continue
        interval = max(1, int(rep.get("interval") or 1))
        count = max(0, int(rep.get("count") or 0))
        first_day = local_date(ev["start"])
        until = date.fromisoformat(rep["until"]) if rep.get("until") else None
        if not count and not until:
            until = _add_months(first_day, DEFAULT_REPEAT_MONTHS) or first_day + timedelta(days=91)
        if ev["all_day"]:
            length = date.fromisoformat(ev["end"][:10]) - first_day if ev["end"] else None
            st_local = None
        else:
            st_local = datetime.fromisoformat(ev["start"]).astimezone(tz)
            length = datetime.fromisoformat(ev["end"]) - datetime.fromisoformat(ev["start"]) if ev["end"] else None

        days: list[date] = []
        step = 0
        limit = min(count or MAX_REPEAT, MAX_REPEAT)
        # Monthly dates that don't exist (the 31st) are skipped / 없는 날(31일)은 건너뛴다
        while len(days) < limit and step < MAX_REPEAT * 2:
            if freq == "monthly":
                d = _add_months(first_day, step * interval)
            else:
                d = first_day + timedelta(days=step * interval * (7 if freq == "weekly" else 1))
            step += 1
            if d is None:
                continue
            # The first one is always kept, even if Claude gave an end before it
            # 첫 번째 일정은 Claude가 그보다 앞선 끝 날짜를 줘도 남긴다
            if until and d > until and days:
                break
            days.append(d)

        for n, d in enumerate(days, 1):
            if st_local is None:
                start = d.isoformat()
                end = (d + length).isoformat() if length else ""
            else:
                s = datetime(d.year, d.month, d.day, st_local.hour, st_local.minute, tzinfo=tz)
                start = s.isoformat()
                end = (s + length).isoformat() if length else ""
            item = {**ev, "start": start, "end": end}
            if len(days) > 1:
                item.update(series=index, series_n=n, series_total=len(days))
            out.append(item)
    return out


class PageNotFound(RuntimeError):
    """The page doesn't exist (permanently deleted) or isn't shared with this connection.

    페이지가 없거나(완전히 삭제됨) 이 연결에 공유되지 않았다.
    """


class Notion:
    def __init__(self, token: str, database_id: str):
        self.database_id = database_id.replace("-", "")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self.title_prop, self.date_prop, self.desc_prop, self.location_prop = self._detect_properties()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        # Notion allows about 3 requests a second; adding a repeating event can send dozens,
        # so wait and retry when it answers 429 (rate limited).
        # 노션은 초당 약 3번까지 허용한다. 반복 일정은 수십 번 보낼 수 있으니 429(한도 초과)면 기다렸다 다시 보낸다.
        for attempt in range(5):
            try:
                r = self.session.request(method, f"{NOTION_API}{path}", timeout=30, **kwargs)
            except requests.RequestException:
                raise RuntimeError(tr("notion.network"))
            if r.status_code != 429 or attempt == 4:
                break
            try:
                wait = float(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 0
            time.sleep(min(max(wait, 2 ** attempt * 0.5), 10))
        if r.status_code == 401:
            raise RuntimeError(tr("notion.badToken"))
        if r.status_code == 404 and path.startswith("/databases/"):
            raise RuntimeError(tr("notion.dbNotFound"))
        if r.status_code == 404 and path.startswith("/pages/"):
            raise PageNotFound(tr("notion.pageNotFound"))
        if not r.ok:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise RuntimeError(tr("notion.apiError", status=r.status_code, detail=msg))
        return r.json()

    def _detect_properties(self) -> tuple[str, str, str | None, str | None]:
        """Find the title/date/description/location property names (can be set in .env).

        데이터베이스 속성 중 제목/날짜/메모/장소 속성 이름을 찾는다 (.env로 지정 가능).
        """
        props = self._request("GET", f"/databases/{self.database_id}")["properties"]
        by_type: dict[str, list[str]] = {}
        for name, p in props.items():
            by_type.setdefault(p["type"], []).append(name)

        title = os.getenv("NOTION_TITLE_PROPERTY") or by_type.get("title", [None])[0]
        date_prop = os.getenv("NOTION_DATE_PROPERTY") or (by_type.get("date") or [None])[0]
        desc = os.getenv("NOTION_DESCRIPTION_PROPERTY") or None
        texts = by_type.get("rich_text", [])
        location = os.getenv("NOTION_LOCATION_PROPERTY") or next(
            (n for n in ("장소", "Location", "위치", "location") if n in texts), None
        )

        if not title:
            raise RuntimeError(tr("db.noTitle"))
        if not date_prop or date_prop not in props:
            raise RuntimeError(tr("db.noDate"))
        if desc and props.get(desc, {}).get("type") != "rich_text":
            raise RuntimeError(tr("db.notText", name=desc))
        if location and props.get(location, {}).get("type") != "rich_text":
            raise RuntimeError(tr("db.notText", name=location))
        return title, date_prop, desc, location

    def add_event(self, ev: dict) -> dict:
        """Create the event page and return {"id", "url"}.

        일정 페이지를 만들고 {"id", "url"}을 돌려준다.
        """
        date_value = {"start": ev["start"]}
        if ev["end"]:
            date_value["end"] = ev["end"]
        properties = {
            self.title_prop: {"title": [{"text": {"content": ev["title"]}}]},
            self.date_prop: {"date": date_value},
        }
        body: dict = {"parent": {"database_id": self.database_id}, "properties": properties}
        description = ev.get("description", "")
        if ev.get("location") and self.location_prop:
            properties[self.location_prop] = {"rich_text": [{"text": {"content": ev["location"][:2000]}}]}
        # No location property: keep the location in the description
        # 장소 속성이 없으면 메모에 남긴다
        elif ev.get("location"):
            description = f"장소: {ev['location']}" + (f"\n{description}" if description else "")
        if description:
            rich = [{"text": {"content": description[:2000]}}]
            if self.desc_prop:
                properties[self.desc_prop] = {"rich_text": rich}
            # No description property: write it in the page body
            # 메모 속성이 없으면 페이지 본문에 적는다
            else:
                body["children"] = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich}}
                ]
        page = self._request("POST", "/pages", json=body)
        return {"id": page["id"], "url": page["url"]}

    def find_events(self, date_from: str, date_to: str) -> list[dict]:
        """Fetch events whose start date (in the local timezone) is between date_from and date_to.

        시작 날짜(로컬 타임존 기준)가 date_from~date_to 사이인 일정을 가져온다.
        """
        d_from, d_to = date.fromisoformat(date_from), date.fromisoformat(date_to)
        # Query one extra day on each side so timezone differences don't drop edge events,
        # then filter again by local date.
        # 타임존 차이로 경계 일정이 빠지지 않게 하루씩 넓혀 조회한 뒤 로컬 날짜로 다시 거른다
        body: dict = {
            "filter": {
                "and": [
                    {"property": self.date_prop, "date": {"on_or_after": (d_from - timedelta(days=1)).isoformat()}},
                    {"property": self.date_prop, "date": {"on_or_before": (d_to + timedelta(days=1)).isoformat()}},
                ]
            },
            "sorts": [{"property": self.date_prop, "direction": "ascending"}],
            "page_size": 100,
        }
        found = []
        while True:
            data = self._request("POST", f"/databases/{self.database_id}/query", json=body)
            for page in data["results"]:
                ev = self._page_to_event(page)
                if ev and d_from <= local_date(ev["start"]) <= d_to:
                    found.append(ev)
            if not data.get("has_more"):
                return found
            body["start_cursor"] = data["next_cursor"]

    def _page_to_event(self, page: dict) -> dict | None:
        props = page["properties"]
        dv = (props.get(self.date_prop) or {}).get("date")
        if not dv or not dv.get("start"):
            return None
        title = "".join(t.get("plain_text", "") for t in props[self.title_prop]["title"])
        return {
            "id": page["id"],
            "url": page["url"],
            "title": title or "(제목 없음)",
            "all_day": "T" not in dv["start"],
            "start": dv["start"],
            "end": dv.get("end") or "",
            "location": self._text(props, self.location_prop),
            "description": "",
            "created": page.get("created_time", ""),
        }

    def recently_created(self, limit: int = 10) -> list[dict]:
        """The most recently created events (newest first), whatever their date.

        날짜와 관계없이 가장 최근에 만든 일정 (최신순).
        """
        body = {
            "filter": {"property": self.date_prop, "date": {"is_not_empty": True}},
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            "page_size": limit,
        }
        data = self._request("POST", f"/databases/{self.database_id}/query", json=body)
        return [ev for ev in map(self._page_to_event, data["results"]) if ev]

    @staticmethod
    def _text(props: dict, name: str | None) -> str:
        if not name or name not in props:
            return ""
        return "".join(t.get("plain_text", "") for t in props[name].get("rich_text", []))

    def delete_event(self, page_id: str) -> None:
        """Move the page to the trash (restorable from Notion's trash for 30 days).

        페이지를 휴지통으로 보낸다 (Notion 휴지통에서 30일간 복구 가능).
        """
        self._request("PATCH", f"/pages/{page_id}", json={"archived": True})

    def restore_event(self, page_id: str) -> str | None:
        """Take a deleted page out of the trash and return its URL.
        Returns None if it's gone (emptied from the trash, or more than 30 days have passed).
        Only pages in the configured database are restored.

        휴지통에 있는 페이지를 되살리고 URL을 돌려준다.
        이미 완전히 삭제됐으면(휴지통 비움·30일 경과) None을 돌려준다.
        설정한 데이터베이스의 페이지만 되살린다.
        """
        try:
            page = self._request("GET", f"/pages/{page_id}")
        except PageNotFound:
            return None
        parent = (page.get("parent") or {}).get("database_id", "").replace("-", "")
        if parent != self.database_id:
            raise RuntimeError(tr("notion.notOurPage"))
        if page.get("archived") or page.get("in_trash"):
            page = self._request("PATCH", f"/pages/{page_id}", json={"archived": False})
        return page["url"]

    def update_event(self, page_id: str, start: str, end: str, title: str = "", location: str = "") -> str:
        """Change the page's date, and its title/location when given (the page content stays as it is).

        기존 페이지의 날짜와, 주어지면 제목·장소를 바꾼다 (페이지 내용은 그대로).
        """
        properties: dict = {self.date_prop: {"date": {"start": start, "end": end or None}}}
        if title:
            properties[self.title_prop] = {"title": [{"text": {"content": title[:2000]}}]}
        if location:
            if not self.location_prop:
                raise RuntimeError(tr("db.noLocation"))
            properties[self.location_prop] = {"rich_text": [{"text": {"content": location[:2000]}}]}
        page = self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})
        return page["url"]


def local_date(value: str) -> date:
    if "T" not in value:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(TIMEZONE))
    return dt.astimezone(ZoneInfo(TIMEZONE)).date()


def _norm(s: str) -> str:
    return "".join(s.split()).lower()


def starts_at(ev: dict, hhmm: str) -> bool:
    """True if no time is given, or the event starts at HH:MM in the local timezone.
    All-day events never match a time.

    시각이 없으면 True, 있으면 로컬 타임존 기준 그 시각에 시작하는 일정인지.
    종일 일정은 시각과 맞지 않는다.
    """
    if not hhmm:
        return True
    if ev["all_day"]:
        return False
    st = datetime.fromisoformat(ev["start"])
    if st.tzinfo is None:
        st = st.replace(tzinfo=ZoneInfo(TIMEZONE))
    return f"{st.astimezone(ZoneInfo(TIMEZONE)):%H:%M}" == hhmm


def same_start(a: dict, b: dict) -> bool:
    """Same start: the same date for all-day events, the same moment for timed ones.

    시작이 같은지: 종일 일정은 같은 날짜, 시간 일정은 같은 시각.
    """
    if a["all_day"] or b["all_day"]:
        return a["all_day"] == b["all_day"] and a["start"][:10] == b["start"][:10]
    return datetime.fromisoformat(a["start"]) == datetime.fromisoformat(b["start"])


def attach_nearby(notion: Notion, events: list[dict]) -> list[dict]:
    """Add "nearby" to each event: existing events starting from the day before through its last day
    (the day before catches events running past midnight). Duplicates and overlaps are decided
    from these by start/end, so the popup can re-check them after AM/PM is picked.

    추가할 일정마다 "nearby"를 붙인다: 전날부터 그 일정의 마지막 날까지 시작하는 기존 일정
    (전날은 자정을 넘기는 일정 때문). 중복·겹침은 이것과 시작/종료로 판단하므로,
    팝업이 오전/오후를 고른 뒤 다시 확인할 수 있다.
    """
    if not events:
        return events
    spans = [(local_date(ev["start"]) - timedelta(days=1), local_date(ev["end"] or ev["start"])) for ev in events]
    found = notion.find_events(min(f for f, _ in spans).isoformat(), max(t for _, t in spans).isoformat())
    for ev, (first, last) in zip(events, spans):
        ev["nearby"] = [
            {"title": x["title"], "start": x["start"], "end": x["end"], "all_day": x["all_day"]}
            for x in found
            if first <= local_date(x["start"]) <= last
        ]
    return events


def is_duplicate(ev: dict) -> bool:
    """An existing event has the same title and the same start / 같은 제목, 같은 시작의 기존 일정이 있다"""
    key = _norm(ev["title"])
    return any(_norm(x["title"]) == key and same_start(x, ev) for x in ev.get("nearby", []))


def _span(ev: dict) -> tuple[datetime, datetime]:
    """Start/end of a timed event; with no end it's taken as 1 hour / 시간 일정의 시작·끝 (끝이 없으면 1시간)"""
    st = datetime.fromisoformat(ev["start"])
    return st, datetime.fromisoformat(ev["end"]) if ev["end"] else st + timedelta(hours=1)


def overlapping(ev: dict) -> list[dict]:
    """Existing timed events whose time overlaps this timed event (duplicates excluded).
    All-day events are left out: they'd overlap everything that day.

    이 시간 일정과 시간이 겹치는 기존 시간 일정 (중복은 제외).
    종일 일정은 그날 모든 일정과 겹치므로 뺀다.
    """
    if ev["all_day"]:
        return []
    s, e = _span(ev)
    key = _norm(ev["title"])
    out = []
    for x in ev.get("nearby", []):
        if x["all_day"] or (_norm(x["title"]) == key and same_start(x, ev)):
            continue
        xs, xe = _span(x)
        if xs < e and s < xe:
            out.append(x)
    return out


def overlap_label(x: dict, ev: dict) -> str:
    """"'팀 회의'(15:00 ~ 16:00)": the name with its local time; the date is added when it starts on another day.

    이름과 로컬 시간. 다른 날 시작하면 날짜도 붙인다.
    """
    tz = ZoneInfo(TIMEZONE)
    s = datetime.fromisoformat(x["start"]).astimezone(tz)
    other_day = s.date() != local_date(ev["start"])
    time = (f"{s.month}/{s.day} " if other_day else "") + f"{s:%H:%M}"
    if x["end"]:
        time += f" ~ {datetime.fromisoformat(x['end']).astimezone(tz):%H:%M}"
    return f"'{x['title']}'({time})"


def resolve_cancellations(notion: Notion, cancellations: list[dict]) -> list[dict]:
    """Find candidate events in Notion for each cancellation condition.

    Returns: [{"keyword", "date_from", "date_to", "time", "exact": bool, "matches": [event + "selected"]}]
    If nothing matches the keyword, all events in that range are returned unselected (exact=False).

    취소 조건마다 Notion에서 후보 일정을 찾는다.
    키워드와 맞는 일정이 없으면 같은 기간의 모든 일정을 선택 해제 상태로 보여준다(exact=False).
    """
    resolved = []
    for c in cancellations:
        in_range = notion.find_events(c["date_from"], c["date_to"])
        kw = _norm(c["keyword"])
        hits = [ev for ev in in_range if kw in _norm(ev["title"]) and starts_at(ev, c.get("time", ""))]
        exact = bool(hits)
        matches = hits if exact else in_range
        for ev in matches:
            ev["selected"] = exact
        resolved.append({**c, "exact": exact, "matches": matches})
    return resolved


def compute_move(ev: dict, mv: dict) -> dict:
    """Compute the new start/end by applying the change (mv) to the original event (ev). Keeps the duration.

    원래 일정(ev)에 변경 내용(mv)을 적용한 새 시작/종료를 계산한다. 소요 시간은 유지.
    """
    tz = ZoneInfo(TIMEZONE)
    shift = timedelta(days=mv["shift_days"], minutes=mv["shift_minutes"])

    if ev["all_day"] and not mv["new_time"]:
        s = date.fromisoformat(ev["start"][:10])
        new_s = date.fromisoformat(mv["new_date"]) if mv["new_date"] else s
        new_s += timedelta(days=mv["shift_days"])
        e = ev["end"] and date.fromisoformat(ev["end"][:10])
        return {"all_day": True, "start": new_s.isoformat(), "end": (e + (new_s - s)).isoformat() if e else ""}

    # A time was given for an all-day event → make it a timed event (1 hour by default)
    # 종일 일정에 시각을 지정 → 시간 일정으로 변경 (기본 1시간)
    if ev["all_day"]:
        d = date.fromisoformat(ev["start"][:10])
        st = datetime(d.year, d.month, d.day, tzinfo=tz)
        duration = timedelta(hours=1)
    else:
        st = datetime.fromisoformat(ev["start"]).astimezone(tz)
        duration = datetime.fromisoformat(ev["end"]).astimezone(tz) - st if ev["end"] else None

    if mv["new_date"]:
        d = date.fromisoformat(mv["new_date"])
        st = st.replace(year=d.year, month=d.month, day=d.day)
    if mv["new_time"]:
        h, m = map(int, mv["new_time"].split(":"))
        st = st.replace(hour=h, minute=m, second=0, microsecond=0)
    st += shift
    if mv["new_duration_minutes"] > 0:
        duration = timedelta(minutes=mv["new_duration_minutes"])
    end = (st + duration).isoformat() if duration else ""
    return {"all_day": False, "start": st.isoformat(), "end": end}


def resolve_moves(notion: Notion, moves: list[dict]) -> list[dict]:
    """Find the original event for each change condition and compute its new time.

    Returns: [{..condition, "exact", "matches": [event + "selected" + "new": {all_day, start, end, title, location}]}]

    변경 조건마다 원래 일정을 찾아 새 시간을 계산한다 (새 제목·장소도 함께).
    """
    resolved = []
    for mv in resolve_cancellations(notion, moves):
        for ev in mv["matches"]:
            ev["new"] = compute_move(ev, mv)
            # New title/location, or empty to keep / 새 제목·장소, 비어 있으면 그대로
            ev["new"]["title"] = mv.get("new_title", "").strip()
            ev["new"]["location"] = mv.get("new_location", "").strip()
            # Caught here, not halfway through applying / 반영 도중이 아니라 여기서 알린다
            if ev["new"]["location"] and not notion.location_prop:
                raise RuntimeError(tr("db.noLocation"))
            ev["ampm_unclear"] = bool(mv.get("ampm_unclear")) and not ev["new"]["all_day"]
        resolved.append(mv)
    return resolved


def moved_event(ev: dict) -> dict:
    """The event as it will be after the change (an empty new title/location keeps the old one).

    변경한 뒤의 일정 (새 제목·장소가 비어 있으면 원래 값).
    """
    new = ev["new"]
    return {**ev, "all_day": new["all_day"], "start": new["start"], "end": new["end"],
            "title": new.get("title") or ev["title"], "location": new.get("location") or ev.get("location", "")}


def set_ampm(ev: dict, pm: bool) -> dict:
    """Move a timed event to the AM or PM version of its start hour, keeping the duration.
    Returns {"start", "end"}.

    시간 일정을 시작 시각의 오전 또는 오후 쪽으로 옮긴다 (길이 유지). {"start", "end"}를 돌려준다.
    """
    st = datetime.fromisoformat(ev["start"])
    delta = timedelta(hours=st.hour % 12 + (12 if pm else 0) - st.hour)
    end = (datetime.fromisoformat(ev["end"]) + delta).isoformat() if ev["end"] else ""
    return {"start": (st + delta).isoformat(), "end": end}


def time_on(day: str, when: dict) -> dict:
    """{"all_day", "start", "end"} on `day` (YYYY-MM-DD) for a timed parse_answer() result.

    parse_answer() 결과(시각)를 `day`(YYYY-MM-DD)에 적용한 {"all_day", "start", "end"}.
    """
    st = datetime.fromisoformat(f"{day}T{when['time']}:00").replace(tzinfo=ZoneInfo(TIMEZONE))
    return {"all_day": False, "start": st.isoformat(), "end": (st + timedelta(minutes=when["duration_minutes"])).isoformat()}


def question(missing: list[str]) -> str:
    """The question for what's missing: '언제 할까요?', '어디서 할까요?', '언제, 어디서 할까요?' …

    빠진 것에 맞춘 질문.
    """
    when = "언제" if "date" in missing else "몇 시에" if "time" in missing else ""
    where = "어디서" if "location" in missing else ""
    return ", ".join(x for x in (when, where) if x) + " 할까요?"


def ask_missing(ev: dict) -> dict | None:
    """Ask on the command line, in plain language, for what an event is missing (date, time, place).
    Returns a parse_answer() result, or None if left empty (keep it as it is).

    일정에 빠진 것(날짜·시간·장소)을 명령줄에서 자연어로 묻는다.
    parse_answer() 결과를 돌려주고, 비우면 None(그대로 둠).
    """
    while True:
        answer = input(f"   💬 '{ev['title']}' {question(ev['missing'])} (예: 다음 주 화요일 오후 3시, 강남역 · 장소가 없으면 '없음' · 비우면 그대로) ").strip()
        if not answer:
            return None
        try:
            return parse_answer(answer, ev["title"], ev["missing"])
        except (RuntimeError, ValueError) as e:
            print(f"   ❓ {e}")


def ask_ampm(ev: dict) -> dict:
    """Ask on the command line whether an unclear time is AM or PM. Returns {"start", "end"}.

    명령줄에서 오전/오후를 묻는다. {"start", "end"}를 돌려준다.
    """
    am, pm = set_ampm(ev, False), set_ampm(ev, True)
    def label(v: dict) -> str:
        st = datetime.fromisoformat(v["start"])
        return f"{st.hour % 12 or 12}:{st:%M}"

    while True:
        answer = input(f"   ⏰ '{ev['title']}' 오전인가요, 오후인가요? [1] 오전 {label(am)}  [2] 오후 {label(pm)} ").strip()
        if answer in ("1", "오전", "am", "AM"):
            return am
        if answer in ("2", "오후", "pm", "PM"):
            return pm


def format_event(ev: dict) -> str:
    def fmt(v: str) -> str:
        if ev["all_day"]:
            return v
        return datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M")

    when = fmt(ev["start"]) + (f" ~ {fmt(ev['end'])}" if ev["end"] else "")
    missing = ev.get("missing", [])
    if "date" in missing:
        # The date is a placeholder until answered / 답하기 전 날짜는 임시 값
        time = "시간 미정" if "time" in missing else "종일" if ev["all_day"] else when.split(" ", 1)[1].replace(fmt(ev["start"])[:11], "")
        when = f"날짜 미정 · {time}"
    elif "time" in missing:
        when = f"{ev['start'][:10]} · 시간 미정"
    elif ev["all_day"]:
        when += " (종일)"
    line = f"  • {ev['title']}  |  {when}"
    if ev.get("series_total"):
        line += f"  (반복 {ev['series_n']}/{ev['series_total']})"
    if ev.get("location"):
        line += f"\n      📍 {ev['location']}"
    if ev["description"]:
        line += f"\n      메모: {ev['description']}"
    return line


def handle(text: str, notion: Notion | None, assume_yes: bool) -> None:
    print("⏳ 요청 해석 중...")
    req = parse_request(text, notion)
    events, cancellations, moves = req["events"], req["cancellations"], req["moves"]
    if not events and not cancellations and not moves:
        print("❓ 일정을 찾지 못했습니다. 날짜와 할 일을 함께 적어 주세요.")
        return

    if events:
        print(f"\n📅 추가할 일정 {len(events)}개:")
        # AM/PM is asked once per repeating event and used for all its occurrences
        # 반복 일정은 오전/오후를 한 번만 묻고 모든 일정에 쓴다
        picked: dict[int, bool] = {}
        # What an event is missing (date, time, place) is also asked once per repeating event
        # 일정에 빠진 것(날짜·시간·장소)도 반복 일정이면 한 번만 묻는다
        answers: dict[int, dict | None] = {}
        for ev in events:
            print(format_event(ev))
            if ev.get("missing") and not assume_yes:
                series = ev.get("series")
                if series is not None and series in answers:
                    ans = answers[series]
                    if ans:
                        apply_answer(ev, ans, own=False)
                else:
                    # Keep asking while the date or time is still unknown / 날짜·시간을 아직 모르면 다시 묻는다
                    ans = None
                    while ev["missing"]:
                        got = ask_missing(ev)
                        if not got:
                            break
                        apply_answer(ev, got)
                        ans = got
                    if series is not None:
                        answers[series] = ans
                if ans:
                    print("   →" + format_event(ev).strip().lstrip("•"))
            if ev.get("ampm_unclear") and not ev["all_day"] and not assume_yes:
                series = ev.get("series")
                if series is not None and series in picked:
                    ev.update(set_ampm(ev, picked[series]))
                else:
                    ev.update(ask_ampm(ev))
                    if series is not None:
                        picked[series] = datetime.fromisoformat(ev["start"]).hour >= 12
                print("   →" + format_event(ev).strip().lstrip("•"))
        # Skip events that already exist (same title, same start); warn about overlaps
        # 이미 있는 일정(같은 제목, 같은 시작)은 건너뛰고, 시간이 겹치면 알린다
        if notion is not None:
            attach_nearby(notion, events)
            for ev in list(events):
                if is_duplicate(ev):
                    print(f"   ⚠ 이미 있는 일정이라 건너뜁니다: {ev['title']}")
                    events.remove(ev)
                elif others := overlapping(ev):
                    names = ", ".join(overlap_label(x, ev) for x in others)
                    print(f"   ⚠ '{ev['title']}' 시간에 {names} 일정이 있습니다.")

    to_delete: list[dict] = []
    if cancellations:
        if notion is None:
            print("\n🗑  취소 요청:")
            for c in cancellations:
                print(f"  • '{c['keyword'] or '(전체)'}'  |  {c['date_from']} ~ {c['date_to']}")
        else:
            for c in resolve_cancellations(notion, cancellations):
                label = f"'{c['keyword'] or '(전체)'}' ({c['date_from']} ~ {c['date_to']})"
                if c["exact"]:
                    print(f"\n🗑  삭제할 일정 — {label}:")
                    for ev in c["matches"]:
                        print(format_event(ev))
                    to_delete += c["matches"]
                else:
                    print(f"\n❓ {label}에 맞는 일정이 없습니다.")
                    for ev in c["matches"]:
                        print("   (같은 기간 일정)" + format_event(ev).strip().lstrip("•"))

    to_move: list[dict] = []
    if moves:
        if notion is None:
            print("\n🔁 변경 요청:")
            for m in moves:
                print(f"  • '{m['keyword']}' ({m['date_from']}~{m['date_to']}) → "
                      f"날짜 {m['new_date'] or '-'}, 시각 {m['new_time'] or '-'}, "
                      f"{m['shift_days']}일 {m['shift_minutes']}분 이동, "
                      f"제목 {m['new_title'] or '-'}, 장소 {m['new_location'] or '-'}")
        else:
            for m in resolve_moves(notion, moves):
                if not m["exact"]:
                    print(f"\n❓ '{m['keyword']}' ({m['date_from']} ~ {m['date_to']})에 맞는 일정이 없습니다.")
                    continue
                print("\n🔁 변경할 일정:")
                for ev in m["matches"]:
                    print(f"  • {describe_event(ev)}  →  {describe_event(moved_event(ev))}")
                    if ev["new"]["location"]:
                        print(f"      📍 {ev['location'] or '-'}  →  {ev['new']['location']}")
                    if ev.get("ampm_unclear") and not assume_yes:
                        ev["new"].update(ask_ampm({**ev["new"], "title": ev["title"]}))
                        print(f"    →  {describe_event(moved_event(ev))}")
                to_move += m["matches"]

    if notion is None:
        print("\n(--dry-run: Notion에는 반영하지 않았습니다.)")
        return
    if not events and not to_delete and not to_move:
        return
    if not assume_yes:
        answer = input("\nNotion에 반영할까요? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes", "ㅛ", "네", "응"):
            print("취소했습니다.")
            return
    for ev in to_move:
        new = ev["new"]
        notion.update_event(ev["id"], new["start"], new["end"], new["title"], new["location"])
        print(f"🔁 변경됨: {describe_event(moved_event(ev))}")
    for ev in to_delete:
        notion.delete_event(ev["id"])
        print(f"🗑  삭제됨: {ev['title']}")
    for ev in events:
        url = notion.add_event(ev)["url"]
        print(f"✅ 추가됨: {ev['title']}  →  {url}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="자연어 → Notion 캘린더 일정 추가")
    parser.add_argument("text", nargs="*", help="일정 문장 (생략하면 대화형 모드)")
    parser.add_argument("-y", "--yes", action="store_true", help="확인 없이 바로 추가")
    parser.add_argument("--dry-run", action="store_true", help="Notion에 올리지 않고 해석만")
    args = parser.parse_args()

    notion = None
    if not args.dry_run:
        token, db = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID")
        if not token or not db:
            print("❌ .env에 NOTION_TOKEN과 NOTION_DATABASE_ID를 설정해 주세요. (README.md 참고)")
            return 1
        try:
            notion = Notion(token, db)
        except RuntimeError as e:
            print(f"❌ {e}")
            return 1

    def run(text: str) -> None:
        try:
            handle(text, notion, args.yes)
        except requests.RequestException as e:
            print(f"❌ Notion에 연결할 수 없습니다: {e}")
        except (RuntimeError, ValueError, KeyError) as e:
            print(f"❌ {e}")

    if args.text:
        run(" ".join(args.text))
        return 0

    print("🗓  자연어로 일정을 입력하세요. (종료: 빈 줄 또는 Ctrl+C)")
    try:
        while True:
            text = input("\n> ").strip()
            if not text:
                break
            run(text)
    except (KeyboardInterrupt, EOFError):
        pass
    print("\n👋 종료합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
