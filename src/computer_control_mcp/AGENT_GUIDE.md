# Computer Control MCP — Agent Skill Guide

Best practices for AI agents using the Computer Control MCP to see, understand, and interact with desktop applications. This guide covers tool selection, optimization, common workflows, and pitfalls learned from real testing.

---

## Core Concepts

### Four-Layer Perception Model

No single source captures everything on screen. Use the right combination:

| Layer | What it captures | What it misses | When to use |
|-------|-----------------|----------------|-------------|
| **Screenshot** (image) | Everything visual — layout, colors, icons, graphics | No coordinates, no semantic info | Always — your primary "eyes" |
| **UI Automation** (accessibility tree) | Widgets: buttons, menus, entries, tabs — with names, roles, actions, bounding boxes | Custom-drawn content, canvas, images | When you need to find clickable elements |
| **Deep UI Automation** (element refs + semantic actions) | Full element tree with stable refs, text values, supported patterns/actions, tree traversal | Same as UI Automation — limited for custom-drawn content | When you need to interact semantically (toggle, select, set values) or navigate the UI tree |
| **OCR** (text detection) | Any visible text rendered on screen | Non-text graphics, icons without labels | When reading text from images/canvas that UI automation can't see |

**Choosing between UI Automation and Deep UI Automation:**
- **UI Automation** (`take_screenshot_with_ui_automation`) — lightweight, returns elements with screenshot, good for finding coordinates to click
- **Deep UI Automation** (`find_ui_elements`, semantic actions) — heavier, returns element refs with full metadata, supports direct interaction (toggle, set text, select) without coordinates. Use when you need to *do something* with the element, not just click it

### Coordinate System

- All coordinates are in **absolute screen space** (ready for `click_screen` directly)
- Screenshots are **prescaled** to max 960x540 for agent consumption — use the returned `scale_factor` to convert visual coordinate estimates back to real screen coords
- OCR and UI automation coordinates are **already in real screen space** — no conversion needed
- When estimating coordinates from a screenshot image, multiply by `scale_factor`

---

## CRITICAL: Verify Every Action (Never Blind-Chain)

**Keyboard and mouse tools always report "success" even when the intended target didn't receive the input.** This is the #1 cause of agent failures. `pyautogui` sends keystrokes to whatever window is focused — it has no way to know if the right window got them.

### The problem: blind action chaining

```
# DANGEROUS — this can silently fail at any step
press_keys("win+r")           # → "success" (but Run dialog may not have opened)
type_text("notepad")          # → "success" (but typed into the wrong window)
press_keys("enter")           # → "success" (but hit enter in VS Code terminal)
press_keys([["ctrl", "o"]])   # → "success" (but Ctrl+O in the wrong app)
```

Every tool reports success because it successfully *sent* the input — but nothing verified the *effect*. The agent proceeds confidently through 4 actions, all targeting the wrong window.

### The fix: verify after every state-changing action

```
# SAFE — verify each step before proceeding
press_keys("win+r")
take_screenshot_full(image_format="webp", quality=30, include_ocr=false, include_ui=false)
# → Verify: is the Run dialog visible? If not, retry or try a different approach

type_text("notepad")
press_keys("enter")
wait_for_element(name_filter="Notepad", title_pattern="Notepad", timeout_ms=5000)
# → Verify: did Notepad open? If timed out, it didn't work

take_screenshot_full(image_format="webp", quality=30, include_ocr=false, include_ui=false)
# → Visual confirmation: Notepad is in foreground

press_keys([["ctrl", "o"]])
take_screenshot_full(image_format="webp", quality=30, include_ocr=false, include_ui=false)
# → Verify: is the Open dialog showing?
```

### Rules for safe autonomous operation

1. **Screenshot after every major action** — opening apps, switching windows, clicking buttons, submitting forms. Use Tier 1 screenshots (webp, quality=30, image only) — they're cheap (~67 KB).

2. **Use `wait_for_text` / `wait_for_element` after launching apps** — don't assume the app opened. Wait for it with a timeout.

3. **Activate the target window before keyboard input** — always call `activate_window(title_pattern="...")` before `type_text` or `press_keys` to ensure the right window is focused.

4. **Never chain more than 1-2 blind actions** — if you type + press Enter, take a screenshot to see what happened before doing more.

5. **If something looks wrong, stop and re-assess** — don't keep sending inputs hoping it'll work. Take a screenshot, understand the current state, then decide.

### Actions that ALWAYS need verification

| Action | Verify with |
|--------|------------|
| Launch an app | `wait_for_window` (cheapest) or screenshot |
| Open a dialog (Ctrl+O, Ctrl+S, etc.) | `wait_for_window` for known title, or screenshot |
| Switch windows | Screenshot — is the right window in foreground? |
| Submit a form / press Enter | Screenshot — did the expected result happen? |
| Close a dialog / window | `wait_for_window(mode="disappear")` or screenshot |
| Navigate to a URL | Screenshot or `wait_for_text` — did the page load? |
| Click a button | Screenshot — did the UI change as expected? |
| Toggle a switch / checkbox | `get_element_details` to check toggle state, or screenshot |
| Set a text field | `get_element_text` to read back the value |

### Cost of verification vs cost of failure

A Tier 1 confirmation screenshot costs **~67 KB**. A failed blind action chain can waste **5-10 tool calls** going down the wrong path, plus the recovery effort. Always verify — it's cheaper than debugging.

---

## Tool Selection Quick Reference

