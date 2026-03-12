# Computer Control MCP — Agent Skill Guide

Best practices for AI agents using the Computer Control MCP to see, understand, and interact with desktop applications. This guide covers tool selection, optimization, common workflows, and pitfalls learned from real testing.

---

## Core Concepts

### Three-Layer Perception Model

No single source captures everything on screen. Use the right combination:

| Layer | What it captures | What it misses | When to use |
|-------|-----------------|----------------|-------------|
| **Screenshot** (image) | Everything visual — layout, colors, icons, graphics | No coordinates, no semantic info | Always — your primary "eyes" |
| **UI Automation** (accessibility tree) | Widgets: buttons, menus, entries, tabs — with names, roles, actions, bounding boxes | Custom-drawn content, canvas, images | When you need to find clickable elements |
| **OCR** (text detection) | Any visible text rendered on screen | Non-text graphics, icons without labels | When reading text from images/canvas that UI automation can't see |

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
| Launch an app | `wait_for_element` or screenshot |
| Open a dialog (Ctrl+O, Ctrl+S, etc.) | Screenshot — is the dialog visible? |
| Switch windows | Screenshot — is the right window in foreground? |
| Submit a form / press Enter | Screenshot — did the expected result happen? |
| Close a dialog / window | Screenshot — is it gone? |
| Navigate to a URL | Screenshot or `wait_for_text` — did the page load? |
| Click a button | Screenshot — did the UI change as expected? |

### Cost of verification vs cost of failure

A Tier 1 confirmation screenshot costs **~67 KB**. A failed blind action chain can waste **5-10 tool calls** going down the wrong path, plus the recovery effort. Always verify — it's cheaper than debugging.

---

## Tool Selection Quick Reference

| I want to... | Use this tool | Key parameters |
|--------------|--------------|----------------|
| See what's on screen | `take_screenshot_full` | `image_format="webp", quality=50` |
| Find a button/field to click | `take_screenshot_with_ui_automation` | `interactable_only=true` |
| Find specific UI elements | `take_screenshot_with_ui_automation` | `name_filter`, `role_filter` |
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
wait_for_element(name_filter="Notepad", role_filter="window", timeout_ms=5000)
# OR
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
