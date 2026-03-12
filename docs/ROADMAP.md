# Computer Control MCP — Roadmap & Missing Capabilities

Audit of what's needed for full autonomous computer use. Based on real testing with Claude Code against Windows desktop + Microsoft Edge.

---

## Current Tool Inventory (as of 2026-03-12)

| Category | Tools | Status |
|----------|-------|--------|
| **Vision** | `take_screenshot`, `take_screenshot_with_ocr` (with `ocr_text_filter`), `take_screenshot_with_ui_automation`, `take_screenshot_full` (combined 3-layer), `capture_region_around`, `check_screen_changed` / `check_screen_changed_full` / `check_screen_changed_with_images`, `check_ocr_changed`, `check_ui_automation_changed`, `find_text` | Solid |
| **Mouse** | `click_screen` (left/right/middle, single/double via `button` + `num_clicks`), `move_mouse`, `drag_mouse`, `scroll` (with window activation), `mouse_down` / `mouse_up`, `get_mouse_position`, `get_cursor_position` | Solid |
| **Keyboard** | `type_text`, `press_keys`, `key_down` / `key_up` | Solid |
| **Windows** | `activate_window`, `list_windows`, `launch_app` | Partial — missing resize/move/minimize/maximize/close |
| **Utility** | `get_screen_size`, `wait_for_screen_change`, `wait_milliseconds`, `set_clipboard`, `perform_actions` (batch), `fill_text_field` | Partial — missing get_clipboard, conditional waits |

---

## High Priority — Fundamental Operations

### 1. Read Clipboard (`get_clipboard`)

**Gap:** We have `set_clipboard` but no way to READ the clipboard.

**Why it matters:**
- Copy-paste is one of the most reliable ways to extract exact text from any application
- Workflow: `Ctrl+A → Ctrl+C → get_clipboard()` gets exact text — more reliable than OCR for precision
- Needed for: extracting URLs, copying error messages, reading form values, transferring data between apps
- Without this, agents can see text (OCR) but can't reliably extract it for processing

**Implementation:** Simple — Python's `pyperclip.paste()` or `tkinter` clipboard access. Cross-platform.

**Priority:** Highest — one function, massive capability unlock.

---

### 2. Window Management (resize / move / minimize / maximize / close)

**Gap:** We can only activate windows. No way to resize, move, minimize, maximize, or close them.

**Why it matters:**
- Can't rearrange windows side-by-side (e.g., reference doc + code editor)
- Can't maximize an app to see more content or minimize something blocking the view
- Can't close dialogs or windows programmatically
- Currently requires fragile keyboard shortcuts (Win+Up to maximize, Alt+F4 to close)
- Window arrangement is fundamental to multi-app workflows

**Proposed tools:**
```
resize_window(title_pattern, width, height)
move_window(title_pattern, x, y)
minimize_window(title_pattern)
maximize_window(title_pattern)
restore_window(title_pattern)       # un-maximize / un-minimize
close_window(title_pattern)
snap_window(title_pattern, position)  # "left", "right", "top-left", etc.
```

**Implementation:**
- Windows: `MoveWindow()`, `ShowWindow()` with `SW_MAXIMIZE`, `SW_MINIMIZE`, `SW_RESTORE`, `PostMessage(WM_CLOSE)`
- Linux: `wmctrl` or `xdotool` commands
- macOS: AppleScript or `pyautogui` + accessibility APIs

**Priority:** High — multi-window workflows are common and keyboard shortcuts are unreliable.

---

### 3. Wait for Specific Condition (conditional wait / poll)

**Gap:** `wait_for_screen_change` only detects generic pixel differences. No way to wait for specific text or UI elements to appear/disappear.

**Why it matters:**
- Slow-loading pages: "wait until 'Loading...' disappears"
- File downloads: "wait until the download complete notification appears"
- Installations: "wait until the 'Finish' button is enabled"
- App startup: "wait until the main window appears"
- Currently agents must poll manually with repeated screenshot + check cycles, wasting tokens and time

**Proposed tools:**
```
wait_for_text(
    text="Loading|Please wait",        # pipe-separated, disappears when NOT found
    mode="appear" | "disappear",
    timeout=30,                         # seconds
    poll_interval=2,                    # seconds between checks
    title_pattern="Edge",
    region=[x, y, w, h]                 # optional — check only this area
) -> {"found": bool, "elapsed_s": float, "text": "matched text"}

wait_for_element(
    name_filter="Submit|Finish",
    role_filter="push button",
    mode="appear" | "disappear",
    timeout=30,
    poll_interval=2,
    title_pattern="Edge"
) -> {"found": bool, "elapsed_s": float, "element": {...}}
```

**Implementation:** Loop internally — take screenshot/OCR/UIA, check condition, sleep, repeat. Return when condition met or timeout. All polling happens server-side, saving the agent from multiple round-trips.

**Priority:** High — saves agents from building poll loops with 5-10 tool calls each time.

---

## Medium Priority — Common Real-World Needs

### 4. Hover / Tooltip Reading

**Gap:** No dedicated hover-and-read pattern. Some UIs only reveal info on hover (tooltips, preview popups, hover menus, status bar updates).

**Current workaround:** `move_mouse(x, y)` → `wait_milliseconds(500)` → `take_screenshot(region=...)` — works but manual.

