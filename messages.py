"""User-facing error messages (English / Korean).

The Chrome extension sends "lang" with every request and the native host picks it with set_lang().
The command line (notion_cal.py) uses the default, Korean.

사용자에게 보여주는 오류 메시지 (한국어 / English).
크롬 확장은 요청마다 "lang"을 보내고, native host가 set_lang()으로 언어를 정한다.
명령줄(notion_cal.py)은 기본값인 한국어를 쓴다.
"""

from __future__ import annotations

_lang = "ko"

MESSAGES: dict[str, dict[str, str]] = {
    "claude.notFound": {
        "ko": "Claude Code(claude 명령)를 찾지 못했습니다. https://claude.com/claude-code 에서 설치한 뒤 "
              "터미널에서 `claude`를 실행해 Pro 계정으로 로그인해 주세요.",
        "en": "Claude Code (the `claude` command) wasn't found. Install it from https://claude.com/claude-code, "
              "then run `claude` in a terminal and sign in with your Pro account.",
    },
    "claude.timeout": {
        "ko": "Claude 응답이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.",
        "en": "Claude is taking too long to respond. Please try again shortly.",
    },
    "claude.runFailed": {
        "ko": "Claude Code 실행 실패: {detail}",
        "en": "Claude Code failed to run: {detail}",
    },
    "claude.error": {
        "ko": "Claude 오류: {detail}",
        "en": "Claude error: {detail}",
    },
    "claude.loginHint": {
        "ko": "터미널에서 `claude`를 실행해 /login 으로 로그인해 주세요.",
        "en": "Run `claude` in a terminal and sign in with /login.",
    },
    "unknown": {
        "ko": "알 수 없는 오류",
        "en": "Unknown error",
    },
    "notion.apiError": {
        "ko": "Notion API 오류 ({status}): {detail}",
        "en": "Notion API error ({status}): {detail}",
    },
    "notion.network": {
        "ko": "노션에 연결할 수 없습니다. 인터넷 연결을 확인해 주세요.",
        "en": "Couldn't reach Notion. Check your internet connection.",
    },
    "notion.badToken": {
        "ko": "노션 토큰이 올바르지 않습니다.",
        "en": "The Notion token is invalid.",
    },
    "notion.dbNotFound": {
        "ko": "데이터베이스를 찾지 못했습니다. ID가 맞는지, 데이터베이스 ••• → 연결에 이 연결을 추가했는지 확인하세요.",
        "en": "Database not found. Check the ID, and make sure this connection is added under the database's ••• → Connections.",
    },
    "notion.pageNotFound": {
        "ko": "노션에서 일정을 찾지 못했습니다. 완전히 삭제되었거나 이 연결에 공유되지 않은 페이지입니다.",
        "en": "Event not found in Notion. It was permanently deleted or isn't shared with this connection.",
    },
    "notion.notOurPage": {
        "ko": "설정한 데이터베이스의 일정이 아니어서 복구하지 않았습니다.",
        "en": "Not restored: this page isn't in the configured database.",
    },
    "notion.badPageId": {
        "ko": "일정 ID 형식이 올바르지 않습니다.",
        "en": "Invalid event ID.",
    },
    "notion.needToken": {
        "ko": "노션 토큰을 입력하세요.",
        "en": "Enter a Notion token.",
    },
    "notion.notConfigured": {
        "ko": "노션 토큰과 데이터베이스가 설정되지 않았습니다. 확장 프로그램 설정 페이지에서 입력해 주세요.",
        "en": "The Notion token and database aren't set. Enter them on the extension's settings page.",
    },
    "db.noTitle": {
        "ko": "데이터베이스에서 제목(title) 속성을 찾지 못했습니다.",
        "en": "The database has no title property.",
    },
    "db.noDate": {
        "ko": "데이터베이스에 날짜(date) 속성이 없습니다. 노션에서 날짜 속성을 추가하거나 설정 페이지에서 날짜 속성을 고르세요.",
        "en": "The database has no date property. Add one in Notion, or choose the date property on the settings page.",
    },
    "db.notText": {
        "ko": "'{name}' 속성은 텍스트 속성이어야 합니다.",
        "en": "The '{name}' property must be a text property.",
    },
    "db.noLocation": {
        "ko": "데이터베이스에 위치(텍스트) 속성이 없어 장소를 바꿀 수 없습니다. 설정 페이지에서 위치 속성을 고르세요.",
        "en": "The database has no location (text) property, so the location can't be changed. Choose one on the settings page.",
    },
    "db.badId": {
        "ko": "데이터베이스 ID를 찾지 못했습니다. 노션 데이터베이스 링크나 32자리 ID를 입력하세요.",
        "en": "No database ID found. Enter a Notion database link or a 32-character ID.",
    },
    "answer.notUnderstood": {
        "ko": "알아듣지 못했습니다. 예: 다음 주 화요일 오후 3시, 강남역 · 장소가 없으면 '없음'",
        "en": "Couldn't understand that. e.g. next Tuesday 3 PM, Gangnam Station · say 'none' if there's no place",
    },
    "input.empty": {
        "ko": "일정을 입력해 주세요.",
        "en": "Please enter an event.",
    },
    "settings.badModel": {
        "ko": "지원하지 않는 모델입니다: {model}",
        "en": "Unsupported model: {model}",
    },
    "settings.badTimezone": {
        "ko": "알 수 없는 타임존입니다: {tz}",
        "en": "Unknown time zone: {tz}",
    },
    "settings.badWeekStart": {
        "ko": "지원하지 않는 한 주의 시작 요일입니다: {value}",
        "en": "Unsupported first day of the week: {value}",
    },
    "settings.badValue": {
        "ko": "{name} 값에 줄바꿈이나 제어 문자를 넣을 수 없습니다.",
        "en": "{name} can't contain line breaks or control characters.",
    },
    "host.unknownAction": {
        "ko": "알 수 없는 요청: {action}",
        "en": "Unknown request: {action}",
    },
    "host.unexpected": {
        "ko": "예상하지 못한 오류가 발생했습니다: {detail}",
        "en": "An unexpected error occurred: {detail}",
    },
}


def set_lang(lang: str | None) -> None:
    global _lang
    _lang = lang if lang in ("ko", "en") else "ko"


def tr(key: str, **kwargs) -> str:
    entry = MESSAGES[key]
    return entry.get(_lang, entry["ko"]).format(**kwargs)
