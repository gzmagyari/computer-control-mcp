# Computer Control MCP (Enhanced)

### Enhanced MCP server for full computer control: mouse, keyboard, screenshots, OCR, UI automation, region capture, and accessibility-aware app launching. Built for AI agents that need to see, understand, and interact with desktop applications.

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

- **UI Automation** — Full Windows UI Automation (UIA) tree traversal with occlusion filtering, exposing interactive elements (buttons, text fields, menus) with absolute screen coordinates
- **Combined perception** (`take_screenshot_full`) — Image + OCR + UI automation in a single call with parallel execution, selectable via `include_image`/`include_ocr`/`include_ui` flags
- **Region capture** — All screenshot/OCR/UI tools accept a `region=[x, y, w, h]` parameter to capture arbitrary screen rectangles instead of full screen or full window
- **Coordinate verification** (`capture_region_around`) — Capture a small area around target coordinates with an optional red circle marker for visual verification before clicking
- **Mouse/cursor position** (`get_mouse_position`, `get_cursor_position`) — Know where the pointer and text caret are for context-aware region captures
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
- Window management (list, activate, fuzzy/regex matching)
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
| `launch_app(command, ...)` | Launch an app with accessibility flags enabled for better UI automation |

### Utilities
| Tool | Description |
|------|-------------|
| `set_clipboard(text)` | Set clipboard contents |
| `wait_milliseconds(ms)` | Wait/sleep |
| `perform_actions(actions)` | Execute a batch of actions sequentially |

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
