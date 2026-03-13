"""
Cross-platform UI Automation (Accessibility Tree) support.

Provides structured widget data (buttons, menus, entries) with semantic roles,
names, actions, and precise bounding boxes. Supports:
- Windows: Microsoft UI Automation (UIA) via `uiautomation` package
- Linux: AT-SPI via `gi.repository.Atspi` + wmctrl/xprop for window stacking

Key feature: occlusion filtering — only returns elements from visible/foreground
windows, filtering out "ghost" elements hidden behind other windows.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


# ── Geometry Helpers ────────────────────────────────────────────────────
# Ported from dump_visible_screen.py — pure functions, no platform deps.


def _rect_intersect(
    a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]
) -> Optional[Tuple[int, int, int, int]]:
    """Compute intersection of two rectangles (x1, y1, x2, y2). Returns None if no overlap."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x1 < x2 and y1 < y2:
        return (x1, y1, x2, y2)
    return None


def _subtract_rect(
    base: Tuple[int, int, int, int], cut: Tuple[int, int, int, int]
) -> List[Tuple[int, int, int, int]]:
    """Subtract cut from base, return list of remaining rectangles."""
    overlap = _rect_intersect(base, cut)
    if overlap is None:
        return [base]
    bx1, by1, bx2, by2 = base
    ox1, oy1, ox2, oy2 = overlap
    result = []
    # Top strip
    if by1 < oy1:
        result.append((bx1, by1, bx2, oy1))
    # Bottom strip
    if oy2 < by2:
        result.append((bx1, oy2, bx2, by2))
    # Left strip (middle band only)
    if bx1 < ox1:
        result.append((bx1, oy1, ox1, oy2))
    # Right strip (middle band only)
    if ox2 < bx2:
        result.append((ox2, oy1, bx2, oy2))
    return result


def _compute_visible_regions(
    windows: List[Dict], screen_w: int, screen_h: int
) -> Dict[str, List[Tuple[int, int, int, int]]]:
    """
    For each window, compute which rectangular regions are actually visible
    (not occluded by windows above it in the stacking order).

    Windows list must be ordered bottom-to-top (lowest z-order first).
    Returns {window_id: [(x1, y1, x2, y2), ...]} for visible rectangles.
    """
    visible = {}
    for i, win in enumerate(windows):
        # Start with the full window rect, clipped to screen
        wx1 = max(0, win["x"])
        wy1 = max(0, win["y"])
        wx2 = min(screen_w, win["x"] + win["w"])
        wy2 = min(screen_h, win["y"] + win["h"])
        if wx1 >= wx2 or wy1 >= wy2:
            visible[win["id"]] = []
            continue

        regions = [(wx1, wy1, wx2, wy2)]

        # Subtract all windows above this one
        for j in range(i + 1, len(windows)):
            above = windows[j]
            ax1 = max(0, above["x"])
            ay1 = max(0, above["y"])
            ax2 = min(screen_w, above["x"] + above["w"])
            ay2 = min(screen_h, above["y"] + above["h"])
            if ax1 >= ax2 or ay1 >= ay2:
                continue
            cut = (ax1, ay1, ax2, ay2)
            new_regions = []
            for r in regions:
                new_regions.extend(_subtract_rect(r, cut))
            regions = new_regions

        visible[win["id"]] = regions

    return visible


def _point_in_regions(
    px: int, py: int, regions: List[Tuple[int, int, int, int]]
) -> bool:
    """Check if a point falls within any of the given rectangles."""
    for x1, y1, x2, y2 in regions:
        if x1 <= px < x2 and y1 <= py < y2:
            return True
    return False


def _rect_mostly_in_regions(
    bx: int, by: int, bw: int, bh: int,
    regions: List[Tuple[int, int, int, int]],
    threshold: float = 0.6,
) -> bool:
    """Check if at least threshold fraction of the element's area overlaps visible regions."""
    if bw <= 0 or bh <= 0:
        return False
    elem_area = bw * bh
    visible_area = 0
    for rx1, ry1, rx2, ry2 in regions:
        ox1 = max(bx, rx1)
        oy1 = max(by, ry1)
        ox2 = min(bx + bw, rx2)
        oy2 = min(by + bh, ry2)
        if ox1 < ox2 and oy1 < oy2:
            visible_area += (ox2 - ox1) * (oy2 - oy1)
    return (visible_area / elem_area) >= threshold


def _make_element(
    role: str,
    name: str = "",
    bounds: Optional[Dict[str, int]] = None,
    actions: Optional[List[str]] = None,
    depth: int = 0,
    text: str = "",
    **extras: Any,
) -> Dict[str, Any]:
    """Create a normalized UI element dict with abs_center computed from bounds."""
    entry = {"role": role, "depth": depth}
    if name:
        entry["name"] = name
    if text:
        entry["text"] = text
    if bounds:
        entry["bounds"] = bounds
        entry["abs_center_x"] = bounds["x"] + bounds["w"] // 2
        entry["abs_center_y"] = bounds["y"] + bounds["h"] // 2
    if actions:
        entry["actions"] = actions
    for key, value in extras.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        entry[key] = value
    return entry


def _element_in_region(el: Dict, region_rect: Tuple[int, int, int, int]) -> bool:
    """Check if element's center falls within the region rectangle (x1, y1, x2, y2)."""
    cx = el.get("abs_center_x")
    cy = el.get("abs_center_y")
    if cx is None or cy is None:
        return False
    rx1, ry1, rx2, ry2 = region_rect
    return rx1 <= cx <= rx2 and ry1 <= cy <= ry2


def _filter_apps_by_region(all_apps: List[Dict], region: list) -> Tuple[List[Dict], int]:
    """Filter application element lists to only include elements within the region.

    Returns (filtered_apps, count_removed).
    """
    rx, ry, rw, rh = int(region[0]), int(region[1]), int(region[2]), int(region[3])
    region_rect = (rx, ry, rx + rw, ry + rh)
    filtered_apps = []
    removed = 0
    for app in all_apps:
        kept = [el for el in app["elements"] if _element_in_region(el, region_rect)]
        removed += len(app["elements"]) - len(kept)
        if kept:
            filtered_apps.append({
                "application": app["application"],
                "window_ids": app.get("window_ids", []),
                "elements": kept,
            })
    return filtered_apps, removed


def _flatten_applications(apps: List[Dict]) -> List[Dict]:
    flat: List[Dict] = []
    for app in apps:
        flat.extend(app.get("elements", []))
    return flat


def _element_contains_point(el: Dict[str, Any], x: int, y: int) -> bool:
    b = el.get("bounds")
    if not b:
        return False
    return b["x"] <= x <= (b["x"] + b["w"]) and b["y"] <= y <= (b["y"] + b["h"])


def _compact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: v for k, v in data.items()
        if v is not None and v != "" and v != [] and v != {}
    }


def _sanitize_match_text(value: str) -> str:
    return re.sub(r'[\u200b\u200c\u200d\ufeff]', '', (value or '')).strip().lower()


# ── Windows UIA Implementation ──────────────────────────────────────────

UI_AUTOMATION_AVAILABLE = False

if sys.platform == "win32":
    try:
        import uiautomation as auto
        import win32gui
        import win32con
        UI_AUTOMATION_AVAILABLE = True
    except ImportError:
        pass


# UIA ControlType to friendly role name mapping
_UIA_ROLE_MAP = {
    "ButtonControl": "push button",
    "CalendarControl": "calendar",
    "CheckBoxControl": "check box",
    "ComboBoxControl": "combo box",
    "DataGridControl": "data grid",
    "DataItemControl": "data item",
    "DocumentControl": "document",
    "EditControl": "entry",
    "GroupControl": "group",
    "HeaderControl": "header",
    "HeaderItemControl": "header item",
    "HyperlinkControl": "link",
    "ImageControl": "image",
    "ListControl": "list",
    "ListItemControl": "list item",
    "MenuControl": "menu",
    "MenuBarControl": "menu bar",
    "MenuItemControl": "menu item",
    "PaneControl": "pane",
    "ProgressBarControl": "progress bar",
    "RadioButtonControl": "radio button",
    "ScrollBarControl": "scroll bar",
    "SemanticZoomControl": "semantic zoom",
    "SeparatorControl": "separator",
    "SliderControl": "slider",
    "SpinnerControl": "spinner",
    "SplitButtonControl": "split button",
    "StatusBarControl": "status bar",
    "TabControl": "tab",
    "TabItemControl": "page tab",
    "TableControl": "table",
    "TextControl": "text",
    "ThumbControl": "thumb",
    "TitleBarControl": "title bar",
    "ToolBarControl": "tool bar",
    "ToolTipControl": "tool tip",
    "TreeControl": "tree",
    "TreeItemControl": "tree item",
    "WindowControl": "frame",
    "AppBarControl": "app bar",
    "CustomControl": "custom",
}


def _get_windows_stacking_order_win32() -> List[Dict]:
    """Get windows ordered by Z-order (bottom to top) using win32gui."""
    if not UI_AUTOMATION_AVAILABLE:
        return []

    windows = []
    try:
        # GetTopWindow returns the topmost child of the desktop
        hwnd = win32gui.GetTopWindow(None)
        # Traverse Z-order top to bottom using GW_HWNDNEXT
        top_to_bottom = []
        while hwnd:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:  # Only include windows with titles
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        x, y = rect[0], rect[1]
                        w, h = rect[2] - rect[0], rect[3] - rect[1]
                        if w > 0 and h > 0:
                            top_to_bottom.append({
                                "id": hex(hwnd),
                                "hwnd": hwnd,
                                "name": title,
                                "x": x, "y": y, "w": w, "h": h,
                            })
                    except Exception:
                        pass
            hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)

        # Reverse to get bottom-to-top order (matching dump_visible_screen.py convention)
        windows = list(reversed(top_to_bottom))
    except Exception:
        pass

    return windows


# Roles that are typically actionable — used as heuristic instead of expensive COM pattern queries
_CLICKABLE_ROLES = frozenset({
    "push button", "menu item", "hyperlink", "split button", "menu",
    "page tab", "tree item", "list item", "check box", "radio button",
    "toggle", "button",
})
_TOGGLEABLE_ROLES = frozenset({"check box", "radio button", "toggle"})
_EXPANDABLE_ROLES = frozenset({"menu", "menu item", "tree item", "combo box", "split button"})
_SELECTABLE_ROLES = frozenset({"list item", "tree item", "page tab"})


