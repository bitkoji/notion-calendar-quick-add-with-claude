"""Read/write .env settings (used by the extension's settings page).

Write rules: replace the existing line (including a commented `# KEY=`) in place, or append it.
An empty value turns the line back into a `# KEY=` comment. Other lines and comments are untouched.

.env 설정 읽기/쓰기 (크롬 확장 설정 페이지에서 사용).
쓰기 규칙: 기존 줄(주석 처리된 `# KEY=` 포함)을 그 자리에서 바꾸고, 없으면 끝에 추가한다.
값을 비우면 `# KEY=` 주석 줄로 되돌린다. 다른 줄과 주석은 그대로 둔다.
"""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import dotenv_values

from messages import tr

ENV_PATH = Path(__file__).resolve().parent / ".env"

KEYS = [
    "NOTION_TOKEN",
    "NOTION_DATABASE_ID",
    "CLAUDE_MODEL",
    "TIMEZONE",
    "WEEK_START",
    "NOTION_TITLE_PROPERTY",
    "NOTION_DATE_PROPERTY",
    "NOTION_LOCATION_PROPERTY",
    "NOTION_DESCRIPTION_PROPERTY",
]
# "" = Claude Code's default model
# "" = Claude Code 기본 모델
MODELS = ["", "opus", "sonnet", "haiku"]
# "" = monday / "" 이면 월요일
WEEK_STARTS = ["", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    return {k: v or "" for k, v in dotenv_values(ENV_PATH, encoding="utf-8").items()}


def _format(key: str, value: str) -> str:
    if re.search(r'[\s#"\'=]', value):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{key}={value}"


def update_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    for key, value in updates.items():
        value = (value or "").strip()
        # Reject line breaks/control characters so a value can't add extra lines to .env
        # 줄바꿈·제어 문자는 거부해 값이 .env에 다른 줄을 끼워 넣지 못하게 한다
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(tr("settings.badValue", name=key))
        pattern = re.compile(rf"^\s*(#\s*)?{re.escape(key)}\s*=")
        idx = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
        new_line = _format(key, value) if value else f"# {key}="
        if idx is not None:
            commented = lines[idx].lstrip().startswith("#")
            # Clearing a line that is already commented out: keep its original explanation
            # 비우는데 이미 주석이면 원래 설명을 그대로 둔다
            if value or not commented:
                lines[idx] = new_line
        elif value:
            lines.append(new_line)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_database_id(value: str) -> str:
    """Extract the 32-character ID from a Notion database link or ID (with or without hyphens).

    노션 데이터베이스 링크나 ID(하이픈 포함/미포함)에서 32자리 ID를 뽑는다.
    """
    value = (value or "").strip()
    # ?v=<view ID> is not the database ID
    # ?v=뷰ID 는 데이터베이스 ID가 아니다
    path = value.split("?", 1)[0]
    uuid = r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}(?![0-9a-fA-F])"
    # Match on boundaries so letters from the page title in the link don't get mixed in
    # 링크의 페이지 제목 부분과 섞이지 않게 경계를 지켜 찾는다
    found = re.findall(uuid, path)
    if not found:
        raise ValueError(tr("db.badId"))
    return found[-1].replace("-", "").lower()
