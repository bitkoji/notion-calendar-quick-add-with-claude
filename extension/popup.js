// Uses t from i18n.js and callHost · icon · escapeHtml · showBanner · formatWhen from common.js
// i18n.js 의 t · common.js 의 callHost · icon · escapeHtml · showBanner · formatWhen 를 사용한다
const DRAFT_KEY = "draft";

const $ = (id) => document.getElementById(id);
const form = $("form");
const input = $("input");
const submitBtn = $("submit");
const statusEl = $("status");
const preview = $("preview");
const groupsEl = $("groups");
const applyBtn = $("apply");

// Checkbox key → { kind: "add" | "delete" | "move", ev }
// 체크박스 key → { kind, ev }
let items = new Map();

applyI18n();

// ---------- View / 화면 ----------
const setStatus = (kind, html) => showBanner(statusEl, kind, html);
const showError = (e) => bannerError(statusEl, e);

function setBusy(busy, label) {
  submitBtn.disabled = busy;
  applyBtn.disabled = busy;
  input.disabled = busy;
  if (busy) setStatus("loading", escapeHtml(label));
}

const LABEL_ICON = { add: "plus", delete: "trash", move: "arrow" };

// ---------- AM / PM choice / 오전·오후 선택 ----------
// When only "3 o'clock" is given, Claude marks the time unclear and the user picks AM or PM.
// Times are shifted on the ISO string's own wall clock, keeping its offset and the duration.
// "3시"처럼 숫자만 있으면 Claude가 불분명으로 표시하고, 사용자가 오전/오후를 고른다.
// ISO 문자열의 시각 그대로 옮기며 오프셋과 길이는 유지한다.

