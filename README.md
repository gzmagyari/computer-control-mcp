# Computer Control MCP (Enhanced)

### Enhanced MCP server for full computer control: mouse, keyboard, screenshots, OCR, deep UI automation, semantic element actions, process management, filesystem watching, and accessibility-aware app launching. Built for AI agents that need to see, understand, and interact with desktop applications.

> Enhanced fork of [computer-control-mcp](https://github.com/AB498/computer-control-mcp) by AB498.

<div align="center" style="text-align:center;font-family: monospace; display: flex; align-items: center; justify-content: center; width: 100%; gap: 10px">
    <a href="https://img.shields.io/badge/License-MIT-yellow.svg"><img
            src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge&color=00CC00" alt="License: MIT"></a>
    <a href="https://pypi.org/project/computer-control-mcp-enhanced"><img
            src="https://img.shields.io/pypi/v/computer-control-mcp-enhanced?style=for-the-badge" alt="PyPi"></a>
</div>

---

## Quick Usage (MCP Setup Using `uvx`)

*Running `uvx computer-control-mcp-enhanced@latest` for the first time will download Python dependencies (~70MB). Subsequent runs are instant.*

```json
{
  "mcpServers": {
    "computer-control": {
      "command": "uvx",
      "args": ["computer-control-mcp-enhanced@latest"]
    }
  }
}
```

Or install globally with `pip`:
```bash
pip install computer-control-mcp-enhanced
computer-control-mcp-enhanced
```

## What's New (vs upstream)

This fork adds significant perception and automation capabilities for AI agents:

- **UI Automation** — Full Windows UI Automation (UIA) and Linux AT-SPI tree traversal with occlusion filtering, exposing interactive elements (buttons, text fields, menus) with absolute screen coordinates
- **Deep UI Automation** — Discover elements with stable refs, traverse the element tree (parent/child navigation), and perform semantic actions (toggle, select, invoke, set text/range values, expand/collapse, move/resize) — no coordinate math needed
- **Combined perception** (`take_screenshot_full`) — Image + OCR + UI automation in a single call with parallel execution, selectable via `include_image`/`include_ocr`/`include_ui` flags
- **Region capture** — All screenshot/OCR/UI tools accept a `region=[x, y, w, h]` parameter to capture arbitrary screen rectangles instead of full screen or full window
- **Coordinate verification** (`capture_region_around`) — Capture a small area around target coordinates with an optional red circle marker for visual verification before clicking
- **Wait & polling tools** — `wait_for_window` (appear/disappear/active), `wait_for_focused_element`, `wait_for_screen_change` — synchronize with application state instead of blind delays
- **Filesystem watching** — Persistent directory watchers with event queues, or one-shot waits for file changes. Monitor builds, downloads, or any filesystem activity
- **Process & system management** — `kill_process`, `list_processes`, `get_system_info` — full process lifecycle and system diagnostics
- **Accessibility-aware app launching** (`launch_app`) — Launch apps with the right accessibility flags for maximum UI element exposure (e.g. `--force-renderer-accessibility` for Chromium, `ACCESSIBILITY_ENABLED=1` for VS Code on Linux)
- **Change detection** — Pixel diff, OCR diff, and UI diff tools to detect what changed on screen between actions
- **Screenshot optimization** — Prescaling to agent-friendly sizes, WebP/JPEG compression, grayscale/BW modes for token savings
- **Performance** — Parallel OCR tiling for full-screen captures, `app_filter` to skip irrelevant window trees in UI automation (~18s to ~0.2s for targeted windows), role-based heuristics instead of expensive COM pattern queries

## Features

- Full mouse control (click, move, drag, button hold)
- Keyboard input (type text, press keys, key combinations, hold keys)
- Screenshots of full screen, specific windows, or arbitrary regions
- OCR text extraction with absolute screen coordinates
- UI automation element detection (buttons, fields, menus, etc.)
- Deep UI automation with stable element refs, tree traversal, and semantic actions
- Semantic element actions: toggle, select, invoke, focus, expand/collapse, set text, set range value, move/resize
- Window management (list, activate, wait for appear/disappear/active, fuzzy/regex matching)
- Process management (list, kill) and system diagnostics (CPU, memory, disk, OS)
- Filesystem watching (persistent watchers with event queues, one-shot file change waits)
- Screen change detection (pixel, OCR, and UI automation diffs)
- Accessibility-aware app launching for better UI element exposure
- Coordinate verification with visual markers for precise clicking
- Image optimization (format, quality, color mode, prescaling)
- GPU-accelerated window capture via WGC (Windows only)
- Clipboard operations
- Action batching via `perform_actions`

## Available Tools

### Mouse Control
| Tool | Description |
|------|-------------|
| `click_screen(x, y)` | Click at screen coordinates |
| `move_mouse(x, y)` | Move mouse to coordinates |
| `get_mouse_position()` | Get current mouse pointer coordinates |
| `drag_mouse(from_x, from_y, to_x, to_y, duration)` | Drag from one position to another |
| `mouse_down(button)` | Hold down a mouse button |
| `mouse_up(button)` | Release a mouse button |

### Keyboard Control
| Tool | Description |
|------|-------------|
| `type_text(text)` | Type text at current cursor position |
| `press_keys(keys)` | Press keys (single, sequences, or combinations like `[["ctrl", "c"]]`) |
| `key_down(key)` | Hold down a key |
| `key_up(key)` | Release a key |

### Screenshots & Perception
| Tool | Description |
|------|-------------|
| `take_screenshot(...)` | Capture screen/window/region as an image. Supports `title_pattern`, `region`, format/quality options |
| `take_screenshot_with_ocr(...)` | Screenshot + OCR text extraction with absolute coordinates |
| `take_screenshot_with_ui_automation(...)` | Get UI automation elements (buttons, fields, etc.) with coordinates |
| `take_screenshot_full(...)` | Combined image + OCR + UI automation in one call. Use `include_image`, `include_ocr`, `include_ui` flags to select layers |
| `capture_region_around(x, y, radius, mark_center, ...)` | Capture a small region around coordinates, optionally with a red circle marker for verification |

### Screen Change Detection
| Tool | Description |
|------|-------------|
| `check_screen_changed(...)` | Pixel-level diff between current screen and last baseline |
| `check_screen_changed_with_images(...)` | Pixel diff with annotated diff images |
| `check_screen_changed_full(...)` | Combined pixel + OCR + UI diff. Use `include_image_diff`, `include_ocr_diff`, `include_ui_diff` flags |
| `check_ocr_changed(...)` | Text-level diff via OCR (added/removed/changed text) |
| `check_ui_automation_changed(...)` | UI element diff (added/removed/changed elements) |
| `wait_for_screen_change(...)` | Poll until screen changes or timeout |

### Text Interaction
| Tool | Description |
|------|-------------|
| `find_text(text, ...)` | Find text on screen via OCR with fuzzy matching |
| `click_text(text, ...)` | Find and click on text |
| `fill_text_field(x, y, text, ...)` | Click a field, clear it, and type new text |

### Cursor & Position
| Tool | Description |
|------|-------------|
| `get_mouse_position()` | Current mouse pointer coordinates |
| `get_cursor_position()` | Text caret/cursor position (Windows only) |
| `get_screen_size()` | Screen resolution |

### Window & App Management
| Tool | Description |
|------|-------------|
| `list_windows()` | List all open windows with titles and positions |
| `activate_window(title_pattern, ...)` | Bring a window to foreground (fuzzy or regex matching) |
| `get_active_window()` | Get the currently active/foreground window |
| `close_window(title_pattern, ...)` | Close a window |
| `launch_app(command, ...)` | Launch an app with accessibility flags enabled for better UI automation |
| `wait_for_window(title_pattern, mode, ...)` | Wait for a window to appear, disappear, or become active |

### Deep UI Automation — Discovery
| Tool | Description |
|------|-------------|
| `find_ui_elements(title_pattern, ...)` | Deep-search UI elements by name, role, or text content with paging support |
| `get_focused_element(title_pattern, ...)` | Get the currently focused accessible element |
| `get_element_at_point(x, y)` | Get the deepest UI element at screen coordinates |
| `get_element_details(element_ref)` | Get full details of an element (patterns, states, properties) |
| `get_element_children(element_ref)` | Get child elements of a container |
| `get_element_parent(element_ref)` | Get parent element |

### Deep UI Automation — Semantic Actions
| Tool | Description |
|------|-------------|
| `focus_element(element_ref)` | Give keyboard focus to an element |
| `invoke_element(element_ref)` | Click/activate a button, link, or menu item |
| `toggle_element(element_ref)` | Toggle a checkbox, switch, or toggle button |
| `select_element(element_ref)` | Select a list item, tab, or radio button |
| `expand_element(element_ref)` | Expand a tree node, combo box, or menu |
| `collapse_element(element_ref)` | Collapse a tree node or combo box |
| `set_element_text(element_ref, text)` | Set text value of an input field |
| `get_element_text(element_ref)` | Read text value from an element |
| `scroll_element_into_view(element_ref)` | Scroll an element into the visible area |
| `set_element_range_value(element_ref, value)` | Set numeric value on a slider or range control |
| `move_element_ui(element_ref, x, y)` | Move an element (window) to a position |
| `resize_element_ui(element_ref, width, height)` | Resize an element (window) |
| `set_element_extents(element_ref, x, y, width, height)` | Move + resize in one call |
| `wait_for_focused_element(...)` | Wait until the focused element matches name/role filters |

### Process & System Management
| Tool | Description |
|------|-------------|
| `list_processes()` | List all running processes with PIDs and memory usage |
| `kill_process(process_name, pid, force)` | Kill/terminate a running process |
| `get_system_info()` | Get CPU, memory, disk, OS, and network information |

### Filesystem Watching
| Tool | Description |
|------|-------------|
| `start_file_watch(paths, ...)` | Start a persistent filesystem watcher, returns a watch_id |
| `get_file_watch_events(watch_id)` | Read queued events from a persistent watcher |
| `stop_file_watch(watch_id)` | Stop a persistent watcher |
| `wait_for_file_change(paths, timeout_ms)` | One-shot wait for the next filesystem change |

### Utilities
| Tool | Description |
|------|-------------|
| `set_clipboard(text)` | Set clipboard contents |
| `get_clipboard()` | Get clipboard contents |
| `wait_milliseconds(ms)` | Wait/sleep |
| `perform_actions(actions)` | Execute a batch of actions sequentially |
| `get_monitors()` | Get information about connected monitors |

## Region Capture

All screenshot, OCR, UI automation, and change detection tools accept a `region` parameter:

```python
# Capture just the top-left quadrant
take_screenshot_full(region=[0, 0, 960, 540])

# OCR only within a specific area
take_screenshot_with_ocr(region=[100, 200, 400, 300])

# Activate a window, then capture a sub-region of it
take_screenshot_full(title_pattern="Notepad", region=[1300, 280, 200, 100])

# Detect changes only within a region
check_screen_changed(region=[500, 500, 400, 300])
```

This lets an agent start with a full-screen capture, identify the area of interest, then focus subsequent captures on just that region to save tokens.

## Coordinate Verification Workflow

AI agents often misjudge coordinates from screenshots. The `capture_region_around` tool enables a verification loop:

1. Agent takes a full screenshot and estimates target coordinates
2. Calls `capture_region_around(x=500, y=300, mark_center=True)` to see a zoomed-in view with a red circle marker
3. Analyzes the small image to check if the marker is on the right element
4. Adjusts coordinates if needed and repeats
5. Once verified, clicks the confirmed coordinates

## Accessibility-Aware App Launching

The `launch_app` tool automatically applies the right accessibility flags per app family:

| App Family | Flag/Env Var | Platform |
|------------|-------------|----------|
| Chromium browsers | `--force-renderer-accessibility` | All |
| Electron apps | `--force-renderer-accessibility` | All |
| VS Code family | `ACCESSIBILITY_ENABLED=1` | Linux |
| Qt/KDE apps | `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` | Linux |
| GTK/GNOME apps | Session-level AT-SPI activation | Linux |

Example: Microsoft Edge exposes **90 UI elements** normally vs **199 elements** with the accessibility flag (2.2x increase).

```python
# Launch Chrome with accessibility enabled
launch_app(command=["google-chrome", "https://example.com"])

# Preview what would happen without launching
launch_app(command=["code", "."], dry_run=True)
```

## Deep UI Automation

Go beyond coordinate-based clicking — interact with UI elements semantically using stable element refs.

**Discovery:** Find elements by name, role, or text content across any window. Results include stable refs that can be passed directly to action tools.

```python
# Find all toggle switches in Windows Settings
find_ui_elements(title_pattern="Settings", role_filter="push button", text_filter="Night light")

# Get the element under specific coordinates
get_element_at_point(x=500, y=300)

# Navigate the element tree
get_element_children(element_ref={...})
get_element_parent(element_ref={...})
```

**Semantic Actions:** Toggle switches, select tabs, fill text fields, adjust sliders — all without calculating coordinates.

```python
# Toggle a switch
toggle_element(element_ref={...})

# Set a text field directly
set_element_text(element_ref={...}, text="Hello World")

# Adjust a slider
set_element_range_value(element_ref={...}, value=75)

# Select a tab or list item
select_element(element_ref={...})

# Move/resize a window via UI automation
set_element_extents(element_ref={...}, x=100, y=100, width=800, height=600)
```

Element refs survive minor UI changes (scrolling, focus shifts) but need re-discovery if the window title changes or the element tree restructures.

## Filesystem Watching

Monitor directories for file changes — useful for watching build output, downloads, or log files.

```python
# Persistent watcher
start_file_watch(paths="C:/project/dist")
# ... trigger a build ...
get_file_watch_events(watch_id="...")  # → created, modified, deleted events
stop_file_watch(watch_id="...")

# One-shot wait
wait_for_file_change(paths="C:/Users/me/Downloads", timeout_ms=30000)
```

Requires the `watchdog` Python library (`pip install watchdog`).

## Configuration

### Custom Screenshot Directory

```json
{
  "mcpServers": {
    "computer-control": {
      "command": "uvx",
      "args": ["computer-control-mcp-enhanced@latest"],
      "env": {
        "COMPUTER_CONTROL_MCP_SCREENSHOT_DIR": "C:\\Users\\YourName\\Pictures\\Screenshots"
      }
    }
  }
}
```

### Automatic WGC for Specific Windows

For GPU-accelerated windows that render black with standard capture:

```json
{
  "env": {
    "COMPUTER_CONTROL_MCP_WGC_PATTERNS": "obs, discord, game, steam"
  }
}
```

## Development

```bash
# Clone
git clone https://github.com/gzmagyari/computer-control-mcp.git
cd computer-control-mcp

# Install in dev mode (edits reflect immediately)
pip install -e .

# Run the server
computer-control-mcp-enhanced

# Run tests
python -m pytest

# Build
pip install hatch
hatch build
```

## License

MIT

Based on [computer-control-mcp](https://github.com/AB498/computer-control-mcp) by AB498.
