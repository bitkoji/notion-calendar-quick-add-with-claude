**English** | [한국어](README.ko.md)

# Natural language → Notion Calendar

Type something like "Team meeting tomorrow 3 PM for 1 hour" and Claude works out the date and time and adds the event to a Notion database.
If that database is connected to Notion Calendar, the event shows up on your calendar right away.

**No API key needed.** Claude is called through the Claude Code CLI (`claude -p`), so it runs on your Claude Pro/Max subscription.

Repository: https://github.com/bitkoji/notion-calendar-quick-add-with-claude

## Requirements

- **Windows** (the Chrome extension's local helper is registered in the Windows registry; the command line also works elsewhere)
- **Python 3.9+** (the `py` launcher from python.org)
- **Chrome** or **Edge**
- **Claude Code** with a Claude Pro/Max login: https://claude.com/claude-code
- A **Notion** account

## 1. Install

Download the project (or use **Code → Download ZIP** on GitHub and unzip it):

```powershell
git clone https://github.com/bitkoji/notion-calendar-quick-add-with-claude.git
cd notion-calendar-quick-add-with-claude
py -m pip install -r requirements.txt
copy .env.example .env
```

Keep the folder where it is after setup; if you move it, run `install_host.py` again (step 4-3).

Claude Code must be installed and logged in with a Pro account. You're ready when `claude auth status` shows `"subscriptionType": "pro"`. If you're not logged in, run `claude` and type `/login`.

## 2. Set up Notion

1. **API connection token**: https://www.notion.so/profile/integrations (Developer tools → Connections) → `+ New connection` → enter a name and pick a workspace → `•••` next to the new connection → **Copy API token** → put it in `NOTION_TOKEN` in `.env`
   (Notion renamed "Integrations" to "Connections". On Free/Plus plans only the workspace owner can create one.)
2. **Database**
   - Create a calendar database in Notion (a title + a **date** property) or use an existing one
   - On the database page, top right `•••` → `More` → **Connections** → `Add connection` → pick the connection you just made (skipping this gives a 404 error)
   - From the database link `https://www.notion.so/xxxx/<32-char ID>?v=...`, put `<32-char ID>` in `NOTION_DATABASE_ID`
3. (Optional) Notion Calendar app → Settings → Notion → show that database

## 3. Command line

```powershell
py notion_cal.py "Dinner with a friend at Gangnam Station next Friday at 7 PM"
py notion_cal.py "Jeju trip from Dec 24 to 26"
py notion_cal.py "Dentist tomorrow at 10, project review the day after from 2 to 4 PM"   # several events at once
py notion_cal.py "Cancel tomorrow's dentist appointment"                               # delete an event
py notion_cal.py "Move Wednesday's team meeting to the next day"                       # reschedule
py notion_cal.py "Change the team meeting's location to room 201"                      # change title or location
py notion_cal.py "Study group every Tuesday at 7 PM for 4 weeks"                       # repeating event
py notion_cal.py                 # interactive mode (keep typing)
py notion_cal.py -y "..."        # add without confirming
py notion_cal.py --dry-run "..." # show the parse only (no Notion setup needed)
```

The command-line output is in Korean.

## 4. Chrome extension

Click the extension icon in the toolbar to open the "Which event should I add to your Notion calendar?" input.
Type and press Enter → check the parsed events (select them with checkboxes) → **Add / Delete / Apply** to Notion.

- **Cancel**: "Cancel tomorrow's dentist" → finds events on that date whose title contains "dentist" and lists them for deletion.
  If you don't give a date, it searches from today through one year ahead. If nothing matches, it lists that period's events unselected so you can pick.
- **Move**: "Move Wednesday's meeting to the next day", "Push the meeting back an hour", "Change the meeting to Friday 10 AM"
  → the new time is computed from the original event's actual time in Notion (the duration is kept). Only the existing page's date changes, so the page content stays as it is.
- **Change title or location**: "Change the team meeting's location to room 201", "Rename Friday's lunch to 'Lunch with Minsu'"
  → the preview shows the old and new values; the rest of the page stays as it is. Changing the location needs a location text property in the database.
- **Repeating events**: "Study group every Tuesday at 7 PM for 4 weeks", "Rent on the 25th of every month until December", "Every other Monday standup"
  → each occurrence becomes its own event in the preview, so you can uncheck the ones you don't want (Notion's API has no repeating events).
  With no end given, it repeats for 3 months; one request makes at most 60. Picking AM/PM on one occurrence applies to all of them.