/** ISO date-time shifted by `hours`, keeping its UTC offset (or none) / 오프셋을 유지한 채 hours 만큼 옮긴 ISO */
function shiftIso(iso, hours) {
  if (!iso) return iso;
  const m = iso.match(/(Z|[+-]\d{2}:?\d{2})$/);
  const offset = m ? m[1] : "";
  // Read the wall clock as if it were UTC, shift, and write it back with the same offset
  // 벽시계 시각을 UTC처럼 읽어 옮긴 뒤 같은 오프셋을 붙여 다시 쓴다
  const d = new Date(Date.parse(iso.slice(0, 19) + "Z") + hours * 3600000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}${offset}`;
}

/** { start, end } moved to the AM (pm=false) or PM side of the start hour / 시작 시각의 오전·오후 쪽으로 옮긴 { start, end } */
function withAmpm(ev, pm) {
  const h = parseInt(ev.start.slice(11, 13), 10);
  const delta = (h % 12) + (pm ? 12 : 0) - h;
  return { start: shiftIso(ev.start, delta), end: shiftIso(ev.end, delta) };
}

/** "오전 3:00" / "3:00 AM" from the ISO wall clock / ISO 시각으로 만든 표시 */
function ampmLabel(iso) {
  const h = parseInt(iso.slice(11, 13), 10);
  const time = `${h % 12 || 12}:${iso.slice(14, 16)}`;
  const mark = t(h < 12 ? "ampm.am" : "ampm.pm");
  return getLang() === "ko" ? `${mark} ${time}` : `${time} ${mark}`;
}

/** "11/18(수)" / "Wed 11/18" from the ISO date / ISO 날짜로 만든 표시 */
function dayLabel(iso) {
  const [y, mo, d] = iso.slice(0, 10).split("-").map(Number);
  const wd = t("date.weekdays").split(",")[new Date(Date.UTC(y, mo - 1, d)).getUTCDay()];
  return getLang() === "ko" ? `${mo}/${d}(${wd})` : `${wd} ${mo}/${d}`;
}

/** The times an item shows and changes: the event itself, or the new time for a move
 *  항목이 보여 주고 바꾸는 시간: 일정 자체, 옮기기면 새 시간 */
const timesOf = (item) => (item.kind === "move" ? item.ev.new : item.ev);

/** Same start: the same date for all-day events, the same moment for timed ones
 *  시작이 같은지: 종일 일정은 같은 날짜, 시간 일정은 같은 시각 */
function sameStart(a, b) {
  if (a.all_day || b.all_day) return !!a.all_day === !!b.all_day && a.start.slice(0, 10) === b.start.slice(0, 10);
  return Date.parse(a.start) === Date.parse(b.start);
}

const normTitle = (s) => String(s).replace(/\s+/g, "").toLowerCase();

/** An event to add that already exists (same title, same start). Unknown until AM/PM is chosen.
 *  이미 있는 일정인지 (같은 제목, 같은 시작). 오전/오후를 고르기 전에는 판단하지 않는다 */
const isDuplicate = (item) =>
  item.kind === "add" && item.ampm !== null &&
  (item.ev.nearby || []).some((x) => normTitle(x.title) === normTitle(item.ev.title) && sameStart(x, item.ev));

/** Start/end in ms of a timed event; with no end it's taken as 1 hour / 시간 일정의 시작·끝 (끝이 없으면 1시간) */
function spanOf(ev) {
  const s = Date.parse(ev.start);
  return [s, ev.end ? Date.parse(ev.end) : s + 3600000];
}

/** Existing timed events whose time overlaps the event to add (duplicates and all-day events left out)
 *  추가할 일정과 시간이 겹치는 기존 시간 일정 (중복과 종일 일정은 제외) */
function overlapping(item) {
  const { ev } = item;
  if (item.kind !== "add" || item.ampm === null || ev.all_day) return [];
  const [s, e] = spanOf(ev);
  return (ev.nearby || []).filter((x) => {
    if (x.all_day || (normTitle(x.title) === normTitle(ev.title) && sameStart(x, ev))) return false;
    const [xs, xe] = spanOf(x);
    return xs < e && s < xe;
  });
}

/** "'팀 회의'(15:00 ~ 16:00)": the name with its time; the date is added when it starts on another day
 *  "'팀 회의'(15:00 ~ 16:00)": 이름과 시간. 다른 날 시작하면 날짜도 붙인다 */
function overlapLabel(x, ev) {
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const s = new Date(x.start);
  const day = (d) => `${d.getMonth() + 1}/${d.getDate()}`;
  const otherDay = day(s) !== day(new Date(ev.start));
  const time = (otherDay ? `${day(s)} ` : "") + hm(s) + (x.end ? ` ~ ${hm(new Date(x.end))}` : "");
  return `'${x.title}'(${time})`;
}

function whenHtml(item) {
  const { kind, ev } = item;
  const target = timesOf(item);
  const shown = item.ampm === null
    ? `${dayLabel(target.start)} · ${t("popup.ampm.pick")}`
    : formatWhen(target);
  const warn = (text) => `<div class="meta warn">${icon("info")}<span>${escapeHtml(text)}</span></div>`;
  const others = overlapping(item);
  const notes =
    (isDuplicate(item) ? warn(t("popup.duplicate")) : "") +
    (others.length ? warn(t("popup.overlap", { titles: others.map((x) => overlapLabel(x, ev)).join(", ") })) : "");
  return kind === "move"
    ? `<div class="meta">${icon("clock")}<s>${escapeHtml(formatWhen(ev))}</s></div>
       <div class="meta new">${icon("arrow")}${escapeHtml(shown)}</div>`
    : `<div class="meta">${icon("clock")}${escapeHtml(shown)}</div>${notes}`;
}

function ampmHtml(item) {
  if (!item.orig) return "";
  const btn = (pm) => {
    const v = withAmpm(item.orig, pm);
    const on = item.ampm === (pm ? "pm" : "am");
    return `<button type="button" class="chip${on ? " selected" : ""}" data-ampm="${pm ? "pm" : "am"}" aria-pressed="${on}">${escapeHtml(ampmLabel(v.start))}</button>`;
  };
  return `<div class="ampm" role="group" aria-label="${escapeHtml(t("popup.ampm.pick"))}">${btn(false)}${btn(true)}</div>`;
}

function renderItem(kind, ev, checked) {
  const key = `k${items.size}`;
  const target = kind === "move" ? ev.new : ev;
  const unclear = !!ev.ampm_unclear && !target.all_day;
  // ampm: null = not chosen yet / orig: the times Claude guessed
  // ampm: null 이면 아직 안 고름 / orig: Claude가 추정한 시간
  const item = { kind, ev, ampm: unclear ? null : "fixed", orig: unclear ? { start: target.start, end: target.end } : null };
  items.set(key, item);
  // An event that already exists starts unchecked / 이미 있는 일정은 선택 해제로 시작
  if (isDuplicate(item)) checked = false;
  const li = document.createElement("li");
  li.className = `item ${kind}${checked ? "" : " unchecked"}`;
  li.innerHTML = `
    <input type="checkbox" data-key="${key}" ${checked ? "checked" : ""} aria-label="${escapeHtml(t("popup.select", { title: ev.title }))}">
    <div class="content">
      <div class="title-row"><span class="tag ${kind}">${t(`popup.tag.${kind}`)}</span><span class="title">${escapeHtml(ev.title)}</span></div>
      <div class="when">${whenHtml(item)}</div>
      ${ampmHtml(item)}
      ${ev.location ? `<div class="meta">${icon("pin")}${escapeHtml(ev.location)}</div>` : ""}
      ${ev.description ? `<div class="meta">${escapeHtml(ev.description)}</div>` : ""}
    </div>`;
  const box = li.querySelector("input");
  li.addEventListener("click", (e) => {
    const chip = e.target.closest("button[data-ampm]");
    if (chip) {
      // Pick AM/PM: update the times and select the event / 오전·오후 선택: 시간을 바꾸고 일정을 선택
      item.ampm = chip.dataset.ampm;
      Object.assign(timesOf(item), withAmpm(item.orig, item.ampm === "pm"));
      li.querySelector(".when").innerHTML = whenHtml(item);
      li.querySelectorAll("button[data-ampm]").forEach((b) => {
        b.classList.toggle("selected", b === chip);
        b.setAttribute("aria-pressed", b === chip);
      });
      box.checked = true;
      li.classList.remove("unchecked", "attention");
      // Clear the "choose AM or PM" notice once nothing is left to choose
      // 고를 일정이 더 없으면 "오전/오후를 골라야" 안내를 지운다
      if (!groupsEl.querySelector(".item.attention")) setStatus("", "");
      return;
    }
    if (e.target !== box) box.checked = !box.checked;
    li.classList.toggle("unchecked", !box.checked);
  });
  box.addEventListener("change", () => li.classList.toggle("unchecked", !box.checked));
  return li;
}

function addGroup(title, kind, list, note, checked) {
  const section = document.createElement("div");
  section.className = "group";
  section.innerHTML =
    `<h2 class="section-label">${icon(LABEL_ICON[kind])}${escapeHtml(title)}</h2>` +
    (note ? `<p class="note">${escapeHtml(note)}</p>` : "");
  const ul = document.createElement("ul");
  ul.className = "items";
  list.forEach((ev) => ul.appendChild(renderItem(kind, ev, checked ?? ev.selected ?? true)));
  section.appendChild(ul);
  groupsEl.appendChild(section);
}

/** Group of existing events found by a delete/move condition
 *  취소·변경 조건으로 찾은 기존 일정 묶음 */
function addLookupGroup(c, kind) {
  const range = (c.date_from === c.date_to ? c.date_from : `${c.date_from} ~ ${c.date_to}`) + (c.time ? ` ${c.time}` : "");
  const label = c.keyword ? `'${c.keyword}'` : t("popup.allInRange");
  if (!c.matches.length) {
    addGroup(t(`popup.group.${kind}None`), kind, [], t("popup.noneNote", { range, label }));
  } else if (c.exact) {
    addGroup(t(`popup.group.${kind}`), kind, c.matches);
  } else {
    addGroup(t(`popup.group.${kind}Pick`), kind, c.matches, t("popup.pickNote", { range, label }), false);
  }
}

function renderPreview(events, cancellations, moves) {
  items = new Map();
  groupsEl.innerHTML = "";
  moves.forEach((m) => addLookupGroup(m, "move"));
  cancellations.forEach((c) => addLookupGroup(c, "delete"));
  if (events.length) addGroup(t("popup.group.add"), "add", events, null, true);

  const kinds = new Set([...items.values()].map((x) => x.kind));
  applyBtn.textContent =
    kinds.size > 1 ? t("popup.applyMixed")
    : kinds.has("delete") ? t("popup.applyDelete")
    : kinds.has("move") ? t("popup.applyMove")
    : t("popup.applyAdd");
  applyBtn.hidden = !items.size;
  preview.hidden = false;
}

/** [Add details on web] / [Add details in app] (desktop app via notion://)
 *  [웹으로 세부 내용 추가] / [앱으로 세부 내용 추가] (notion:// 으로 PC 앱 열기) */
function openLinks(url) {
  if (!isNotionUrl(url)) return "";
  return `<a href="${escapeHtml(url)}" target="_blank">${escapeHtml(t("popup.openWeb"))}</a>` +
    `<span class="sep">/</span><a href="#" class="app-link" data-url="${escapeHtml(url)}">${escapeHtml(t("popup.openApp"))}</a>`;
}

/** Title, then the links on the line below
 *  제목 아래 줄에 링크 */
function detailLinks(url, text) {
  const links = openLinks(url);
  return `<span class="title">${escapeHtml(text)}</span>` + (links ? `<span class="actions">${links}</span>` : "");
}

// ---------- Recently deleted / 최근 삭제한 일정 ----------
// Notion's API can't search the trash, so events deleted here are recorded in the browser.
// Notion empties its trash after 30 days, so records are kept for the same time.
// Each record has a state: "deleted" → "restored" (can be deleted again) or "gone" (emptied from Notion's trash).
// Restored/gone records stay visible until the popup is reopened, so a wrong restore can be undone.
// 노션 API는 휴지통을 검색할 수 없어서, 여기서 삭제한 일정을 브라우저에 기록해 둔다.
// 노션 휴지통이 30일 뒤 비워지므로 기록도 같은 기간만 보관한다.
// 기록마다 상태가 있다: "deleted" → "restored"(다시 삭제 가능) 또는 "gone"(노션 휴지통에서 완전히 삭제됨).
// 복구·완전 삭제된 기록은 팝업을 다시 열 때까지 남겨 두어, 잘못 복구해도 되돌릴 수 있다.
const TRASH_KEY = "deleted";
const TRASH_DAYS = 30;
const DAY_MS = 86400000;
const trashEl = $("trash");
const trashList = $("trash-list");

function loadTrash() {
  try {
    const list = JSON.parse(localStorage.getItem(TRASH_KEY) || "[]");
    const cutoff = Date.now() - TRASH_DAYS * DAY_MS;
    return Array.isArray(list)
      ? list.filter((x) => x && typeof x.id === "string" && x.deleted_at > cutoff && (x.state || "deleted") === "deleted")
      : [];
  } catch {
    return [];
  }
}

// Records shown in the list (newest first)
// 목록에 보이는 기록 (최신순)
let trash = loadTrash().map((x) => ({ ...x, state: "deleted" }));
// Every record seen in this popup, including ones removed from the list (result-banner lines still use them)
// 이 팝업에서 본 모든 기록 (목록에서 지운 것도 결과 배너 줄이 계속 쓴다)
const known = new Map(trash.map((x) => [x.id, x]));

function saveTrash() {
  const keep = trash.slice(0, 100).map(({ error, ...x }) => x);
  try { localStorage.setItem(TRASH_KEY, JSON.stringify(keep)); } catch {}
}
saveTrash();

function rememberDeleted(evs) {
  if (!evs.length) return;
  const now = Date.now();
  const fresh = evs.map((e) => ({ id: e.id, title: e.title, start: e.start, end: e.end || "", all_day: !!e.all_day, deleted_at: now, state: "deleted" }));
  const ids = new Set(fresh.map((x) => x.id));
  trash = [...fresh, ...trash.filter((x) => !ids.has(x.id))];
  fresh.forEach((x) => known.set(x.id, x));
  saveTrash();
  renderTrash();
}

/** today / yesterday / N days ago (by calendar day)
 *  오늘 / 어제 / N일 전 (날짜 기준) */
function daysAgo(ts) {
  const day = (v) => new Date(v).setHours(0, 0, 0, 0);
  const n = Math.round((day(Date.now()) - day(ts)) / DAY_MS);
  return n <= 0 ? t("date.today") : n === 1 ? t("date.yesterday") : t("date.daysAgo", { n });
}

const whenOf = (x) => (x.start ? formatWhen(x) : "");
const actBtn = (x, act, label) =>
  `<button type="button" class="btn btn-secondary btn-small" data-act="${act}" data-id="${escapeHtml(x.id)}">${escapeHtml(label)}</button>`;
const actLink = (x, act, label) =>
  `<a href="#" data-act="${act}" data-id="${escapeHtml(x.id)}">${escapeHtml(label)}</a>`;
const errorLine = (x) => (x.error ? `<div class="meta error">${icon("error")}${escapeHtml(x.error)}</div>` : "");

function trashItem(x) {
  const restored = x.state === "restored";
  const links = restored ? openLinks(x.url) : "";
  const status =
    restored ? `<div class="meta">${icon("check")}${links || escapeHtml(t("popup.restoredTag"))}</div>`
    : x.state === "gone" ? `<div class="meta">${icon("info")}${escapeHtml(t("popup.gone"))}</div>`
    : `<div class="meta">${icon("trash")}${escapeHtml(t("popup.trash.deletedAt", { when: daysAgo(x.deleted_at) }))}</div>`;
  const main =
    x.state === "deleted" ? actBtn(x, "restore", t("popup.trash.restore"))
    : restored ? actBtn(x, "redelete", t("popup.redelete"))
    : "";
  const tag = restored ? `<span class="tag restored">${escapeHtml(t("popup.restoredTag"))}</span>` : "";
  return `
    <li class="item ${x.state}" data-id="${escapeHtml(x.id)}">
      <div class="content">
        <div class="title-row">${tag}<span class="title">${escapeHtml(x.title)}</span></div>
        ${whenOf(x) ? `<div class="meta">${icon("clock")}${escapeHtml(whenOf(x))}</div>` : ""}
        ${status}${errorLine(x)}
      </div>
      <div class="item-actions">
        ${main}
        <button type="button" class="icon-btn small" data-act="dismiss" data-id="${escapeHtml(x.id)}" title="${escapeHtml(t("popup.trash.dismiss"))}" aria-label="${escapeHtml(t("popup.trash.dismiss"))}">${icon("close")}</button>
      </div>
    </li>`;
}

function renderTrash() {
  trashEl.hidden = !trash.length;
  trashEl.querySelector("summary").innerHTML =
    `${icon("chevron")}${escapeHtml(t("popup.trash.title", { n: trash.length }))}`;
  trashList.innerHTML = trash.map(trashItem).join("");
}

/** An added/deleted event's line in the result banner
 *  - added / restored: title · time · [Delete], then [Add details on web] / [Add details in app] below
 *  - deleted: title · time, then [Undo] below
 *  [Delete] always sits right after the time, whatever the popup width.
 *  결과 배너의 추가·삭제 일정 줄
 *  - 추가됨 / 복구됨: 제목 · 시간 · [삭제], 아래 줄에 [웹으로 세부 내용 추가] / [앱으로 세부 내용 추가]
 *  - 삭제됨: 제목 · 시간, 아래 줄에 [되돌리기]
 *  [삭제]는 팝업 폭과 관계없이 항상 시간 바로 뒤에 둔다. */
function bannerLine(x) {
  const when = whenOf(x) ? `<span class="when">${escapeHtml(whenOf(x))}</span>` : "";
  const title = `<span class="title">${escapeHtml(x.title)}</span>${when}`;
  if (x.state === "added" || x.state === "restored") {
    const head = x.state === "added" ? icon("plus")
      : `${icon("check")}<span class="tag restored">${escapeHtml(t("popup.restoredTag"))}</span>`;
    const links = openLinks(x.url);
    const del = `<span class="del">${actLink(x, "redelete", t("popup.delete"))}</span>`;
    return `${head}${title}${del}${links ? `<span class="actions">${links}</span>` : ""}${errorLine(x)}`;
  }
  const action = x.state === "gone" ? `<span>${escapeHtml(t("popup.gone"))}</span>` : actLink(x, "restore", t("popup.undo"));
  return `${icon("trash")}${title}<span class="actions">${action}</span>${errorLine(x)}`;
}

/** Redraw one record everywhere it appears (the list and the result banner)
 *  한 기록이 보이는 곳(목록·결과 배너)을 다시 그린다 */
function refresh(id) {
  renderTrash();
  const x = known.get(id);
  statusEl.querySelectorAll("li[data-id]").forEach((li) => {
    if (li.dataset.id === id && x) li.innerHTML = bannerLine(x);
  });
}

/** [Restore]/[Undo], [Delete]/[Delete again], [×] (removes from the list only; Notion is untouched)
 *  [복구]/[되돌리기], [삭제]/[다시 삭제], [×](목록에서만 지움, 노션은 그대로) */
async function trashAction(control) {
  const { act, id } = control.dataset;
  const x = known.get(id);
  if (!x || control.dataset.busy) return;
  if (act === "dismiss") {
    trash = trash.filter((y) => y.id !== id);
    saveTrash();
    return refresh(id);
  }
  control.dataset.busy = "1";
  control.textContent = t(act === "restore" ? "popup.restoring" : "popup.redeleting");
  delete x.error;
  try {
    if (act === "restore") {
      const res = await callHost({ action: "restore", id });
      Object.assign(x, res.gone ? { state: "gone" } : { state: "restored", url: res.url });
      // [Undo] in the result message: the event is back, so it leaves the recently deleted list
      // (its line in the result still has [Delete], which puts it back in the list).
      // [Restore] in the list keeps the entry, with [Delete again], in case it was the wrong one.
      // 결과 메시지의 [되돌리기]: 일정이 돌아왔으니 최근 삭제 목록에서 뺀다
      // (결과 줄의 [삭제]로 다시 지우면 목록에 다시 들어간다).
      // 목록의 [복구]는 잘못 복구했을 때를 위해 [다시 삭제]와 함께 남겨 둔다.
      if (!res.gone && control.closest("#status")) trash = trash.filter((y) => y.id !== id);
    } else {
      await callHost({ action: "apply", delete: [{ id, title: x.title }] });
      Object.assign(x, { state: "deleted", deleted_at: Date.now() });
      if (!trash.includes(x)) trash.unshift(x);
    }
  } catch (e) {
    // Shown on that line, so the rest of the screen stays as it is
    // 그 줄에 표시해 나머지 화면은 그대로 둔다
    x.error = e instanceof SetupError ? t("common.setupShort") : e.message;
  }
  saveTrash();
  refresh(id);
  loadWeek();
}

// ---------- Actions / 동작 ----------
async function parse() {
  const text = input.value.trim();
  if (!text) return input.focus();
  preview.hidden = true;
  setBusy(true, t("popup.parsing"));
  try {
    const { events, cancellations, moves } = await callHost({ action: "parse", text });
    if (!events.length && !cancellations.length && !moves.length) {
      setStatus("info", escapeHtml(t("popup.notFound")));
      return;
    }
    setStatus("", "");
    renderPreview(events, cancellations, moves);
  } catch (e) {
    showError(e);
  } finally {
    setBusy(false);
  }
}

async function apply() {
  const checked = [...groupsEl.querySelectorAll("input:checked")];
  // Selected events whose AM/PM hasn't been chosen yet: point them out and stop
  // 오전/오후를 아직 고르지 않은 선택 일정: 표시하고 멈춘다
  const unclear = checked.filter((c) => items.get(c.dataset.key).ampm === null);
  if (unclear.length) {
    unclear.forEach((c) => c.closest("li").classList.add("attention"));
    return setStatus("info", escapeHtml(t("popup.ampm.needed")));
  }
  const chosen = checked.map((c) => items.get(c.dataset.key));
  const add = chosen.filter((x) => x.kind === "add").map((x) => x.ev);
  const del = chosen.filter((x) => x.kind === "delete").map((x) => ({ id: x.ev.id, title: x.ev.title }));
  const move = chosen.filter((x) => x.kind === "move").map((x) => x.ev);
  if (!add.length && !del.length && !move.length) return setStatus("info", escapeHtml(t("popup.selectOne")));

  setBusy(true, t("popup.applying"));
  try {
    const { added, deleted, moved } = await callHost({ action: "apply", add, delete: del, move });
    preview.hidden = true;
    input.value = "";
    saveDraft();
    // Keep what was deleted so it can be restored later
    // 나중에 복구할 수 있도록 삭제한 일정을 기록한다
    const doneIds = new Set(deleted.map((r) => r.id));
    rememberDeleted(chosen.filter((x) => x.kind === "delete" && doneIds.has(x.ev.id)).map((x) => x.ev));
    // Added events can be deleted right from the result (the host keeps the request order)
    // 추가한 일정은 결과에서 바로 삭제할 수 있다 (호스트가 요청 순서를 유지한다)
    const addedEntries = added.map((r, i) => ({
      id: r.id, title: r.title, url: r.url, start: add[i].start, end: add[i].end || "", all_day: !!add[i].all_day, state: "added",
    }));
    addedEntries.forEach((x) => known.set(x.id, x));
    // Re-format moved events in the UI language (the host's `when` is Korean-formatted)
    // 변경 결과는 화면 언어로 다시 포맷한다 (호스트가 준 when 은 한국어 형식)
    const movedEv = new Map(move.map((m) => [m.title, m]));
    const lines = [
      ...moved.map((r) => {
        const m = movedEv.get(r.title);
        return `<li>${icon("arrow")}${detailLinks(r.url, m ? `${formatWhen(m.new)} ${r.title}` : r.when)}</li>`;
      }),
      // Title + time, then [Undo] on the line below
      // 제목 + 시간, 아래 줄에 [되돌리기]
      ...deleted.map((r) => `<li data-id="${escapeHtml(r.id)}">${bannerLine(known.get(r.id) || { ...r, state: "deleted" })}</li>`),
      ...addedEntries.map((x) => `<li data-id="${escapeHtml(x.id)}">${bannerLine(x)}</li>`),
    ];
    const summary = [
      moved.length && t("popup.moved", { n: moved.length }),
      deleted.length && t("popup.deleted", { n: deleted.length }),
      added.length && t("popup.added", { n: added.length }),
    ].filter(Boolean).join(", ");
    setStatus("success", `<b>${escapeHtml(t("popup.done", { summary }))}</b><ul class="links">${lines.join("")}</ul>`);
    loadWeek();
  } catch (e) {
    showError(e);
  } finally {
    setBusy(false);
    input.focus();
  }
}

// Keep the draft even when the popup closes
// 팝업이 닫혀도 입력 중인 내용은 유지
function saveDraft() {
  try { localStorage.setItem(DRAFT_KEY, input.value); } catch {}
}
try { input.value = localStorage.getItem(DRAFT_KEY) || ""; } catch {}

form.addEventListener("submit", (e) => { e.preventDefault(); parse(); });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); parse(); }
});
input.addEventListener("input", saveDraft);
applyBtn.addEventListener("click", apply);

document.addEventListener("click", (e) => {
  // [Restore] / [Undo] / [Delete again] / [×] in the result banner and the recently deleted list
  // 결과 배너와 최근 삭제 목록의 [복구] / [되돌리기] / [다시 삭제] / [×]
  const control = e.target.closest("[data-act]");
  if (control) {
    e.preventDefault();
    return trashAction(control);
  }
  // Open the page in the Notion desktop app: the page ID at the end of the link → notion://www.notion.so/<id>
  // (works for both https://app.notion.com/p/<id> and https://www.notion.so/<title>-<id>)
  // The current tab hands the link to Windows (no new empty tab), and Chrome may ask "Open Notion?" the first time.
  // 노션 PC 앱으로 페이지 열기: 링크 끝의 페이지 ID로 notion://www.notion.so/<id> 를 만든다.
  // (https://app.notion.com/p/<id> 와 https://www.notion.so/<제목>-<id> 모두 처리)
  // 현재 탭이 링크를 윈도우에 넘기므로 빈 탭이 생기지 않고, 처음에는 크롬이 "Notion을 여시겠습니까?"를 물을 수 있다.
  const a = e.target.closest("a.app-link");
  if (!a) return;
  e.preventDefault();
  if (!isNotionUrl(a.dataset.url)) return;
  const id = new URL(a.dataset.url).pathname.replace(/-/g, "").match(/[0-9a-f]{32}$/i);
  const appUrl = id ? `notion://www.notion.so/${id[0]}` : a.dataset.url.replace(/^https?:\/\//, "notion://");
  chrome.tabs.update({ url: appUrl }).catch(() => chrome.tabs.create({ url: appUrl }));
});
$("cancel").addEventListener("click", () => { preview.hidden = true; setStatus("", ""); input.focus(); });
$("settings").addEventListener("click", () => chrome.runtime.openOptionsPage());
renderTrash();