| I want to... | Use this tool | Key parameters |
|--------------|--------------|----------------|
| See what's on screen | `take_screenshot_full` | `image_format="webp", quality=50` |
| Find a button/field to click | `take_screenshot_with_ui_automation` | `interactable_only=true` |
| Find specific UI elements | `take_screenshot_with_ui_automation` | `name_filter`, `role_filter` |
| **Deep-search UI elements** | `find_ui_elements` | `text_filter`, `role_filter`, `name_filter` with paging |
| **Get focused element details** | `get_focused_element` | `title_pattern` to scope to a window |
| **Inspect element at coordinates** | `get_element_at_point` | `x, y` — returns the deepest element |
| **Get element full details** | `get_element_details` | `element_ref` from any discovery tool |
| **Navigate element tree** | `get_element_children` / `get_element_parent` | `element_ref` — walk the UI tree |
| **Perform semantic action** | `invoke_element`, `toggle_element`, `select_element`, etc. | `element_ref` — no coordinates needed |
| **Set text via automation** | `set_element_text` | `element_ref`, `text` — uses ValuePattern |
| **Read text via automation** | `get_element_text` | `element_ref` — reads from ValuePattern/TextPattern |
| **Select text by offsets** | `select_text_range` | `element_ref`, `start`, `end` — character offsets |
| **Find & select text** | `select_text_by_search` | `element_ref`, `search_text` — finds and highlights |
| **Read selected text** | `get_text_selection` | `element_ref` — returns currently selected text |
| **Get cursor position in text** | `get_text_caret_offset` | `element_ref` — returns character offset |
| **Move cursor in text** | `set_text_caret_offset` | `element_ref`, `offset` — moves caret |
| **Get word/line at position** | `get_text_at_offset` | `element_ref`, `offset`, `unit` (char/word/line/paragraph) |
| **Get text screen coordinates** | `get_text_bounds` | `element_ref`, `start`, `end` — screen rectangles for text |
| **Set slider/range value** | `set_element_range_value` | `element_ref`, `value` |
| **Move/resize window via UIA** | `move_element_ui`, `resize_element_ui`, `set_element_extents` | `element_ref` of a window frame |
| **Read table/grid data** | `get_table_data` | `element_ref`, `start_row`, `max_rows` — returns headers + rows |
| **Scroll a container** | `scroll_element_container` | `element_ref`, `direction`, `amount`, `unit` (page/line/percent) |
| **Get scroll position** | `get_scroll_info` | `element_ref` — scroll percentages and scrollability |
| **Switch element view** | `get_element_views` / `set_element_view` | Get available views, switch between them |
| **Load virtualized item** | `realize_element` | `element_ref` — force-load item in virtual list |
| **Get drag info** | `get_drag_info` | `element_ref` — check if draggable and drop effects |
| **Get hyperlinks in text** | `get_hyperlinks` | `element_ref` — links with URIs and offsets (Linux) |
| **Click a hyperlink** | `activate_hyperlink` | `element_ref`, `link_index` (Linux) |
| Read text on screen | `take_screenshot_with_ocr` | `ocr_text_filter` for targeted search |
| Find specific text (like grep) | `take_screenshot_with_ocr` | `ocr_text_filter="mem4\|mem 4"` |
| Find text to click | `find_text` | `text="Submit\|OK"` with pipe-separated OR |
| Click something | `click_screen` | `x, y` from UI automation or OCR |
| Right-click something | `click_screen` | `button="right"` |
| Double-click (open files/icons) | `click_screen` | `num_clicks=2` |
| Type into a field | `click_screen` → `type_text` | Click the field first, then type |
| Scroll a page | `scroll` | `title_pattern` to activate first |
| Bring a window to front | `activate_window` | `title_pattern` |
| Open an app (known command) | `launch_app` | `command=["google-chrome"]` — enables accessibility |
| Open an app (desktop icon) | OCR + double-click | `ocr_text_filter="VLC"` → `click_screen(num_clicks=2)` |
| **Wait for a window** | `wait_for_window` | `title_pattern`, `mode="appear\|disappear\|active"` |
| **Wait for focused element** | `wait_for_focused_element` | `name_filter`, `role_filter` with timeout |
| **Watch filesystem changes** | `start_file_watch` → `get_file_watch_events` | Persistent watcher with event queue |
| **Wait for a file change** | `wait_for_file_change` | One-shot wait with timeout |
| **Kill a process** | `kill_process` | `process_name` or `pid`, `force=true` for stubborn apps |
| **List running processes** | `list_processes` | Returns process names and PIDs |
| **Get system info** | `get_system_info` | CPU, memory, disk, OS details |
| Verify before clicking | `capture_region_around` | Small region around target coords |
| Check if something changed | `check_screen_changed_full` | After performing an action |

---

## Two-Tier Screenshot Strategy

Use two tiers to balance information vs cost. The default PNG config produces **110+ KB** responses that get truncated — always use one of these optimized tiers instead.

### Tier 1: Action Confirmation (use after every action)

```
take_screenshot_full(
    title_pattern="<app name>",
    image_format="webp",
    quality=30,
    include_ocr=false,
    include_ui=false
)
```

- **~67 KB** (color) or **~59 KB** (grayscale) — image only, no data overhead
- Use after clicking, typing, scrolling, or any action to verify it worked
- Answers: "Did the page load? Did the dialog close? Did it scroll?"
- This is your routine screenshot — use it liberally

### Tier 2: Full Perception (use when you need to interact)

```
take_screenshot_full(
    title_pattern="<app name>",
    image_format="webp",
    quality=50,
    include_ocr=false,
    ui_interactable_only=true
)
```

- **~85 KB total** (~80 KB image + ~5 KB UI data)
- Returns screenshot + all actionable UI elements (buttons, fields, links, tabs)
- Use when you need to find elements to click, fill forms, or navigate
- First look at a new screen, or when you need coordinates for interaction

### Size Comparison

| Config | Image | OCR | UI | Total |
|--------|-------|-----|-----|-------|
| **Default (avoid!)** | 420 KB PNG | ~5 KB | ~14 KB unfiltered | **110+ KB (truncated)** |
| **Tier 2 (interact)** | ~80 KB webp | off | ~5 KB filtered | **~85 KB** |
| **Tier 1 (confirm)** | ~67 KB webp | off | off | **~67 KB** |

### Region-Based Optimization

After your first full-window screenshot, you know the layout. Use `region=[x, y, w, h]` on
subsequent calls to capture only the area you're working in — dramatically reduces image size
and UI element count.

**Workflow:**
1. **First look** — Tier 2 full window (get layout + all elements)
2. **Subsequent actions** — Region-based Tier 1 on just the area of interest

**Examples:**
```
# After scrolling, confirm just the content area (skip toolbar/tabs)
take_screenshot_full(
    title_pattern="Edge",
    image_format="webp", quality=30,
    include_ocr=false, include_ui=false,
    region=[619, 120, 1289, 500]
)

# Zoom into a specific area with UI elements
take_screenshot_full(
    title_pattern="Edge",
    image_format="webp", quality=30,
    include_ocr=false, ui_interactable_only=true,
    region=[619, 120, 1289, 500]
)
```

**Why this helps:**
- Smaller region = smaller image (less to compress, less to prescale)
- Regions under 960x540 get `scale_factor: 1.0` — no prescaling, pixel-perfect clarity
- UI elements are filtered to the region bounds (12 elements vs 62 for full window in testing)
- Coordinates remain in absolute screen space — `click_screen` works directly

**Best for:**
- Verifying a scroll moved the page (capture just the content area)
- Inspecting a specific panel, form, or dialog
- Following up on a known area after an action
- Reading a sidebar or embedded widget

