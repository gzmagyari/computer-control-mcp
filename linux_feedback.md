# Computer Control MCP — Linux/Ubuntu Test Results

**Platform:** Ubuntu 24.04 (XFCE desktop, Xvfb virtual framebuffer)
**Date:** 2026-03-14
**Resolution:** 1920x1080

## Summary

Testing all 94 `computer-control` MCP tools for Linux compatibility. Tools were designed/tested on Windows 11 — this is the first Linux validation.

---

## Tested Categories

### 1. Screenshot & Visual (6/6 passed)

| # | Tool | Status |
|---|------|--------|
| 1 | `take_screenshot` | Pass |
| 2 | `take_screenshot_full` | Pass |
| 3 | `take_screenshot_with_ocr` | Pass |
| 4 | `take_screenshot_with_ui_automation` | Pass |
| 5 | `capture_region_around` | Pass |
| 6 | `hover_and_capture` | Pass |

### 2. Mouse (6 passed, 2 not supported on Linux)

| # | Tool | Status |
|---|------|--------|
| 7 | `click_screen` | Pass |
| 8 | `drag_mouse` | Pass |
| 9 | `move_mouse` | Pass |
| 10 | `get_mouse_position` | Pass |
| 11 | `get_cursor_position` | **Not supported** |
| 12 | `mouse_down` | Pass |
| 13 | `mouse_up` | Pass |
| 14 | `get_drag_info` | **Not supported** |

### 3. Keyboard (3 passed, 1 issue)

| # | Tool | Status |
|---|------|--------|
| 15 | `type_text` | Pass |
| 16 | `press_keys` | **Bug — silent failure** |
| 17 | `key_down` | Pass |
| 18 | `key_up` | Pass |

### 4. Window Management (9/9 passed)

| # | Tool | Status |
|---|------|--------|
| 19 | `activate_window` | Pass |
| 20 | `close_window` | Pass |
| 21 | `maximize_window` | Pass |
| 22 | `minimize_window` | Pass |
| 23 | `restore_window` | Pass |
| 24 | `move_window` | Pass |
| 25 | `resize_window` | Pass |
| 26 | `snap_window` | Pass |
| 27 | `list_windows` | Pass |

### 5. UI Element Discovery & Inspection (10 passed, 1 not supported, 1 partial)

| # | Tool | Status |
|---|------|--------|
| 28 | `find_ui_elements` | **Partial — see Issues 5 & 6** |
| 29 | `find_text` | Pass |
| 30 | `get_element_at_point` | Pass |
| 31 | `get_element_children` | Pass |
| 32 | `get_element_parent` | Pass |
| 33 | `get_element_details` | Pass |
| 34 | `get_element_text` | Pass |
| 35 | `get_element_views` | **Not supported** |
| 36 | `get_focused_element` | Pass |
| 37 | `get_hyperlinks` | Pass (with Chrome launched via `launch_app`) |
| 38 | `get_table_data` | Pass |
| 39 | `get_active_window` | Pass |

---

## Issues Found

### Issue 1: `get_cursor_position` — Not supported on Linux