// ---------- This week's events / 이번 주 일정 ----------
// Shown when the popup opens, as a list by day or as Mon–Sun calendar columns (settings page).
// Each event is marked past (✓) · now (●) · upcoming (→). Clicking one opens it in Notion.
// 팝업을 열 때 날짜별 목록 또는 월~일 캘린더 칸으로 보여 준다 (설정 페이지에서 선택).
// 일정마다 지남(✓) · 진행 중(●) · 예정(→)을 표시하고, 누르면 노션에서 연다.
const weekEl = $("week");
const weekBody = $("week-body");
const WEEK_MARK = { past: "done", now: "dot", next: "arrow" };
const pad2 = (n) => String(n).padStart(2, "0");
const hhmm = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
/** Local "YYYY-MM-DD" of a Date / Date 의 로컬 "YYYY-MM-DD" */
const ymd = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;

function addDays(day, n) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** Days an event is shown on: all-day → every day it covers, timed → its start day
 *  일정을 보여 줄 날: 종일은 걸친 모든 날, 시간 일정은 시작한 날 */
function daysOf(ev) {
  if (!ev.all_day) return [ymd(new Date(ev.start))];
  const out = [];
  const end = (ev.end || ev.start).slice(0, 10);
  for (let d = ev.start.slice(0, 10); d <= end && out.length < 62; d = addDays(d, 1)) out.push(d);
  return out;
}

