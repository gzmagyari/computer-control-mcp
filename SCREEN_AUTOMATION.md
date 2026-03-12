# Screen Automation Knowledge Base

Everything learned from testing OS-level UI automation on the Dockerized XFCE desktop.

## Three-Layer Perception Model

No single source captures everything on screen. An AI agent needs all three:

| Layer | What it captures | What it misses | Speed |
|-------|-----------------|----------------|-------|
| **AT-SPI** (accessibility tree) | Widgets: buttons, menus, entries, tabs, toolbars, scroll bars, dialogs — with semantic names, roles, actions, keyboard shortcuts | Custom-drawn content (icon views, canvas), desktop icons | ~0.5s |
| **RapidOCR** (visual text detection) | Any visible text rendered on screen — file names in icon views, desktop icon labels, page content | Icons without text, non-text graphics | ~1.3s |
| **Screenshot** (raw image) | Everything visual — icons, graphics, layout, colors | No coordinates, no semantic info — requires vision model to interpret | ~0.1s |

**Always search both AT-SPI and OCR** when looking for an element. AT-SPI gives precise coordinates and semantic meaning; OCR fills the gaps for custom-drawn text.

## AT-SPI (Assistive Technology Service Provider Interface)

### What it is
Linux's accessibility framework. Apps expose their UI tree (widgets, names, roles, bounds, actions) via D-Bus. Python bindings: `gi.repository.Atspi` from `gir1.2-atspi-2.0`.

### Enabling accessibility by app type

| App type | How to enable | Env var / flag |
|----------|--------------|----------------|
| **GTK apps** (Thunar, XFCE panel, terminals) | Environment variable | `GTK_MODULES=gail:atk-bridge` |
| **Qt apps** | Environment variable | `QT_ACCESSIBILITY=1` and `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` |
| **Chromium/Electron** (Chrome, VSCode, Slack) | CLI flag | `--force-renderer-accessibility` |

General env var that signals accessibility is active: `ACCESSIBILITY_ENABLED=1`

### AT-SPI requires
- `at-spi2-core` package (bus launcher + registryd)
- `gir1.2-atspi-2.0` package (Python GObject bindings)
- D-Bus session bus running
- `at-spi2-registryd` running (usually auto-started)

### Basic usage
```python
import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

desktop = Atspi.get_desktop(0)
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    print(app.get_name(), app.get_child_count())
```

### Key element properties
- `get_role_name()` — "push button", "menu item", "entry", "page tab", "frame", etc.
- `get_name()` — human-readable label, e.g. "Source Control (Ctrl+Shift+G G)"
- `get_description()` — additional description
- `get_component_iface().get_extents(Atspi.CoordType.SCREEN)` — bounding box (x, y, width, height)
- `get_text_iface().get_text(0, n)` — text content for text widgets
- `get_action_iface()` — available actions (click, press, etc.)
- `get_state_set()` — states (focused, selected, visible, etc.)

