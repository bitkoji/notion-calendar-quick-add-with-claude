"""Native Messaging host that connects the Chrome extension ↔ notion_cal.

Chrome runs this script for each message and exchanges length (4 bytes) + JSON over stdin/stdout.
Note: stdout is reserved for the protocol, so never use print().

크롬 확장 ↔ notion_cal 연결용 Native Messaging 호스트.
크롬이 메시지마다 이 스크립트를 실행하고, 표준입출력으로 길이(4바이트)+JSON을 주고받는다.
주의: stdout은 프로토콜 전용이므로 print()를 쓰면 안 된다.

Requests / 요청:
  {"action": "ping"}                     → check setup / 설정 상태 확인
  {"action": "parse", "text": "..."}     → {"events": [...], "cancellations": [{..., "matches": [...]}]}
  {"action": "apply", "add": [...], "delete": [{"id", "title"}]}
                                         → {"added": [{"id", "title", "url"}], "deleted": [{"id", "title"}]}
  {"action": "week"}                     → {"from", "to", "today", "events": [...]}  this week / 이번 주 (WEEK_START)
  {"action": "restore", "id": "..."}     → {"url"} or {"gone": true} if permanently deleted / 완전히 삭제됐으면 gone
  {"action": "get_settings"}             → {"settings": {...}, "token_set", "claude": {...}}  (never sends any part of the token / 토큰은 일부도 보내지 않음)
  {"action": "test_connection", "token"?, "database_id"}
                                         → {"database_id", "database_title", "properties": {type: [names]}}
  {"action": "save_settings", "settings": {...}}  (empty token keeps the saved one / token이 비어 있으면 기존 값 유지)
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import subprocess  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import requests  # noqa: E402

import messages  # noqa: E402
import notion_cal  # noqa: E402
import settings  # noqa: E402
from messages import tr  # noqa: E402


def read_message() -> dict | None:
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    (length,) = struct.unpack("<I", raw_len)
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send_message(msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def notion_client() -> notion_cal.Notion:
    token, db = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID")
    if not token or not db:
        raise RuntimeError(tr("notion.notConfigured"))
    return notion_cal.Notion(token, db)


def claude_status() -> dict:
    """Claude Code login status (never passes on personal info such as the email).

    Claude Code 로그인 상태 (이메일 등 개인정보는 넘기지 않는다).
    """
    try:
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        out = subprocess.run(
            [notion_cal.find_claude(), "auth", "status"], capture_output=True, text=True,
            encoding="utf-8", env=env, timeout=20,
        ).stdout
        info = json.loads(out)
        return {
            "installed": True,
            "logged_in": bool(info.get("loggedIn")),
            "plan": info.get("subscriptionType") or info.get("planTier") or "",
            "method": info.get("authMethod") or "",
        }
    except RuntimeError:
        return {"installed": False, "logged_in": False, "plan": "", "method": ""}
    except Exception:
        return {"installed": True, "logged_in": False, "plan": "", "method": ""}


def test_connection(token: str, database_id: str) -> dict:
    db = settings.normalize_database_id(database_id)
    try:
        r = requests.get(
            f"{notion_cal.NOTION_API}/databases/{db}",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": notion_cal.NOTION_VERSION},
            timeout=20,
        )
    except requests.RequestException:
        raise RuntimeError(tr("notion.network"))
    if r.status_code == 401:
        raise RuntimeError(tr("notion.badToken"))
    # 400 for a malformed ID, 404 for a database that doesn't exist or isn't shared
    # 형식이 틀린 ID는 400, 없거나 공유되지 않은 DB는 404
    if r.status_code in (400, 404):
        raise RuntimeError(tr("notion.dbNotFound"))
    if not r.ok:
        raise RuntimeError(tr("notion.apiError", status=r.status_code, detail=r.json().get("message", r.text)))
    data = r.json()
    props: dict[str, list[str]] = {}
    for name, p in data["properties"].items():
        props.setdefault(p["type"], []).append(name)
    title = "".join(t.get("plain_text", "") for t in data.get("title", [])) or "(제목 없음)"
    return {"database_id": db, "database_title": title, "properties": props}


def handle(msg: dict) -> dict:
    action = msg.get("action")
    if action == "get_settings":
        env = settings.read_env()
        token = env.get("NOTION_TOKEN", "")
        values = {k: env.get(k, "") for k in settings.KEYS if k != "NOTION_TOKEN"}
        return {
            "ok": True,
            "settings": values,
            # Never send any part of the token
            # 토큰은 일부도 보내지 않는다
            "token_set": bool(token),
            "claude": claude_status(),
        }
    if action == "test_connection":
        token = (msg.get("token") or "").strip() or settings.read_env().get("NOTION_TOKEN", "")
        if not token:
            raise RuntimeError(tr("notion.needToken"))
        return {"ok": True, **test_connection(token, msg.get("database_id") or "")}
    if action == "save_settings":
        values = {k: str(v or "").strip() for k, v in (msg.get("settings") or {}).items() if k in settings.KEYS}
        if not values.get("NOTION_TOKEN"):
            # Left empty: keep the existing token
            # 비워 두면 기존 토큰 유지
            values.pop("NOTION_TOKEN", None)
        if values.get("NOTION_DATABASE_ID"):
            values["NOTION_DATABASE_ID"] = settings.normalize_database_id(values["NOTION_DATABASE_ID"])
        if values.get("CLAUDE_MODEL", "") not in settings.MODELS:
            raise RuntimeError(tr("settings.badModel", model=values["CLAUDE_MODEL"]))
        if values.get("WEEK_START", "") not in settings.WEEK_STARTS:
            raise RuntimeError(tr("settings.badWeekStart", value=values["WEEK_START"]))
        if values.get("TIMEZONE"):
            try:
                ZoneInfo(values["TIMEZONE"])
            except Exception:
                raise RuntimeError(tr("settings.badTimezone", tz=values["TIMEZONE"]))
        settings.update_env(values)
        return {"ok": True}
    if action == "ping":
        notion_cal.find_claude()
        notion_client()
        return {"ok": True}
    if action == "parse":
        text = str(msg.get("text", "")).strip()
        if not text:
            raise RuntimeError(tr("input.empty"))
        notion = notion_client()
        req = notion_cal.parse_request(text, notion)
        return {
            "ok": True,
            # Each event carries "nearby" so the popup can warn about duplicates and overlaps
            # 일정마다 "nearby"를 붙여 팝업이 중복·겹침을 알릴 수 있게 한다
            "events": notion_cal.attach_nearby(notion, req["events"]),
            "cancellations": notion_cal.resolve_cancellations(notion, req["cancellations"]),
            "moves": notion_cal.resolve_moves(notion, req["moves"]),
        }
    if action == "apply":
        to_add, to_delete, to_move = msg.get("add") or [], msg.get("delete") or [], msg.get("move") or []
        notion = notion_client()
        moved = []
        for ev in to_move:
            new = ev["new"]
            notion_cal.validate_event({**new, "title": ev.get("title", "")})
            url = notion.move_event(ev["id"], new["start"], new["end"])
            moved.append({"title": ev.get("title", ""), "url": url, "when": notion_cal.describe_event({**ev, **new})})
        deleted = []
        for ev in to_delete:
            notion.delete_event(ev["id"])
            deleted.append({"id": ev["id"], "title": ev.get("title", "")})
        added = []
        for ev in to_add:
            notion_cal.validate_event(ev)
            added.append({"title": ev["title"], **notion.add_event(ev)})
        return {"ok": True, "added": added, "deleted": deleted, "moved": moved}
    if action == "week":
        # This week (from the configured first day) in the local timezone, plus events from the
        # week before that run into it
        # 로컬 기준 이번 주(설정한 시작 요일부터 7일). 지난주에 시작해 이번 주까지 이어지는 일정도 포함
        today = datetime.now(ZoneInfo(notion_cal.TIMEZONE)).date()
        first, last = notion_cal.week_range(today)
        events = [
            {k: ev[k] for k in ("id", "title", "start", "end", "all_day", "url", "location")}
            for ev in notion_client().find_events((first - timedelta(days=7)).isoformat(), last.isoformat())
            if notion_cal.local_date(ev["end"] or ev["start"]) >= first
        ]
        return {"ok": True, "from": first.isoformat(), "to": last.isoformat(), "today": today.isoformat(), "events": events}
    if action == "restore":
        page_id = str(msg.get("id", ""))
        if not re.fullmatch(r"[0-9a-fA-F]{32}", page_id.replace("-", "")):
            raise RuntimeError(tr("notion.badPageId"))
        url = notion_client().restore_event(page_id)
        return {"ok": True, "url": url} if url else {"ok": True, "gone": True}
    raise RuntimeError(tr("host.unknownAction", action=action))


def use_pc_timezone(tz: str | None) -> None:
    """If .env has no TIMEZONE, interpret times in the PC timezone the extension reports.

    .env에 TIMEZONE이 없으면 확장이 알려준 PC 시간대로 해석한다.
    """
    if os.getenv("TIMEZONE") or not tz:
        return
    try:
        ZoneInfo(tz)
    except Exception:
        return
    notion_cal.TIMEZONE = tz


def main() -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    msg = read_message()
    if msg is None:
        return
    # Build error messages in the extension's UI language
    # 확장 화면 언어로 오류 메시지를 만든다
    messages.set_lang(msg.get("lang"))
    use_pc_timezone(msg.get("tz"))
    try:
        send_message(handle(msg))
    # Errors that already carry a user-facing message
    # 사용자에게 보여줄 메시지로 만든 오류
    except (RuntimeError, ValueError) as e:
        traceback.print_exc(file=sys.stderr)
        send_message({"ok": False, "error": str(e)})
    # Any other error is also shown in the popup as a message
    # 그 밖의 오류도 팝업에 메시지로 보여준다
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        send_message({"ok": False, "error": tr("host.unexpected", detail=f"{type(e).__name__}: {e}")})


if __name__ == "__main__":
    main()