/** "past" | "now" | "next" (timed events with no end count as 1 hour)
 *  지남 | 진행 중 | 예정 (끝이 없는 시간 일정은 1시간) */
function statusOf(ev, now = Date.now()) {
  if (ev.all_day) {
    const today = ymd(new Date(now));
    if ((ev.end || ev.start).slice(0, 10) < today) return "past";
    return ev.start.slice(0, 10) > today ? "next" : "now";
  }
  const [s, e] = spanOf(ev);
  return now >= e ? "past" : now >= s ? "now" : "next";
}

const timeText = (ev) =>
  ev.all_day ? t("date.allDay") : hhmm(new Date(ev.start)) + (ev.end ? ` ~ ${hhmm(new Date(ev.end))}` : "");

const weekMark = (st) =>
  `<span class="wk-mark ${st}" title="${escapeHtml(t(`popup.week.${st}`))}">${icon(WEEK_MARK[st])}</span>`;

/** { "YYYY-MM-DD": [events] } for the 7 days, all-day first then by start
 *  7일 각각의 일정 (종일 먼저, 그다음 시작 순) */
function groupByDay(data) {
  const days = Array.from({ length: 7 }, (_, i) => addDays(data.from, i));
  const byDay = Object.fromEntries(days.map((d) => [d, []]));
  for (const ev of data.events) for (const d of daysOf(ev)) if (byDay[d]) byDay[d].push(ev);
  const key = (ev) => (ev.all_day ? 0 : 1) * 1e13 + Date.parse(ev.all_day ? ev.start.slice(0, 10) : ev.start);
  for (const d of days) byDay[d].sort((a, b) => key(a) - key(b));
  return { days, byDay };
}