### When to upgrade beyond Tier 2

Add layers only when needed:

- **Add OCR** (`include_ocr=true`) — when you need to read text that UI automation can't see (canvas, images, custom-rendered content)
- **Add color at higher quality** (`quality=70`) — when you need to inspect visual details, colors, or subtle UI differences
- **Remove interactable filter** — when you need to find passive text labels or container names

## Additional Configurations

### Reading/Verifying Page Content

```
take_screenshot_full(
    title_pattern="<app name>",
    image_format="webp",
    quality=50,
    include_ui=false,
    include_ocr=true
)
```

- Image + OCR text, no UI tree
- Good for: verifying text content, reading articles, checking data on screen

### Finding Specific Elements (targeted search)

```
take_screenshot_with_ui_automation(
    title_pattern="<app name>",
    name_filter="Search|Submit|Cancel",
    role_filter="push button|entry|link"
)
```

- Dramatically reduces output — only matching elements returned
- Filters support **pipe-separated OR** conditions
- Good for: finding a specific button, locating input fields, targeted interaction
- No screenshot — just UI element data (~200 bytes to ~2 KB depending on matches)

---

## Image Format Guide

| Use Case | Format | Quality | Color | Size (1080p) |
|----------|--------|---------|-------|--------------|
| **Smallest color** | webp | 30 | color | ~67 KB |
| **Best balance** | webp | 50 | color | ~80 KB |
| **Good quality** | webp | 70 | color | ~92 KB |
| **Default (avoid)** | png | n/a | color | ~420 KB |

- **Always use WebP** — 4-7x smaller than PNG, no visible quality loss at q=50+
- **Keep color** for QA — needed to spot error states, highlights, wrong colors
- **Grayscale** only when color doesn't matter (saves ~10-15%)
- **Avoid "bw" (black & white)** — counterintuitively produces much larger files due to dithering

---

## UI Automation Filters

### Available filters

| Filter | Example | Effect |
|--------|---------|--------|
| `interactable_only=true` | | Only elements with actions (click, toggle, select, expand) |
| `role_filter="push button\|entry\|link"` | Pipe-separated roles | Only matching roles |
| `name_filter="Search\|Submit"` | Pipe-separated substrings | Only elements whose name contains any pattern |

### Common role names

| Role | What it is | Has actions? |
|------|-----------|-------------|
| `push button` | Clickable button | Yes (click) |
| `entry` | Text input field | No (but important to find) |
| `combo box` | Dropdown / select | Yes (expand/collapse) |
| `link` | Hyperlink | No (but clickable via coordinates) |
| `list item` | Item in a list | Yes (click, select) |
| `page tab` | Tab in a tab bar | Yes (click, select) |
| `menu item` | Menu entry | Yes (click) |
| `check box` | Checkbox | Yes (click, toggle) |
| `radio button` | Radio option | Yes (click, toggle) |
| `text` | Static text label | No |
| `image` | Image element | No |
| `pane` | Container/panel | No |
| `group` | Grouping container | No |

### Token impact

- **Unfiltered** Edge new tab: ~560 elements, ~14k tokens
- **`interactable_only=true`**: ~70 elements, ~3k tokens
- **`role_filter="push button|entry"`**: ~40 elements, ~1.5k tokens
- **`name_filter="Search"`**: ~5 elements, ~200 tokens

---

## OCR Text Filter (grep for the screen)

### The problem

A full-screen OCR dump returns **60,000+ characters** — way too much for an agent to process. Most of the time you only need one or two text elements.

### The solution: `ocr_text_filter`

All OCR tools support server-side filtering with fuzzy matching and pipe-separated OR terms:

```
# Find "mem4" on screen — returns only matching elements
take_screenshot_with_ocr(ocr_text_filter="mem4|mem 4")

# Same filter works in take_screenshot_full
take_screenshot_full(
    include_image=false, include_ui=false, include_ocr=true,
    ocr_text_filter="VLC|vlc media"
)

# find_text also supports pipe-separated terms
find_text(text="Submit|OK|Save")
```

### How it works