def _collect_uia_elements(control, depth: int = 0, max_depth: int = 40) -> List[Dict]:
    """Recursively collect UIA elements in normalized format.

    Optimized to minimize expensive COM calls:
    - Action detection uses role heuristics instead of GetXPattern() COM queries
    - Text extraction via GetValuePattern() removed (expensive per-node COM call)
    """
    if control is None or depth > max_depth:
        return []

    elements = []

    try:
        control_type = control.ControlTypeName
        role = _UIA_ROLE_MAP.get(control_type, control_type.replace("Control", "").lower())
    except Exception:
        role = "unknown"

    name = ""
    try:
        name = control.Name or ""
    except Exception:
        pass

    bounds = None
    try:
        rect = control.BoundingRectangle
        if rect.width() > 0 and rect.height() > 0 and rect.left >= 0 and rect.top >= 0:
            bounds = {
                "x": int(rect.left),
                "y": int(rect.top),
                "w": int(rect.width()),
                "h": int(rect.height()),
            }
    except Exception:
        pass

    # Infer actions from role (avoids expensive COM pattern queries like
    # GetInvokePattern, GetTogglePattern, GetExpandCollapsePattern, GetSelectionItemPattern)
    actions = []
    if role in _CLICKABLE_ROLES:
        actions.append("click")
    if role in _TOGGLEABLE_ROLES:
        actions.append("toggle")
    if role in _EXPANDABLE_ROLES:
        actions.append("expand/collapse")
    if role in _SELECTABLE_ROLES:
        actions.append("select")

    element = _make_element(
        role=role, name=name, bounds=bounds,
        actions=actions if actions else None,
        depth=depth,
    )
    elements.append(element)

    # Recurse into children
    try:
        children = control.GetChildren()
        if children:
            for child in children:
                elements.extend(_collect_uia_elements(child, depth + 1, max_depth))
    except Exception:
        pass

    return elements


def _match_uia_window_to_stacking(uia_window, windows: List[Dict]) -> List[str]:
    """Match a UIA top-level window to win32gui windows by HWND or title."""
    matched = set()

    # Try matching by NativeWindowHandle (HWND)
    try:
        hwnd = uia_window.NativeWindowHandle
        if hwnd:
            hwnd_hex = hex(hwnd)
            for win in windows:
                if win["id"] == hwnd_hex:
                    matched.add(win["id"])
    except Exception:
        pass

    # Fallback: match by title
    if not matched:
        try:
            uia_name = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', (uia_window.Name or "").lower())
            if uia_name:
                for win in windows:
                    wn = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', win["name"].lower())
                    if wn and (uia_name in wn or wn in uia_name):
                        matched.add(win["id"])
        except Exception:
            pass

    # Fallback: match by bounds overlap
    if not matched:
        try:
            rect = uia_window.BoundingRectangle
            ub = {"x": int(rect.left), "y": int(rect.top), "w": int(rect.width()), "h": int(rect.height())}
            for win in windows:
                if (abs(ub["x"] - win["x"]) < 80 and
                    abs(ub["y"] - win["y"]) < 80 and
                    abs(ub["w"] - win["w"]) < 80 and
                    abs(ub["h"] - win["h"]) < 80):
                    matched.add(win["id"])
        except Exception:
            pass

    return list(matched)


