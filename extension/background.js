// Right-click menu: send the selected text on a web page to the popup.
// The text goes into the popup's input and is interpreted as usual, so nothing is added before the preview.
// 우클릭 메뉴: 웹페이지에서 고른 글을 팝업으로 보낸다.
// 팝업 입력 칸에 들어가 평소처럼 해석되므로, 미리보기 전에는 아무것도 추가되지 않는다.

// Same values as common.js / common.js 와 같은 값
const MENU_ID = "add-selection";
const PENDING_TEXT_KEY = "pendingText";
// Longer selections are cut (an e-mail's worth is enough) / 이보다 긴 글은 자른다 (메일 한 통이면 충분)
const MAX_TEXT = 2000;

// The popup renames the item to the extension's language later; until then the browser's is used
// 이름은 나중에 팝업이 확장 화면 언어로 바꾼다. 그 전에는 브라우저 언어를 쓴다
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU_ID, title: chrome.i18n.getMessage("menuAddSelection"), contexts: ["selection"] });
  });
});

chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== MENU_ID) return;
  const text = String(info.selectionText || "").trim().slice(0, MAX_TEXT);
  if (!text) return;
  await chrome.storage.session.set({ [PENDING_TEXT_KEY]: text });
  try {
    await chrome.action.openPopup();
  } catch {
    // The popup can't open (e.g. no focused browser window): open it in a small window instead
    // 팝업을 열 수 없으면 (예: 앞에 있는 브라우저 창이 없을 때) 작은 창으로 연다
    chrome.windows.create({ url: "popup.html?window", type: "popup", width: 460, height: 680 });
  }
});