### Known limitations
- **Custom-drawn widgets** (Thunar icon view, xfdesktop icons) appear as a single opaque widget with no children for individual items
- **AT-SPI `showing`/`visible` states** may not work correctly in all environments (didn't work in our Docker container) — cannot rely on them for occlusion detection
- **Chromium/Electron apps** expose nothing unless `--force-renderer-accessibility` is passed
- **Deprecated warnings**: `get_text()`, `get_action_name()` show deprecation warnings but still work

## RapidOCR

### What it is
Python OCR engine using ONNX Runtime. Detects text regions with bounding boxes (quadrilateral polygons). Installed via `pip install rapidocr-onnxruntime`.

### Comparison with Tesseract

| Metric | Tesseract | RapidOCR |
|--------|-----------|----------|
| Speed | ~0.4s (3x faster) | ~1.3s |
| Output granularity | Individual words (noisy) | Logical text lines/phrases (clean) |
| False positives | Many (fragments like "a", "ae", "3") | Zero — everything returned is real text |
| Avg confidence | 80.4% | 82.8% |
| Best for | Word-level positioning | UI automation (grouped labels, click targets) |

**RapidOCR is better for UI automation** because it returns meaningful grouped text regions rather than scattered words.

### Usage
```python
from rapidocr_onnxruntime import RapidOCR
engine = RapidOCR()
result, _ = engine("screenshot.png")
# result = [(box, text, confidence), ...]
# box = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]  (quadrilateral)
```

## Window Management & Occlusion

### The problem
AT-SPI reports elements from ALL running applications, even if their windows are hidden behind other windows. Naive dumping produces ghost elements from occluded windows.

### Solution: wmctrl + xprop stacking order
1. Get window stacking order from `xprop -root _NET_CLIENT_LIST_STACKING` (bottom to top)
2. Get window geometries from `wmctrl -l -G`
3. Compute visible regions per window by subtracting all windows above
4. Filter AT-SPI elements: keep only those whose bounds fall within visible regions

### Important: Window ID format mismatch
`wmctrl` uses zero-padded hex (`0x01a00003`), `xprop` uses unpadded hex (`0x1a00003`). **Normalize to int for comparison**: `int(wid_str, 16)`.

### Window-to-app matching
AT-SPI apps and wmctrl windows use different names. Match by:
1. **Frame name ↔ window title** (substring match) — most reliable
2. **Bounds overlap** with generous tolerance (~80px) for window decorations
3. **App name ↔ window title** as fallback

One AT-SPI app can have **multiple windows** (e.g., xfce4-panel has top bar + bottom taskbar). Must match per-frame, not per-app.

## Interaction via xdotool

### Key patterns
```bash
# CRITICAL: Activate the target window first, otherwise input goes to focused window
xdotool windowactivate <window_id>

# Click at coordinates
xdotool mousemove <x> <y> click 1          # left click
xdotool mousemove <x> <y> click 3          # right click
xdotool mousemove <x> <y> click --repeat 2 --delay 100 1  # double click

# Scroll
xdotool mousemove <x> <y>
xdotool click 4    # scroll up
xdotool click 5    # scroll down

# Type text
xdotool type --delay 30 "text here"

# Keyboard shortcuts
xdotool key ctrl+a
xdotool key ctrl+l    # Thunar: open location bar
xdotool key F1        # VSCode: command palette
xdotool key Return
```

### Critical lesson: Window focus
**Always activate the window before sending input.** If you just `xdotool type`, it goes to whichever window has focus (usually the terminal you're running from). Use `xdotool windowactivate <wid>` with the hex window ID from wmctrl.

## Other OS-Level Data Sources

### D-Bus
- `xfdesktop` exposes actions (arrange, reload, next wallpaper, quit) but **not** desktop icon list
- Desktop icons come from `~/Desktop/*.desktop` files — read the filesystem instead

### wmctrl
- `wmctrl -l -G` — list windows with geometry
- `wmctrl -a <title>` — activate window by title

### xprop
- `xprop -root _NET_CLIENT_LIST_STACKING` — window stacking order

## Docker Setup for Accessibility

### Packages to install
```
at-spi2-core        # AT-SPI bus and registryd
gir1.2-atspi-2.0    # Python GObject introspection bindings
wmctrl               # Window management CLI
xdotool              # Mouse/keyboard automation
```

### Environment variables (set in Dockerfile ENV and /etc/profile.d/)
```bash
GTK_MODULES=gail:atk-bridge           # GTK accessibility bridge
ACCESSIBILITY_ENABLED=1                # General accessibility flag
QT_ACCESSIBILITY=1                     # Qt accessibility
QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1     # Qt always-on accessibility
```

### App launcher wrappers
Chrome (`chrome-safe`):
```bash
exec /usr/bin/google-chrome-stable --no-sandbox --disable-gpu \
  --password-store=basic --disable-infobars --no-default-browser-check \
  --force-renderer-accessibility "$@"
```

VSCode (`code-safe`):
```bash
exec /usr/bin/code --no-sandbox --disable-gpu --password-store=basic \
  --force-renderer-accessibility --user-data-dir="${HOME}/.vscode" "$@"
```

VSCode also supports `"force-renderer-accessibility": true` in `~/.vscode/argv.json`.

## Scripts Created

| Script | Purpose |
|--------|---------|
| `dump_atspi.py` | Dump full AT-SPI tree to JSON |
| `dump_screen.py` | Combined AT-SPI + RapidOCR dump (no occlusion filtering) |
| `dump_visible_screen.py` | **Main script** — AT-SPI + RapidOCR + wmctrl occlusion filtering. Outputs JSON + annotated PNG map |
| `dump_screen_elements.py` | AT-SPI + Tesseract OCR combined dump |
| `compare_ocr.py` | Tesseract vs RapidOCR comparison |
| `render_screen_map.py` | Renders white-background "perception map" from JSON |

### Primary script: `dump_visible_screen.py`
```bash
DISPLAY=:1 /usr/bin/python3 /workspace/dump_visible_screen.py [output.json]
```

Output JSON structure:
```json
{
  "screen": {"width": 1280, "height": 720},
  "windows": [{"id": "0x...", "name": "...", "x": 0, "y": 0, "w": 1280, "h": 720}],
  "atspi": {
    "element_count": 86,
    "applications": [{
      "application": "xfce4-terminal",
      "window_ids": ["0x02e00003"],
      "elements": [{
        "role": "push button",
        "name": "File",
        "bounds": {"x": 384, "y": 81, "w": 40, "h": 25},
        "actions": ["click"],
        "depth": 3
      }]
    }]
  },
  "ocr": {
    "element_count": 30,
    "elements": [{
      "text": "File System",
      "confidence": 77.7,
      "bounds": {"x": 30, "y": 102, "w": 80, "h": 21},
      "polygon": [[30,102],[110,102],[110,123],[30,123]]
    }]
  }
}
```

## Agent Interaction Loop

The proven pattern for an AI agent to control the desktop:

1. **Dump** — Run `dump_visible_screen.py` to get JSON + screenshot
2. **Analyze** — Search both `atspi.applications[].elements` and `ocr.elements` for the target element
3. **Activate** — `xdotool windowactivate <window_id>` (get ID from JSON `windows` array)
4. **Act** — `xdotool mousemove <cx> <cy> click 1` at the element's center coordinates
5. **Verify** — Dump again to confirm the action took effect
6. **Repeat**

### Computing click coordinates
From bounds `{"x": 40, "y": 158, "w": 48, "h": 48}`:
- Center X = `x + w/2` = `40 + 24` = `64`
- Center Y = `y + h/2` = `158 + 24` = `182`

### Performance
- Full dump (AT-SPI + OCR + screenshot): ~2-3 seconds
- AT-SPI only query: ~0.5 seconds
- For quick lookups after known actions, query AT-SPI directly instead of full dump
