// Settings page: show the .env values, test the connection, then save. (uses i18n.js · common.js)
// 설정 페이지: .env 값을 읽어 보여주고, 연결 확인 후 저장한다. (i18n.js · common.js 사용)
const $ = (id) => document.getElementById(id);
const PROP_KEYS = ["NOTION_TITLE_PROPERTY", "NOTION_DATE_PROPERTY", "NOTION_LOCATION_PROPERTY", "NOTION_DESCRIPTION_PROPERTY"];
const TIMEZONES = ["Asia/Seoul", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Europe/London", "Europe/Paris", "America/New_York", "America/Los_Angeles", "UTC"];

const tokenInput = $("token");
const dbInput = $("database");
// Last .env values read
// 마지막으로 읽은 .env 값
let saved = {};
// Whether a token is saved (the token itself is never received)
// 토큰 저장 여부 (토큰 값은 받지 않는다)
let tokenSet = false;
// Claude Code login status
// Claude Code 로그인 상태
let claude = null;
// { type: [names] } from the connection test
// 연결 확인으로 받은 { type: [이름] }
let dbProps = null;
// Title of the connected database
// 연결된 데이터베이스 제목
let dbTitle = "";

// ---------- Rendering (called again when the language changes) ----------
// ---------- 화면 그리기 (언어를 바꾸면 다시 호출) ----------
function fillSelect(select, names, current) {
  const options = [["", t("options.props.auto")], ...names.map((n) => [n, n])];
  if (current && !names.includes(current)) options.push([current, t("options.props.missing", { name: current })]);
  select.innerHTML = options.map(([v, label]) => `<option value="${escapeHtml(v)}">${escapeHtml(label)}</option>`).join("");
  select.value = current || "";
}

function renderProps() {
  for (const key of PROP_KEYS) {
    const select = $(key);
    const current = select.dataset.touched ? select.value : saved[key] || "";
    const names = dbProps ? dbProps[select.dataset.type] || [] : current ? [current] : [];
    fillSelect(select, names, current);
  }
  $("propsHelp").textContent = dbTitle ? t("options.props.loaded", { title: dbTitle }) : t("options.props.help");
}

/** "Automatic from PC" (value "") at the top is the default. A timezone picked by hand is saved to .env
 *  맨 위 "PC 시간대 자동"(값 "")이 기본. 직접 고른 타임존은 .env 에 저장된다 */
function renderTimezone() {
  const select = $("TIMEZONE");
  const current = select.dataset.touched ? select.value : saved.TIMEZONE || "";
  const list = !current || TIMEZONES.includes(current) ? TIMEZONES : [current, ...TIMEZONES];
  const auto = `<option value="">${escapeHtml(t("options.locale.auto", { tz: PC_TIMEZONE || "?" }))}</option>`;
  select.innerHTML = auto + list.map((z) => `<option value="${escapeHtml(z)}">${escapeHtml(z)}</option>`).join("");
  select.value = current;
}

/** Keeps an unsaved choice; the language changes only when saved
 *  저장 전에 고른 값은 유지한다. 언어는 저장해야 바뀐다 */
/** First day of the week, saved in .env (WEEK_START; empty = Monday)
 *  한 주의 시작 요일. .env 의 WEEK_START 에 저장 (비우면 월요일) */
// Sunday first, then Monday … Saturday / 일요일부터 월 … 토 순서
const WEEK_STARTS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
function renderWeekStart() {
  const select = $("WEEK_START");
  const current = select.dataset.touched ? select.value : saved.WEEK_START || "monday";
  select.innerHTML = WEEK_STARTS.map((d) => `<option value="${d}">${escapeHtml(t(`options.locale.${d}`))}</option>`).join("");
  select.value = WEEK_STARTS.includes(current) ? current : "monday";
}

function renderLanguage() {
  const select = $("language");
  const current = select.dataset.touched ? select.value : getLang();
  select.innerHTML = Object.entries(LANGS).map(([code, name]) => `<option value="${code}">${name}</option>`).join("");
  select.value = current;
}

function renderClaude() {
  const el = $("claudeStatus");
  if (!claude) return;
  let text, cls;
  if (!claude.installed) [text, cls] = [t("options.claude.notInstalled"), "bad"];
  else if (!claude.logged_in) [text, cls] = [t("options.claude.notLoggedIn"), "bad"];
  else [text, cls] = [t("options.claude.loggedIn") + (claude.plan ? t("options.claude.plan", { plan: claude.plan.toUpperCase() }) : ""), "ok"];
  el.className = `status-line ${cls}`;
  el.innerHTML = `<span class="dot"></span><span>${escapeHtml(text)}</span>`;
}

function renderToken() {
  tokenInput.placeholder = tokenSet ? t("options.notion.tokenSaved") : "ntn_…";
  $("tokenHelp").textContent = tokenSet ? t("options.notion.tokenSavedHelp") : t("options.notion.tokenHelp");
}

/** Eye button: toggles show/hide. isHidden/setHidden define how each field is masked
 *  눈 버튼: 누를 때마다 보이기/숨기기. isHidden/setHidden 으로 입력칸마다 가리는 방식을 정한다 */
const toggles = [];
function setupToggle(button, nameKey, isHidden, setHidden) {
  const render = () => {
    const hidden = isHidden();
    button.innerHTML = icon(hidden ? "eye" : "eyeOff");
    button.title = button.ariaLabel = t(hidden ? "common.show" : "common.hide", { name: t(nameKey) });
  };
  button.addEventListener("click", () => { setHidden(!isHidden()); render(); });
  toggles.push(render);
}

// ---------- Keyboard shortcut / 단축키 ----------
// Extensions can't change their own shortcut; Chrome's shortcut page does it. This only shows it.
// 확장은 자기 단축키를 바꿀 수 없고 Chrome의 단축키 페이지에서 바꾼다. 여기서는 보여 주기만 한다.
let shortcut = null;

async function loadShortcut() {
  try {
    const cmd = (await chrome.commands.getAll()).find((c) => c.name === "_execute_action");
    shortcut = cmd ? cmd.shortcut || "" : "";
  } catch {
    shortcut = "";
  }
  renderShortcut();
}

function renderShortcut() {
  const el = $("shortcutStatus");
  if (shortcut === null) return (el.innerHTML = "");
  if (!shortcut) {
    el.className = "status-line bad";
    el.innerHTML = `<span class="dot"></span><span>${escapeHtml(t("options.shortcut.none"))}</span>`;
    return;
  }
  // "Ctrl+Shift+Y" → Ctrl + Shift + Y as keys / 키 모양으로 표시
  const keys = shortcut.split("+").map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join("+");
  el.className = "status-line ok";
  el.innerHTML = `<span class="dot"></span><span>${escapeHtml(t("options.shortcut.current"))} ${keys}</span>`;
}

// ---------- Updates / 업데이트 ----------
// Latest release from GitHub: { version, url } · "checking" · "failed" · null (not checked)
// GitHub 최신 릴리스: { version, url } · "checking" · "failed" · null(확인 안 함)
let release = null;

function renderUpdate() {
  const box = $("updateCheck");
  if (!box.dataset.touched) box.checked = updateCheckEnabled();
  const el = $("versionStatus");
  let cls = "";
  let state = "";
  if (release === "checking") {
    state = escapeHtml(t("options.update.checking"));
  } else if (release === "failed") {
    cls = "bad";
    state = escapeHtml(t("options.update.failed"));
  } else if (release && isNewer(release.version, currentVersion())) {
    cls = "new";
    state = `${escapeHtml(t("options.update.newer", { version: release.version }))} ` +
      `<a href="${escapeHtml(release.url)}" target="_blank">${escapeHtml(t("update.view"))}</a>`;
  } else if (release) {
    cls = "ok";
    state = escapeHtml(t("options.update.latest"));
  }
  const current = escapeHtml(t("options.update.current", { version: currentVersion() }));
  // "New version" next to Updates in the sidebar / 사이드바의 업데이트 옆 "새 버전"
  $("navUpdateBadge").hidden = cls !== "new";
  el.className = `status-line ${cls}`;
  el.innerHTML = `<span class="dot"></span><span>${current}${state ? ` · ${state}` : ""}</span>`;
}

async function checkUpdate(force) {
  if (force) {
    release = "checking";
    $("checkNow").disabled = true;
    renderUpdate();
  }
  try {
    release = await latestRelease(force);
  } catch {
    release = "failed";
  } finally {
    $("checkNow").disabled = false;
  }
  renderUpdate();
}

function renderAll() {
  applyI18n();
  document.title = t("options.docTitle");
  renderUpdate();
  renderShortcut();
  renderLanguage();
  renderTimezone();
  renderWeekStart();
  renderProps();
  renderClaude();
  renderToken();
  toggles.forEach((render) => render());
}

// ---------- Actions / 동작 ----------
// ---------- Unsaved changes / 저장하지 않은 변경 ----------
// The form is compared with what was loaded (or last saved); while it differs, a red notice sits next to Save.
// 불러온(또는 마지막으로 저장한) 값과 비교해, 다르면 저장 버튼 옆에 빨간 안내를 띄운다.
let baseline = null;
let unsavedShown = false;

function formValues() {
  return JSON.stringify({
    token: tokenInput.value.trim(),
    database: dbInput.value.trim(),
    model: (document.querySelector("input[name=model]:checked") || {}).value,
    language: $("language").value,
    timezone: $("TIMEZONE").value,
    weekStart: $("WEEK_START").value,
    props: PROP_KEYS.map((key) => $(key).value),
    updateCheck: $("updateCheck").checked,
    weekView: (document.querySelector("input[name=weekView]:checked") || {}).value,
  });
}

const isDirty = () => baseline !== null && formValues() !== baseline;

function updateUnsaved() {
  const dirty = isDirty();
  if (dirty) showBanner($("saveStatus"), "critical", escapeHtml(t("options.unsaved")));
  else if (unsavedShown) showBanner($("saveStatus"), "", "");
  unsavedShown = dirty;
}

function markClean() {
  baseline = formValues();
  updateUnsaved();
}

async function load() {
  showBanner($("pageStatus"), "loading", escapeHtml(t("options.loading")));
  try {
    const res = await callHost({ action: "get_settings" });
    saved = res.settings;
    tokenSet = res.token_set;
    claude = res.claude;
    showBanner($("pageStatus"), "", "");
    dbInput.value = saved.NOTION_DATABASE_ID || "";
    const model = saved.CLAUDE_MODEL === "opus" ? "" : saved.CLAUDE_MODEL || "";
    (document.querySelector(`input[name=model][value="${model}"]`) || document.querySelector("input[name=model]")).checked = true;
    renderAll();
    markClean();
    if (tokenSet && saved.NOTION_DATABASE_ID) testConnection(true);
  } catch (e) {
    bannerError($("pageStatus"), e);
    claude = { installed: true, logged_in: false };
    renderAll();
    markClean();
  }
}

async function testConnection(quiet = false) {
  const status = $("testStatus");
  $("test").disabled = true;
  // The automatic check on load only tidies the shown values, so it isn't an unsaved change
  // 불러올 때의 자동 확인은 표시 값만 다듬는 것이라 저장할 변경으로 치지 않는다
  const wasClean = quiet && !isDirty();
  showBanner(status, "loading", escapeHtml(t("options.notion.testing")));
  try {
    const res = await callHost({ action: "test_connection", token: tokenInput.value.trim(), database_id: dbInput.value.trim() });
    dbProps = res.properties;
    dbTitle = res.database_title;
    dbInput.value = res.database_id;
    renderProps();
    if (wasClean && !isDirty()) markClean();
    else updateUnsaved();
    showBanner(status, "success", t("options.notion.connected", { title: escapeHtml(dbTitle) }));
    if (quiet) setTimeout(() => showBanner(status, "", ""), 2500);
  } catch (e) {
    bannerError(status, e);
  } finally {
    $("test").disabled = false;
  }
}

async function save(e) {
  e.preventDefault();
  // The language is stored in the extension only (not in .env), so it's applied first:
  // it takes effect even when the .env values can't be saved yet, and the messages below use it.
  // 언어는 확장에만 저장되므로(.env 와 무관) 먼저 적용한다.
  // .env 값을 아직 저장할 수 없어도 언어는 바뀌고, 아래 안내 문구도 새 언어로 나온다.
  // The update-check switch is also stored in the extension / 업데이트 확인 설정도 확장에 저장된다
  setUpdateCheckEnabled($("updateCheck").checked);
  delete $("updateCheck").dataset.touched;
  // How the popup shows this week's events, also stored in the extension / 팝업의 이번 주 일정 보기도 확장에 저장
  setWeekView((document.querySelector("input[name=weekView]:checked") || {}).value);
  const lang = $("language").value;
  delete $("language").dataset.touched;
  if (lang !== getLang()) {
    setLang(lang);
    syncMenuTitle();
    ["pageStatus", "testStatus"].forEach((id) => showBanner($(id), "", ""));
    renderAll();
  }
  const status = $("saveStatus");
  const values = {
    NOTION_TOKEN: tokenInput.value.trim(),
    NOTION_DATABASE_ID: dbInput.value.trim(),
    CLAUDE_MODEL: document.querySelector("input[name=model]:checked").value,
    // "" = automatic from PC / PC 시간대 자동
    TIMEZONE: $("TIMEZONE").value,
    WEEK_START: $("WEEK_START").value,
  };
  for (const key of PROP_KEYS) values[key] = $(key).value;
  if (!values.NOTION_DATABASE_ID) return showBanner(status, "critical", escapeHtml(t("options.needDatabase")));

  $("save").disabled = true;
  showBanner(status, "loading", escapeHtml(t("options.saving")));
  try {
    await callHost({ action: "save_settings", settings: values });
    const res = await callHost({ action: "get_settings" });
    saved = res.settings;
    tokenSet = res.token_set;
    tokenInput.value = "";
    dbInput.value = saved.NOTION_DATABASE_ID || "";
    renderToken();
    markClean();
    showBanner(status, "success", escapeHtml(t("options.saved")));
  } catch (err) {
    bannerError(status, err);
  } finally {
    $("save").disabled = false;
  }
}

setupToggle($("toggleToken"), "options.notion.tokenName",
  () => tokenInput.type === "password",
  (hide) => (tokenInput.type = hide ? "password" : "text"));
setupToggle($("toggleDb"), "options.notion.databaseName",
  () => dbInput.classList.contains("masked"),
  (hide) => dbInput.classList.toggle("masked", hide));

$("test").addEventListener("click", () => testConnection());
$("form").addEventListener("submit", save);
// Any edit (typing, picking) re-checks for unsaved changes / 입력하거나 고를 때마다 저장 안 된 변경을 다시 확인
$("form").addEventListener("input", updateUnsaved);
$("form").addEventListener("change", updateUnsaved);
// Remember hand-picked values so re-rendering doesn't reset them (they apply on Save)
// 직접 고른 값은 다시 그려도 유지한다 (저장할 때 적용)
for (const key of [...PROP_KEYS, "TIMEZONE", "WEEK_START", "language", "updateCheck"]) $(key).addEventListener("change", (e) => (e.target.dataset.touched = "1"));
$("checkNow").addEventListener("click", () => checkUpdate(true));
// chrome:// pages can't be opened by a link, but an extension can open them in a new tab
// chrome:// 페이지는 링크로 못 열지만 확장은 새 탭으로 열 수 있다
$("changeShortcut").addEventListener("click", () => chrome.tabs.create({ url: "chrome://extensions/shortcuts" }));
// Show the new shortcut when coming back from Chrome's shortcut page
// Chrome 단축키 페이지에서 돌아오면 바뀐 단축키를 보여 준다
addEventListener("focus", loadShortcut);
loadShortcut();

// Sidebar: highlight the section being viewed (the last one whose top has scrolled past, or the last at the bottom)
// 사이드바: 보고 있는 섹션 강조 (위쪽을 지난 마지막 섹션, 맨 아래면 마지막 섹션)
// A clicked item stays highlighted until the user scrolls by hand
// (a section near the bottom can't scroll to the top, so the position alone would pick the wrong one).
// 누른 항목은 사용자가 직접 스크롤할 때까지 강조를 유지한다
// (맨 아래 근처 섹션은 위쪽까지 올라오지 못해, 위치만으로는 다른 섹션이 골라진다).
const navLinks = [...document.querySelectorAll("#nav a")].map((a) => [a, document.querySelector(a.getAttribute("href"))]);
let pinnedLink = null;

function setActive(a) {
  navLinks.forEach(([link]) => link.classList.toggle("active", link === a));
}

function markActiveSection() {
  if (pinnedLink) return setActive(pinnedLink);
  let active = navLinks[0];
  for (const link of navLinks) if (link[1].getBoundingClientRect().top < 140) active = link;
  if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) active = navLinks[navLinks.length - 1];
  setActive(active[0]);
}

navLinks.forEach(([a, section]) => a.addEventListener("click", (e) => {
  e.preventDefault();
  pinnedLink = a;
  setActive(a);
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}));
for (const type of ["wheel", "touchmove", "keydown", "mousedown"]) addEventListener(type, () => (pinnedLink = null), { passive: true });
addEventListener("scroll", markActiveSection, { passive: true });
addEventListener("resize", markActiveSection);
markActiveSection();

// Saved popup view / 저장된 팝업 보기
document.querySelector(`input[name=weekView][value="${getWeekView()}"]`).checked = true;
renderAll();
load();
// Automatic check uses the once-a-day result; [Check now] always asks GitHub
// 자동 확인은 하루 한 번 결과를 쓰고, [지금 확인]은 항상 GitHub에 묻는다
if (updateCheckEnabled()) checkUpdate(false);
