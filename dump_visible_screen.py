#!/usr/bin/env python3
"""
Dump only VISIBLE screen elements by combining:
  1. Window manager stacking order (wmctrl + _NET_CLIENT_LIST_STACKING)
  2. AT-SPI elements filtered to only visible window regions
  3. RapidOCR text detection from screenshot

Handles occlusion: elements behind other windows are excluded.

Usage: DISPLAY=:1 /usr/bin/python3 dump_visible_screen.py [output.json]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

import importlib
if not importlib.util.find_spec("rapidocr_onnxruntime"):
    sys.path.insert(0, "/opt/agent-venv/lib/python3.12/site-packages")
from rapidocr_onnxruntime import RapidOCR
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path("/workspace")
SCREENSHOT = OUTPUT_DIR / "screen_capture.png"


# ── Window Manager ──────────────────────────────────────────────────────

def get_windows() -> list[dict]:
    """Get all windows with geometry from wmctrl, ordered by stacking."""
    env = {**os.environ, "DISPLAY": ":1"}

    # Get stacking order (bottom to top)
    result = subprocess.run(
        ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
        capture_output=True, text=True, env=env,
    )
    stacking_ids = []
    m = re.search(r"window id #\s*(.+)", result.stdout)
    if m:
        # Normalize to int for comparison (wmctrl zero-pads, xprop doesn't)
        stacking_ids = [int(x.strip(), 16) for x in m.group(1).split(",")]

    # Get window list with geometry
    result = subprocess.run(
        ["wmctrl", "-l", "-G"], capture_output=True, text=True, env=env,
    )
    win_map = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        wid_int = int(parts[0], 16)
        wid_str = parts[0]
        desktop = int(parts[1])
        x, y, w, h = int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5])
        name = parts[7] if len(parts) > 7 else ""
        win_map[wid_int] = {
            "id": wid_str, "desktop": desktop, "name": name,
            "x": x, "y": y, "w": w, "h": h,
        }

    # Return in stacking order (bottom to top)
    ordered = []
    for wid_int in stacking_ids:
        if wid_int in win_map:
            ordered.append(win_map[wid_int])
    return ordered


def compute_visible_regions(windows: list[dict], screen_w: int, screen_h: int) -> dict[str, list[tuple]]:
    """
    For each window, compute which rectangular regions are actually visible
    (not occluded by windows above it in the stacking order).

    Returns {window_id: [(x1,y1,x2,y2), ...]} for visible rectangles.
    """
    def rect_intersect(a, b):
        x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
        x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
        if x1 < x2 and y1 < y2:
            return (x1, y1, x2, y2)
        return None

    def subtract_rect(base, cut):
        """Subtract cut from base, return list of remaining rectangles."""
        overlap = rect_intersect(base, cut)
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
                new_regions.extend(subtract_rect(r, cut))
            regions = new_regions

        visible[win["id"]] = regions

    return visible


def point_in_regions(px, py, regions: list[tuple]) -> bool:
    for x1, y1, x2, y2 in regions:
        if x1 <= px < x2 and y1 <= py < y2:
            return True
    return False


def rect_mostly_in_regions(bx, by, bw, bh, regions: list[tuple], threshold=0.5) -> bool:
    """Check if at least threshold fraction of the element's area overlaps visible regions."""
    if bw <= 0 or bh <= 0:
        return False
    elem_area = bw * bh
    visible_area = 0
    for rx1, ry1, rx2, ry2 in regions:
        ox1 = max(bx, rx1); oy1 = max(by, ry1)
        ox2 = min(bx + bw, rx2); oy2 = min(by + bh, ry2)
        if ox1 < ox2 and oy1 < oy2:
            visible_area += (ox2 - ox1) * (oy2 - oy1)
    return (visible_area / elem_area) >= threshold


# ── AT-SPI ──────────────────────────────────────────────────────────────