def _get_ui_elements_win32(app_filter: Optional[str] = None) -> Dict:
    """Full Windows pipeline: stacking order → UIA collection → occlusion filtering.

    Args:
        app_filter: If provided, only collect elements from windows whose title
                    contains this string (case-insensitive). Massively speeds up
                    collection by skipping irrelevant app trees (e.g. VS Code).
    """
    import pyautogui

    # Ensure COM is initialized for this thread (needed when called from ThreadPoolExecutor)
    try:
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass

    screen_w, screen_h = pyautogui.size()

    t0 = time.perf_counter()

    # Get window stacking order
    windows = _get_windows_stacking_order_win32()
    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)

    # Collect UIA elements per top-level window
    all_apps = []
    total_before = 0
    total_after = 0
    app_filter_lower = app_filter.lower() if app_filter else None

    try:
        root = auto.GetRootControl()
        top_level_windows = root.GetChildren()

        for uia_window in (top_level_windows or []):
            try:
                app_name = uia_window.Name or "unknown"
            except Exception:
                app_name = "unknown"

            # Skip windows that don't match the filter (avoids expensive tree traversal)
            # Strip zero-width characters for comparison (Edge uses \u200b in title)
            app_name_clean = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', app_name.lower())
            if app_filter_lower and app_filter_lower not in app_name_clean:
                continue

            elements = _collect_uia_elements(uia_window)
            total_before += len(elements)

            # Match to stacking windows
            win_ids = _match_uia_window_to_stacking(uia_window, windows)

            if win_ids:
                # Merge visible regions from all matched windows
                all_regions = []
                for wid in win_ids:
                    if wid in visible_regions:
                        all_regions.extend(visible_regions[wid])

                # Filter: keep only elements whose bounds are mostly visible
                filtered = []
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
                        filtered.append(el)

                if filtered:
                    all_apps.append({
                        "application": app_name,
                        "window_ids": win_ids,
                        "elements": filtered,
                    })
                    total_after += len(filtered)
            else:
                # Windows without stacking match — include if on screen
                screen_region = [(0, 0, screen_w, screen_h)]
                filtered = []
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], screen_region):
                        filtered.append(el)
                if filtered:
                    all_apps.append({
                        "application": app_name,
                        "window_ids": [],
                        "elements": filtered,
                    })
                    total_after += len(filtered)
    except Exception as e:
        return {
            "available": True,
            "error": f"Error collecting UIA elements: {str(e)}",
            "screen": {"width": screen_w, "height": screen_h},
            "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
            "ui_elements": {
                "time_s": round(time.perf_counter() - t0, 3),
                "element_count": 0,
                "filtered_out": 0,
                "applications": [],
            },
        }

    elapsed = time.perf_counter() - t0

    return {
        "available": True,
        "error": None,
        "screen": {"width": screen_w, "height": screen_h},
        "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
        "ui_elements": {
            "time_s": round(elapsed, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
    }


# ── Linux AT-SPI Implementation ────────────────────────────────────────

ATSPI_AVAILABLE = False

if sys.platform != "win32":
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        ATSPI_AVAILABLE = True
    except (ImportError, ValueError):
        pass


def _get_windows_stacking_order_linux() -> List[Dict]:
    """Get windows with geometry from wmctrl, ordered by stacking (bottom to top)."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return []
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":1")}

    # Get stacking order (bottom to top)
    try:
        result = subprocess.run(
            ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
            capture_output=True, text=True, env=env, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    stacking_ids = []
    m = re.search(r"window id #\s*(.+)", result.stdout)
    if m:
        stacking_ids = [int(x.strip(), 16) for x in m.group(1).split(",")]

    # Get window list with geometry
    try:
        result = subprocess.run(
            ["wmctrl", "-l", "-G"],
            capture_output=True, text=True, env=env, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    win_map = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        wid_int = int(parts[0], 16)
        wid_str = parts[0]
        x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
        name = parts[7] if len(parts) > 7 else ""
        win_map[wid_int] = {
            "id": wid_str, "name": name,
            "x": x, "y": y, "w": w, "h": h,
        }

    # Return in stacking order (bottom to top)
    ordered = []
    for wid_int in stacking_ids:
        if wid_int in win_map:
            ordered.append(win_map[wid_int])
    return ordered


def _collect_atspi_elements(node, depth: int = 0, max_depth: int = 40) -> List[Dict]:
    """Recursively collect AT-SPI elements in normalized format."""
    if node is None or depth > max_depth:
        return []

    elements = []

    try:
        role = node.get_role_name()
    except Exception:
        role = "unknown"

    name = ""
    try:
        name = node.get_name() or ""
    except Exception:
        pass

    text = ""
    try:
        ti = node.get_text_iface()
        if ti:
            cc = ti.get_character_count()
            text = ti.get_text(0, min(cc, 1000))
    except Exception:
        pass

    actions = []
    try:
        ai = node.get_action_iface()
        if ai:
            for i in range(ai.get_n_actions()):
                actions.append(ai.get_action_name(i))
    except Exception:
        pass

    bounds = None
    try:
        comp = node.get_component_iface()
        if comp is not None:
            r = comp.get_extents(Atspi.CoordType.SCREEN)
            if r.width > 0 and r.height > 0 and r.x >= 0 and r.y >= 0:
                bounds = {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
    except Exception:
        pass

    element = _make_element(
        role=role, name=name, bounds=bounds,
        actions=actions if actions else None,
        depth=depth, text=text,
    )
    elements.append(element)

    # Recurse into children
    try:
        for i in range(node.get_child_count()):
            try:
                child = node.get_child_at_index(i)
                elements.extend(_collect_atspi_elements(child, depth + 1, max_depth))
            except Exception:
                continue
    except Exception:
        pass

    return elements


def _match_app_to_windows_linux(
    app_name: str, app_elements: List[Dict], windows: List[Dict]
) -> List[str]:
    """Match an AT-SPI app to wmctrl windows. Port of dump_visible_screen.py:237-270."""
    matched = set()

    # Match each frame to a window by name or bounds
    for el in app_elements:
        if el.get("role") != "frame":
            continue
        frame_name = (el.get("name") or "").lower()
        eb = el.get("bounds")

        # Try name match first
        if frame_name:
            for win in windows:
                wn = win["name"].lower()
                if wn and (frame_name in wn or wn in frame_name):
                    matched.add(win["id"])

        # Try bounds match
        if eb:
            for win in windows:
                if (abs(eb["x"] - win["x"]) < 80 and
                    abs(eb["y"] - win["y"]) < 80 and
                    abs(eb["w"] - win["w"]) < 80 and
                    abs(eb["h"] - win["h"]) < 80):
                    matched.add(win["id"])

    # Fallback: match by app name substring
    if not matched:
        for win in windows:
            if app_name.lower() in win["name"].lower() or win["name"].lower() in app_name.lower():
                matched.add(win["id"])

    return list(matched)


def _get_screen_size_linux() -> Tuple[int, int]:
    """Get screen dimensions on Linux via xdpyinfo or fallback."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        try:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[0]
                return mon["width"], mon["height"]
        except Exception:
            pass
    try:
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":1")}
        result = subprocess.run(
            ["xdpyinfo"], capture_output=True, text=True, env=env, timeout=5,
        )
        m = re.search(r"dimensions:\s+(\d+)x(\d+)", result.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1280, 720  # fallback


def _get_ui_elements_linux(app_filter: Optional[str] = None) -> Dict:
    """Full Linux pipeline: stacking order → AT-SPI collection → occlusion filtering.

    Args:
        app_filter: If provided, only collect elements from apps whose name
                    contains this string (case-insensitive).
    """
    screen_w, screen_h = _get_screen_size_linux()

    t0 = time.perf_counter()

    # Get window stacking order
    windows = _get_windows_stacking_order_linux()
    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)

    # Collect AT-SPI elements
    all_apps = []
    total_before = 0
    total_after = 0
    app_filter_lower = app_filter.lower() if app_filter else None

    try:
        desktop = Atspi.get_desktop(0)

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                app_name = app.get_name() or f"app_{i}"
            except Exception:
                continue

            # Skip apps that don't match the filter
            if app_filter_lower and app_filter_lower not in app_name.lower():
                continue

            elements = _collect_atspi_elements(app)
            total_before += len(elements)

            # Match app to one or more windows
            win_ids = _match_app_to_windows_linux(app_name, elements, windows)

            if win_ids:
                # Merge visible regions from all matched windows
                all_regions = []
                for wid in win_ids:
                    if wid in visible_regions:
                        all_regions.extend(visible_regions[wid])

                # Filter: keep only elements whose bounds are mostly visible
                filtered = []
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
                        filtered.append(el)

                if filtered:
                    all_apps.append({
                        "application": app_name,
                        "window_ids": win_ids,
                        "elements": filtered,
                    })
                    total_after += len(filtered)
            else:
                # Apps without matching windows (desktop, etc.)
                screen_region = [(0, 0, screen_w, screen_h)]
                filtered = []
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], screen_region):
                        filtered.append(el)
                if filtered:
                    all_apps.append({
                        "application": app_name,
                        "window_ids": [],
                        "elements": filtered,
                    })
                    total_after += len(filtered)
    except Exception as e:
        return {
            "available": True,
            "error": f"Error collecting AT-SPI elements: {str(e)}",
            "screen": {"width": screen_w, "height": screen_h},
            "windows": windows,
            "ui_elements": {
                "time_s": round(time.perf_counter() - t0, 3),
                "element_count": 0,
                "filtered_out": 0,
                "applications": [],
            },
        }

    elapsed = time.perf_counter() - t0

    return {
        "available": True,
        "error": None,
        "warning": (
            "Wayland session detected; AT-SPI is available, but X11-based window stacking/"
            "occlusion data may be incomplete."
            if (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"))
            else None
        ),
        "screen": {"width": screen_w, "height": screen_h},
        "windows": windows,
        "ui_elements": {
            "time_s": round(elapsed, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
    }


# ── Deep UI Automation / AT-SPI Helpers ────────────────────────────────


def _uia_pattern_names(control) -> List[str]:
    mapping = [
        ("invoke", "IsInvokePatternAvailable"),
        ("value", "IsValuePatternAvailable"),
        ("text", "IsTextPatternAvailable"),
        ("selection", "IsSelectionPatternAvailable"),
        ("selection_item", "IsSelectionItemPatternAvailable"),
        ("toggle", "IsTogglePatternAvailable"),
        ("expand_collapse", "IsExpandCollapsePatternAvailable"),
        ("scroll", "IsScrollPatternAvailable"),
        ("scroll_item", "IsScrollItemPatternAvailable"),
        ("range_value", "IsRangeValuePatternAvailable"),
        ("transform", "IsTransformPatternAvailable"),
        ("window", "IsWindowPatternAvailable"),
        ("legacy_iaccessible", "IsLegacyIAccessiblePatternAvailable"),
    ]
    out: List[str] = []
    for name, attr in mapping:
        try:
            if bool(getattr(control, attr)):
                out.append(name)
        except Exception:
            pass
    return out


def _uia_state_flags(control) -> Dict[str, Any]:
    mapping = [
        ("enabled", "IsEnabled"),
        ("keyboard_focusable", "IsKeyboardFocusable"),
        ("has_keyboard_focus", "HasKeyboardFocus"),
        ("offscreen", "IsOffscreen"),
        ("password", "IsPassword"),
        ("content_element", "IsContentElement"),
        ("control_element", "IsControlElement"),
    ]
    out: Dict[str, Any] = {}
    for key, attr in mapping:
        try:
            out[key] = bool(getattr(control, attr))
        except Exception:
            pass
    return out


def _uia_text_value_snapshot(control, max_chars: int = 2000) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        value_pattern = control.GetValuePattern()
        if value_pattern:
            value = getattr(value_pattern, "Value", None)
            if value is not None:
                result["value"] = str(value)[:max_chars]
    except Exception:
        pass
    try:
        text_pattern = control.GetTextPattern()
        if text_pattern and getattr(text_pattern, "DocumentRange", None):
            text = text_pattern.DocumentRange.GetText(max_chars)
            if text:
                result["text"] = text[:max_chars]
    except Exception:
        pass
    if "text" not in result:
        try:
            name = control.Name or ""
            if name:
                result["text"] = name[:max_chars]
        except Exception:
            pass
    return result


def _atspi_interface_names(node) -> List[str]:
    checks = [
        ("action", "get_action_iface"),
        ("component", "get_component_iface"),
        ("text", "get_text_iface"),
        ("editable_text", "get_editable_text_iface"),
        ("value", "get_value_iface"),
        ("selection", "get_selection_iface"),
        ("document", "get_document_iface"),
        ("image", "get_image_iface"),
        ("table", "get_table_iface"),
        ("hypertext", "get_hypertext_iface"),
    ]
    out: List[str] = []
    for name, getter_name in checks:
        try:
            getter = getattr(node, getter_name)
            if getter() is not None:
                out.append(name)
        except Exception:
            pass
    return out


def _atspi_state_names(node) -> List[str]:
    out: List[str] = []
    try:
        ss = node.get_state_set()
        for st in ss.get_states():
            value = getattr(st, "value_nick", None) or getattr(st, "value_name", None) or str(st)
            out.append(str(value).lower())
    except Exception:
        pass
    return out


def _atspi_text_value_snapshot(node, max_chars: int = 2000) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        ti = node.get_text_iface()
        if ti:
            count = ti.get_character_count()
            result["text"] = ti.get_text(0, min(count, max_chars))
    except Exception:
        pass
    try:
        vi = node.get_value_iface()
        if vi:
            try:
                value_text = vi.get_text()
                if value_text:
                    result["value"] = value_text[:max_chars]
            except Exception:
                result["value"] = str(vi.get_current_value())
    except Exception:
        pass
    if "text" not in result:
        try:
            name = node.get_name() or ""
            if name:
                result["text"] = name[:max_chars]
        except Exception:
            pass
    return result


def _collect_uia_elements_deep(
    control,
    app_name: str,
    window_ids: List[str],
    path: Optional[List[int]] = None,
    depth: int = 0,
    max_depth: int = 40,
) -> List[Dict[str, Any]]:
    if control is None or depth > max_depth:
        return []

    path = list(path or [])

    try:
        control_type = control.ControlTypeName
        role = _UIA_ROLE_MAP.get(control_type, control_type.replace("Control", "").lower())
    except Exception:
        role = "unknown"

    name = ""
    try:
        name = control.Name or ""
    except Exception:
        pass

    bounds = None
    try:
        rect = control.BoundingRectangle
        if rect.width() > 0 and rect.height() > 0 and rect.left >= 0 and rect.top >= 0:
            bounds = {
                "x": int(rect.left),
                "y": int(rect.top),
                "w": int(rect.width()),
                "h": int(rect.height()),
            }
    except Exception:
        pass

    children = []
    try:
        children = control.GetChildren() or []
    except Exception:
        children = []

    states = _uia_state_flags(control)
    patterns = _uia_pattern_names(control)
    snapshot = _uia_text_value_snapshot(control)

    element_ref = _compact_dict({
        "backend": "uia",
        "app": app_name,
        "window_ids": window_ids,
        "path": path,
        "role": role,
        "name": name,
        "bounds": bounds,
    })

    element = _make_element(
        role=role,
        name=name,
        bounds=bounds,
        actions=patterns or None,
        depth=depth,
        text=snapshot.get("text", ""),
        value=snapshot.get("value"),
        backend="uia",
        application=app_name,
        window_ids=window_ids,
        ref=element_ref,
        patterns=patterns,
        states=states,
        child_count=len(children),
        automation_id=getattr(control, "AutomationId", None),
        class_name=getattr(control, "ClassName", None),
        framework_id=getattr(control, "FrameworkId", None),
        process_id=getattr(control, "ProcessId", None),
        native_window_handle=getattr(control, "NativeWindowHandle", None),
        description=getattr(control, "HelpText", None),
        keyboard_shortcut=(getattr(control, "AccessKey", None) or getattr(control, "AcceleratorKey", None)),
        localized_control_type=getattr(control, "LocalizedControlType", None),
    )

    elements = [element]
    for idx, child in enumerate(children):
        elements.extend(
            _collect_uia_elements_deep(
                child,
                app_name=app_name,
                window_ids=window_ids,
                path=path + [idx],
                depth=depth + 1,
                max_depth=max_depth,
            )
        )
    return elements


def _collect_atspi_elements_deep(
    node,
    app_name: str,
    window_ids: List[str],
    path: Optional[List[int]] = None,
    depth: int = 0,
    max_depth: int = 40,
) -> List[Dict[str, Any]]:
    if node is None or depth > max_depth:
        return []

    path = list(path or [])

    try:
        role = node.get_role_name()
    except Exception:
        role = "unknown"

    try:
        name = node.get_name() or ""
    except Exception:
        name = ""

    bounds = None
    try:
        comp = node.get_component_iface()
        if comp is not None:
            r = comp.get_extents(Atspi.CoordType.SCREEN)
            if r.width > 0 and r.height > 0 and r.x >= 0 and r.y >= 0:
                bounds = {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
    except Exception:
        pass

    snapshot = _atspi_text_value_snapshot(node)
    states = _atspi_state_names(node)
    interfaces = _atspi_interface_names(node)

    actions: List[str] = []
    try:
        ai = node.get_action_iface()
        if ai:
            for i in range(ai.get_n_actions()):
                try:
                    actions.append(ai.get_action_name(i))
                except Exception:
                    continue
    except Exception:
        pass

    child_count = 0
    try:
        child_count = node.get_child_count()
    except Exception:
        pass

    description = None
    try:
        description = node.get_description() or None
    except Exception:
        pass

    element_ref = _compact_dict({
        "backend": "atspi",
        "app": app_name,
        "window_ids": window_ids,
        "path": path,
        "role": role,
        "name": name,
        "bounds": bounds,
    })

    element = _make_element(
        role=role,
        name=name,
        bounds=bounds,
        actions=actions or None,
        depth=depth,
        text=snapshot.get("text", ""),
        value=snapshot.get("value"),
        backend="atspi",
        application=app_name,
        window_ids=window_ids,
        ref=element_ref,
        interfaces=interfaces,
        states=states,
        child_count=child_count,
        description=description,
    )

    elements = [element]
    for i in range(child_count):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            continue
        elements.extend(
            _collect_atspi_elements_deep(
                child,
                app_name=app_name,
                window_ids=window_ids,
                path=path + [i],
                depth=depth + 1,
                max_depth=max_depth,
            )
        )
    return elements


def _get_deep_ui_elements_win32(
    app_filter: Optional[str] = None,
    include_hidden: bool = False,
    max_depth: int = 40,
) -> Dict[str, Any]:
    import pyautogui

    try:
        import ctypes
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass

    screen_w, screen_h = pyautogui.size()
    t0 = time.perf_counter()

    windows = _get_windows_stacking_order_win32()
    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)

    all_apps = []
    total_before = 0
    total_after = 0
    app_filter_lower = _sanitize_match_text(app_filter) if app_filter else None

    try:
        root = auto.GetRootControl()
        top_level_windows = root.GetChildren()

        for uia_window in (top_level_windows or []):
            try:
                app_name = uia_window.Name or "unknown"
            except Exception:
                app_name = "unknown"

            if app_filter_lower and app_filter_lower not in _sanitize_match_text(app_name):
                continue

            win_ids = _match_uia_window_to_stacking(uia_window, windows)
            elements = _collect_uia_elements_deep(
                uia_window,
                app_name=app_name,
                window_ids=win_ids,
                path=[],
                depth=0,
                max_depth=max_depth,
            )
            total_before += len(elements)

            if include_hidden:
                filtered = elements
            else:
                filtered = []
                all_regions = []
                for wid in win_ids:
                    all_regions.extend(visible_regions.get(wid, []))
                if not all_regions:
                    all_regions = [(0, 0, screen_w, screen_h)]
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
                        filtered.append(el)

            if filtered:
                all_apps.append({
                    "application": app_name,
                    "window_ids": win_ids,
                    "elements": filtered,
                })
                total_after += len(filtered)
    except Exception as e:
        return {
            "available": True,
            "backend": "uia",
            "error": f"Error collecting deep UIA elements: {str(e)}",
            "screen": {"width": screen_w, "height": screen_h},
            "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
            "ui_elements": {
                "time_s": round(time.perf_counter() - t0, 3),
                "element_count": 0,
                "filtered_out": 0,
                "applications": [],
            },
        }

    return {
        "available": True,
        "backend": "uia",
        "error": None,
        "screen": {"width": screen_w, "height": screen_h},
        "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
        "ui_elements": {
            "time_s": round(time.perf_counter() - t0, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
    }


def _get_deep_ui_elements_linux(
    app_filter: Optional[str] = None,
    include_hidden: bool = False,
    max_depth: int = 40,
) -> Dict[str, Any]:
    screen_w, screen_h = _get_screen_size_linux()
    t0 = time.perf_counter()

    windows = _get_windows_stacking_order_linux()
    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)

    all_apps = []
    total_before = 0
    total_after = 0
    app_filter_lower = _sanitize_match_text(app_filter) if app_filter else None

    try:
        desktop = Atspi.get_desktop(0)

        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                app_name = app.get_name() or f"app_{i}"
            except Exception:
                continue

            if app_filter_lower and app_filter_lower not in _sanitize_match_text(app_name):
                continue

            elements = _collect_atspi_elements_deep(
                app,
                app_name=app_name,
                window_ids=[],
                path=[],
                depth=0,
                max_depth=max_depth,
            )
            total_before += len(elements)

            win_ids = _match_app_to_windows_linux(app_name, elements, windows)

            if include_hidden:
                filtered = elements
            else:
                filtered = []
                all_regions = []
                for wid in win_ids:
                    all_regions.extend(visible_regions.get(wid, []))
                if not all_regions:
                    all_regions = [(0, 0, screen_w, screen_h)]
                for el in elements:
                    b = el.get("bounds")
                    if not b:
                        continue
                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
                        filtered.append(el)

            if filtered:
                for el in filtered:
                    el["window_ids"] = win_ids
                    if "ref" in el:
                        el["ref"]["window_ids"] = win_ids
                all_apps.append({
                    "application": app_name,
                    "window_ids": win_ids,
                    "elements": filtered,
                })
                total_after += len(filtered)
    except Exception as e:
        return {
            "available": True,
            "backend": "atspi",
            "error": f"Error collecting deep AT-SPI elements: {str(e)}",
            "screen": {"width": screen_w, "height": screen_h},
            "windows": windows,
            "ui_elements": {
                "time_s": round(time.perf_counter() - t0, 3),
                "element_count": 0,
                "filtered_out": 0,
                "applications": [],
            },
        }

    return {
        "available": True,
        "backend": "atspi",
        "error": None,
        "screen": {"width": screen_w, "height": screen_h},
        "windows": windows,
        "ui_elements": {
            "time_s": round(time.perf_counter() - t0, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
    }


def _uia_follow_path(control, path: List[int]):
    current = control
    for idx in path:
        try:
            children = current.GetChildren() or []
        except Exception:
            return None
        if idx < 0 or idx >= len(children):
            return None
        current = children[idx]
    return current


def _atspi_follow_path(node, path: List[int]):
    current = node
    for idx in path:
        try:
            current = current.get_child_at_index(idx)
        except Exception:
            return None
    return current


def _resolve_uia_element(ref: Dict[str, Any]) -> Dict[str, Any]:
    target_app = _sanitize_match_text(ref.get("app", ""))
    target_ids = set(ref.get("window_ids") or [])
    target_path = list(ref.get("path") or [])

    windows = _get_windows_stacking_order_win32()
    try:
        root = auto.GetRootControl()
        for top in (root.GetChildren() or []):
            app_name = getattr(top, "Name", "") or ""
            app_name_clean = _sanitize_match_text(app_name)
            if target_app and target_app not in app_name_clean and app_name_clean not in target_app:
                continue
            candidate_ids = set(_match_uia_window_to_stacking(top, windows))
            if target_ids and not (candidate_ids & target_ids):
                continue
            node = _uia_follow_path(top, target_path)
            if node is None:
                continue
            return {
                "success": True,
                "backend": "uia",
                "node": node,
                "app_name": app_name,
                "window_ids": list(candidate_ids or target_ids),
            }
    except Exception as e:
        return {"success": False, "backend": "uia", "error": str(e)}
    return {"success": False, "backend": "uia", "error": "Element reference could not be resolved"}


def _resolve_atspi_element(ref: Dict[str, Any]) -> Dict[str, Any]:
    target_app = _sanitize_match_text(ref.get("app", ""))
    target_path = list(ref.get("path") or [])

    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                app_name = app.get_name() or f"app_{i}"
            except Exception:
                continue
            app_name_clean = _sanitize_match_text(app_name)
            if target_app and target_app not in app_name_clean and app_name_clean not in target_app:
                continue
            node = _atspi_follow_path(app, target_path)
            if node is None:
                continue
            return {
                "success": True,
                "backend": "atspi",
                "node": node,
                "app_name": app_name,
                "window_ids": ref.get("window_ids") or [],
            }
    except Exception as e:
        return {"success": False, "backend": "atspi", "error": str(e)}
    return {"success": False, "backend": "atspi", "error": "Element reference could not be resolved"}


def _resolve_ui_element(ref: Dict[str, Any]) -> Dict[str, Any]:
    backend = ref.get("backend")
    if backend == "uia":
        return _resolve_uia_element(ref)
    if backend == "atspi":
        return _resolve_atspi_element(ref)
    return {"success": False, "error": f"Unsupported element ref backend: {backend}"}


def _pick_atspi_named_action(node, candidates: List[str]) -> Optional[Tuple[Any, int, str]]:
    try:
        ai = node.get_action_iface()
        if not ai:
            return None
        for i in range(ai.get_n_actions()):
            try:
                name = (ai.get_action_name(i) or "").strip().lower()
            except Exception:
                continue
            for candidate in candidates:
                if name == candidate or candidate in name:
                    return ai, i, name
    except Exception:
        pass
    return None


def find_ui_elements_deep(
    app_filter: Optional[str] = None,
    region: Optional[list] = None,
    name_filter: Optional[str] = None,
    role_filter: Optional[str] = None,
    interactable_only: bool = False,
    include_hidden: bool = False,
    max_depth: int = 40,
) -> Dict[str, Any]:
    if sys.platform == "win32":
        if not UI_AUTOMATION_AVAILABLE:
            return {
                "available": False,
                "backend": "uia",
                "error": "uiautomation/pywin32 not installed",
                "elements": [],
                "windows": [],
                "screen": {"width": 0, "height": 0},
            }
        result = _get_deep_ui_elements_win32(app_filter=app_filter, include_hidden=include_hidden, max_depth=max_depth)
    else:
        if not ATSPI_AVAILABLE:
            return {
                "available": False,
                "backend": "atspi",
                "error": "AT-SPI not available",
                "elements": [],
                "windows": [],
                "screen": {"width": 0, "height": 0},
            }
        result = _get_deep_ui_elements_linux(app_filter=app_filter, include_hidden=include_hidden, max_depth=max_depth)

    if not result.get("available"):
        result["elements"] = []
        return result

    if region and result.get("ui_elements", {}).get("applications"):
        apps = result["ui_elements"]["applications"]
        filtered_apps, removed = _filter_apps_by_region(apps, region)
        result["ui_elements"]["applications"] = filtered_apps
        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + removed
        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in filtered_apps)

    if (name_filter or role_filter or interactable_only) and result.get("ui_elements", {}).get("applications"):
        new_apps = []
        removed_total = 0
        for app in result["ui_elements"]["applications"]:
            original_count = len(app["elements"])
            kept = _filter_elements(app["elements"], name_filter, role_filter, interactable_only)
            removed_total += original_count - len(kept)
            if kept:
                new_apps.append({
                    "application": app["application"],
                    "window_ids": app.get("window_ids", []),
                    "elements": kept,
                })
        result["ui_elements"]["applications"] = new_apps
        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + removed_total
        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in new_apps)

    flat = _flatten_applications(result["ui_elements"]["applications"])
    flat.sort(key=lambda e: (
        (e.get("bounds") or {}).get("y", 10**9),
        (e.get("bounds") or {}).get("x", 10**9),
        e.get("depth", 0),
    ))
    result["elements"] = flat
    return result


def get_focused_ui_element_deep(
    app_filter: Optional[str] = None,
    region: Optional[list] = None,
    max_depth: int = 40,
) -> Dict[str, Any]:
    result = find_ui_elements_deep(
        app_filter=app_filter,
        region=region,
        include_hidden=True,
        max_depth=max_depth,
    )
    if not result.get("available"):
        return result

    candidates = []
    for el in result.get("elements", []):
        if el.get("backend") == "uia":
            if el.get("states", {}).get("has_keyboard_focus"):
                candidates.append(el)
        else:
            if "focused" in (el.get("states") or []):
                candidates.append(el)

    if not candidates:
        return {
            "available": True,
            "backend": result.get("backend"),
            "found": False,
            "element": None,
        }

    candidates.sort(key=lambda e: (
        -(e.get("depth", 0)),
        ((e.get("bounds") or {}).get("w", 10**9) * (e.get("bounds") or {}).get("h", 10**9)),
    ))
    return {
        "available": True,
        "backend": result.get("backend"),
        "found": True,
        "element": candidates[0],
    }


def get_ui_element_at_point_deep(
    x: int,
    y: int,
    app_filter: Optional[str] = None,
    max_depth: int = 40,
) -> Dict[str, Any]:
    result = find_ui_elements_deep(
        app_filter=app_filter,
        include_hidden=False,
        max_depth=max_depth,
    )
    if not result.get("available"):
        return result

    matches = [el for el in result.get("elements", []) if _element_contains_point(el, x, y)]
    if not matches:
        return {
            "available": True,
            "backend": result.get("backend"),
            "found": False,
            "element": None,
        }

    matches.sort(key=lambda e: (
        ((e.get("bounds") or {}).get("w", 10**9) * (e.get("bounds") or {}).get("h", 10**9)),
        -(e.get("depth", 0)),
    ))
    return {
        "available": True,
        "backend": result.get("backend"),
        "found": True,
        "element": matches[0],
    }


def get_ui_element_details(element_ref: Dict[str, Any]) -> Dict[str, Any]:
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"found": False, "error": resolved.get("error")}

    if resolved["backend"] == "uia":
        el = _collect_uia_elements_deep(
            resolved["node"],
            app_name=resolved["app_name"],
            window_ids=resolved["window_ids"],
            path=list(element_ref.get("path") or []),
            depth=0,
            max_depth=0,
        )[0]
    else:
        el = _collect_atspi_elements_deep(
            resolved["node"],
            app_name=resolved["app_name"],
            window_ids=resolved["window_ids"],
            path=list(element_ref.get("path") or []),
            depth=0,
            max_depth=0,
        )[0]
    return {"found": True, "element": el}


def get_ui_element_parent(element_ref: Dict[str, Any]) -> Dict[str, Any]:
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"found": False, "error": resolved.get("error")}

    parent_path = list(element_ref.get("path") or [])[:-1]
    if resolved["backend"] == "uia":
        try:
            parent = resolved["node"].GetParentControl()
        except Exception as e:
            return {"found": False, "error": str(e)}
        if not parent:
            return {"found": False, "error": "No parent element"}
        element = _collect_uia_elements_deep(
            parent,
            app_name=resolved["app_name"],
            window_ids=resolved["window_ids"],
            path=parent_path,
            depth=0,
            max_depth=0,
        )[0]
    else:
        try:
            parent = resolved["node"].get_parent()
        except Exception as e:
            return {"found": False, "error": str(e)}
        if not parent:
            return {"found": False, "error": "No parent element"}
        element = _collect_atspi_elements_deep(
            parent,
            app_name=resolved["app_name"],
            window_ids=resolved["window_ids"],
            path=parent_path,
            depth=0,
            max_depth=0,
        )[0]
    return {"found": True, "element": element}


def get_ui_element_children(element_ref: Dict[str, Any], max_depth: int = 1) -> Dict[str, Any]:
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"found": False, "error": resolved.get("error")}

    max_depth = max(1, max_depth)
    base_path = list(element_ref.get("path") or [])
    elements: List[Dict[str, Any]] = []

    if resolved["backend"] == "uia":
        try:
            children = resolved["node"].GetChildren() or []
        except Exception as e:
            return {"found": False, "error": str(e)}
        for idx, child in enumerate(children):
            elements.extend(
                _collect_uia_elements_deep(
                    child,
                    app_name=resolved["app_name"],
                    window_ids=resolved["window_ids"],
                    path=base_path + [idx],
                    depth=1,
                    max_depth=max_depth,
                )
            )
    else:
        try:
            child_count = resolved["node"].get_child_count()
        except Exception as e:
            return {"found": False, "error": str(e)}
        for idx in range(child_count):
            try:
                child = resolved["node"].get_child_at_index(idx)
            except Exception:
                continue
            elements.extend(
                _collect_atspi_elements_deep(
                    child,
                    app_name=resolved["app_name"],
                    window_ids=resolved["window_ids"],
                    path=base_path + [idx],
                    depth=1,
                    max_depth=max_depth,
                )
            )

    return {"found": True, "element_count": len(elements), "elements": elements}


def _perform_uia_action(
    control,
    action: str,
    text: Optional[str] = None,
    value: Optional[float] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        if action == "focus":
            try:
                control.SetFocus()
            except Exception:
                control.SetActive()
            return {"success": True, "message": "Focused element"}

        if action in ("invoke", "click"):
            try:
                control.GetInvokePattern().Invoke()
                return {"success": True, "message": "Invoked element"}
            except Exception:
                control.Click()
                return {"success": True, "message": "Clicked element"}

        if action == "get_text":
            return {"success": True, **_uia_text_value_snapshot(control, max_chars=4000)}

        if action in ("set_text", "append_text", "clear_text"):
            target = text or ""
            if action == "append_text":
                snap = _uia_text_value_snapshot(control, max_chars=4000)
                target = (snap.get("value") or snap.get("text") or "") + target
            elif action == "clear_text":
                target = ""
            try:
                control.GetValuePattern().SetValue(target)
                return {"success": True, "message": f"{action} via ValuePattern"}
            except Exception:
                try:
                    control.SetFocus()
                except Exception:
                    try:
                        control.Click()
                    except Exception:
                        pass
                try:
                    control.SendKeys('{Ctrl}a{Del}')
                except Exception:
                    pass
                if target:
                    control.SendKeys(target)
                return {"success": True, "message": f"{action} via SendKeys fallback"}

        if action == "select":
            try:
                control.GetSelectionItemPattern().Select()
            except Exception:
                control.Select()
            return {"success": True, "message": "Selected element"}

        if action == "toggle":
            control.GetTogglePattern().Toggle()
            return {"success": True, "message": "Toggled element"}

        if action == "expand":
            control.GetExpandCollapsePattern().Expand()
            return {"success": True, "message": "Expanded element"}

        if action == "collapse":
            control.GetExpandCollapsePattern().Collapse()
            return {"success": True, "message": "Collapsed element"}

        if action == "scroll_into_view":
            control.GetScrollItemPattern().ScrollIntoView()
            return {"success": True, "message": "Scrolled element into view"}

        if action == "set_range_value":
            if value is None:
                return {"success": False, "error": "value is required for set_range_value"}
            control.GetRangeValuePattern().SetValue(float(value))
            return {"success": True, "message": f"Set range value to {value}"}

        if action in ("move", "resize", "set_extents"):
            tp = control.GetTransformPattern()
            if action == "move":
                if x is None or y is None:
                    return {"success": False, "error": "x and y are required for move"}
                tp.Move(x, y)
                return {"success": True, "message": f"Moved element to ({x}, {y})"}
            if action == "resize":
                if width is None or height is None:
                    return {"success": False, "error": "width and height are required for resize"}
                tp.Resize(width, height)
                return {"success": True, "message": f"Resized element to {width}x{height}"}
            if x is None or y is None or width is None or height is None:
                return {"success": False, "error": "x, y, width, height are required for set_extents"}
            tp.Move(x, y)
            tp.Resize(width, height)
            return {"success": True, "message": f"Set element extents to ({x}, {y}, {width}, {height})"}

        if action == "close":
            try:
                control.GetWindowPattern().Close()
            except Exception:
                control.GetTopLevelControl().GetWindowPattern().Close()
            return {"success": True, "message": "Closed element/window"}

        return {"success": False, "error": f"Unsupported UIA action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _perform_atspi_action(
    node,
    action: str,
    text: Optional[str] = None,
    value: Optional[float] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        if action == "focus":
            comp = node.get_component_iface()
            if not comp:
                return {"success": False, "error": "Component interface not available"}
            ok = comp.grab_focus()
            return {"success": bool(ok), "message": "Focused element" if ok else "Could not focus element"}

        if action in ("invoke", "click"):
            picked = _pick_atspi_named_action(node, ["click", "press", "activate", "open", "jump"])
            if not picked:
                return {"success": False, "error": "No actionable AT-SPI action found"}
            ai, index, name = picked
            ok = ai.do_action(index)
            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}

        if action == "get_text":
            return {"success": True, **_atspi_text_value_snapshot(node, max_chars=4000)}

        if action in ("set_text", "append_text", "clear_text"):
            editable = node.get_editable_text_iface()
            if not editable:
                return {"success": False, "error": "EditableText interface not available"}
            if action == "clear_text":
                ok = editable.set_text_contents("")
                return {"success": bool(ok), "message": "Cleared text"}
            if action == "set_text":
                ok = editable.set_text_contents(text or "")
                return {"success": bool(ok), "message": "Set text"}
            ti = node.get_text_iface()
            if not ti:
                return {"success": False, "error": "Text interface not available for append_text"}
            count = ti.get_character_count()
            payload = text or ""
            ok = editable.insert_text(count, payload, len(payload.encode("utf-8")))
            return {"success": bool(ok), "message": "Appended text"}

        if action == "select":
            picked = _pick_atspi_named_action(node, ["select", "activate", "click"])
            if picked:
                ai, index, name = picked
                ok = ai.do_action(index)
                return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
            try:
                parent = node.get_parent()
                sel = parent.get_selection_iface() if parent else None
                idx = node.get_index_in_parent()
                if sel and idx >= 0:
                    ok = sel.select_child(idx)
                    return {"success": bool(ok), "message": "Selected element via Selection iface"}
            except Exception:
                pass
            return {"success": False, "error": "No selection mechanism available"}

        if action == "toggle":
            picked = _pick_atspi_named_action(node, ["toggle", "press", "click", "activate"])
            if not picked:
                return {"success": False, "error": "No toggle-like AT-SPI action found"}
            ai, index, name = picked
            ok = ai.do_action(index)
            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}

        if action == "expand":
            picked = _pick_atspi_named_action(node, ["expand", "open"])
            if not picked:
                return {"success": False, "error": "No expand-like AT-SPI action found"}
            ai, index, name = picked
            ok = ai.do_action(index)
            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}

        if action == "collapse":
            picked = _pick_atspi_named_action(node, ["collapse", "close"])
            if not picked:
                return {"success": False, "error": "No collapse-like AT-SPI action found"}
            ai, index, name = picked
            ok = ai.do_action(index)
            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}

        if action == "scroll_into_view":
            comp = node.get_component_iface()
            if not comp:
                return {"success": False, "error": "Component interface not available"}
            ok = comp.scroll_to(Atspi.ScrollType.ANYWHERE)
            return {"success": bool(ok), "message": "Scrolled element into view"}

        if action == "set_range_value":
            if value is None:
                return {"success": False, "error": "value is required for set_range_value"}
            vi = node.get_value_iface()
            if not vi:
                return {"success": False, "error": "Value interface not available"}
            ok = vi.set_current_value(float(value))
            return {"success": bool(ok), "message": f"Set range value to {value}"}

        if action in ("move", "resize", "set_extents"):
            comp = node.get_component_iface()
            if not comp:
                return {"success": False, "error": "Component interface not available"}
            if action == "move":
                if x is None or y is None:
                    return {"success": False, "error": "x and y are required for move"}
                ok = comp.set_position(x, y, Atspi.CoordType.SCREEN)
                return {"success": bool(ok), "message": f"Moved element to ({x}, {y})"}
            if action == "resize":
                if width is None or height is None:
                    return {"success": False, "error": "width and height are required for resize"}
                ok = comp.set_size(width, height)
                return {"success": bool(ok), "message": f"Resized element to {width}x{height}"}
            if x is None or y is None or width is None or height is None:
                return {"success": False, "error": "x, y, width, height are required for set_extents"}
            ok = comp.set_extents(x, y, width, height, Atspi.CoordType.SCREEN)
            return {"success": bool(ok), "message": f"Set element extents to ({x}, {y}, {width}, {height})"}

        if action == "close":
            picked = _pick_atspi_named_action(node, ["close"])
            if not picked:
                return {"success": False, "error": "No close-like AT-SPI action found"}
            ai, index, name = picked
            ok = ai.do_action(index)
            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}

        return {"success": False, "error": f"Unsupported AT-SPI action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def perform_ui_action(
    element_ref: Dict[str, Any],
    action: str,
    text: Optional[str] = None,
    value: Optional[float] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"success": False, "error": resolved.get("error")}

    if resolved["backend"] == "uia":
        result = _perform_uia_action(
            resolved["node"],
            action=action,
            text=text,
            value=value,
            x=x,
            y=y,
            width=width,
            height=height,
        )
    else:
        result = _perform_atspi_action(
            resolved["node"],
            action=action,
            text=text,
            value=value,
            x=x,
            y=y,
            width=width,
            height=height,
        )

    result["backend"] = resolved["backend"]
    result["action"] = action
    result["ref"] = element_ref
    return result


