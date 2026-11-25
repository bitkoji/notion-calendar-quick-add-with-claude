// Shared by the popup and settings page: local host calls, icons, escaping, date display (load after i18n.js)
// 팝업·설정 페이지 공용: 로컬 프로그램 통신, 아이콘, 이스케이프, 날짜 표시 (i18n.js 다음에 로드)
const HOST = "com.notionupload.calendar";
// OS timezone (e.g. "Asia/Seoul", "America/New_York"). Independent of the browser language
// 운영체제 시간대 (예: "Asia/Seoul", "America/New_York"). 브라우저 언어와는 무관하다
const PC_TIMEZONE = (() => {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; }
})();

const ICON_PATHS = {
  check: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-1.2 14.2-4-4 1.4-1.4 2.6 2.6 5.6-5.6 1.4 1.4-7 7Z",
  error: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 15h-2v-2h2v2Zm0-4h-2V7h2v6Z",
  info: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 15h-2v-6h2v6Zm0-8h-2V7h2v2Z",
  pin: "M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z",
  clock: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm.5-13H11v6l5.2 3.2.8-1.3-4.5-2.7V7Z",
  arrow: "M13.3 5.3 12 6.6l4.4 4.4H4v2h12.4L12 17.4l1.3 1.3L20 12l-6.7-6.7Z",
  trash: "M9 3h6l1 2h4v2H4V5h4l1-2Zm-3 6h12l-1 12H7L6 9Z",
  plus: "M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5Z",
  chevron: "M9.3 6.3 7.9 7.7l4.3 4.3-4.3 4.3 1.4 1.4 5.7-5.7-5.7-5.7Z",
  dot: "M12 6.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11Z",
  done: "M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6 11-11-1.4-1.4-9.6 9.6Z",
  repeat: "M7 7h10v3l4-4-4-4v3H5v6h2V7Zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4Z",
  close: "M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12Z",
  eye: "M12 5C6.5 5 2.7 9.3 1.5 12c1.2 2.7 5 7 10.5 7s9.3-4.3 10.5-7C21.3 9.3 17.5 5 12 5Zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9Zm0-7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z",
  eyeOff: "M3.3 2 2 3.3l3.1 3.1C3.4 7.8 2.2 9.8 1.5 12c1.2 2.7 5 7 10.5 7 1.8 0 3.4-.5 4.8-1.2l3.9 3.9 1.3-1.3L3.3 2ZM12 16.5A4.5 4.5 0 0 1 7.5 12c0-.8.2-1.5.5-2.1l1.5 1.5a2.5 2.5 0 0 0 3.1 3.1l1.5 1.5c-.6.3-1.3.5-2.1.5ZM12 5c-1.3 0-2.6.2-3.7.7l2 2c.5-.1 1.1-.2 1.7-.2a4.5 4.5 0 0 1 4.5 4.5c0 .6-.1 1.2-.3 1.7l3.1 3.1c1.4-1.2 2.5-2.7 3.2-4.3C21.3 9.3 17.5 5 12 5Z",
};
const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON_PATHS[name]}"/></svg>`;

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Only https links to Notion are turned into links (blocks javascript: and other schemes).
 *  The API now returns https://app.notion.com/p/<id>; older pages use notion.so / notion.site.
 *  노션의 https 링크만 링크로 만든다 (javascript: 등 다른 형식 차단).
 *  API가 이제 https://app.notion.com/p/<id> 를 돌려주고, 예전 주소는 notion.so / notion.site 이다. */
function isNotionUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && /(^|\.)notion\.(so|site|com)$/.test(u.hostname);
  } catch {
    return false;
  }
}

class SetupError extends Error {}

async function callHost(message) {
  let res;
  try {
    // lang: so error messages come back in the UI language / tz: PC timezone used when none is saved
    // lang: 오류 메시지를 화면 언어로 만들도록 / tz: 타임존을 따로 저장하지 않았을 때 쓸 PC 시간대
    res = await chrome.runtime.sendNativeMessage(HOST, { ...message, lang: getLang(), tz: PC_TIMEZONE });
  } catch (e) {
    const msg = String(e && e.message ? e.message : e);
    if (/not found|forbidden/i.test(msg)) throw new SetupError();
    throw new Error(t("common.hostError", { msg }));
  }
  if (!res || !res.ok) throw new Error(res && res.error ? res.error : t("common.unknownError"));
  return res;
}

const SETUP_HTML = () => t("common.setup") + `<code>py install_host.py ${chrome.runtime.id}</code>`;

const BANNER_ICON = { info: "info", success: "check", critical: "error" };

/** Show a banner. kind: "loading" | "info" | "success" | "critical" | "" (hidden)
 *  배너 표시. kind: "" 이면 숨김 */
function showBanner(el, kind, html) {
  el.hidden = !kind;
  el.className = `banner ${kind === "loading" ? "" : kind}`;
  if (!kind) return (el.innerHTML = "");
  const lead = kind === "loading" ? `<span class="spinner"></span>` : icon(BANNER_ICON[kind]);
  el.innerHTML = `${lead}<div class="body">${html}</div>`;
}

/** Format an event's time. en: Wed 11/18 15:00 ~ 16:00 · ko: 11/18(수) 15:00 ~ 16:00
 *  일정 시간 표시 */