- **Right-click a selection**: select text on a web page (an e-mail, a notice, ...) → right-click → **Add to Notion Calendar** → the popup opens with that text and shows the preview. Nothing is added until you press Add, and any deletes or changes found in the text start unchecked.
- When parsing a request, Claude is also shown your upcoming events (from a week ago to 60 days ahead) so it picks the event you mean.
- Deleted events go to the Notion trash and can be restored within 30 days.
- **This week**: when the popup opens, it shows this week's events, each marked past (✓), now (●) or upcoming (→). Click one to open it in Notion; use ‹ › to see the previous or next week. Each event has **Delete** (at the end of the row in the list view, under the event in the calendar view) (restore it with **Undo** in the result message or from Recently deleted). Choose a list by day, calendar columns, or hide it on the settings page (This week's events). The week starts on Monday by default; change it under Database properties → First day of the week (also used for "this week" / "next week" in requests).
- **Duplicates and overlaps**: if an event with the same title already exists at the same time, the preview says so and leaves it unchecked. If its time overlaps another event, the preview shows which one ("Overlaps with 'Team meeting'(15:00 ~ 16:00)") but keeps it checked. The command line skips duplicates and prints overlaps.
- **Asks for what's missing, like a secretary**: if you leave out the date, the time (for events that usually have one: "vocabulary test every Monday", "dentist") or the place (for events you usually go somewhere for: "dinner with Minsu on Friday"), the preview asks "When?", "What time?", "Where?" or "When and where?" with a text box. Answer in plain language ("next Tuesday 3 PM, Gangnam Station") and press **OK**; Claude reads it again. Each question stays until it's answered: if you answer only the time, it keeps asking for the date and place. The date and time must be answered before applying; the place can be left out, or answered "none". You can answer again to change things. Naturally all-day events (trips, birthdays, deadlines) and online or personal to-dos aren't asked about. For a repeating event, the time and place apply to all of it. The command line asks the same way (leave it empty to keep it as it is).
- If a time could be AM or PM ("meeting tomorrow at 3"), the preview shows **AM 3:00 / PM 3:00** buttons and nothing is applied until you pick one. The command line asks the same question.
- After adding, each event in the result shows its time and **Add details on web / Add details in app / Delete**, so a wrong one can be removed right away.
- **Restore**: press **Undo** under a deleted event in the result message (each one shows its time), or open **Recently deleted** at the bottom of the popup and press **Restore**.
  If you restored the wrong one, press **Delete again**. **×** removes an entry from the list only (Notion isn't changed).
  The list shows events deleted with this extension in the last 30 days (Notion's API can't search the trash, so the extension keeps this record in the browser). Only events in the configured database are restored.
- "Delete the event I just added" works too: Claude is also shown your 10 most recently created events with their creation time.

Install (once):
1. Finish steps 1–2 above (`.env` setup) first.
2. In Chrome go to `chrome://extensions` → turn on **Developer mode** (top right) → **Load unpacked** → pick the `extension` folder inside the project folder
3. Copy the extension **ID** shown (32 letters) and run the register command:
   ```powershell
   py install_host.py <extension ID>
   ```
   (The extension popup also shows this command with the ID filled in.)
4. Pin it from the puzzle icon in the toolbar for easy access.
5. **Keyboard shortcut**: press `Ctrl+Shift+Y` to open the input while a Chrome window is in front. To change it, use Settings → Keyboard shortcut → **Change shortcut** (opens `chrome://extensions/shortcuts`).
   If the settings page says no shortcut is set, another extension already uses those keys; if pressing it does nothing, another program does. Pick a different combination in either case.

**Settings page**: the gear at the top right of the popup (or right-click the extension icon → Options) lets you change the Claude model, language (English/한국어), timezone, Notion token, database and properties.
The language applies to the extension UI and error messages and changes when you press **Save**, like the other settings (it's stored in the extension, not in `.env`). At first the extension starts in Korean if Chrome's language is Korean, and in English otherwise.
The timezone defaults to "Automatic from PC": the extension reports the OS timezone (e.g. `America/New_York`). If you pick one on the settings page, it's saved in `.env` and takes priority. (The command-line `notion_cal.py` uses `Asia/Seoul` when `.env` has no timezone.)
Saving writes to `.env`, so the extension and the command line share the same settings. No part of the token is ever shown on screen (only whether one is saved); saving with the field empty keeps the existing token.
You can paste the Notion link straight into the database field; "Test connection" loads the list of properties.

Architecture: extension → Chrome Native Messaging → `native_host/host.py` → `claude -p` (Pro subscription) + Notion API.
To unregister, run `py install_host.py --uninstall`. If you move the folder, run step 3 again.

**Updates**: the extension checks the latest [GitHub release](https://github.com/bitkoji/notion-calendar-quick-add-with-claude/releases) once a day and shows "Version X is available" at the top of the popup. Only the version is requested; no personal data or events are sent. You can turn this off on the settings page (Updates → Check for new versions automatically), or press **Check now** there.
To update, run `git pull` in the project folder (or download the zip again), then press reload (↻) on the extension in `chrome://extensions`.

## How it works

- A JSON schema (`--json-schema`) is passed to `claude -p` so the events come back structured. Tools, MCP and user settings are turned off to keep it light; one run takes about 5 seconds.
- Relative dates are computed from the current time and timezone. With no time, the event is all-day; with no duration, it's assumed to be 1 hour.
- The `ANTHROPIC_API_KEY` environment variable is removed when running, because if it's set, usage is billed to the API instead of your subscription.
- Usage counts against your Pro plan limits (shared with claude.ai and Claude Code).
- The database's title/date properties are detected automatically. To set the names yourself, use the optional entries in `.env`.
- The **location** ("ML206", "Gangnam Station Starbucks", ...) is saved exactly as typed in the database's text property `위치` (Location).
  Create one **text** property named `Location` (or `위치` / `장소`) in the database (without it, the location is written in the page body as "장소: …").
  Note: the built-in "Location" field in a Notion Calendar event is for Google Calendar events only, so for Notion database events it appears as the location property.
- Notes go into `NOTION_DESCRIPTION_PROPERTY` (a text property), or into the page body if it isn't set.
- For personal use only. Using a subscription login to provide this as a service to other people isn't allowed under Anthropic's terms.
