"""Register the local host (native_host/host.py) so the Chrome extension can run it. (Windows)
크롬 확장이 로컬 호스트(native_host/host.py)를 실행할 수 있도록 등록합니다. (Windows)

Usage / 사용법:
    py install_host.py <extension ID>     # register / 등록
    py install_host.py --uninstall        # unregister / 등록 해제

Find the extension ID at chrome://extensions or in the extension popup's setup message.
확장프로그램 ID는 chrome://extensions 에서 확인하거나, 확장 팝업의 안내 문구에 표시됩니다.
"""

import json
import re
import sys
import winreg
from pathlib import Path

HOST_NAME = "com.notionupload.calendar"
ROOT = Path(__file__).resolve().parent
HOST_DIR = ROOT / "native_host"
REG_PATHS = [
    rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    # Edge is supported too
    # Edge도 함께 지원
    rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
]


def uninstall() -> None:
    for path in REG_PATHS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
    print("Unregistered.\n등록을 해제했습니다.")


def install(ext_id: str) -> None:
    if not re.fullmatch(r"[a-p]{32}", ext_id):
        sys.exit(f"Not a valid extension ID: {ext_id} (32 lowercase letters)\n"
                 f"확장프로그램 ID 형식이 아닙니다: {ext_id} (영문 소문자 32자)")

    bat = HOST_DIR / "host.bat"
    bat.write_text(
        f'@echo off\r\n"{sys.executable}" -u "{HOST_DIR / "host.py"}" %*\r\n', encoding="utf-8"
    )
    manifest = HOST_DIR / f"{HOST_NAME}.json"
    manifest.write_text(
        json.dumps(
            {
                "name": HOST_NAME,
                "description": "Natural language → Notion Calendar host",
                "path": str(bat),
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{ext_id}/"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for path in REG_PATHS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))

    print(f"✅ Registered (extension ID: {ext_id})\n   등록 완료 (확장 ID: {ext_id})")
    print(f"   Python: {sys.executable}")
    if not (ROOT / ".env").exists():
        print("⚠ No .env file. Copy .env.example to .env and fill in NOTION_TOKEN and NOTION_DATABASE_ID.\n"
              "  .env 파일이 없습니다. .env.example을 복사해 NOTION_TOKEN, NOTION_DATABASE_ID를 채워 주세요.")
    print("Close and reopen the extension popup to apply.\n확장 팝업을 닫았다가 다시 열면 적용됩니다.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    uninstall() if sys.argv[1] == "--uninstall" else install(sys.argv[1].strip())