- Each OCR result is scored against **every** search term using fuzzy matching (`fuzz.partial_ratio`)
- A length penalty prevents short garbage matches from scoring high
- Results are sorted by **best match score** descending
- Only results above `ocr_match_threshold` (default 60) are returned
- Each result includes a `match_score` field

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ocr_text_filter` | `None` (returns all) | Pipe-separated search terms, e.g. `"mem4\|mem 4\|mem_4"` |
| `ocr_match_threshold` | `60` | Minimum score (0-100). Lower = more results, higher = stricter |

### Impact on response size

| Scenario | Without filter | With filter | Reduction |
|----------|---------------|-------------|-----------|
| Full screen OCR | ~61,000 chars | ~2,000 chars | **97%** |
| Window OCR | ~15,000 chars | ~500 chars | **96%** |

### When to use which OCR approach

| Scenario | Tool & approach |
|----------|----------------|
| **Find specific text to click** | `take_screenshot_with_ocr(ocr_text_filter="Submit\|OK")` → `click_screen(abs_center_x, abs_center_y)` |
| **Open a desktop icon** | `take_screenshot_with_ocr(ocr_text_filter="VLC\|Chrome")` → `click_screen(..., num_clicks=2)` |
| **Read all text on screen** | `take_screenshot_with_ocr()` (no filter — returns everything) |
| **Combined: see screen + find text** | `take_screenshot_full(include_ocr=true, ocr_text_filter="Search")` |
| **Text + UI combined search** | `take_screenshot_full(include_ocr=true, ocr_text_filter="...", ui_name_filter="...")` |

### Best practices

- **Always use a filter** when searching for specific text — the unfiltered response is too large
- Use **pipe-separated terms** when you're unsure of exact spelling: `"Settings|Setting|Settngs"`
- **Lower the threshold** to 40-50 if you get no results — OCR may have slight misreadings
- The filter uses **fuzzy matching** so minor OCR errors (like `l` vs `1`, `O` vs `0`) still match
- Prefer `take_screenshot_with_ocr` with filter over `find_text` — same OCR engine but more flexible output format

---

## Deep UI Automation

Deep UI automation gives you **semantic access** to application elements — you can discover, inspect, and interact with UI elements by their role, name, and actions rather than just clicking coordinates. This is more reliable than coordinate-based interaction because element refs survive minor layout shifts.

### When to Use Deep UI vs Screenshot-Based Approach

| Scenario | Use | Why |
|----------|-----|-----|
| Toggle a switch, check a checkbox | Deep UI (`toggle_element`) | Semantic action — no coordinates needed |
| Fill a text field | Deep UI (`set_element_text`) | Direct value injection, no click+type needed |
| Select a list item or tab | Deep UI (`select_element`) | Works even if element is partially hidden |
| Read a field's current value | Deep UI (`get_element_text`) | Exact value, not OCR approximation |
| Click a web page link | Screenshot + coordinate | Web content often not in deep UI tree |
| Interact with canvas/games | Screenshot + coordinate | Custom-drawn content has no UI elements |
| Verify visual appearance | Screenshot | Deep UI has no visual information |

### Element Refs (Stable Handles)

Every deep UI tool returns and accepts **element refs** — JSON objects that identify a specific UI element. Refs contain the element's path in the UI tree, window ID, and metadata for re-resolution.

```json
{
  "backend": "uia",
  "app": "Settings",
  "window_ids": ["0x3fc001a"],
  "path": [1, 1, 3, 0, 3, 0, 1],
  "role": "push button",
  "name": "Schedule night light",
  "bounds": {"x": 1095, "y": 363, "w": 72, "h": 40}
}
```

**Key properties of refs:**
- Refs are re-resolved each time you use them — the path is walked from the window root
- They survive minor UI changes (scrolling, focus changes) as long as the tree structure hasn't changed
- They break when the **window title changes** (e.g., Notepad title changes after editing: `"Untitled - Notepad"` → `"*Hello - Notepad"`) — re-discover with `find_ui_elements`
- They break when the **element tree restructures** (e.g., new items added above the target)
- Pass them directly to any action tool: `toggle_element(element_ref={...})`

### Discovery Tools

| Tool | Purpose | Best for |
|------|---------|----------|
| `find_ui_elements` | Search for elements by name, role, or text content | Finding specific controls across a window |
| `get_focused_element` | Get the currently focused element | Checking what has keyboard focus |
| `get_element_at_point` | Get the deepest element at screen coordinates | Identifying what's under the cursor |

#### `find_ui_elements` — Your Primary Discovery Tool

```
find_ui_elements(
    title_pattern="Settings",           # Window to search in (fuzzy match)
    text_filter="Night light|Bluetooth", # Search text/name/value (pipe-separated OR)
    role_filter="push button|slider",    # Filter by role (pipe-separated OR)
    interactable_only=true,              # Only elements with actions
    offset=0, limit=20                   # Paging — essential for large results
)
```

**Important parameters:**
- `text_filter` — Searches across element name, text, and value fields. Pipe-separated OR terms.
- `role_filter` — Filters by accessibility role. Use the role names from the Common Roles table below.
- `name_filter` — Filters by element name only (stricter than `text_filter`).
- `offset` / `limit` — Pagination. Default limit is 100. Use `limit=20` for focused searches.
- `max_depth` — Tree traversal depth (default 40). Lower for faster but shallower searches.
- `interactable_only` — Only returns elements that support actions (invoke, toggle, select, etc.).

**Response includes:** `total_count`, `offset`, `limit`, `has_more` for paging through large result sets.

#### `get_element_at_point` — Identify by Coordinates

```
get_element_at_point(x=500, y=300)
# Returns the deepest element at that screen position
```

Useful when you can see something in a screenshot but don't know its name/role.

### Tree Traversal

Navigate the element hierarchy to understand structure or find related elements:

```
# Get children of a container
get_element_children(element_ref={...})

# Get parent of an element
get_element_parent(element_ref={...})

# Get full details (patterns, states, properties)
get_element_details(element_ref={...})
```

**When to traverse:**
- You found a container (group, pane, tab) and need its child controls
- You found an element and need context about its parent (which dialog/group it belongs to)
- You need to check what patterns (actions) an element supports before trying to interact

### Semantic Actions

These actions operate on element refs — no coordinate math needed.

| Action Tool | What it does | Requires pattern |
|------------|-------------|-----------------|
| `focus_element` | Give keyboard focus to element | SetFocus |
| `invoke_element` | Click/activate (buttons, menu items, links) | InvokePattern |
| `toggle_element` | Toggle on/off (checkboxes, switches) | TogglePattern |
| `select_element` | Select (list items, tabs, radio buttons) | SelectionItemPattern |
| `expand_element` | Expand (tree nodes, combo boxes, menus) | ExpandCollapsePattern |
| `collapse_element` | Collapse (tree nodes, combo boxes) | ExpandCollapsePattern |
| `set_element_text` | Set entire text value (input fields) | ValuePattern |
| `get_element_text` | Read entire text value | ValuePattern / TextPattern |
| `select_text_range` | Select text by character offsets | TextPattern |
| `select_text_by_search` | Find and select a substring | TextPattern |
| `get_text_selection` | Read the currently selected text | TextPattern |
| `get_text_caret_offset` | Get cursor position as character offset | TextPattern |
| `set_text_caret_offset` | Move cursor to a character offset | TextPattern |
| `get_text_at_offset` | Get word/line/paragraph at an offset | TextPattern |
| `get_text_bounds` | Get screen rectangles for a text range | TextPattern |
| `scroll_element_into_view` | Scroll element into visible area | ScrollItemPattern |
| `set_element_range_value` | Set numeric value (sliders, progress bars) | RangeValuePattern |
| `move_element_ui` | Move element to position (windows) | TransformPattern |
| `resize_element_ui` | Resize element (windows) | TransformPattern |
| `set_element_extents` | Move + resize in one call (windows) | TransformPattern |

**Pattern support varies by app.** If an element doesn't support the required pattern, the action will fail with an error. Use `get_element_details` to check what patterns an element supports before attempting less-common actions.

### Deep UI Common Roles

| Role | What it is | Common actions |
|------|-----------|---------------|
| `push button` | Clickable button | invoke |
| `document` / `edit` | Text input area | set_text, get_text, focus, select_text_range, select_text_by_search, get_text_caret_offset, get_text_bounds |
| `combo box` | Dropdown / select | expand, collapse |
| `list item` | Item in a list | select, invoke |
| `page tab` / `tab item` | Tab in a tab bar | select |
| `menu item` | Menu entry | invoke |
| `check box` | Checkbox | toggle |
| `toggle switch` | On/off switch (Win11 Settings) | toggle |
| `slider` | Range slider | set_range_value |
| `tree item` | Tree node | expand, collapse, select |
| `frame` / `window` | Top-level window | move, resize, set_extents |
| `link` | Hyperlink | invoke |

### Deep UI Workflow Example — Toggle a Setting

```
# 1. Find the toggle switch
find_ui_elements(
    title_pattern="Settings",
    text_filter="Night light",
    role_filter="push button",    # Toggle switches appear as "push button" in UIA
    interactable_only=true
)
# → Returns element with ref and localized_control_type="toggle switch"