# ── Text Pattern Actions ───────────────────────────────────────────────

_VALID_TEXT_UNITS = {"char", "word", "line", "paragraph", "sentence"}


def _uia_get_text_pattern(control):
    """Get TextPattern from a UIA control. Returns (pattern, error_dict)."""
    try:
        tp = control.GetTextPattern()
        if tp and getattr(tp, "DocumentRange", None):
            return tp, None
    except Exception:
        pass
    return None, {"success": False, "error": "TextPattern not available on this element"}


def _uia_position_range(text_pattern, start: int, end: int):
    """Create a TextRange positioned at [start, end) character offsets."""
    import uiautomation as auto
    EP = auto.TextPatternRangeEndpoint
    TU = auto.TextUnit
    doc = text_pattern.DocumentRange.Clone()
    # Collapse range to document start by moving End to Start
    doc.MoveEndpointByRange(EP.End, doc, EP.Start)
    # Move both endpoints by character count
    if start > 0:
        doc.MoveEndpointByUnit(EP.Start, TU.Character, start)
    doc.MoveEndpointByUnit(EP.End, TU.Character, end)
    return doc


def _uia_text_unit(unit: str):
    """Map logical unit name to UIA TextUnit constant."""
    import uiautomation as auto
    TU = auto.TextUnit
    mapping = {
        "char": TU.Character,
        "word": TU.Word,
        "line": TU.Line,
        "paragraph": TU.Paragraph,
        "sentence": TU.Paragraph,  # no sentence unit in UIA
    }
    return mapping.get(unit, TU.Character)