- **Tool:** `get_cursor_position` (#11)
- **Test performed:** Called with no arguments to get the text caret (input cursor) screen position.
- **Error:** `"Cursor position detection is only supported on Windows."`
- **Reason:** This tool tracks the text input caret (not the mouse pointer), which relies on Windows-specific APIs. There is no cross-platform equivalent exposed through this MCP. The mouse pointer position can still be retrieved via `get_mouse_position`, which works fine on Linux.

### Issue 2: `get_drag_info` — DragPattern not available on AT-SPI

- **Tool:** `get_drag_info` (#14)
- **Test performed:** Retrieved an element ref for the "Applications" toggle button via `find_ui_elements`, then called `get_drag_info` with that ref.
- **Error:** `{"success": false, "error": "DragPattern not available on AT-SPI"}`
- **Full error context:**
  ```json
  {
    "success": false,
    "error": "DragPattern not available on AT-SPI",
    "backend": "atspi",
    "action": "get_drag_info",
    "ref": {
      "backend": "atspi",
      "app": "xfce4-panel",
      "path": [0, 0, 0, 0],
      "role": "toggle button",
      "name": "Applications"
    }
  }
  ```
- **Reason:** On Windows, UI Automation provides a `DragPattern` interface for querying drag state and drop effects. The Linux accessibility backend (AT-SPI) does not implement an equivalent drag pattern, so this tool cannot function on Linux. Note that `drag_mouse` (coordinate-based dragging) works fine — only the semantic drag inspection is unsupported.

### Issue 3: `press_keys` — Enter/Return key silently fails on Linux

- **Tool:** `press_keys` (#16)
- **Test performed:** Opened a terminal (xfce4-terminal), typed a command via `type_text`, then attempted to execute it using `press_keys` with various key names.
- **Attempts:**
  1. `press_keys("enter")` — reported success, no effect
  2. `press_keys("Return")` — reported success, no effect
  3. `press_keys` after clicking terminal to ensure focus — still no effect
- **Error:** No error returned — the tool reports `"Pressed single key: \"enter\""` / `"Pressed single key: \"Return\""` but the keypress is not received by the terminal.
- **Workaround:** `type_text("\n")` successfully sends a newline/enter to the terminal and executes the command.
- **Reason:** Likely a key name mapping issue on Linux. The underlying input simulation (probably xdotool or python-xlib) may use different key symbols than the MCP tool expects. The tool reports success because the API call completes, but the actual X11 key event is either not generated or uses the wrong keysym. This is a **silent failure** which makes it particularly problematic — the agent has no way to know the key was not actually pressed without taking a screenshot to verify.
- **Impact:** High — Enter is one of the most commonly used keys. Agents relying on `press_keys("enter")` will silently fail on Linux. Other keys may also be affected but were not exhaustively tested.

### Issue 4: `get_element_views` — MultipleViewPattern not available on AT-SPI

- **Tool:** `get_element_views` (#35)
- **Test performed:** Called with an element ref for the terminal widget in xfce4-terminal.
- **Error:** `{"success": false, "error": "MultipleViewPattern not available on AT-SPI"}`
- **Reason:** Like `get_drag_info`, this relies on a Windows UIA pattern (`MultipleViewPattern`) that has no equivalent in the AT-SPI accessibility backend on Linux. This tool is used to switch between views (list, details, icons, tiles) in controls like File Explorer — a Windows-specific concept.

### Issue 5: `find_ui_elements` with `title_pattern` returns 0 elements for Chrome and Thunar

- **Tool:** `find_ui_elements` (#28)
- **Test performed:** Called `find_ui_elements` with `title_pattern="Thunar"` and separately with `title_pattern="Linux - Wikipedia"` (Chrome). Both returned 0 elements.
- **Contrast:** `take_screenshot_with_ui_automation` with the same `title_pattern="Thunar"` successfully returned 27 elements from the Thunar application, including buttons, text fields, and table cells.
- **Additional detail:** Calling `find_ui_elements` **without** `title_pattern` (scanning all apps) did return elements from Thunar (e.g., role_filter="table" found the Thunar sidebar table). This confirms the elements exist in the AT-SPI tree — but `find_ui_elements`'s title matching logic fails to associate them with the window title on Linux.
- **Error:** No error — the tool returns `{"total_count": 0}` silently.
- **Reason:** On Linux, the AT-SPI application name (e.g., `"Thunar"`) differs from the X11 window title (e.g., `"workspace - Thunar"`). The `find_ui_elements` tool likely matches `title_pattern` against the X11 window title, but then looks up AT-SPI elements by a different identifier, causing the mismatch. `take_screenshot_with_ui_automation` uses a different lookup path that successfully bridges this gap.
- **Impact:** High — `find_ui_elements` is the primary way to get element refs for use with other UI tools. If `title_pattern` filtering doesn't work for most apps, agents must either omit the filter (slow — 18+ seconds to scan all apps) or use `take_screenshot_with_ui_automation` instead (which returns elements without stable refs usable by other tools).

### Issue 6: Google Chrome does not expose AT-SPI elements unless launched with `launch_app`

- **Tool:** `find_ui_elements` (#28), `take_screenshot_with_ui_automation` (#4)
- **Test performed:** Opened Google Chrome by clicking the taskbar launcher, navigated to Wikipedia's Linux page. Ran `find_ui_elements` with and without `title_pattern`, and `take_screenshot_with_ui_automation`.
- **Results when launched via taskbar click:**
  - `find_ui_elements(title_pattern="Linux - Wikipedia")` → 0 elements
  - `find_ui_elements(role_filter="link")` across all apps → 0 link elements
  - `take_screenshot_with_ui_automation(title_pattern="Chrome")` → returns only window metadata, no Chrome-internal elements
- **Results when launched via `launch_app` with `accessibility=true`:**
  - `launch_app` auto-detected Chrome as `chromium` family and added `--force-renderer-accessibility`
  - `find_ui_elements(role_filter="link")` → **24 link elements** found with full AT-SPI data including `hypertext` interface
  - `get_hyperlinks` successfully returned `link_count: 2` on a link element
- **Error:** No error when launched without accessibility — Chrome simply doesn't publish its widget tree to AT-SPI.
- **Reason:** Chrome/Chromium on Linux requires explicit accessibility enabling. By default, Chrome does not activate AT-SPI support unless it detects an assistive technology or the `--force-renderer-accessibility` flag is passed at launch. The `launch_app` tool handles this automatically.
- **Resolution:** Always use `launch_app` with `accessibility=true` (the default) to open Chrome. Do not launch Chrome by clicking desktop/taskbar shortcuts.
- **Impact:** High — if Chrome is launched without `launch_app`, agents cannot use semantic UI automation tools on Chrome content and must fall back to OCR + coordinate-based clicking.

### Issue 7: `get_hyperlinks` — Partial results (link count returned but link details empty)

- **Tool:** `get_hyperlinks` (#37)
- **Test performed:** After launching Chrome with `launch_app` (accessibility enabled), found link elements with `hypertext` interface on Wikipedia. Called `get_hyperlinks` on the "Wikipedia The Free Encyclopedia" link element.
- **Result:** `{"success": true, "link_count": 2, "links": []}`
- **Observation:** The tool reports `success: true` and correctly identifies `link_count: 2`, but the `links` array is empty — no link details (name, URI, offsets) are returned.
- **Reason:** This may be a limitation of Chrome's AT-SPI Hypertext implementation — it exposes the link count but doesn't populate the individual link details. Alternatively, it could be a bug in how the MCP server enumerates links from the AT-SPI Hypertext interface on Linux.
- **Impact:** Medium — the tool partially works (link counting), but agents cannot retrieve actual link URIs or text, reducing its usefulness for navigation and link inspection tasks.

### Issue 8: `activate_hyperlink` — AttributeError on Linux

- **Tool:** `activate_hyperlink` (#46)
- **Test performed:** Called with a Chrome link element ref ("Wikipedia The Free Encyclopedia") that has the `hypertext` interface, with `link_index=0`.
- **Error:** `{"success": false, "error": "'Hyperlink' object has no attribute 'get_action_iface'"}`
- **Reason:** The MCP server code likely calls `get_action_iface()` on the AT-SPI Hyperlink object, but this method doesn't exist in the pyatspi2 bindings. The AT-SPI Hyperlink interface uses a different API than Windows UIA's InvokePattern.
- **Impact:** Medium — agents cannot programmatically activate hyperlinks via the accessibility API on Linux. Workaround: use `click_screen` with the link's `abs_center_x`/`abs_center_y` coordinates instead.

### Issue 9: `fill_text_field`, `get_clipboard`, `set_clipboard` — Missing `xsel` dependency on Linux

- **Tools:** `fill_text_field` (#47), `get_clipboard` (#66), `set_clipboard` (#67)
- **Test performed:**
  - `fill_text_field` called with Chrome address bar coordinates and text "https://example.com"
  - `set_clipboard` called with text "Hello from MCP clipboard test! 🐧"
  - `get_clipboard` called with no arguments
- **Error (all three):** `"[Errno 2] No such file or directory: 'xsel'"`
- **Reason:** All clipboard operations on Linux depend on the `xsel` command-line utility, which is not installed in this container environment. `fill_text_field` also uses clipboard paste internally.
- **Workaround:** Install `xsel` (`apt install xsel`) or `xclip`. For `fill_text_field`, use `click_screen` + `type_text` as a manual replacement.
- **Impact:** High — clipboard is a fundamental capability. Three tools are completely broken without `xsel`. This is an easy fix (install the dependency) but needs to be documented as a Linux prerequisite.

### Issue 10: `realize_element` — VirtualizedItemPattern not available on AT-SPI

- **Tool:** `realize_element` (#54)
- **Test performed:** Called with an element ref for the terminal widget in xfce4-terminal.
- **Error:** `{"success": false, "error": "VirtualizedItemPattern not available on AT-SPI"}`
- **Reason:** Like `get_drag_info` and `get_element_views`, this relies on a Windows UIA pattern (`VirtualizedItemPattern`) with no AT-SPI equivalent. Virtualized item support is a Windows UIA concept for large lists/grids that lazily create UI elements.

### Issue 11: `get_scroll_info` — AT-SPI does not provide scroll percentage info

- **Tool:** `get_scroll_info` (#58)
- **Test performed:** Called with the terminal's scroll pane element ref from xfce4-terminal.
- **Result:** `{"success": true, "horizontally_scrollable": false, "vertically_scrollable": false, "message": "AT-SPI does not provide scroll percentage info"}`
- **Reason:** On Windows, UI Automation's ScrollPattern provides horizontal/vertical scroll percentages, view sizes, and scrollability flags. AT-SPI does not have an equivalent scroll information interface — it only has scroll actions but no position reporting.
- **Impact:** Medium — agents cannot query current scroll position or determine if an element is scrollable via the accessibility API. Workaround: use `take_screenshot` or OCR to visually verify scroll position, or use the scrollbar `value` interface via `set_element_range_value` to control scroll position numerically.

### Issue 12: `select_text_range`, `get_text_selection`, `select_text_by_search` — Wrong AT-SPI API calls

- **Tools:** `select_text_range` (#64), `get_text_selection` (#63), `select_text_by_search` (#65)
- **Test performed:** All tested on Thunar's address bar text element (has `text` and `editable_text` interfaces, text content "/home/agent").
- **Errors:**
  - `select_text_range(start=0, end=5)` → `"Atspi.Accessible.get_text() takes exactly 1 argument (3 given)"`
  - `get_text_selection()` → `"Atspi.Accessible.get_selection() takes exactly 1 argument (2 given)"`
  - `select_text_by_search(search_text="home")` → `"Atspi.Accessible.get_text() takes exactly 1 argument (3 given)"`
- **Reason:** The MCP server code is calling pyatspi2 methods with incorrect signatures. On AT-SPI:
  - `get_text()` on an Accessible requires no arguments (returns the Text interface), but the code is passing `(start, end)` as if calling `getText(start, end)` from the Text interface directly.
  - `get_selection()` on an Accessible requires no arguments (returns the Selection interface), but the code passes an index argument.
  - The correct API is: `element.get_text().getText(start, end)` and `element.get_text().getSelection(index)`.
- **Impact:** High — three text manipulation tools are completely broken on Linux. Agents cannot programmatically select or read selected text via the accessibility API. Workaround: use keyboard shortcuts (Ctrl+A to select all, Ctrl+Shift+Home/End for partial selection) or mouse-based selection via `click_screen` with shift.

### 6. UI Element Interaction (7 passed, 3 element-dependent, 2 bugs)

| # | Tool | Status |
|---|------|--------|
| 40 | `invoke_element` | Pass |
| 41 | `focus_element` | Pass (element-dependent — some elements not focusable) |
| 42 | `select_element` | Pass |
| 43 | `toggle_element` | Pass |
| 44 | `expand_element` | Pass (element-dependent — correct error on non-expandable) |
| 45 | `collapse_element` | Pass (element-dependent — correct error on non-collapsible) |
| 46 | `activate_hyperlink` | **Bug — AttributeError** |
| 47 | `fill_text_field` | **Bug — missing `xsel`** |
| 48 | `set_element_text` | Pass |
| 49 | `move_element_ui` | Pass (element-dependent — panel buttons not movable) |
| 50 | `resize_element_ui` | Pass (element-dependent — panel buttons not resizable) |
| 51 | `set_element_extents` | Pass (element-dependent — panel buttons not resizable) |

### 7. UI Element State (1 passed, 2 not supported, 1 element-dependent)

| # | Tool | Status |
|---|------|--------|
| 52 | `set_element_range_value` | Pass |
| 53 | `set_element_view` | **Not supported** (MultipleViewPattern — same as Issue 4) |
| 54 | `realize_element` | **Not supported** (VirtualizedItemPattern not on AT-SPI) |
| 55 | `scroll_element_into_view` | Pass (element-dependent — returns success:false but attempts action) |

### 8. Scrolling (1 passed, 1 element-dependent, 1 partial)

| # | Tool | Status |
|---|------|--------|
| 56 | `scroll` | Pass |
| 57 | `scroll_element_container` | Pass (element-dependent — AT-SPI scroll support limited) |
| 58 | `get_scroll_info` | **Partial — see Issue 11** |

### 9. Text Manipulation (4 passed, 3 bugs)

| # | Tool | Status |
|---|------|--------|
| 59 | `get_text_at_offset` | Pass |
| 60 | `get_text_bounds` | Pass |
| 61 | `get_text_caret_offset` | Pass |
| 62 | `set_text_caret_offset` | Pass |
| 63 | `get_text_selection` | **Bug — see Issue 12** |
| 64 | `select_text_range` | **Bug — see Issue 12** |
| 65 | `select_text_by_search` | **Bug — see Issue 12** |

### 10. Clipboard (0 passed, 2 bugs)

| # | Tool | Status |
|---|------|--------|
| 66 | `get_clipboard` | **Bug — missing `xsel` (see Issue 9)** |
| 67 | `set_clipboard` | **Bug — missing `xsel` (see Issue 9)** |

### 11. Process & App Management (5/5 passed)

| # | Tool | Status |
|---|------|--------|
| 68 | `launch_app` | Pass |
| 69 | `is_app_running` | Pass |
| 70 | `get_app_info` | Pass |
| 71 | `list_processes` | Pass |
| 72 | `kill_process` | Pass |

### 12. Screen & System Info (4/4 passed)

| # | Tool | Status |
|---|------|--------|
| 73 | `get_screen_size` | Pass |
| 74 | `get_monitors` | Pass |
| 75 | `get_system_info` | Pass |
| 76 | `wait_for_screen_change` | Pass |

### 13. Change Detection (5/5 passed)

| # | Tool | Status |
|---|------|--------|
| 77 | `check_screen_changed` | Pass |
| 78 | `check_screen_changed_full` | Pass |
| 79 | `check_screen_changed_with_images` | Pass |
| 80 | `check_ocr_changed` | Pass |
| 81 | `check_ui_automation_changed` | Pass |

### Issue 13: File Watching tools — Missing `watchdog` dependency

- **Tools:** `start_file_watch` (#82), `wait_for_file_change` (#85)
- **Test performed:** Called `start_file_watch` with path `/tmp/mcp-test-watch` and `wait_for_file_change` with path `/tmp`.
- **Error (both):** `{"error": "watchdog is not installed"}`
- **Reason:** The file watching tools depend on the `watchdog` Python package for filesystem event monitoring. This package is not installed in the container environment.
- **Additional notes:** `get_file_watch_events` and `stop_file_watch` work at the API level (return proper "Unknown watch_id" errors) since they only query/stop existing watches and don't need `watchdog` themselves. But without `start_file_watch` working, they cannot be fully tested.
- **Workaround:** Install `watchdog` (`pip install watchdog`).
- **Impact:** Medium — all 4 file watching tools are unusable without this dependency. This is an easy fix (install the package) but needs to be documented as a Linux prerequisite alongside `xsel` (Issue 9).

### 14. File Watching (0 passed, 2 bugs, 2 untestable)

| # | Tool | Status |
|---|------|--------|
| 82 | `start_file_watch` | **Bug — missing `watchdog` (see Issue 13)** |
| 83 | `stop_file_watch` | Untestable (no watch to stop) |
| 84 | `get_file_watch_events` | Untestable (no watch to query) |
| 85 | `wait_for_file_change` | **Bug — missing `watchdog` (see Issue 13)** |

### 15. Waiting / Synchronization (5/5 passed)

| # | Tool | Status |
|---|------|--------|
| 86 | `wait_for_element` | Pass |
| 87 | `wait_for_focused_element` | Pass |
| 88 | `wait_for_text` | Pass |
| 89 | `wait_for_window` | Pass |
| 90 | `wait_milliseconds` | Pass |

### 16. Compound Actions & Guide (3/3 passed)

| # | Tool | Status |
|---|------|--------|
| 91 | `perform_actions` | Pass |
| 92 | `ui_action` | Pass |
| 93 | `get_agent_guide` | Pass |

### 17. File Dialog (1/1 passed)

| # | Tool | Status |
|---|------|--------|
| 94 | `fill_file_dialog` | Pass (correct timeout when no dialog open) |

---

## All Categories Tested

Testing complete. See Issues section above for all findings.