# 2. Toggle it
toggle_element(element_ref={...ref from step 1...})
# → "Toggled element"

# 3. Verify with screenshot
take_screenshot_full(title_pattern="Settings", image_format="webp", quality=30,
                     include_ocr=false, include_ui=false)
```

### Deep UI Workflow Example — Fill a Form Field

```
# 1. Find the text field
find_ui_elements(
    title_pattern="Notepad",
    role_filter="document|edit",
    limit=5
)

# 2. Set text directly (no click needed)
set_element_text(element_ref={...ref...}, text="Hello World")

# 3. Read back to verify
get_element_text(element_ref={...ref...})
# → "Hello World"
```

### Text Manipulation Tools (TextPattern)

These tools operate on text elements (`document`, `edit`) that support the UIA TextPattern or AT-SPI Text interface. They enable **native programmatic text selection, cursor positioning, and text querying** — more reliable than keyboard simulation.

#### When to Use Text Tools vs Keyboard Shortcuts

| Scenario | Use | Why |
|----------|-----|-----|
| Select a specific substring | `select_text_by_search` | Precise, finds text regardless of cursor position |
| Select text by offset range | `select_text_range` | Exact character-level control |
| Copy specific text to clipboard | `select_text_by_search` → `press_keys([["ctrl","c"]])` | Select natively, copy with keyboard |
| Move cursor to a known position | `set_text_caret_offset` | Instant, no repeated arrow key presses |
| Check what's selected | `get_text_selection` | Reads selection directly from the control |
| Get the word/line at a position | `get_text_at_offset` | No need to select + copy + parse |
| Find screen position of text | `get_text_bounds` | Exact pixel rectangles, useful for click targeting |
| Select all text | `press_keys([["ctrl","a"]])` | Simpler than `select_text_range(0, length)` |
| Type new text into a field | `set_element_text` or `type_text` | Text tools don't type — they select/navigate |

#### Text Units for `get_text_at_offset`

| Unit | What it returns | Example |
|------|----------------|---------|
| `"char"` | Single character | `"q"` |
| `"word"` | Word + trailing whitespace | `"quick "` |
| `"line"` | Full line including line break | `"The quick brown fox jumps over the lazy dog.\r"` |
| `"paragraph"` | Full paragraph | Same as line for single-line paragraphs |

### Deep UI Workflow Example — Select, Copy, and Paste Text

```
# 1. Find the text element in the source app
find_ui_elements(title_pattern="Notepad", role_filter="document", limit=5)

# 2. Find and select a specific substring
select_text_by_search(element_ref={...ref...}, search_text="brown fox")
# → Highlights "brown fox" in the document

# 3. Copy to clipboard
press_keys([["ctrl", "c"]])

# 4. Switch to target app and paste
activate_window(title_pattern="Other App")
press_keys([["ctrl", "v"]])
# → "brown fox" pasted into the other app
```

### Deep UI Workflow Example — Navigate and Inspect Text

```
# 1. Get current cursor position
get_text_caret_offset(element_ref={...ref...})
# → {"offset": 10, "text_length": 115}

# 2. Get the word at that position
get_text_at_offset(element_ref={...ref...}, offset=10, unit="word")
# → {"text": "brown ", "unit": "word"}

# 3. Get the full line
get_text_at_offset(element_ref={...ref...}, offset=10, unit="line")
# → {"text": "The quick brown fox jumps over the lazy dog.\r", "unit": "line"}

# 4. Move cursor to a different position
set_text_caret_offset(element_ref={...ref...}, offset=50)

# 5. Get screen coordinates of a text range (for click targeting)
get_text_bounds(element_ref={...ref...}, start=4, end=19)
# → {"bounds": [{"x": 979, "y": 266, "width": 152, "height": 34}]}
```

### Deep UI Workflow Example — Move/Resize a Window

```
# 1. Find the window frame element
find_ui_elements(
    title_pattern="Notepad",
    max_depth=0          # Only top-level — the window itself
)
# → Returns frame element with role="frame"

# 2. Move it
move_element_ui(element_ref={...frame ref...}, x=100, y=100)

# 3. Resize it
resize_element_ui(element_ref={...frame ref...}, width=800, height=600)

# 4. Or do both at once
set_element_extents(element_ref={...frame ref...}, x=200, y=200, width=900, height=700)
```

---

## Table & Grid Reading

Read structured data from tables, data grids, spreadsheets, and file lists.

```
# Find a table/grid element
find_ui_elements(title_pattern="Explorer", role_filter="data grid|list|table")

# Read the data (with paging)
get_table_data(element_ref={...}, start_row=0, max_rows=50)
# → {"row_count": 200, "column_count": 4, "headers": ["Name", "Date", "Type", "Size"],
#    "rows": [[{"value": "file.txt"}, ...], ...], "has_more": true}

# Read next page
get_table_data(element_ref={...}, start_row=50, max_rows=50)
```

Common table/grid roles: `data grid`, `list`, `table`, `tree`

## Programmatic Container Scrolling

Scroll specific containers precisely — more reliable than mouse wheel which targets whatever is under the cursor.

```
# Find a scrollable container
find_ui_elements(title_pattern="App", role_filter="list|pane|document")

# Scroll by page
scroll_element_container(element_ref={...}, direction="down", amount=1, unit="page")

# Scroll by line (small increments)
scroll_element_container(element_ref={...}, direction="down", amount=3, unit="line")

# Scroll by percentage (absolute)
scroll_element_container(element_ref={...}, direction="down", amount=25, unit="percent")

# Check scroll position
get_scroll_info(element_ref={...})
# → {"vertical_percent": 25.0, "vertically_scrollable": true, ...}
```

**When to use `scroll_element_container` vs `scroll` (mouse wheel):**
- Use `scroll_element_container` when you have a specific scrollable element ref and need precise control
- Use `scroll` (mouse wheel) for general page scrolling or when you don't have an element ref

## View Switching & Virtualization

**Switch between views** (e.g., File Explorer list/details/icons):
```
get_element_views(element_ref={...})
# → {"views": [{"id": 1, "name": "Details"}, {"id": 2, "name": "List"}, ...]}

set_element_view(element_ref={...}, view_id=1)
```

**Realize virtualized items** — force-load items in large lists that only render visible rows:
```
realize_element(element_ref={...})
# → Item is now fully created in the UI tree and can be interacted with
```

---

## Wait & Polling Tools

Use these to synchronize with application state changes instead of blind delays.

### `wait_for_window` — Wait for Window State

```
# Wait for an app to open
wait_for_window(title_pattern="Notepad", mode="appear", timeout_ms=10000)