function renderWeekList(data) {
  const { days, byDay } = groupByDay(data);
  if (!data.events.length) return `<p class="note">${escapeHtml(t("popup.week.empty"))}</p>`;
  return days
    .filter((d) => byDay[d].length || d === data.today)
    .map((d) => {
      const rows = byDay[d].map((ev) => {
        const st = statusOf(ev);
        return `<li class="wk-item ${st}" data-url="${escapeHtml(ev.url)}" title="${escapeHtml(t("popup.week.open"))}">` +
          `${weekMark(st)}<span class="wk-time">${escapeHtml(timeText(ev))}</span>` +
          `<span class="wk-title">${escapeHtml(ev.title)}</span>` +
          (st === "now" ? `<span class="tag now">${escapeHtml(t("popup.week.now"))}</span>` : "") +
          `</li>`;
      }).join("") || `<li class="wk-empty">${escapeHtml(t("popup.week.dayEmpty"))}</li>`;
      const today = d === data.today ? `<span class="tag today">${escapeHtml(t("popup.week.today"))}</span>` : "";
      return `<div class="wk-day${d === data.today ? " today" : ""}${d < data.today ? " past" : ""}">` +
        `<div class="wk-day-head">${escapeHtml(dayLabel(d))}${today}</div><ul class="wk-list">${rows}</ul></div>`;
    })
    .join("");
}

