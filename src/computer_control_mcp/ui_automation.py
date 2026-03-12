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
        "screen": {"width": screen_w, "height": screen_h},
        "windows": windows,
        "ui_elements": {
            "time_s": round(elapsed, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
    }


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