# Wait for a dialog to close
wait_for_window(title_pattern="Save As", mode="disappear", timeout_ms=5000)

# Wait for a window to become active (foreground)
wait_for_window(title_pattern="Chrome", mode="active", timeout_ms=5000)
```

**Modes:** `appear` (default), `disappear`, `active`

**Returns:** `found`, `active`, `elapsed_ms`, `timed_out`, and `title` of matched window.

### `wait_for_focused_element` — Wait for Focus Target

```
# Wait until a specific type of element gets focus
wait_for_focused_element(
    title_pattern="Notepad",
    role_filter="document",
    timeout_ms=5000
)
```

Polls until the focused element matches your name/role filters. Useful after programmatically focusing an element or opening a dialog.

### When to Use Wait Tools vs Screenshots

| Scenario | Use |
|----------|-----|
| Launched an app, need to know when it's ready | `wait_for_window` — cheap, precise, returns immediately when found |
| Clicked a button, need to verify dialog opened | `wait_for_window` for known dialog title |
| Need to see what happened after an action | Screenshot — visual verification |
| Waiting for an element to gain focus | `wait_for_focused_element` |
| Need to verify complex visual state | Screenshot — wait tools can't check visual layout |

---

## File System Watching

Monitor filesystem changes — useful for watching build output, log files, downloads, or any directory where files change.

### Persistent Watch (long-running)

```
# 1. Start watching a directory
start_file_watch(paths="C:/Users/me/Downloads", recursive=true)
# → {"watch_id": "abc-123", ...}

# 2. Do other things... files get created/modified/deleted

# 3. Check what changed
get_file_watch_events(watch_id="abc-123")
# → {"events": [{"event_type": "created", "src_path": "...", "timestamp": "..."}]}

# 4. Stop when done
stop_file_watch(watch_id="abc-123")
```

**`start_file_watch` parameters:**
- `paths` — Single path string or list of paths to watch
- `recursive` — Watch subdirectories (default `true`)
- `event_types` — Filter: `"created"`, `"modified"`, `"deleted"`, `"moved"` (default: all)
- `max_events` — Queue size limit (default 500, oldest dropped when full)

**`get_file_watch_events` parameters:**
- `watch_id` — From `start_file_watch` response
- `clear` — Clear events after reading (default `true`)
- `max_events` — Max events to return (default 100)

### One-Shot Wait (block until change)

```
# Wait for any change in a directory (blocks until change or timeout)
wait_for_file_change(
    paths="C:/Users/me/project/dist",
    timeout_ms=30000
)
# → {"changed": true, "events": [{"event_type": "modified", ...}]}
```

Useful for waiting on build output, file downloads, or log updates.

### File Watch Workflow — Monitor a Build

```
# 1. Start watching the output directory
start_file_watch(paths="C:/project/dist")

# 2. Trigger the build (via terminal, button click, etc.)
type_text("npm run build")
press_keys("enter")

# 3. Wait for output
wait_for_file_change(paths="C:/project/dist", timeout_ms=60000)
# → Build output files detected

# 4. Or poll periodically
get_file_watch_events(watch_id="...")
# → Check what files were created/modified
```

### File Watch Workflow — Watch for Downloads

```
# 1. Start watching Downloads folder
start_file_watch(paths="C:/Users/me/Downloads", event_types="created")

# 2. Click download button in browser
click_screen(x=500, y=300)

# 3. Wait for file to appear
wait_for_file_change(paths="C:/Users/me/Downloads", timeout_ms=30000)
# → {"events": [{"event_type": "created", "src_path": "...\\report.pdf"}]}
```

**Note:** Requires the `watchdog` Python library. If not installed, these tools return `{"error": "watchdog is not installed"}`.

---

## Process & System Management

### `kill_process` — Terminate a Process

```
# Kill by name (all matching processes)
kill_process(process_name="Notepad.exe")

# Kill specific PID
kill_process(pid=12345)

# Force kill (SIGKILL / taskkill /F) for stubborn processes
kill_process(process_name="chrome.exe", force=true)
```

**Tips:**
- Graceful kill (`force=false`) may not work for some apps (e.g., Windows Notepad ignores it). Use `force=true` if graceful fails.
- Killing by `process_name` kills **all** matching processes. Use `pid` for precision.
- The PID returned by `launch_app` may differ from the actual app PID (parent process exits, child continues). Use `list_processes` to find the real PID.

### `list_processes` — List Running Processes

```
list_processes()
# → {"processes": [{"name": "chrome.exe", "pid": 1234, "session": "Console", "mem_usage": "150,432 K"}, ...]}
```

Returns all running processes with PID and memory usage. Useful for finding a process before killing it or checking if an app is running.

### `get_system_info` — System Diagnostics

```
get_system_info()
# → {"cpu": {...}, "memory": {...}, "disk": [...], "os": {...}, "network": {...}}
```

Returns CPU, memory, disk, OS, and network information. Useful for diagnostics, checking available resources, or understanding the environment.

---

## Common Workflows

### Navigate a Browser to a URL

```
1. activate_window(title_pattern="Edge")
2. take_screenshot_with_ui_automation(title_pattern="Edge", role_filter="entry", name_filter="Address")
   → Find the address bar coordinates
3. click_screen(x=<addr_bar_x>, y=<addr_bar_y>)
4. type_text("https://example.com")
5. press_keys("enter")
6. take_screenshot_full(...)  → verify page loaded
```

### Fill a Form

```
1. take_screenshot_with_ui_automation(title_pattern="...", role_filter="entry|combo box|check box")
   → Get all input fields with coordinates
2. For each field:
   a. click_screen(x, y)  → focus the field
   b. press_keys([["ctrl", "a"]])  → select all existing text
   c. type_text("value")  → type new value
3. take_screenshot_with_ui_automation(..., name_filter="Submit|Save|OK")
   → Find submit button
4. click_screen(x, y)  → click submit
```

### Scroll and Read Content

```
1. scroll(title_pattern="Edge", direction="down", amount=5)
   → Activates window + scrolls
2. scroll(direction="down", amount=3)
   → Keep scrolling (mouse stays in position)
3. take_screenshot_full(...)
   → See what's visible now
4. Repeat as needed
```

### Open a Desktop Icon

```
1. press_keys("win+d")                                    → show desktop
2. take_screenshot_with_ocr(ocr_text_filter="VLC|Chrome")  → find the icon label
   → Get abs_center_x, abs_center_y of the top match