function renderWeekCalendar(data) {
  const { days, byDay } = groupByDay(data);
  const names = t("date.weekdays").split(",");
  return `<div class="wk-grid">` + days.map((d) => {
    const [y, m, dd] = d.split("-").map(Number);
    const wd = names[new Date(Date.UTC(y, m - 1, dd)).getUTCDay()];
    const chips = byDay[d].map((ev) => {
      const st = statusOf(ev);
      const time = ev.all_day ? t("date.allDay") : hhmm(new Date(ev.start));
      return `<div class="wk-chip ${st}" data-url="${escapeHtml(ev.url)}" title="${escapeHtml(`${timeText(ev)} ${ev.title}`)}">` +
        `<span class="wk-chip-time">${weekMark(st)}${escapeHtml(time)}</span><span class="wk-chip-title">${escapeHtml(ev.title)}</span></div>`;
    }).join("");
    const cls = d === data.today ? " today" : d < data.today ? " past" : "";
    return `<div class="wk-col${cls}"><div class="wk-col-head"><span>${escapeHtml(wd)}</span><b>${dd}</b></div>${chips}</div>`;
  }).join("") + `</div>`;
}

let weekSeq = 0;

/** Load and show this week (again after any change) / 이번 주 일정을 불러와 보여 준다 (바뀔 때마다 다시) */
async function loadWeek() {
  const view = getWeekView();
  // The calendar needs more room, so the popup gets wider / 캘린더는 칸이 많아 팝업을 넓힌다
  document.body.classList.toggle("wide", view === "calendar");
  if (view === "off") return (weekEl.hidden = true);
  const seq = ++weekSeq;
  weekEl.hidden = false;
  $("week-legend").innerHTML = ["past", "now", "next"]
    .map((st) => `<span>${weekMark(st)}${escapeHtml(t(`popup.week.${st}`))}</span>`).join("");
  if (!weekBody.innerHTML) {
    $("week-title").innerHTML = `${icon("clock")}${escapeHtml(t("popup.week.title"))}`;
    weekBody.innerHTML = `<p class="note">${escapeHtml(t("popup.week.loading"))}</p>`;
  }
  try {
    const data = await callHost({ action: "week" });
    if (seq !== weekSeq) return;
    $("week-title").innerHTML = `${icon("clock")}${escapeHtml(t("popup.week.title"))}` +
      `<span class="range">${escapeHtml(`${dayLabel(data.from)} ~ ${dayLabel(data.to)}`)}</span>`;
    weekBody.innerHTML = view === "calendar" ? renderWeekCalendar(data) : renderWeekList(data);
  } catch (e) {
    if (seq !== weekSeq) return;
    // Not set up yet: the setup notice elsewhere covers it / 아직 설정 전이면 다른 곳의 안내로 충분
    if (e instanceof SetupError) return (weekEl.hidden = true);
    weekBody.innerHTML = `<p class="note">${escapeHtml(t("popup.week.error"))}</p>`;
  }
}