function formatWhen(ev) {
  const days = t("date.weekdays").split(",");
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (v) => {
    if (ev.all_day) {
      const [, m, d] = v.split("-").map(Number);
      return `${m}/${d}`;
    }
    const d = new Date(v);
    const md = `${d.getMonth() + 1}/${d.getDate()}`;
    const date = getLang() === "ko" ? `${md}(${days[d.getDay()]})` : `${days[d.getDay()]} ${md}`;
    return `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  let s = fmt(ev.start);
  if (ev.end) {
    const sameDay = !ev.all_day && ev.start.slice(0, 10) === ev.end.slice(0, 10);
    s += " ~ " + (sameDay ? fmt(ev.end).split(" ").pop() : fmt(ev.end));
  }
  return ev.all_day ? `${s} ${t("date.allDay")}` : s;
}

// ---------- This week's events in the popup / 팝업의 이번 주 일정 ----------
// "list" (by day) · "calendar" (Mon–Sun columns) · "off". Stored in the extension, set on the settings page.
// "list"(날짜별) · "calendar"(월~일 칸) · "off". 확장에 저장하고 설정 페이지에서 바꾼다.
const WEEK_VIEW_KEY = "weekView";
const WEEK_VIEWS = ["list", "calendar", "off"];

function getWeekView() {
  try {
    const v = localStorage.getItem(WEEK_VIEW_KEY);
    return WEEK_VIEWS.includes(v) ? v : "list";
  } catch {
    return "list";
  }
}

function setWeekView(v) {
  try { localStorage.setItem(WEEK_VIEW_KEY, WEEK_VIEWS.includes(v) ? v : "list"); } catch {}
}

// ---------- Update check / 업데이트 확인 ----------
// Unpacked extensions don't update themselves, so the latest GitHub release is checked
// (at most once a day; only a version request, no personal data or events are sent).
// 압축해제로 설치한 확장은 스스로 업데이트되지 않으므로 GitHub 최신 릴리스를 확인한다
// (하루 최대 한 번, 버전만 조회하며 개인 정보나 일정은 보내지 않는다).
const REPO = "bitkoji/notion-calendar-quick-add-with-claude";
const RELEASES_URL = `https://github.com/${REPO}/releases`;
const UPDATE_KEY = "updateCheck";
const UPDATE_OFF_KEY = "updateCheckOff";
const UPDATE_EVERY_MS = 86400000;

const currentVersion = () => chrome.runtime.getManifest().version;

/** a > b for versions like "1.2.0" / "1.2.0" 같은 버전에서 a > b 인지 */
function isNewer(a, b) {
  const pa = String(a).split(".").map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

function updateCheckEnabled() {
  try { return localStorage.getItem(UPDATE_OFF_KEY) !== "1"; } catch { return true; }
}

function setUpdateCheckEnabled(on) {
  try { on ? localStorage.removeItem(UPDATE_OFF_KEY) : localStorage.setItem(UPDATE_OFF_KEY, "1"); } catch {}
}

function readUpdateCache() {
  try { return JSON.parse(localStorage.getItem(UPDATE_KEY) || "null"); } catch { return null; }
}

/** Latest release { version, url }, or null if unknown. Uses the saved result for a day unless force.
 *  With force, throws when GitHub can't be reached.
 *  최신 릴리스 { version, url }, 모르면 null. force 가 아니면 하루 동안 저장된 결과를 쓴다.
 *  force 일 때 GitHub에 연결하지 못하면 오류를 던진다. */
async function latestRelease(force = false) {
  // A result saved while a different version was installed is stale (e.g. after updating or reinstalling)
  // 다른 버전이 설치돼 있을 때 저장한 결과는 쓰지 않는다 (업데이트·재설치 후 등)
  const saved = readUpdateCache();
  const cached = saved && saved.for === currentVersion() ? saved : null;
  if (!force && cached && Date.now() - cached.checked_at < UPDATE_EVERY_MS) return cached.version ? cached : null;
  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
      cache: "no-store",
      credentials: "omit",
    });
    if (!r.ok) throw new Error(`GitHub ${r.status}`);
    const data = await r.json();
    const version = String(data.tag_name || "").replace(/^v/i, "");
    if (!/^\d+(\.\d+){0,2}$/.test(version)) throw new Error(`GitHub: ${version}`);
    // Only link to this repository's pages / 이 저장소 페이지로만 링크한다
    const url = isGithubRepoUrl(data.html_url) ? data.html_url : RELEASES_URL;
    const result = { version, url, checked_at: Date.now(), for: currentVersion() };
    try { localStorage.setItem(UPDATE_KEY, JSON.stringify(result)); } catch {}
    return result;
  } catch (e) {
    // Remember the failed attempt so it isn't retried on every popup open; keep the last known version
    // 실패도 기록해 팝업을 열 때마다 다시 시도하지 않게 하고, 마지막으로 알던 버전은 유지한다
    try { localStorage.setItem(UPDATE_KEY, JSON.stringify({ ...(cached || {}), checked_at: Date.now(), for: currentVersion() })); } catch {}
    if (force) throw e;
    return cached && cached.version ? cached : null;
  }
}

function isGithubRepoUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && u.hostname === "github.com" && u.pathname.startsWith(`/${REPO}/`);
  } catch {
    return false;
  }
}

// ---------- Right-click menu / 우클릭 메뉴 ----------
// Shared with background.js (keep the values the same there).
// background.js 와 같은 값을 쓴다 (바꾸면 그쪽도 같이).
const MENU_ID = "add-selection";
const PENDING_TEXT_KEY = "pendingText";

/** Show the menu item in the extension's language (background.js can only use the browser's)
 *  메뉴 이름을 확장 화면 언어로 맞춘다 (background.js 는 브라우저 언어만 알 수 있다) */
function syncMenuTitle() {
  try { chrome.contextMenus.update(MENU_ID, { title: t("menu.addSelection") }).catch(() => {}); } catch {}
}

function bannerError(el, e) {
  showBanner(el, "critical", e instanceof SetupError ? SETUP_HTML() : escapeHtml(e.message));
}