3. click_screen(x=<x>, y=<y>, num_clicks=2)               → double-click to open
4. take_screenshot_full(...)                                → verify app opened
```

**Why OCR works best for desktop icons:**
- Desktop icons are not well-exposed by UI automation (they're in a special shell ListView)
- OCR reads icon labels with 99%+ confidence
- With `ocr_text_filter`, the response is tiny (~500 bytes) and the top match has exact coordinates
- This is a 2-call workflow: OCR filter → double-click

### Right-Click Context Menu

```
1. click_screen(x=<x>, y=<y>, button="right")             → right-click target
2. take_screenshot_with_ui_automation(name_filter="Copy|Paste|Delete|Properties")
   → Find menu items
3. click_screen(x=<item_x>, y=<item_y>)                   → click menu item
```

### Handle Dialogs/Popups

```
1. take_screenshot_with_ui_automation(title_pattern="...", name_filter="Accept|OK|Allow|Dismiss|Cancel")
   → Find dialog buttons
2. click_screen(x, y)  → click the appropriate button
3. take_screenshot_full(...)  → verify dialog dismissed
```

### Launch an Application

**Always prefer `launch_app` when you know the app's command-line name.** It launches the app with accessibility flags enabled, which makes UI automation dramatically more effective.

```
# Open Chrome with full accessibility (exposes all web page elements via UIA)
launch_app(command=["google-chrome", "https://example.com"])

# Open VS Code in a specific directory
launch_app(command=["code", "/path/to/project"])

# Open Notepad
launch_app(command=["notepad"])

# Preview what would happen without launching
launch_app(command=["google-chrome"], dry_run=true)
```

**Why this matters:**
- Chromium/Electron apps launched normally expose **very few** web page elements to UI automation
- `launch_app` adds `--force-renderer-accessibility`, which makes the browser expose **all** page elements (links, headings, paragraphs, form fields, etc.)
- Without this flag, you're limited to OCR + vision for web content; with it, you get precise coordinates from UI automation
- Also handles VS Code (`ACCESSIBILITY_ENABLED=1`), Qt apps (`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`), and GTK/GNOME apps (AT-SPI activation)

**Common app commands:**

| App | Command |
|-----|---------|
| Google Chrome | `["google-chrome"]` or `["chrome"]` (Windows) |
| Microsoft Edge | `["msedge"]` or `["microsoft-edge"]` |
| Firefox | `["firefox"]` |
| VS Code | `["code"]` or `["code", "."]` |
| Notepad | `["notepad"]` |
| Notepad++ | `["notepad++"]` |
| File Explorer | `["explorer"]` |
| Terminal | `["cmd"]` or `["powershell"]` (Windows), `["gnome-terminal"]` (Linux) |

**When to use `launch_app` vs double-clicking a desktop icon:**

| Scenario | Use |
|----------|-----|
| You know the command name | `launch_app` — faster, more reliable, enables accessibility |
| App has no CLI command / only has a desktop shortcut | OCR + double-click the desktop icon |
| Need to pass arguments (URL, file path, flags) | `launch_app` — supports full command-line args |
| App is already running, need another instance | `launch_app` — opens a new instance |

**Verification after launch:**
```
launch_app(command=["notepad"])
wait_for_window(title_pattern="Notepad", timeout_ms=5000)
# OR for visual confirmation:
take_screenshot_full(image_format="webp", quality=30, include_ocr=false, include_ui=false)
```

---

### Coordinate Refinement Loop (vision-based interaction)

**When to use:** When UI automation doesn't expose the element you need to interact with.
This works for any coordinate-based action — clicking links, locating input fields to type into,
finding drag start/end points, targeting scroll areas, or positioning for right-clicks.
This is your universal fallback for arbitrary coordinate-based interaction using only vision.

**How it works:**
1. Take an image-only screenshot to see the target
2. Estimate coordinates by multiplying image position × `scale_factor` + window offset
3. Use `capture_region_around` with `mark_center=true` to verify — it draws a red circle
   at your estimated coordinates on a zoomed-in view
4. If the marker is off, adjust and repeat
5. Once the marker is on the target, click

**Step by step:**
```
# Step 1: Image-only screenshot to see the target
take_screenshot_full(
    title_pattern="Edge",
    image_format="webp", quality=50,
    include_ocr=false, include_ui=false
)
# Note the scale_factor from the response (e.g. 1.88)

# Step 2: Estimate coordinates
# Visual position in image: (x_img, y_img)
# Real coords ≈ window_left + (x_img × scale_factor), window_top + (y_img × scale_factor)

# Step 3: Verify with marker
capture_region_around(
    x=<estimated_x>, y=<estimated_y>,
    radius=100,          # 200x200px capture area
    mark_center=true,    # draw red circle at target
    image_format="webp", quality=50
)
# → See zoomed-in view with red circle marker

# Step 4: Adjust if marker is off-target
# - Marker too far left? Increase x
# - Marker too high? Increase y
# Repeat capture_region_around with adjusted coordinates

# Step 5: Once marker is on target, perform your action
click_screen(x=<verified_x>, y=<verified_y>)       # click a button/link
# OR: click_screen(...) then type_text("query")     # fill an input field
# OR: drag_mouse(from_x, from_y, to_x, to_y)       # drag from verified point
# OR: scroll(x=<verified_x>, y=<verified_y>)        # scroll a specific panel