weekBody.addEventListener("click", (e) => {
  const el = e.target.closest("[data-url]");
  if (el && isNotionUrl(el.dataset.url)) chrome.tabs.create({ url: el.dataset.url });
});
loadWeek();

// ---------- New version notice / 새 버전 안내 ----------
// × hides it until an even newer version is released
// × 를 누르면 그보다 새 버전이 나올 때까지 숨긴다
const UPDATE_DISMISSED_KEY = "updateDismissed";

async function showUpdateNotice() {
  if (!updateCheckEnabled()) return;
  const rel = await latestRelease();
  if (!rel || !isNewer(rel.version, currentVersion())) return;
  let dismissed = "";
  try { dismissed = localStorage.getItem(UPDATE_DISMISSED_KEY) || ""; } catch {}
  if (dismissed === rel.version) return;
  const el = $("update");
  el.innerHTML =
    `${icon("info")}<div class="body">${escapeHtml(t("update.available", { version: rel.version, current: currentVersion() }))} ` +
    `<a href="${escapeHtml(rel.url)}" target="_blank">${escapeHtml(t("update.view"))}</a></div>` +
    `<button type="button" class="icon-btn small" title="${escapeHtml(t("update.dismiss"))}" aria-label="${escapeHtml(t("update.dismiss"))}">${icon("close")}</button>`;
  el.querySelector("button").addEventListener("click", () => {
    try { localStorage.setItem(UPDATE_DISMISSED_KEY, rel.version); } catch {}
    el.hidden = true;
  });
  el.hidden = false;
}
showUpdateNotice();