def get_bounds(node) -> dict | None:
    try:
        comp = node.get_component_iface()
        if comp is None:
            return None
        r = comp.get_extents(Atspi.CoordType.SCREEN)
        if r.width > 0 and r.height > 0 and r.x >= 0 and r.y >= 0:
            return {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
    except Exception:
        pass
    return None


def collect_atspi(node, depth=0, max_depth=40) -> list[dict]:
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
    bounds = get_bounds(node)
    entry = {"role": role, "depth": depth}
    if name:
        entry["name"] = name
    if text:
        entry["text"] = text
    if bounds:
        entry["bounds"] = bounds
    if actions:
        entry["actions"] = actions
    elements.append(entry)
    try:
        for i in range(node.get_child_count()):
            try:
                child = node.get_child_at_index(i)
                elements.extend(collect_atspi(child, depth + 1, max_depth))
            except Exception:
                continue
    except Exception:
        pass
    return elements


def match_app_to_windows(app_name: str, app_elements: list[dict], windows: list[dict]) -> list[str]:
    """Match an AT-SPI app to one or more wmctrl windows (apps can have multiple frames)."""
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


# ── OCR ─────────────────────────────────────────────────────────────────

def get_ocr_elements() -> list[dict]:
    engine = RapidOCR()
    result, _ = engine(str(SCREENSHOT))
    elements = []
    if result:
        for box, text, conf in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            elements.append({
                "text": text,
                "confidence": round(float(conf) * 100, 1),
                "bounds": {
                    "x": int(min(xs)), "y": int(min(ys)),
                    "w": int(max(xs) - min(xs)), "h": int(max(ys) - min(ys)),
                },
                "polygon": [[int(p[0]), int(p[1])] for p in box],
            })
    return elements


# ── Render ──────────────────────────────────────────────────────────────

def render_map(data: dict, out_path: str):
    w, h = data["screen"]["width"], data["screen"]["height"]
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    base = "/usr/share/fonts/truetype/dejavu"
    try:
        font_label = ImageFont.truetype(f"{base}/DejaVuSans.ttf", 11)
        font_role = ImageFont.truetype(f"{base}/DejaVuSans.ttf", 9)
        font_ocr = ImageFont.truetype(f"{base}/DejaVuSans-Bold.ttf", 12)
    except Exception:
        font_label = font_role = font_ocr = ImageFont.load_default()

    for app in data["atspi"]["applications"]:
        for el in app["elements"]:
            b = el.get("bounds")
            if not b:
                continue
            x, y, bw, bh = b["x"], b["y"], b["w"], b["h"]
            if bw > 1200 and bh > 600:
                continue
            role = el.get("role", "")
            name = el.get("name", "")
            text = el.get("text", "")
            if role in ("push button", "toggle button", "menu item"):
                outline, fill_bg = "#888888", "#f0f0f0"
            elif role in ("menu", "menu bar"):
                outline, fill_bg = "#aaaaaa", "#f8f8f8"
            elif role in ("frame", "window"):
                outline, fill_bg = "#cccccc", None
            elif role in ("scroll bar", "separator", "filler", "panel"):
                outline, fill_bg = "#e0e0e0", None
            else:
                outline, fill_bg = "#bbbbbb", None
            draw.rectangle([x, y, x + bw, y + bh], outline=outline, fill=fill_bg, width=1)
            if role not in ("filler", "panel", "unknown", "separator"):
                draw.text((x + 2, y + 1), role, fill="#999999", font=font_role)
                display = name or text
                if display:
                    if len(display) > 60:
                        display = display[:57] + "..."
                    draw.text((x + 2, y + 12), display, fill="#333333", font=font_label)

    for el in data["ocr"]["elements"]:
        b = el["bounds"]
        conf = el.get("confidence", 0)
        color = "#0055dd" if conf >= 80 else "#3377cc" if conf >= 60 else "#6699bb"
        draw.text((b["x"], b["y"] + max(0, (b["h"] - 14) // 2)),
                  el["text"], fill=color, font=font_ocr)

    img.save(out_path)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else str(OUTPUT_DIR / "visible_screen.json")
    screen_w, screen_h = 1280, 720

    # Screenshot
    print("Taking screenshot...")
    subprocess.run(
        ["import", "-window", "root", str(SCREENSHOT)],
        env={**os.environ, "DISPLAY": ":1"},
        check=True,
    )

    # Window stacking
    print("Getting window stacking order...")
    windows = get_windows()
    for w in windows:
        print(f"  [{w['id']}] {w['x']},{w['y']} {w['w']}x{w['h']} d={w['desktop']} \"{w['name']}\"")

    visible_regions = compute_visible_regions(windows, screen_w, screen_h)
    print("Visible regions per window:")
    for wid, regions in visible_regions.items():
        wname = next((w["name"] for w in windows if w["id"] == wid), "?")
        total_area = sum((r[2]-r[0])*(r[3]-r[1]) for r in regions)
        print(f"  {wname}: {len(regions)} regions, {total_area}px² visible")

    # AT-SPI — collect and filter
    print("Collecting AT-SPI elements...")
    t0 = time.perf_counter()
    desktop = Atspi.get_desktop(0)
    all_apps = []
    total_before = 0
    total_after = 0

    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
            app_name = app.get_name() or f"app_{i}"
        except Exception:
            continue

        elements = collect_atspi(app)
        total_before += len(elements)

        # Match app to one or more windows
        win_ids = match_app_to_windows(app_name, elements, windows)

        if win_ids:
            # Merge visible regions from all matched windows
            all_regions = []
            for wid in win_ids:
                if wid in visible_regions:
                    all_regions.extend(visible_regions[wid])
            # Filter: keep only elements whose bounds are mostly within visible regions
            filtered = []
            for el in elements:
                b = el.get("bounds")
                if not b:
                    continue
                if rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
                    filtered.append(el)
            if filtered:
                all_apps.append({"application": app_name, "window_ids": win_ids, "elements": filtered})
                total_after += len(filtered)
        else:
            # Apps without matching windows (desktop, etc.)
            # These are always-visible — include elements that are on screen
            screen_region = [(0, 0, screen_w, screen_h)]
            filtered = []
            for el in elements:
                b = el.get("bounds")
                if not b:
                    continue
                if rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], screen_region):
                    filtered.append(el)
            if filtered:
                all_apps.append({"application": app_name, "window_ids": [], "elements": filtered})
                total_after += len(filtered)

    atspi_time = time.perf_counter() - t0
    print(f"  {total_before} total -> {total_after} visible ({total_before - total_after} filtered out)")

    # OCR
    print("Running RapidOCR...")
    t0 = time.perf_counter()
    ocr_elements = get_ocr_elements()
    ocr_time = time.perf_counter() - t0
    print(f"  {len(ocr_elements)} text regions")

    result = {
        "screen": {"width": screen_w, "height": screen_h},
        "windows": windows,
        "atspi": {
            "time_s": round(atspi_time, 3),
            "element_count": total_after,
            "filtered_out": total_before - total_after,
            "applications": all_apps,
        },
        "ocr": {
            "time_s": round(ocr_time, 3),
            "element_count": len(ocr_elements),
            "elements": ocr_elements,
        },
    }

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nWrote {total_after + len(ocr_elements)} visible elements to {output_path}")

    # Render map
    map_path = output_path.replace(".json", "_map.png")
    render_map(result, map_path)
    print(f"Wrote perception map to {map_path}")


if __name__ == "__main__":
    main()