# Step 6: Confirm with Tier 1 screenshot
take_screenshot_full(
    title_pattern="Edge",
    image_format="webp", quality=30,
    include_ocr=false, include_ui=false
)
```

**Tips for faster convergence:**
- Start with `radius=100` (200x200 area) for a wider view, shrink to `radius=60` once you're close
- Each iteration is tiny (~5-15 KB for a small webp region) — cheap to do multiple rounds
- Common adjustments: if marker is off by a lot, shift 50-100px; if close, shift 10-20px
- The zoomed-in view has `scale_factor: 1.0` (no prescaling) so you see pixel-perfect detail
- For text links, aim for the horizontal center of the text and vertical middle of the line

**Real example — clicking a "Wikipedia" link not exposed by UI automation:**
```
Attempt 1: (1369, 386) → marker in news section, way off
Attempt 2: (1450, 225) → search bar area, wrong section
Attempt 3: (1530, 320) → About section visible, Wikipedia in corner
Attempt 4: (1575, 390) → almost, just above Wikipedia text
Attempt 5: (1555, 410) → right on "Wikipedia" — click!
→ Wikipedia page loaded successfully
```

**Why this matters:** Not every interactive element appears in the UI automation tree (especially
web content in Chromium browsers). This feedback loop gives the agent a reliable way to target
*any* coordinate on screen using only vision — whether to click, type, drag, or scroll. It's
the universal fallback for any coordinate-based interaction.

---

## Important Gotchas

### Window Activation

- **Always activate the target window** before interacting with it. Use `title_pattern` on tools that support it, or call `activate_window` explicitly.
- Without activation, clicks and keystrokes go to the wrong window, scroll events are ignored, and UI automation may return fewer elements.
- The activation uses `AttachThreadInput` on Windows to reliably bring windows to foreground (not just flash the taskbar).

### Edge/Chromium Zero-Width Spaces

- Microsoft Edge inserts invisible zero-width space characters (`\u200b`) in its window title ("Microsoft​ Edge").
- The MCP handles this internally — you can just match with `title_pattern="Edge"` and it works.

### Scrolling

- The `scroll` tool uses native Windows `mouse_event` with `WHEEL_DELTA=120` per click for reliable scrolling.
- **1 click ≈ 100px** of scroll (varies by app/OS settings).
- `amount=3` (default) ≈ half a page. `amount=10` ≈ roughly a full page.
- For scrolling inside specific elements (sidebars, dropdowns, iframes), use `x`/`y` to position the mouse over that element.
- Mouse wheel events go to whatever element is under the cursor — no click needed after initial positioning.

### UI Automation Limitations

- **Chromium web content**: Browser UI (toolbar, tabs) is well-exposed, but web page content has limited UIA exposure. Use OCR for reading web page text.
- **Custom-drawn widgets**: Canvas, game views, and custom-rendered UI won't appear in the accessibility tree. Use screenshot + vision or OCR instead.
- **Entry fields in web pages**: Often appear as `combo box` or `entry` but may lack the `entry` role. Search by name if role filter returns nothing.

### OCR Limitations

- Takes ~1-20 seconds depending on screen size and hardware.
- Works well for reading text, but coordinates can be slightly off for small text.
- Returns text lines/phrases (not individual words) — good for clicking text targets.
- Does not work on text inside images that are too small or low-contrast.
- **Always use `ocr_text_filter`** when searching for specific text — unfiltered full-screen OCR returns 60K+ chars that may get truncated.

### Coordinate Accuracy

- **UI Automation coordinates** (`abs_center_x`, `abs_center_y`) are the most reliable — click these directly.
- **OCR coordinates** (`abs_center_x`, `abs_center_y`) are good but occasionally off by a few pixels.
- **Screenshot visual estimates** require multiplying by `scale_factor` — least precise.
- When precision matters, use `capture_region_around(x, y)` to visually verify before clicking.

---

## Performance Tips

- Use `take_screenshot_full` with only the layers you need (`include_image`, `include_ocr`, `include_ui`).
- Disable OCR (`include_ocr=false`) when UI automation is sufficient — saves 1-20 seconds.
- Use `interactable_only=true` to cut UI element count by ~70%.
- Use `name_filter` / `role_filter` for targeted searches instead of parsing full UI trees.
- Use `ocr_text_filter` to search OCR results server-side — 97% smaller responses than unfiltered OCR.
- Use `webp` format with `quality=50` — 5x smaller than default PNG with no visible loss.
- For repeated screenshots of the same window, the window matching is cached — subsequent calls are faster.
- **Prefer `wait_for_window` over screenshot** when checking if an app launched — it's a lightweight poll with no image transfer.
- **Use `find_ui_elements` with `limit=20`** for focused searches — avoid returning 100+ elements when you only need a few.
- **Use semantic actions over coordinate clicking** when possible — `toggle_element`, `invoke_element`, `select_element` are more reliable than calculating coordinates and clicking.
- **Reuse element refs** within the same interaction sequence — no need to re-discover elements that haven't changed.
- **Use persistent file watchers** (`start_file_watch`) over one-shot waits when you need to catch events that may happen at unpredictable times.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Window doesn't activate | Old activation method (just flashes taskbar) | Use latest version with `AttachThreadInput` fix |
| UI automation returns 0 elements | Window not in foreground, or app has no accessibility support | Activate window first; use `launch_app` to relaunch with accessibility flags enabled |
| Scroll doesn't work | Mouse not over target window/element | Use `title_pattern` on `scroll` tool, or `click_screen` on the page first |
| Can't find web page elements via UIA | Chromium exposes limited web content in UIA | Use `launch_app(command=["google-chrome", url])` to launch with `--force-renderer-accessibility`; or use OCR/vision for web content |
| Screenshots are too large (tokens) | Default PNG at full resolution | Use `image_format="webp", quality=50` |
| Too many UI elements (tokens) | Unfiltered UI tree includes passive containers | Use `interactable_only=true`, `role_filter`, `name_filter` |
| OCR output too large / truncated | Full-screen OCR returns 60K+ chars | Use `ocr_text_filter="search term"` to filter server-side |
| OCR filter returns no results | Threshold too high or OCR misread the text | Lower `ocr_match_threshold` to 40, try alternate spellings with `\|` |
| Can't find desktop icon via UIA | Desktop icons use shell ListView, poorly exposed | Use `take_screenshot_with_ocr(ocr_text_filter="icon name")` + `click_screen(num_clicks=2)` |
| Element ref fails to resolve | Window title changed (e.g., after editing a file) | Re-discover with `find_ui_elements` using updated `title_pattern` |
| `toggle_element` / `select_element` fails | Element doesn't support the required UIA pattern | Use `get_element_details` to check supported patterns; fall back to `click_screen` |
| `find_ui_elements` returns too many results | No filters applied | Use `text_filter`, `role_filter`, `interactable_only=true`, and `limit=20` |
| `launch_app` PID doesn't match `list_processes` | Parent process exited, child has different PID | Use `list_processes` to find actual PID, or `kill_process(process_name=...)` |
| File watch returns "watchdog not installed" | `watchdog` library missing from Python environment | Install: `pip install watchdog` and restart MCP server |
| `wait_for_file_change` times out | Change happened before watcher initialized, or path wrong | Use persistent `start_file_watch` instead; verify path exists with correct format |
| `select_text_range` / `select_text_by_search` fails | Element doesn't support TextPattern | Only `document` and `edit` roles typically support TextPattern; fall back to `click_screen` + Shift+click for selection |
| `get_text_bounds` returns empty bounds | Window not active or control doesn't implement GetBoundingRectangles | Activate the window first with `activate_window`; some controls may not support bounds |
| `get_text_caret_offset` fails | TextPattern2 not available and no selection exists | Click into the text field first to establish a caret position |