def _perform_uia_text_action(control, action: str, **kwargs) -> Dict[str, Any]:
    """Perform text pattern operations on a UIA control."""
    tp, err = _uia_get_text_pattern(control)
    if err:
        return err

    try:
        if action == "get_selection":
            try:
                sel_array = tp.GetSelection()
                selections = []
                if sel_array:
                    # Handle both list-like and COM array returns
                    items = sel_array if isinstance(sel_array, (list, tuple)) else [sel_array]
                    for r in items:
                        try:
                            txt = r.GetText(-1)
                            selections.append({"text": txt or ""})
                        except Exception:
                            pass
                return {"success": True, "selections": selections, "count": len(selections)}
            except Exception as e:
                return {"success": False, "error": f"GetSelection failed: {e}"}

        if action == "select_range":
            start, end = kwargs.get("start", 0), kwargs.get("end", 0)
            if start < 0 or end < 0:
                return {"success": False, "error": "start and end must be non-negative"}
            if start > end:
                return {"success": False, "error": "start must be <= end"}
            rng = _uia_position_range(tp, start, end)
            rng.Select()
            selected = rng.GetText(-1)
            return {"success": True, "message": f"Selected text range [{start}:{end}]",
                    "start": start, "end": end, "text": selected or ""}

        if action == "select_by_search":
            search_text = kwargs.get("search_text", "")
            if not search_text:
                return {"success": False, "error": "search_text is required"}
            try:
                found = tp.DocumentRange.FindText(search_text, False, False)
                if found:
                    found.Select()
                    selected = found.GetText(-1)
                    return {"success": True, "message": f"Found and selected text",
                            "text": selected or search_text}
            except Exception:
                pass
            # Fallback: get full text, find offset, use range selection
            full = tp.DocumentRange.GetText(-1) or ""
            idx = full.find(search_text)
            if idx < 0:
                return {"success": False, "error": f"Text not found: '{search_text}'"}
            rng = _uia_position_range(tp, idx, idx + len(search_text))
            rng.Select()
            return {"success": True, "message": "Found and selected text (fallback)",
                    "text": search_text, "start": idx, "end": idx + len(search_text)}

        if action == "get_caret":
            import uiautomation as auto
            EP = auto.TextPatternRangeEndpoint
            # Try TextPattern2.GetCaretRange first
            try:
                tp2 = control.GetTextPattern2()
                if tp2 and hasattr(tp2, "GetCaretRange"):
                    is_active, caret_range = tp2.GetCaretRange()
                    full = tp.DocumentRange.GetText(-1) or ""
                    before_range = tp.DocumentRange.Clone()
                    before_range.MoveEndpointByRange(EP.End, caret_range, EP.Start)
                    before_text = before_range.GetText(-1) or ""
                    return {"success": True, "offset": len(before_text), "text_length": len(full)}
            except Exception:
                pass
            # Fallback: use selection as caret indicator
            try:
                sel = tp.GetSelection()
                if sel:
                    r = sel[0] if isinstance(sel, (list, tuple)) else sel
                    full = tp.DocumentRange.GetText(-1) or ""
                    before = tp.DocumentRange.Clone()
                    before.MoveEndpointByRange(EP.End, r, EP.Start)
                    before_text = before.GetText(-1) or ""
                    return {"success": True, "offset": len(before_text), "text_length": len(full)}
            except Exception:
                pass
            return {"success": False, "error": "Could not determine caret position"}

        if action == "set_caret":
            offset = kwargs.get("offset", 0)
            if offset < 0:
                return {"success": False, "error": "offset must be non-negative"}
            rng = _uia_position_range(tp, offset, offset)
            rng.Select()
            return {"success": True, "offset": offset, "message": f"Caret moved to offset {offset}"}

        if action == "get_text_at_offset":
            offset = kwargs.get("offset", 0)
            unit = kwargs.get("unit", "word")
            if unit not in _VALID_TEXT_UNITS:
                return {"success": False, "error": f"Invalid unit '{unit}'. Use: {', '.join(sorted(_VALID_TEXT_UNITS))}"}
            rng = _uia_position_range(tp, offset, offset)
            rng.ExpandToEnclosingUnit(_uia_text_unit(unit))
            txt = rng.GetText(-1) or ""
            return {"success": True, "text": txt, "unit": unit}

        if action == "get_bounds":
            start, end = kwargs.get("start", 0), kwargs.get("end", 0)
            if start < 0 or end < 0 or start > end:
                return {"success": False, "error": "Invalid start/end range"}
            rng = _uia_position_range(tp, start, end)
            try:
                raw = rng.GetBoundingRectangles()
                rects = []
                if raw:
                    for item in raw:
                        try:
                            # uiautomation returns Rect objects with .left/.top/.right/.bottom
                            if hasattr(item, "left"):
                                rects.append({
                                    "x": int(item.left), "y": int(item.top),
                                    "width": int(item.right - item.left),
                                    "height": int(item.bottom - item.top),
                                })
                            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                                rects.append({
                                    "x": int(item[0]), "y": int(item[1]),
                                    "width": int(item[2]), "height": int(item[3]),
                                })
                        except Exception:
                            pass
                return {"success": True, "bounds": rects, "start": start, "end": end,
                        "rect_count": len(rects)}
            except Exception as e:
                return {"success": False, "error": f"GetBoundingRectangles failed: {e}"}

        return {"success": False, "error": f"Unsupported UIA text action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _perform_atspi_text_action(node, action: str, **kwargs) -> Dict[str, Any]:
    """Perform text pattern operations on an AT-SPI node."""
    try:
        ti = node.get_text_iface()
        if not ti:
            return {"success": False, "error": "Text interface not available on this element"}
    except Exception:
        return {"success": False, "error": "Text interface not available on this element"}

    try:
        char_count = ti.get_character_count()

        if action == "get_selection":
            n_sel = ti.get_n_selections()
            selections = []
            for i in range(n_sel):
                r = ti.get_selection(i)
                if r:
                    s, e = r.start_offset, r.end_offset
                    txt = ti.get_text(s, e)
                    selections.append({"start": s, "end": e, "text": txt or ""})
            return {"success": True, "selections": selections, "count": len(selections)}

        if action == "select_range":
            start, end = kwargs.get("start", 0), kwargs.get("end", 0)
            if start < 0 or end < 0:
                return {"success": False, "error": "start and end must be non-negative"}
            if start > end:
                return {"success": False, "error": "start must be <= end"}
            end = min(end, char_count)
            # Remove existing selections
            for i in range(ti.get_n_selections() - 1, -1, -1):
                try:
                    ti.remove_selection(i)
                except Exception:
                    pass
            ok = ti.add_selection(start, end)
            txt = ti.get_text(start, end) if ok else ""
            return {"success": bool(ok), "message": f"Selected text range [{start}:{end}]",
                    "start": start, "end": end, "text": txt or ""}

        if action == "select_by_search":
            search_text = kwargs.get("search_text", "")
            if not search_text:
                return {"success": False, "error": "search_text is required"}
            full = ti.get_text(0, char_count) or ""
            idx = full.find(search_text)
            if idx < 0:
                return {"success": False, "error": f"Text not found: '{search_text}'"}
            # Remove existing selections
            for i in range(ti.get_n_selections() - 1, -1, -1):
                try:
                    ti.remove_selection(i)
                except Exception:
                    pass
            ok = ti.add_selection(idx, idx + len(search_text))
            return {"success": bool(ok), "message": "Found and selected text",
                    "text": search_text, "start": idx, "end": idx + len(search_text)}

        if action == "get_caret":
            offset = ti.get_caret_offset()
            return {"success": True, "offset": offset, "text_length": char_count}

        if action == "set_caret":
            offset = kwargs.get("offset", 0)
            if offset < 0:
                return {"success": False, "error": "offset must be non-negative"}
            ok = ti.set_caret_offset(min(offset, char_count))
            return {"success": bool(ok), "offset": offset,
                    "message": f"Caret moved to offset {offset}"}

        if action == "get_text_at_offset":
            offset = kwargs.get("offset", 0)
            unit = kwargs.get("unit", "word")
            if unit not in _VALID_TEXT_UNITS:
                return {"success": False, "error": f"Invalid unit '{unit}'. Use: {', '.join(sorted(_VALID_TEXT_UNITS))}"}
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as _Atspi
            granularity_map = {
                "char": _Atspi.TextGranularity.CHAR,
                "word": _Atspi.TextGranularity.WORD,
                "line": _Atspi.TextGranularity.LINE,
                "paragraph": _Atspi.TextGranularity.PARAGRAPH,
                "sentence": _Atspi.TextGranularity.SENTENCE,
            }
            try:
                result = ti.get_string_at_offset(offset, granularity_map[unit])
                return {"success": True, "text": result.content or "",
                        "start": result.start_offset, "end": result.end_offset, "unit": unit}
            except Exception:
                # Fallback to deprecated get_text_at_offset
                boundary_map = {
                    "char": _Atspi.TextBoundaryType.CHAR,
                    "word": _Atspi.TextBoundaryType.WORD_START,
                    "line": _Atspi.TextBoundaryType.LINE_START,
                    "paragraph": _Atspi.TextBoundaryType.LINE_START,
                    "sentence": _Atspi.TextBoundaryType.SENTENCE_START,
                }
                result = ti.get_text_at_offset(offset, boundary_map[unit])
                return {"success": True, "text": result.content or "",
                        "start": result.start_offset, "end": result.end_offset, "unit": unit}

        if action == "get_bounds":
            start, end = kwargs.get("start", 0), kwargs.get("end", 0)
            if start < 0 or end < 0 or start > end:
                return {"success": False, "error": "Invalid start/end range"}
            end = min(end, char_count)
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as _Atspi
            # Try get_range_extents first (single bounding box for entire range)
            try:
                rect = ti.get_range_extents(start, end, _Atspi.CoordType.SCREEN)
                if rect and rect.width > 0 and rect.height > 0:
                    return {"success": True, "bounds": [{
                        "x": rect.x, "y": rect.y,
                        "width": rect.width, "height": rect.height,
                    }], "start": start, "end": end, "rect_count": 1}
            except Exception:
                pass
            # Fallback: per-character extents, merge by line
            rects = []
            current_line = None
            for i in range(start, min(end, start + 500)):  # cap to avoid huge loops
                try:
                    ext = ti.get_character_extents(i, _Atspi.CoordType.SCREEN)
                    if ext.width <= 0 and ext.height <= 0:
                        continue
                    # Merge rects on same line (similar y position)
                    if current_line and abs(ext.y - current_line["y"]) < ext.height * 0.5:
                        current_line["width"] = (ext.x + ext.width) - current_line["x"]
                    else:
                        if current_line:
                            rects.append(current_line)
                        current_line = {"x": ext.x, "y": ext.y,
                                        "width": ext.width, "height": ext.height}
                except Exception:
                    continue
            if current_line:
                rects.append(current_line)
            return {"success": True, "bounds": rects, "start": start, "end": end,
                    "rect_count": len(rects)}

        return {"success": False, "error": f"Unsupported AT-SPI text action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def perform_text_action(element_ref: Dict[str, Any], action: str, **kwargs) -> Dict[str, Any]:
    """Cross-platform text pattern action dispatcher.

    Resolves the element ref, then dispatches to the appropriate platform handler.

    Actions:
        get_selection - Get currently selected text
        select_range  - Select text by character offsets (start, end)
        select_by_search - Find and select a substring (search_text)
        get_caret     - Get caret/cursor offset within text
        set_caret     - Move caret to offset (offset)
        get_text_at_offset - Get word/line/paragraph at offset (offset, unit)
        get_bounds    - Get screen rectangles for text range (start, end)
    """
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"success": False, "error": resolved.get("error")}

    if resolved["backend"] == "uia":
        result = _perform_uia_text_action(resolved["node"], action, **kwargs)
    else:
        result = _perform_atspi_text_action(resolved["node"], action, **kwargs)

    result["backend"] = resolved["backend"]
    result["action"] = action
    result["ref"] = element_ref
    return result


# ── Advanced Pattern Actions ───────────────────────────────────────────


def _control_to_compact(ctrl) -> Dict[str, Any]:
    """Convert a UIA control to a compact dict for JSON output."""
    try:
        name = ctrl.Name or ""
        role = _UIA_ROLE_MAP.get(ctrl.ControlTypeName, ctrl.ControlTypeName or "unknown")
        rect = ctrl.BoundingRectangle
        result = {"name": name, "role": role}
        if rect:
            result["bounds"] = {"x": int(rect.left), "y": int(rect.top),
                                "width": int(rect.width()), "height": int(rect.height())}
        # Try to get text value
        try:
            vp = ctrl.GetValuePattern()
            if vp and vp.Value is not None:
                result["value"] = str(vp.Value)[:500]
        except Exception:
            pass
        if not result.get("value"):
            result["value"] = name
        return result
    except Exception:
        return {"name": "", "role": "unknown"}


def _perform_uia_advanced_action(control, action: str, **kwargs) -> Dict[str, Any]:
    """Perform advanced UIA pattern operations (table, scroll, views, realize, drag)."""
    try:
        # ── Table / Grid ──
        if action == "get_table_data":
            gp = control.GetGridPattern()
            if not gp:
                return {"success": False, "error": "GridPattern not available on this element"}
            row_count = gp.RowCount
            col_count = gp.ColumnCount
            start_row = kwargs.get("start_row", 0)
            max_rows = kwargs.get("max_rows", 50)
            end_row = min(start_row + max_rows, row_count)

            # Try to get headers via TablePattern
            headers = []
            try:
                tp = control.GetTablePattern()
                if tp:
                    col_headers = tp.GetColumnHeaders()
                    if col_headers:
                        headers = [_control_to_compact(h).get("value", "") for h in col_headers]
            except Exception:
                pass
            # Fallback: use first row as headers if no TablePattern headers
            if not headers and row_count > 0:
                try:
                    for c in range(col_count):
                        cell = gp.GetItem(0, c)
                        if cell:
                            headers.append(_control_to_compact(cell).get("value", ""))
                except Exception:
                    pass

            rows = []
            for r in range(start_row, end_row):
                row_data = []
                for c in range(col_count):
                    try:
                        cell = gp.GetItem(r, c)
                        row_data.append(_control_to_compact(cell) if cell else {"value": ""})
                    except Exception:
                        row_data.append({"value": ""})
                rows.append(row_data)

            return {"success": True, "row_count": row_count, "column_count": col_count,
                    "headers": headers, "start_row": start_row, "returned_rows": len(rows),
                    "has_more": end_row < row_count, "rows": rows}

        # ── Scroll ──
        if action == "scroll_container":
            sp = control.GetScrollPattern()
            if not sp:
                return {"success": False, "error": "ScrollPattern not available on this element"}
            import uiautomation as auto
            SA = auto.ScrollAmount
            direction = kwargs.get("direction", "down")
            amount = kwargs.get("amount", 1)
            unit = kwargs.get("unit", "page")

            amount_map = {
                "page": {"up": SA.LargeDecrement, "down": SA.LargeIncrement,
                         "left": SA.LargeDecrement, "right": SA.LargeIncrement},
                "line": {"up": SA.SmallDecrement, "down": SA.SmallIncrement,
                         "left": SA.SmallDecrement, "right": SA.SmallIncrement},
            }
            if unit == "percent":
                h_pct = sp.HorizontalScrollPercent
                v_pct = sp.VerticalScrollPercent
                if direction in ("up", "down"):
                    delta = -amount if direction == "up" else amount
                    new_v = max(0, min(100, v_pct + delta))
                    sp.SetScrollPercent(h_pct if sp.HorizontallyScrollable else -1, new_v)
                else:
                    delta = -amount if direction == "left" else amount
                    new_h = max(0, min(100, h_pct + delta))
                    sp.SetScrollPercent(new_h, v_pct if sp.VerticallyScrollable else -1)
                return {"success": True, "message": f"Scrolled {direction} by {amount}%"}

            scroll_amt = amount_map.get(unit, amount_map["page"]).get(direction, SA.NoAmount)
            for _ in range(amount):
                if direction in ("up", "down"):
                    sp.Scroll(SA.NoAmount, scroll_amt)
                else:
                    sp.Scroll(scroll_amt, SA.NoAmount)
            return {"success": True, "message": f"Scrolled {direction} by {amount} {unit}(s)"}

        if action == "get_scroll_info":
            sp = control.GetScrollPattern()
            if not sp:
                return {"success": False, "error": "ScrollPattern not available on this element"}
            return {
                "success": True,
                "horizontally_scrollable": bool(sp.HorizontallyScrollable),
                "vertically_scrollable": bool(sp.VerticallyScrollable),
                "horizontal_percent": sp.HorizontalScrollPercent,
                "vertical_percent": sp.VerticalScrollPercent,
                "horizontal_view_size": sp.HorizontalViewSize,
                "vertical_view_size": sp.VerticalViewSize,
            }

        # ── Multiple View ──
        if action == "get_views":
            mvp = control.GetMultipleViewPattern()
            if not mvp:
                return {"success": False, "error": "MultipleViewPattern not available on this element"}
            current = mvp.CurrentView
            view_ids = mvp.GetSupportedViews() or []
            views = []
            for vid in view_ids:
                try:
                    name = mvp.GetViewName(vid)
                    views.append({"id": vid, "name": name, "current": vid == current})
                except Exception:
                    views.append({"id": vid, "name": f"View {vid}", "current": vid == current})
            return {"success": True, "current_view": current, "views": views}

        if action == "set_view":
            mvp = control.GetMultipleViewPattern()
            if not mvp:
                return {"success": False, "error": "MultipleViewPattern not available on this element"}
            view_id = kwargs.get("view_id")
            if view_id is None:
                return {"success": False, "error": "view_id is required"}
            mvp.SetView(int(view_id))
            name = ""
            try:
                name = mvp.GetViewName(int(view_id))
            except Exception:
                pass
            return {"success": True, "message": f"Switched to view {view_id}" + (f" ({name})" if name else "")}

        # ── Virtualized Item ──
        if action == "realize":
            import uiautomation as auto
            try:
                vip = control.GetPattern(auto.PatternId.VirtualizedItemPattern)
            except Exception:
                vip = None
            if not vip:
                return {"success": False, "error": "VirtualizedItemPattern not available on this element"}
            vip.Realize()
            return {"success": True, "message": "Realized virtualized item"}

        # ── Drag ──
        if action == "get_drag_info":
            import uiautomation as auto
            try:
                dp = control.GetPattern(auto.PatternId.DragPattern)
            except Exception:
                dp = None
            if not dp:
                return {"success": False, "error": "DragPattern not available on this element"}
            return {
                "success": True,
                "is_grabbed": bool(dp.IsGrabbed),
                "drop_effect": dp.DropEffect or "",
                "drop_effects": list(dp.DropEffects or []),
            }

        return {"success": False, "error": f"Unsupported UIA advanced action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _perform_atspi_advanced_action(node, action: str, **kwargs) -> Dict[str, Any]:
    """Perform advanced AT-SPI operations (table, scroll, hyperlinks)."""
    try:
        # ── Table ──
        if action == "get_table_data":
            ti = node.get_table_iface()
            if not ti:
                return {"success": False, "error": "Table interface not available on this element"}
            row_count = ti.get_n_rows()
            col_count = ti.get_n_columns()
            start_row = kwargs.get("start_row", 0)
            max_rows = kwargs.get("max_rows", 50)
            end_row = min(start_row + max_rows, row_count)

            headers = []
            for c in range(col_count):
                try:
                    desc = ti.get_column_description(c) or ""
                    if desc:
                        headers.append(desc)
                    else:
                        hdr = ti.get_column_header(c)
                        headers.append(hdr.get_name() if hdr else f"Col {c}")
                except Exception:
                    headers.append(f"Col {c}")

            rows = []
            for r in range(start_row, end_row):
                row_data = []
                for c in range(col_count):
                    try:
                        cell = ti.get_accessible_at(r, c)
                        if cell:
                            name = cell.get_name() or ""
                            text_iface = cell.get_text_iface()
                            value = ""
                            if text_iface:
                                value = text_iface.get_text(0, text_iface.get_character_count()) or ""
                            row_data.append({"name": name, "value": value or name})
                        else:
                            row_data.append({"value": ""})
                    except Exception:
                        row_data.append({"value": ""})
                rows.append(row_data)

            return {"success": True, "row_count": row_count, "column_count": col_count,
                    "headers": headers, "start_row": start_row, "returned_rows": len(rows),
                    "has_more": end_row < row_count, "rows": rows}

        # ── Scroll ──
        if action == "scroll_container":
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as _Atspi
            comp = node.get_component_iface()
            if not comp:
                return {"success": False, "error": "Component interface not available for scrolling"}
            direction = kwargs.get("direction", "down")
            scroll_map = {
                "up": _Atspi.ScrollType.TOP_EDGE,
                "down": _Atspi.ScrollType.BOTTOM_EDGE,
                "left": _Atspi.ScrollType.LEFT_EDGE,
                "right": _Atspi.ScrollType.RIGHT_EDGE,
            }
            scroll_type = scroll_map.get(direction, _Atspi.ScrollType.ANYWHERE)
            ok = comp.scroll_to(scroll_type)
            return {"success": bool(ok), "message": f"Scrolled {direction}"}

        if action == "get_scroll_info":
            # AT-SPI doesn't have a direct scroll info interface like UIA
            # We can check if the element is scrollable by checking its states
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi as _Atspi
            try:
                state_set = node.get_state_set()
                return {
                    "success": True,
                    "horizontally_scrollable": state_set.contains(_Atspi.StateType.HORIZONTAL) if state_set else False,
                    "vertically_scrollable": state_set.contains(_Atspi.StateType.VERTICAL) if state_set else False,
                    "message": "AT-SPI does not provide scroll percentage info",
                }
            except Exception:
                return {"success": True, "message": "Scroll info not available on AT-SPI"}

        # ── Multiple View ──
        if action in ("get_views", "set_view"):
            return {"success": False, "error": "MultipleViewPattern not available on AT-SPI"}

        # ── Virtualized Item ──
        if action == "realize":
            return {"success": False, "error": "VirtualizedItemPattern not available on AT-SPI"}

        # ── Drag ──
        if action == "get_drag_info":
            return {"success": False, "error": "DragPattern not available on AT-SPI"}

        # ── Hyperlinks ──
        if action == "get_hyperlinks":
            ht = node.get_hypertext_iface()
            if not ht:
                return {"success": False, "error": "Hypertext interface not available"}
            n_links = ht.get_n_links()
            links = []
            for i in range(min(n_links, kwargs.get("max_links", 100))):
                try:
                    link = ht.get_link(i)
                    if link:
                        name = link.get_name() or ""
                        uri = ""
                        try:
                            uri = link.get_uri(0) or ""
                        except Exception:
                            pass
                        start = link.get_start_index()
                        end = link.get_end_index()
                        links.append({"index": i, "name": name, "uri": uri,
                                      "start_offset": start, "end_offset": end})
                except Exception:
                    continue
            return {"success": True, "link_count": n_links, "links": links}

        if action == "activate_hyperlink":
            ht = node.get_hypertext_iface()
            if not ht:
                return {"success": False, "error": "Hypertext interface not available"}
            link_index = kwargs.get("link_index", 0)
            link = ht.get_link(link_index)
            if not link:
                return {"success": False, "error": f"Hyperlink at index {link_index} not found"}
            # Hyperlink extends Accessible, try action interface
            ai = link.get_action_iface()
            if ai and ai.get_n_actions() > 0:
                ok = ai.do_action(0)
                return {"success": bool(ok), "message": f"Activated hyperlink {link_index}"}
            return {"success": False, "error": "Hyperlink has no activatable action"}

        return {"success": False, "error": f"Unsupported AT-SPI advanced action: {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def perform_advanced_action(element_ref: Dict[str, Any], action: str, **kwargs) -> Dict[str, Any]:
    """Cross-platform advanced action dispatcher.

    Actions:
        get_table_data      - Read table/grid data (start_row, max_rows)
        scroll_container    - Scroll a container (direction, amount, unit)
        get_scroll_info     - Get scroll position and scrollability
        get_views           - Get available views (MultipleViewPattern)
        set_view            - Switch to a view (view_id)
        realize             - Realize a virtualized item
        get_drag_info       - Get drag pattern info
        get_hyperlinks      - Get hyperlinks in text (AT-SPI only)
        activate_hyperlink  - Activate a hyperlink by index (AT-SPI only)
    """
    resolved = _resolve_ui_element(element_ref)
    if not resolved.get("success"):
        return {"success": False, "error": resolved.get("error")}

    if resolved["backend"] == "uia":
        result = _perform_uia_advanced_action(resolved["node"], action, **kwargs)
    else:
        result = _perform_atspi_advanced_action(resolved["node"], action, **kwargs)

    result["backend"] = resolved["backend"]
    result["action"] = action
    result["ref"] = element_ref
    return result


# ── Public API ──────────────────────────────────────────────────────────


def _filter_elements(
    elements: List[Dict],
    name_filter: Optional[str] = None,
    role_filter: Optional[str] = None,
    interactable_only: bool = False,
) -> List[Dict]:
    """Filter UI elements by name, role, and/or interactability.

    Supports pipe-separated OR conditions for both name and role filters.

    Args:
        elements: List of UI element dicts.
        name_filter: Case-insensitive substring match on element name.
                     Supports "|" for OR, e.g. "Search|GitHub|Close" matches any.
        role_filter: Pipe-separated roles to keep, e.g. "push button|entry|link".
        interactable_only: If True, only keep elements that have actions.

    Returns:
        Filtered list of elements.
    """
    if not name_filter and not role_filter and not interactable_only:
        return elements

    name_patterns = [n.strip().lower() for n in name_filter.split("|")] if name_filter else None
    role_set = set(r.strip().lower() for r in role_filter.split("|")) if role_filter else None

    filtered = []
    for el in elements:
        if interactable_only and not el.get("actions"):
            continue
        if role_set and el.get("role", "").lower() not in role_set:
            continue
        if name_patterns:
            el_name = (el.get("name") or "").lower()
            if not any(p in el_name for p in name_patterns):
                continue
        filtered.append(el)
    return filtered


def get_ui_elements(
    app_filter: Optional[str] = None,
    region: Optional[list] = None,
    name_filter: Optional[str] = None,
    role_filter: Optional[str] = None,
    interactable_only: bool = False,
) -> Dict:
    """
    Get UI automation (accessibility tree) elements for the current screen.

    Cross-platform: uses Microsoft UIA on Windows, AT-SPI on Linux.
    Only returns elements from visible/foreground windows (occlusion filtered).

    Args:
        app_filter: If provided, only collect elements from windows/apps whose title
                    contains this string (case-insensitive). Massively speeds up
                    collection by skipping irrelevant app trees.
        region: If provided, [x, y, width, height] in absolute screen coordinates.
                Only returns elements whose center falls within this region.
        name_filter: If provided, only return elements whose name contains this
                     string (case-insensitive). Supports "|" for OR conditions,
                     e.g. "Search|GitHub|Close" matches any of those.
        role_filter: If provided, only return elements matching these roles.
                     Pipe-separated, e.g. "push button|entry|link|list item".
        interactable_only: If True, only return elements that have actions
                           (clickable, toggleable, etc.). Dramatically reduces output size.

    Returns a dict with:
        - available: bool — whether the platform's accessibility API is available
        - error: str | None — error message if something went wrong
        - screen: {width, height}
        - windows: list of visible windows with geometry
        - ui_elements: {time_s, element_count, filtered_out, applications: [...]}
    """
    if sys.platform == "win32":
        if not UI_AUTOMATION_AVAILABLE:
            return {
                "available": False,
                "error": "uiautomation not installed. Install with: pip install uiautomation",
                "screen": {"width": 0, "height": 0},
                "windows": [],
                "ui_elements": {
                    "time_s": 0,
                    "element_count": 0,
                    "filtered_out": 0,
                    "applications": [],
                },
            }
        result = _get_ui_elements_win32(app_filter=app_filter)
    else:
        if not ATSPI_AVAILABLE:
            return {
                "available": False,
                "error": "AT-SPI not available. Install: python3-gi gir1.2-atspi-2.0 at-spi2-core",
                "screen": {"width": 0, "height": 0},
                "windows": [],
                "ui_elements": {
                    "time_s": 0,
                    "element_count": 0,
                    "filtered_out": 0,
                    "applications": [],
                },
            }
        result = _get_ui_elements_linux(app_filter=app_filter)

    # Apply region filtering if requested
    if region and result.get("ui_elements", {}).get("applications"):
        apps = result["ui_elements"]["applications"]
        filtered_apps, removed = _filter_apps_by_region(apps, region)
        result["ui_elements"]["applications"] = filtered_apps
        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + removed
        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in filtered_apps)

    # Apply element-level filtering (name, role, interactable)
    if (name_filter or role_filter or interactable_only) and result.get("ui_elements", {}).get("applications"):
        new_apps = []
        total_removed = 0
        for app in result["ui_elements"]["applications"]:
            original_count = len(app["elements"])
            kept = _filter_elements(app["elements"], name_filter, role_filter, interactable_only)
            total_removed += original_count - len(kept)
            if kept:
                new_apps.append({
                    "application": app["application"],
                    "window_ids": app.get("window_ids", []),
                    "elements": kept,
                })
        result["ui_elements"]["applications"] = new_apps
        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + total_removed
        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in new_apps)

    return result