**Proposed tool:**
```
hover_and_capture(
    x, y,
    hover_duration_ms=500,    # how long to hover before capturing
    radius=100,               # capture area around hover point
    include_ocr=true          # OCR the tooltip text
) -> [image, ocr_results]
```

**Why:** Convenience — collapses 3 calls into 1 and handles the timing automatically.

---

### 5. File Dialog Handling

**Gap:** Native OS file dialogs (Open/Save) are hard to automate. They're separate from the app's UI tree and have different UIA exposure on each platform.

**Current workaround:**
- `type_text("C:\\path\\to\\file.txt")` in the filename field + `press_keys("enter")` — works if you know the path
- UI automation to find the filename entry + navigate folders

**What would help:**
```
fill_file_dialog(
    path="C:\\Users\\me\\Documents\\report.pdf",
    action="open" | "save"
) -> str
```

**Implementation:** Platform-specific — find the file dialog window, locate the filename entry (UIA), clear it, type the path, click Open/Save. Tricky because dialog layouts differ across apps and OS versions.

**Priority:** Medium — workaround exists but is fragile.

---

### 6. Multi-Monitor Support

**Gap:** Unknown whether coordinates work correctly across multiple monitors (e.g., second display at x=1920+).

**Needs testing:**
- Does `take_screenshot()` capture all monitors or just the primary?
- Do OCR/UIA coordinates map correctly to the right monitor?
- Does `click_screen(x=2500, y=300)` click on the second monitor?
- Does `mss` capture regions spanning monitor boundaries?

**Proposed additions:**
```
get_monitors() -> [{"name": "Monitor 1", "x": 0, "y": 0, "width": 1920, "height": 1080, "primary": true}, ...]
take_screenshot(monitor=1)  # capture specific monitor
```

**Priority:** Medium — needed for multi-monitor setups (common for power users).

---

### 7. Process / Application Status

**Gap:** Is an app running? Did it crash? Has it finished loading? We have `list_windows` but no process-level info.

**What would help:**
```
is_app_running(name="chrome.exe") -> bool
wait_for_app(name="notepad.exe", timeout=10) -> {"running": bool, "window_title": "..."}
get_app_info(title_pattern="Edge") -> {"pid": 1234, "cpu_percent": 5.2, "memory_mb": 450, "responding": true}
```

**Why:** Detecting crashes, waiting for slow app startups, checking if an app is responding (not hung).

**Priority:** Medium — useful for robustness but not blocking for basic workflows.

---

## Lower Priority — Nice-to-Have

### 8. Screen Recording / Action Replay

**What:** Record agent actions as a video/GIF for debugging or QA test creation.

**Why:** When an agent does a 20-step workflow and something goes wrong at step 15, having a recording makes debugging much easier. Also useful for generating QA test documentation.

**Implementation:** Capture screenshots at each action step, stitch into GIF/video. Could be a wrapper around existing screenshot tools.

---

### 9. Conditional Wait with Callback Pattern

**What:** More advanced polling — "check every 2s, if condition X do action Y, if condition Z do action W, timeout after 30s".

**Example:** "Wait for either 'Accept cookies' dialog OR page loaded — if cookies dialog, click Accept; if page loaded, continue."

**Why:** Real-world web browsing has many conditional branches. Currently agents handle each branch manually.

---

### 10. Input Method / IME Support

**What:** `type_text` via pyautogui sends individual keystrokes, which doesn't work for non-Latin scripts (Chinese, Japanese, Korean, Arabic, etc.) that require input method editors.

**Current workaround:** `set_clipboard(text)` → `press_keys(["ctrl", "v"])` — works but destroys user's clipboard.

**Better solution:** `type_text` could detect non-ASCII and automatically use clipboard-based input, restoring the original clipboard afterward.

---

### 11. System Tray / Notification Area

**What:** Interact with system tray icons — right-click tray icon, read notification popups, dismiss notifications.

**Why:** Some apps (antivirus, VPN, chat apps, Docker) live primarily in the system tray. Notifications require dismissal to keep the desktop clean.

**Implementation:** Windows — UIA can access the notification area. Linux — varies by desktop environment.

---

### 12. Batch Coordinate Operations

**What:** Click/type/interact with a list of elements in sequence without round-tripping for each one.

**Example:** Fill a 10-field form in one call instead of 10 separate click_screen + type_text pairs.

**Current:** `perform_actions` may partially cover this — needs evaluation of its current capabilities and whether it's efficient enough for complex multi-step sequences.

---

## Recommended Implementation Order

| Order | Feature | Effort | Impact |
|-------|---------|--------|--------|
| 1 | `get_clipboard` | Small (1 function) | Very high — unlocks text extraction |
| 2 | Window management (resize/move/min/max/close) | Medium (5-6 functions) | High — multi-window workflows |
| 3 | Conditional wait (`wait_for_text`, `wait_for_element`) | Medium (2 functions with polling) | High — eliminates manual poll loops |
| 4 | Multi-monitor audit + `get_monitors` | Small (testing + 1 function) | Medium — needed for multi-monitor users |
| 5 | Hover + capture | Small (1 function) | Medium — convenience |
| 6 | File dialog handling | Medium (platform-specific) | Medium — common but has workaround |
| 7 | Process status | Small (2-3 functions) | Medium — robustness |
| 8 | IME/clipboard-based typing | Small (enhance type_text) | Low-Medium — needed for i18n |
| 9 | Screen recording | Medium | Low — debugging aid |
| 10 | System tray | Medium (platform-specific) | Low — niche use cases |
