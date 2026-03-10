#!/usr/bin/env python3
"""
Computer Control MCP - Core Implementation
A compact ModelContextProtocol server that provides computer control capabilities
using PyAutoGUI for mouse/keyboard control.
"""

import json
import shutil
import sys
import os
import time
import subprocess
from typing import Dict, Any, List, Optional, Tuple
from io import BytesIO
import re
import asyncio
import uuid
import datetime
from pathlib import Path
import tempfile
from typing import Union
import threading
from concurrent.futures import ThreadPoolExecutor

# --- Auto-install dependencies if needed ---
import pyautogui
from mcp.server.fastmcp import FastMCP, Image
import mss
from PIL import Image as PILImage

try:
    import pywinctl as gw
except (NotImplementedError, ImportError):
    import pygetwindow as gw
from fuzzywuzzy import fuzz, process

import cv2
import numpy as np
from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion

from pydantic import BaseModel

BaseModel.model_config = {"arbitrary_types_allowed": True}

engine = RapidOCR(
    params={
        "Det.model_type": ModelType.MOBILE,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Rec.lang_type": LangRec.EN,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
    }
)

# Storage for last screenshots, keyed by window title or "full_screen"
_last_screenshots: Dict[str, Any] = {}

# Region-splitting OCR configuration (all configurable)
OCR_REGION_GRID = (4, 3)          # (cols, rows) — total regions = cols * rows
OCR_REGION_OVERLAP = 0.15         # 15% overlap between adjacent tiles
OCR_MAX_WORKERS = 4               # max parallel OCR threads (controls batching)
OCR_IOU_DEDUP_THRESHOLD = 0.40    # IoU above this = duplicate
OCR_MIN_IMAGE_AREA = 800 * 600    # only split images larger than this
# Examples of grid vs max_workers for accuracy/speed tradeoffs:
#   (2,2) grid, 4 workers  = 4 regions,  1 batch  — fast, good accuracy
#   (3,3) grid, 4 workers  = 9 regions,  3 batches — slower, better accuracy
#   (4,5) grid, 8 workers  = 20 regions, 3 batches (8+8+4) — slowest, best accuracy
#   (5,4) grid, 10 workers = 20 regions, 2 batches — slower but more parallel

DEBUG = True  # Set to False in production
RELOAD_ENABLED = True  # Set to False to disable auto-reload

# Create FastMCP server instance at module level
mcp = FastMCP("ComputerControlMCP")


# Try to import Windows Graphics Capture API
try:
    from windows_capture import WindowsCapture, Frame, InternalCaptureControl
    WGC_AVAILABLE = True
except ImportError:
    WGC_AVAILABLE = False


# Determine mode automatically
IS_DEVELOPMENT = os.getenv("ENV") == "development"


def log(message: str) -> None:
    """Log to stderr in dev, to stdout or file in production.
    
    Handles Unicode encoding errors gracefully to prevent crashes
    when printing special characters on Windows terminals.
    """
    try:
        if IS_DEVELOPMENT:
            # In dev, write to stderr
            print(f"[DEV] {message}", file=sys.stderr)
        else:
            # In production, write to stdout or a file
            print(f"[PROD] {message}", file=sys.stdout)
            # or append to a file: open("app.log", "a").write(message+"\n")
    except UnicodeEncodeError:
        # Handle encoding errors by escaping or replacing problematic characters
        safe_message = message.encode('utf-8', errors='replace').decode('utf-8')
        if IS_DEVELOPMENT:
            print(f"[DEV] {safe_message}", file=sys.stderr)
        else:
            print(f"[PROD] {safe_message}", file=sys.stdout)
    except Exception:
        # Fallback for any other printing errors
        try:
            safe_message = repr(message)  # Use repr to escape special characters
            if IS_DEVELOPMENT:
                print(f"[DEV] {safe_message}", file=sys.stderr)
            else:
                print(f"[PROD] {safe_message}", file=sys.stdout)
        except Exception:
            # Last resort - if even repr fails, don't crash
            pass


def get_downloads_dir() -> Path:
    """Get the directory for saving screenshots.

    Checks for COMPUTER_CONTROL_MCP_SCREENSHOT_DIR environment variable first,
    then falls back to the OS downloads directory.
    """
    # Check for custom directory from environment variable
    custom_dir = os.getenv("COMPUTER_CONTROL_MCP_SCREENSHOT_DIR")
    if custom_dir:
        custom_path = Path(custom_dir)
        if custom_path.exists() and custom_path.is_dir():
            return custom_path
        else:
            log(f"Warning: COMPUTER_CONTROL_MCP_SCREENSHOT_DIR path '{custom_dir}' does not exist or is not a directory. Falling back to default.")

    # Default: OS downloads directory
    if os.name == "nt":  # Windows
        import winreg

        sub_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        downloads_guid = "{374DE290-123F-4565-9164-39C4925E467B}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            downloads_dir = winreg.QueryValueEx(key, downloads_guid)[0]
        return Path(downloads_dir)
    else:  # macOS, Linux, etc.
        return Path.home() / "Downloads"


def _should_use_wgc_by_default(window_title: str) -> bool:
    """Check if WGC should be used for a window based on environment variable patterns.
    
    Checks the COMPUTER_CONTROL_MCP_WGC_PATTERNS environment variable, which should
    contain comma-separated patterns. If any pattern matches the window title,
    WGC will be used by default.
    
    Args:
        window_title: Title of the window to check
        
    Returns:
        True if WGC should be used by default for this window, False otherwise
    """
    # Get patterns from environment variable
    patterns_str = os.getenv("COMPUTER_CONTROL_MCP_WGC_PATTERNS")
    if not patterns_str:
        return False
    
    # Split patterns by comma and trim whitespace
    patterns = [pattern.strip().lower() for pattern in patterns_str.split(",") if pattern.strip()]
    
    # Convert window title to lowercase for case-insensitive matching
    title_lower = window_title.lower()
    
    # Check if any pattern matches
    for pattern in patterns:
        if pattern in title_lower:
            log(f"Window '{window_title}' matches WGC pattern: {pattern}")
            return True
    
    return False


def _mss_screenshot(region=None):
    """Take a screenshot using mss and return PIL Image.

    Args:
        region: Optional tuple (left, top, width, height) for region capture

    Returns:
        PIL Image object
    """
    with mss.mss() as sct:
        if region is None:
            # Full screen screenshot
            monitor = sct.monitors[0]  # All monitors combined
        else:
            # Region screenshot
            left, top, width, height = region
            monitor = {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }

        screenshot = sct.grab(monitor)
        # Convert to PIL Image
        return PILImage.frombytes(
            "RGB", screenshot.size, screenshot.bgra, "raw", "BGRX"
        )


def _wgc_screenshot(window_title: str) -> Optional[Tuple[bytes, int, int]]:
    """Capture a window using Windows Graphics Capture API.
    
    Args:
        window_title: Title of the window to capture
        
    Returns:
        Tuple of (image_bytes, width, height) or None if failed
    """
    if not WGC_AVAILABLE:
        log("Windows Graphics Capture API not available")
        return None
        
    captured_frame = {"data": None, "width": 0, "height": 0, "error": None}
    capture_event = threading.Event()

    try:
        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            monitor_index=None,
            window_name=window_title,
        )

        @capture.event
        def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl):
            try:
                # Save frame to temp file, then read it back
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp_path = tmp.name

                frame.save_as_image(tmp_path)

                with open(tmp_path, "rb") as f:
                    captured_frame["data"] = f.read()

                # Get dimensions from the saved image
                with PILImage.open(tmp_path) as img:
                    captured_frame["width"] = img.width
                    captured_frame["height"] = img.height

                os.unlink(tmp_path)
            except Exception as e:
                captured_frame["error"] = str(e)
            finally:
                capture_control.stop()
                capture_event.set()

        @capture.event
        def on_closed():
            capture_event.set()

        # Start capture in a thread
        def run_capture():
            try:
                capture.start()
            except Exception as e:
                captured_frame["error"] = str(e)
                capture_event.set()

        thread = threading.Thread(target=run_capture, daemon=True)
        thread.start()

        # Wait for frame (with timeout)
        if not capture_event.wait(timeout=5.0):
            captured_frame["error"] = "Capture timed out"

        if captured_frame["error"]:
            log(f"WGC capture error: {captured_frame['error']}")
            return None

        if captured_frame["data"] is None:
            log("No frame captured with WGC")
            return None

        return captured_frame["data"], captured_frame["width"], captured_frame["height"]

    except Exception as e:
        log(f"WGC capture failed: {e}")
        return None


def save_image_to_downloads(
    image, prefix: str = "screenshot", directory: Path = None,
    image_format: str = "png", quality: int = 80,
) -> Tuple[str, bytes]:
    """Save an image to the downloads directory and return its absolute path.

    Args:
        image: Either a PIL Image object or MCP Image object
        prefix: Prefix for the filename (default: 'screenshot')
        directory: Optional directory to save the image to
        image_format: Output format - "png", "webp", or "jpeg"
        quality: Compression quality 1-100 for webp/jpeg

    Returns:
        Tuple of (absolute_path, image_data_bytes)
    """
    # Create a unique filename with timestamp
    ext_map = {"png": ".png", "webp": ".webp", "jpeg": ".jpg"}
    ext = ext_map.get(image_format, ".png")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    filename = f"{prefix}_{timestamp}_{unique_id}{ext}"

    # Get downloads directory
    downloads_dir = directory or get_downloads_dir()
    filepath = downloads_dir / filename

    # Handle different image types
    if hasattr(image, "save"):  # PIL Image
        if image_format == "webp":
            image.save(filepath, format="WEBP", quality=quality)
        elif image_format == "jpeg":
            if image.mode in ("RGBA", "LA", "PA", "1"):
                image = image.convert("RGB")
            image.save(filepath, format="JPEG", quality=quality)
        else:
            image.save(filepath, format="PNG", optimize=True)
        # Also get the bytes for returning
        img_byte_arr = BytesIO()
        if image_format == "webp":
            image.save(img_byte_arr, format="WEBP", quality=quality)
        elif image_format == "jpeg":
            image.save(img_byte_arr, format="JPEG", quality=quality)
        else:
            image.save(img_byte_arr, format="PNG", optimize=True)
        img_bytes = img_byte_arr.getvalue()
    elif hasattr(image, "data"):  # MCP Image
        img_bytes = image.data
        with open(filepath, "wb") as f:
            f.write(img_bytes)
    else:
        raise TypeError("Unsupported image type")

    log(f"Saved image to {filepath}")
    return str(filepath.absolute()), img_bytes


def _process_image_for_output(
    screenshot: PILImage.Image,
    image_format: str = "png",
    quality: int = 80,
    color_mode: str = "color",
) -> Tuple[bytes, str]:
    """Apply format, quality, and color optimizations to a PIL Image.

    Args:
        screenshot: PIL Image to process
        image_format: Output format - "png", "webp", or "jpeg"
        quality: Compression quality 1-100 for webp/jpeg (ignored for png)
        color_mode: "color" (unchanged), "grayscale", or "bw" (black and white)

    Returns:
        Tuple of (image_bytes, format_string)
    """
    # Validate inputs
    valid_formats = {"png", "webp", "jpeg"}
    if image_format not in valid_formats:
        raise ValueError(f"image_format must be one of {valid_formats}, got '{image_format}'")

    valid_modes = {"color", "grayscale", "bw"}
    if color_mode not in valid_modes:
        raise ValueError(f"color_mode must be one of {valid_modes}, got '{color_mode}'")

    quality = max(1, min(100, quality))

    # Apply color mode conversion
    if color_mode == "grayscale":
        screenshot = screenshot.convert("L")
    elif color_mode == "bw":
        screenshot = screenshot.convert("1")

    # Serialize to bytes
    buf = BytesIO()
    if image_format == "webp":
        # WebP doesn't support mode "1", convert to "L"
        if screenshot.mode == "1":
            screenshot = screenshot.convert("L")
        screenshot.save(buf, format="WEBP", quality=quality)
    elif image_format == "jpeg":
        # JPEG requires RGB mode (no RGBA, no mode "1")
        if screenshot.mode in ("RGBA", "LA", "PA"):
            screenshot = screenshot.convert("RGB")
        elif screenshot.mode == "1":
            screenshot = screenshot.convert("L")
        elif screenshot.mode not in ("RGB", "L"):
            screenshot = screenshot.convert("RGB")
        screenshot.save(buf, format="JPEG", quality=quality)
    else:  # png
        screenshot.save(buf, format="PNG", optimize=True)

    return buf.getvalue(), image_format


def _force_activate_window(window):
    """Force a window to the foreground. Works reliably on Windows."""
    import ctypes
    import time
    try:
        hwnd = window._hWnd  # pywinctl window handle

        # Restore if minimized
        if window.isMinimized:
            window.restore()
            time.sleep(0.1)

        # Bring to top and set foreground
        if sys.platform == "win32":
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
        window.activate()  # fallback / non-Windows
        time.sleep(0.3)  # wait for OS to update

    except Exception as e:
        log(f"Warning: Could not force-activate window: {e}")


def _take_screenshot_as_array(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    activate: bool = False,
) -> Tuple[PILImage.Image, "np.ndarray", str, Optional[Any]]:
    """Take a screenshot and return as PIL Image + numpy array.

    Args:
        title_pattern: Window title pattern. None = full screen.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold.
        activate: If True, activate the matched window before capturing.

    Returns:
        (pil_image, numpy_array, key, window_obj_or_None)
        key is window title or "full_screen", used for _last_screenshots lookup.
    """
    window_obj = None
    key = "full_screen"

    if title_pattern:
        all_windows = gw.getAllWindows()
        windows = []
        for w in all_windows:
            if w.title:
                windows.append({"title": w.title, "window_obj": w})

        matched = _find_matching_window(windows, title_pattern, use_regex, threshold)
        if matched:
            window_obj = matched["window_obj"]
            key = window_obj.title

    if window_obj:
        if activate:
            _force_activate_window(window_obj)
        screen_width, screen_height = pyautogui.size()
        pil_img = _mss_screenshot(region=(
            max(window_obj.left, 0),
            max(window_obj.top, 0),
            min(window_obj.width, screen_width),
            min(window_obj.height, screen_height),
        ))
    else:
        pil_img = _mss_screenshot()

    np_array = np.array(pil_img)
    return pil_img, np_array, key, window_obj


def _compute_diff_regions(
    old_img: "np.ndarray",
    new_img: "np.ndarray",
    pixel_threshold: int = 30,
    min_region_area: int = 100,
) -> Tuple[bool, float, List[Dict[str, int]]]:
    """Compare two screenshot arrays and find changed regions.

    Args:
        old_img: Previous screenshot as numpy array (RGB).
        new_img: Current screenshot as numpy array (RGB).
        pixel_threshold: Per-pixel difference threshold (0-255).
        min_region_area: Minimum bounding box area to report.

    Returns:
        (changed, change_percent, regions)
        regions: list of {"left", "top", "width", "height"} dicts, sorted by area descending.
    """
    # Handle size mismatches (window was resized)
    if old_img.shape != new_img.shape:
        old_img = cv2.resize(old_img, (new_img.shape[1], new_img.shape[0]))

    # Compute absolute difference
    diff = cv2.absdiff(old_img, new_img)
    gray_diff = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)

    # Threshold
    _, thresh = cv2.threshold(gray_diff, pixel_threshold, 255, cv2.THRESH_BINARY)

    # Change percentage
    change_percent = round((np.count_nonzero(thresh) / thresh.size) * 100.0, 2)

    if change_percent == 0:
        return False, 0.0, []

    # Find contours — collect ALL bounding boxes first (no area filter).
    # Small contours (individual changed pixels/characters) must participate in
    # merging so they can combine into larger meaningful regions.
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        boxes.append((x, y, w, h))

    # Merge nearby bounding boxes — boxes that overlap, touch, or are within
    # merge_distance pixels of each other get combined into one region.
    # 80px covers typical UI gaps (title bar → toolbar → content) so related
    # changes in the same window merge into one region.
    merge_distance = 80
    for _ in range(20):  # iterate until no more merges happen
        merged = []
        used = set()
        for i, (x1, y1, w1, h1) in enumerate(boxes):
            if i in used:
                continue
            mx, my, mw, mh = x1, y1, w1, h1
            for j, (x2, y2, w2, h2) in enumerate(boxes):
                if j <= i or j in used:
                    continue
                # Check if boxes overlap or are close
                if (mx - merge_distance <= x2 + w2 and
                    x2 - merge_distance <= mx + mw and
                    my - merge_distance <= y2 + h2 and
                    y2 - merge_distance <= my + mh):
                    # Merge
                    new_x = min(mx, x2)
                    new_y = min(my, y2)
                    new_r = max(mx + mw, x2 + w2)
                    new_b = max(my + mh, y2 + h2)
                    mx, my, mw, mh = new_x, new_y, new_r - new_x, new_b - new_y
                    used.add(j)
            merged.append((mx, my, mw, mh))
            used.add(i)
        if len(merged) == len(boxes):
            boxes = merged
            break
        boxes = merged

    # Filter by min area AFTER merging — small contours may have merged into
    # large meaningful regions, so we only discard truly tiny leftovers now.
    boxes = [(x, y, w, h) for x, y, w, h in boxes if w * h >= min_region_area]

    # Sort by area descending
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)

    # Pad each final region to capture surrounding context. Unchanged pixels
    # near the change boundary are often part of the same visual element
    # (e.g., text characters that happen to be identical between screenshots).
    # Applied AFTER merging to avoid cascading merges across the whole screen.
    img_h, img_w = new_img.shape[:2]
    padding = 40
    regions = []
    for (x, y, w, h) in boxes:
        px = max(0, x - padding)
        py = max(0, y - padding)
        pr = min(img_w, x + w + padding)
        pb = min(img_h, y + h + padding)
        regions.append({"left": px, "top": py, "width": pr - px, "height": pb - py})

    return True, change_percent, regions


def _set_clipboard(text: str) -> None:
    """Set the system clipboard text. Cross-platform (Windows/Linux).

    Args:
        text: Text to place on clipboard.

    Raises:
        RuntimeError: If clipboard operation fails.
    """
    try:
        if sys.platform == "win32":
            # Use PowerShell Set-Clipboard with UTF-8 stdin for full unicode (incl. emojis)
            process = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
                 "$text = [System.IO.StreamReader]::new("
                 "[Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8"
                 ").ReadToEnd(); "
                 "Set-Clipboard -Value $text"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
            if process.returncode != 0:
                raise RuntimeError(f"PowerShell clipboard failed: {process.stderr}")
        else:
            # Linux: try xclip first, fall back to xsel
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Clipboard operation timed out")


def _find_matching_window(
    windows: any,
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
) -> Optional[Dict[str, Any]]:
    """Helper function to find a matching window based on title pattern.

    Args:
        windows: List of window dictionaries
        title_pattern: Pattern to match window title
        use_regex: If True, treat the pattern as a regex, otherwise use fuzzy matching
        threshold: Minimum score (0-100) required for a fuzzy match

    Returns:
        The best matching window or None if no match found
    """
    if not title_pattern:
        log("No title pattern provided, returning None")
        return None

    # For regex matching
    if use_regex:
        for window in windows:
            if re.search(title_pattern, window["title"], re.IGNORECASE):
                log(f"Regex match found: {window['title']}")
                return window
        return None

    # For fuzzy matching using fuzzywuzzy
    # Extract all window titles
    window_titles = [window["title"] for window in windows]

    # Use process.extractOne to find the best match
    best_match_title, score = process.extractOne(
        title_pattern, window_titles, scorer=fuzz.partial_ratio
    )
    log(f"Best fuzzy match: '{best_match_title}' with score {score}")

    # Only return if the score is above the threshold
    if score >= threshold:
        # Find the window with the matching title
        for window in windows:
            if window["title"] == best_match_title:
                return window

    return None


# --- MCP Function Handlers ---


@mcp.tool()
def click_screen(x: int, y: int) -> str:
    """Click at the specified screen coordinates."""
    try:
        pyautogui.click(x=x, y=y)
        return f"Successfully clicked at coordinates ({x}, {y})"
    except Exception as e:
        return f"Error clicking at coordinates ({x}, {y}): {str(e)}"


@mcp.tool()
def get_screen_size() -> Dict[str, Any]:
    """Get the current screen resolution."""
    try:
        width, height = pyautogui.size()
        return {
            "width": width,
            "height": height,
            "message": f"Screen size: {width}x{height}",
        }
    except Exception as e:
        return {"error": str(e), "message": f"Error getting screen size: {str(e)}"}


@mcp.tool()
def type_text(text: str) -> str:
    """Type the specified text at the current cursor position."""
    try:
        pyautogui.typewrite(text)
        return f"Successfully typed text: {text}"
    except Exception as e:
        return f"Error typing text: {str(e)}"


@mcp.tool()
def take_screenshot(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    scale_percent_for_ocr: int = None,
    save_to_downloads: bool = False,
    use_wgc: bool = False,
    image_format: str = "png",
    quality: int = 80,
    color_mode: str = "color",
) -> Image:
    """
    Get screenshot Image as MCP Image object. If no title pattern is provided, get screenshot of entire screen and all text on the screen.

    Args:
        title_pattern: Pattern to match window title, if None, take screenshot of entire screen
        use_regex: If True, treat the pattern as a regex, otherwise best match with fuzzy matching
        threshold: Minimum score (0-100) required for a fuzzy match
        scale_percent_for_ocr: Percentage to scale the image down before processing, you wont need this most of the time unless your pc is extremely old or slow
        save_to_downloads: If True, save the screenshot to the downloads directory and return the absolute path
        use_wgc: If True, use Windows Graphics Capture API for window capture (recommended for GPU-accelerated windows)
        image_format: Output format - "png" (default, lossless), "webp" (much smaller ~85-90%% reduction), or "jpeg" (smallest, lossy, no transparency)
        quality: Compression quality 1-100 for webp/jpeg formats. Lower = smaller file. Ignored for PNG. Default: 80
        color_mode: Color mode - "color" (default), "grayscale" (removes color, ~50%% smaller for PNG, significant for webp/jpeg), or "bw" (black and white, very small, best for text-heavy screens)

    Returns:
        Returns a single screenshot as MCP Image object. "content type image not supported" means preview isnt supported but Image object is there and returned successfully.
    """
    try:
        all_windows = gw.getAllWindows()

        # Convert to list of dictionaries for _find_matching_window
        windows = []
        for window in all_windows:
            if window.title:  # Only include windows with titles
                windows.append(
                    {
                        "title": window.title,
                        "window_obj": window,  # Store the actual window object
                    }
                )

        log(f"Found {len(windows)} windows")
        window = _find_matching_window(windows, title_pattern, use_regex, threshold)
        window = window["window_obj"] if window else None

        # Take the screenshot
        if not window:
            log("No matching window found, taking screenshot of entire screen")
            screenshot = _mss_screenshot()
        else:
            try:
                # Re-fetch window handle to ensure it's valid
                window = gw.getWindowsWithTitle(window.title)[0]
                current_active_window = gw.getActiveWindow()
                log(f"Taking screenshot of window: {window.title}")

                # Determine if we should use WGC:
                # 1. If explicitly requested via use_wgc parameter
                # 2. If the window matches patterns defined in environment variable
                should_use_wgc = use_wgc or _should_use_wgc_by_default(window.title)
                
                # Try WGC capture first if requested or if it's likely a GPU-accelerated window
                if should_use_wgc and WGC_AVAILABLE:
                    log("Attempting WGC capture")
                    wgc_result = _wgc_screenshot(window.title)
                    if wgc_result:
                        image_bytes, width, height = wgc_result
                        screenshot = PILImage.open(BytesIO(image_bytes))
                        log(f"WGC capture successful: {width}x{height}")
                    else:
                        log("WGC capture failed, falling back to MSS")
                        # Fall back to MSS if WGC fails
                        _force_activate_window(window)
                        pyautogui.sleep(0.2)

                        screen_width, screen_height = pyautogui.size()

                        screenshot = _mss_screenshot(
                            region=(
                                max(window.left, 0),
                                max(window.top, 0),
                                min(window.width, screen_width),
                                min(window.height, screen_height),
                            )
                        )
                else:
                    _force_activate_window(window)
                    pyautogui.sleep(0.2)

                    screen_width, screen_height = pyautogui.size()

                    screenshot = _mss_screenshot(
                        region=(
                            max(window.left, 0),
                            max(window.top, 0),
                            min(window.width, screen_width),
                            min(window.height, screen_height),
                        )
                    )

                # Restore previously active window
                if current_active_window and current_active_window != window:
                    try:
                        _force_activate_window(current_active_window)
                        pyautogui.sleep(0.2)
                    except Exception as e:
                        log(f"Error restoring previous window: {str(e)}")
            except Exception as e:
                log(f"Error taking screenshot of window: {str(e)}")
                screenshot = _mss_screenshot()  # fallback to full screen

        # Process image with format/quality/color optimizations
        try:
            img_bytes, fmt = _process_image_for_output(
                screenshot,
                image_format=image_format,
                quality=quality,
                color_mode=color_mode,
            )
        except ValueError as e:
            return f"Invalid parameter: {str(e)}"

        log(f"Processed screenshot: format={fmt}, size={len(img_bytes)} bytes")

        # Create MCP Image directly from bytes
        image = Image(data=img_bytes, format=fmt)

        if save_to_downloads:
            ext_map = {"png": ".png", "webp": ".webp", "jpeg": ".jpg"}
            ext = ext_map.get(fmt, ".png")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"screenshot_{timestamp}_{unique_id}{ext}"
            downloads_path = get_downloads_dir() / filename
            with open(downloads_path, "wb") as f:
                f.write(img_bytes)
            log(f"Saved screenshot to {downloads_path}")

        return image  # MCP Image object

    except Exception as e:
        log(f"Error in screenshot or getting UI elements: {str(e)}")
        import traceback

        stack_trace = traceback.format_exc()
        log(f"Stack trace:\n{stack_trace}")
        return f"Error in screenshot or getting UI elements: {str(e)}\nStack trace:\n{stack_trace}"


def is_low_spec_pc() -> bool:
    try:
        import psutil

        cpu_low = psutil.cpu_count(logical=False) < 4
        ram_low = psutil.virtual_memory().total < 8 * 1024**3
        return cpu_low or ram_low
    except Exception:
        # Fallback if psutil not available or info unavailable
        return False


def _safe_format_ocr_results(results: List[Tuple]) -> str:
    """Safely format OCR results for logging, handling Unicode characters.
    
    Args:
        results: List of OCR results tuples ([boxes], text, confidence)
        
    Returns:
        Safely formatted string representation of the results
    """
    try:
        # Try normal formatting first
        return str(results)
    except UnicodeEncodeError:
        # If that fails, create a safe representation
        safe_items = []
        for item in results:
            # Handle each component of the tuple
            boxes, text, confidence = item
            # Ensure text is safe for printing
            try:
                safe_text = str(text)
                safe_text.encode('utf-8').decode(sys.stdout.encoding or 'utf-8')
            except (UnicodeEncodeError, UnicodeDecodeError):
                # Replace problematic characters
                safe_text = text.encode('utf-8', errors='replace').decode('utf-8')
            
            safe_items.append((boxes, safe_text, confidence))
        
        return str(safe_items)
    except Exception:
        # Ultimate fallback
        return f"<OCR results with {len(results)} items>"


# --- Region-splitting OCR helpers ---

_thread_local = threading.local()

_ENGINE_PARAMS = {
    "Det.model_type": ModelType.MOBILE,
    "Det.ocr_version": OCRVersion.PPOCRV5,
    "Rec.lang_type": LangRec.EN,
    "Rec.model_type": ModelType.MOBILE,
    "Rec.ocr_version": OCRVersion.PPOCRV5,
}


def _get_thread_engine() -> RapidOCR:
    """Get or create a per-thread RapidOCR engine instance."""
    if not hasattr(_thread_local, 'engine'):
        _thread_local.engine = RapidOCR(params=_ENGINE_PARAMS)
    return _thread_local.engine


def _split_image_into_regions(
    img_height: int,
    img_width: int,
    grid: Tuple[int, int] = None,
    overlap: float = None,
) -> List[Tuple[int, int, int, int]]:
    """Compute overlapping region coordinates for tiled OCR.

    Args:
        img_height: Image height in pixels.
        img_width: Image width in pixels.
        grid: (cols, rows) grid dimensions.
        overlap: Overlap fraction between adjacent tiles (0.0-0.5).

    Returns:
        List of (x, y, width, height) tuples for each tile.
    """
    cols, rows = grid or OCR_REGION_GRID
    overlap = overlap if overlap is not None else OCR_REGION_OVERLAP

    base_w = img_width / cols
    base_h = img_height / rows
    overlap_x = int(base_w * overlap)
    overlap_y = int(base_h * overlap)

    regions = []
    for row in range(rows):
        for col in range(cols):
            x_start = max(0, int(col * base_w) - (overlap_x if col > 0 else 0))
            y_start = max(0, int(row * base_h) - (overlap_y if row > 0 else 0))
            x_end = min(img_width, int((col + 1) * base_w) + (overlap_x if col < cols - 1 else 0))
            y_end = min(img_height, int((row + 1) * base_h) + (overlap_y if row < rows - 1 else 0))
            regions.append((x_start, y_start, x_end - x_start, y_end - y_start))

    return regions


def _compute_iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
    """Compute IoU between two quadrilateral bounding boxes.

    Each box is shape (4, 2) — 4 corner points. Converts to axis-aligned
    bounding rectangles for efficient computation.
    """
    # Convert (4,2) corners to axis-aligned (xmin, ymin, xmax, ymax)
    a_xmin, a_ymin = box_a[:, 0].min(), box_a[:, 1].min()
    a_xmax, a_ymax = box_a[:, 0].max(), box_a[:, 1].max()
    b_xmin, b_ymin = box_b[:, 0].min(), box_b[:, 1].min()
    b_xmax, b_ymax = box_b[:, 0].max(), box_b[:, 1].max()

    inter_w = max(0, min(a_xmax, b_xmax) - max(a_xmin, b_xmin))
    inter_h = max(0, min(a_ymax, b_ymax) - max(a_ymin, b_ymin))
    intersection = inter_w * inter_h

    area_a = (a_xmax - a_xmin) * (a_ymax - a_ymin)
    area_b = (b_xmax - b_xmin) * (b_ymax - b_ymin)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def _deduplicate_ocr_results(
    boxes: List[np.ndarray],
    txts: List[str],
    scores: List[float],
    iou_threshold: float = None,
) -> Tuple[List[np.ndarray], List[str], List[float]]:
    """Remove duplicate detections from merged region results.

    Two detections are duplicates when their bounding box IoU exceeds
    the threshold AND their text content has a fuzzy match score >= 80.
    When duplicates are found, keep the one with higher confidence.
    """
    iou_threshold = iou_threshold if iou_threshold is not None else OCR_IOU_DEDUP_THRESHOLD
    if not boxes:
        return [], [], []

    n = len(boxes)
    # Sort by confidence descending
    indices = sorted(range(n), key=lambda i: scores[i], reverse=True)
    keep = [True] * n

    for idx_i in range(n):
        i = indices[idx_i]
        if not keep[i]:
            continue
        for idx_j in range(idx_i + 1, n):
            j = indices[idx_j]
            if not keep[j]:
                continue
            if _compute_iou(boxes[i], boxes[j]) > iou_threshold:
                if fuzz.ratio(txts[i], txts[j]) >= 80:
                    keep[j] = False  # drop lower-confidence duplicate

    return (
        [boxes[i] for i in range(n) if keep[i]],
        [txts[i] for i in range(n) if keep[i]],
        [scores[i] for i in range(n) if keep[i]],
    )


def _ocr_with_regions(
    img: np.ndarray,
    grid: Tuple[int, int] = None,
    overlap: float = None,
    max_workers: int = None,
) -> Tuple[Optional[List[np.ndarray]], Optional[List[str]], Optional[List[float]]]:
    """Run OCR on an image, splitting into overlapping regions for large images.

    For images smaller than OCR_MIN_IMAGE_AREA, runs single-pass OCR.
    For larger images, splits into a grid of overlapping tiles, runs OCR
    on each tile in parallel (batched by max_workers), translates coordinates
    back to full-image space, and deduplicates overlapping results.

    Args:
        img: BGR numpy array (as expected by RapidOCR).
        grid: (cols, rows) grid size, or None for module default.
        overlap: Overlap fraction, or None for module default.
        max_workers: Thread pool size, or None for module default.

    Returns:
        (boxes, txts, scores) — same format as engine() output fields,
        or (None, None, None) if no text found.
    """
    max_workers = max_workers or OCR_MAX_WORKERS

    # Small images: single-pass OCR, no splitting needed
    img_area = img.shape[0] * img.shape[1]
    if img_area < OCR_MIN_IMAGE_AREA:
        output = engine(img)
        return output.boxes, output.txts, output.scores

    # Compute tile regions
    regions = _split_image_into_regions(img.shape[0], img.shape[1], grid, overlap)
    log(f"[OCR Regions] Splitting {img.shape[1]}x{img.shape[0]} image into {len(regions)} tiles, max_workers={max_workers}")

    def _ocr_region(region):
        x, y, w, h = region
        tile = img[y:y + h, x:x + w]
        local_engine = _get_thread_engine()
        output = local_engine(tile)
        return (output.boxes, output.txts, output.scores, x, y)

    # Run OCR on all tiles — ThreadPoolExecutor handles batching automatically
    # e.g., 20 tiles with max_workers=8 runs as 3 batches: 8+8+4
    all_boxes = []
    all_txts = []
    all_scores = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_ocr_region, r) for r in regions]
        for future in futures:
            boxes, txts, scores, x_off, y_off = future.result()
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    box[:, 0] += x_off  # translate x coordinates
                    box[:, 1] += y_off  # translate y coordinates
                all_boxes.extend(boxes)
                all_txts.extend(txts)
                all_scores.extend(scores)

    if not all_boxes:
        return None, None, None

    # Deduplicate overlapping detections from adjacent tiles
    deduped_boxes, deduped_txts, deduped_scores = _deduplicate_ocr_results(
        all_boxes, all_txts, all_scores
    )

    log(f"[OCR Regions] {len(all_boxes)} raw detections → {len(deduped_boxes)} after dedup")
    return deduped_boxes, deduped_txts, deduped_scores


@mcp.tool()
def take_screenshot_with_ocr(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    scale_percent_for_ocr: int = None,
    save_to_downloads: bool = False,
    image_format: str = "png",
    quality: int = 80,
    color_mode: str = "color",
) -> str:
    """
    Get OCR text from screenshot with absolute coordinates as JSON string of List[Tuple[List[List[int]], str, float]] (returned after adding the window offset from true (0, 0) of screen to the OCR coordinates, so clicking is on-point. Recommended to click in the middle of OCR Box) and using confidence from window with the specified title pattern. If no title pattern is provided, get screenshot of entire screen and all text on the screen. Know that OCR takes around 20 seconds on an mid-spec pc at 1080p resolution.

    Args:
        title_pattern: Pattern to match window title, if None, take screenshot of entire screen
        use_regex: If True, treat the pattern as a regex, otherwise best match with fuzzy matching
        threshold: Minimum score (0-100) required for a fuzzy match
        scale_percent_for_ocr: Percentage to scale the image down before processing, you wont need this most of the time unless your pc is extremely old or slow
        save_to_downloads: If True, save the screenshot to the downloads directory and return the absolute path
        image_format: Output format for saved file - "png" (default), "webp" (much smaller), or "jpeg". Only applies when save_to_downloads is True
        quality: Compression quality 1-100 for webp/jpeg when saving. Default: 80
        color_mode: Color mode for saved file - "color" (default), "grayscale", or "bw". Only applies when save_to_downloads is True

    Returns:
        JSON array of detected text elements. Each element has: text, confidence, box (relative corners), abs_box (absolute screen corners), center_x/center_y (relative), abs_center_x/abs_center_y (absolute screen coordinates ready for click_screen).
    """
    try:
        all_windows = gw.getAllWindows()

        # Convert to list of dictionaries for _find_matching_window
        windows = []
        for window in all_windows:
            if window.title:  # Only include windows with titles
                windows.append(
                    {
                        "title": window.title,
                        "window_obj": window,  # Store the actual window object
                    }
                )

        log(f"Found {len(windows)} windows")
        window = _find_matching_window(windows, title_pattern, use_regex, threshold)
        window = window["window_obj"] if window else None

        # Store the currently active window

        # Take the screenshot
        if not window:
            log("No matching window found, taking screenshot of entire screen")
            screenshot = _mss_screenshot()
        else:
            log(f"Taking screenshot of window: {window.title}")
            try:
                _force_activate_window(window)
                screenshot = _mss_screenshot(
                    region=(window.left, window.top, window.width, window.height)
                )
            except Exception as e:
                log(f"Error taking screenshot of window: {str(e)}")
                return f"Error taking screenshot of window: {str(e)}"

        # Create temp directory and save as PNG for OCR processing
        temp_dir = Path(tempfile.mkdtemp())

        # Save screenshot as PNG for OCR (always PNG for cv2.imread compatibility)
        filepath, _ = save_image_to_downloads(
            screenshot, prefix="screenshot", directory=temp_dir
        )

        # Save optimized version to downloads if requested
        if save_to_downloads:
            try:
                img_bytes, fmt = _process_image_for_output(
                    screenshot,
                    image_format=image_format,
                    quality=quality,
                    color_mode=color_mode,
                )
                ext_map = {"png": ".png", "webp": ".webp", "jpeg": ".jpg"}
                ext = ext_map.get(fmt, ".png")
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                filename = f"screenshot_{timestamp}_{unique_id}{ext}"
                downloads_path = get_downloads_dir() / filename
                with open(downloads_path, "wb") as f:
                    f.write(img_bytes)
                log(f"Saved optimized screenshot to {downloads_path}")
            except ValueError as e:
                log(f"Invalid parameter for save: {str(e)}")

        img = cv2.imread(filepath)

        if img is None:
            log(f"Error: Failed to read image from {filepath}")
            return f"Error: Failed to read image from {filepath}"

        if scale_percent_for_ocr is None:
            # Calculate percent to scale height to 360 pixels
            scale_percent_for_ocr = 100  # 360 / img.shape[0] * 100

        # Validate scale_percent_for_ocr
        if scale_percent_for_ocr <= 0:
            log(f"Error: scale_percent_for_ocr must be greater than 0, got {scale_percent_for_ocr}")
            return f"Error: scale_percent_for_ocr must be greater than 0, got {scale_percent_for_ocr}"

        # Lower down resolution before processing
        width = int(img.shape[1] * scale_percent_for_ocr / 100)
        height = int(img.shape[0] * scale_percent_for_ocr / 100)
        
        # Ensure dimensions are at least 1 pixel
        width = max(1, width)
        height = max(1, height)
        
        dim = (width, height)
        log(f"Resizing image from {img.shape[1]}x{img.shape[0]} to {width}x{height} (scale: {scale_percent_for_ocr}%)")
        resized_img = cv2.resize(img, dim, interpolation=cv2.INTER_AREA)
        # save resized image to pwd
        # cv2.imwrite("resized_img.png", resized_img)

        # Use region-splitting OCR for full-screen captures
        if not window:
            boxes, txts, scores = _ocr_with_regions(resized_img)
        else:
            output = engine(resized_img)
            boxes, txts, scores = output.boxes, output.txts, output.scores

        if boxes is None or txts is None:
            return "No text found in screenshot."

        # Calculate window offset for absolute coordinates
        offset_x = 0
        offset_y = 0
        if window:
            offset_x = max(window.left, 0)
            offset_y = max(window.top, 0)

        results = []
        for box, text, score in zip(boxes, txts, scores):
            box_list = box.tolist()
            # Relative coordinates (within the captured region)
            rel_center_x = int(sum(p[0] for p in box_list) / 4)
            rel_center_y = int(sum(p[1] for p in box_list) / 4)
            # Absolute screen coordinates (ready for click_screen)
            abs_center_x = rel_center_x + offset_x
            abs_center_y = rel_center_y + offset_y
            abs_box = [[int(p[0] + offset_x), int(p[1] + offset_y)] for p in box_list]

            results.append({
                "text": text,
                "confidence": round(float(score), 4),
                "box": box_list,
                "abs_box": abs_box,
                "center_x": rel_center_x,
                "center_y": rel_center_y,
                "abs_center_x": abs_center_x,
                "abs_center_y": abs_center_y,
            })

        log(f"Found {len(results)} text items in OCR result.")
        log(f"First 5 items: {_safe_format_ocr_results([(r['box'], r['text'], r['confidence']) for r in results[:5]])}")
        return json.dumps(results) if results else "No text found"

    except Exception as e:
        log(f"Error in screenshot or getting UI elements: {str(e)}")
        import traceback

        stack_trace = traceback.format_exc()
        log(f"Stack trace:\n{stack_trace}")
        return f"Error in screenshot or getting UI elements: {str(e)}\nStack trace:\n{stack_trace}"


@mcp.tool()
def move_mouse(x: int, y: int) -> str:
    """Move the mouse to the specified screen coordinates."""
    try:
        pyautogui.moveTo(x=x, y=y)
        return f"Successfully moved mouse to coordinates ({x}, {y})"
    except Exception as e:
        return f"Error moving mouse to coordinates ({x}, {y}): {str(e)}"


@mcp.tool()
def mouse_down(button: str = "left") -> str:
    """Hold down a mouse button ('left', 'right', 'middle')."""
    try:
        pyautogui.mouseDown(button=button)
        return f"Held down {button} mouse button"
    except Exception as e:
        return f"Error holding {button} mouse button: {str(e)}"


@mcp.tool()
def mouse_up(button: str = "left") -> str:
    """Release a mouse button ('left', 'right', 'middle')."""
    try:
        pyautogui.mouseUp(button=button)
        return f"Released {button} mouse button"
    except Exception as e:
        return f"Error releasing {button} mouse button: {str(e)}"


@mcp.tool()
async def drag_mouse(
    from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5
) -> str:
    """
    Drag the mouse from one position to another.

    Args:
        from_x: Starting X coordinate
        from_y: Starting Y coordinate
        to_x: Ending X coordinate
        to_y: Ending Y coordinate
        duration: Duration of the drag in seconds (default: 0.5)

    Returns:
        Success or error message
    """
    try:
        # First move to the starting position
        pyautogui.moveTo(x=from_x, y=from_y)
        # Then drag to the destination
        log("starting drag")
        await asyncio.to_thread(pyautogui.dragTo, x=to_x, y=to_y, duration=duration)
        log("done drag")
        return f"Successfully dragged from ({from_x}, {from_y}) to ({to_x}, {to_y})"
    except Exception as e:
        return f"Error dragging from ({from_x}, {from_y}) to ({to_x}, {to_y}): {str(e)}"


import pyautogui
from typing import Union, List


@mcp.tool()
def key_down(key: str) -> str:
    """Hold down a specific keyboard key until released."""
    try:
        pyautogui.keyDown(key)
        return f"Held down key: {key}"
    except Exception as e:
        return f"Error holding key {key}: {str(e)}"


@mcp.tool()
def key_up(key: str) -> str:
    """Release a specific keyboard key."""
    try:
        pyautogui.keyUp(key)
        return f"Released key: {key}"
    except Exception as e:
        return f"Error releasing key {key}: {str(e)}"


@mcp.tool()
def press_keys(keys: Union[str, List[Union[str, List[str]]]]) -> str:
    """
    Press keyboard keys.

    Args:
        keys:
            - Single key as string (e.g., "enter")
            - Sequence of keys as list (e.g., ["a", "b", "c"])
            - Key combinations as nested list (e.g., [["ctrl", "c"], ["alt", "tab"]])

    Examples:
        press_keys("enter")
        press_keys(["a", "b", "c"])
        press_keys([["ctrl", "c"], ["alt", "tab"]])
    """
    try:
        if isinstance(keys, str):
            # Single key
            pyautogui.press(keys)
            return f"Pressed single key: {keys}"

        elif isinstance(keys, list):
            for item in keys:
                if isinstance(item, str):
                    # Sequential key press
                    pyautogui.press(item)
                elif isinstance(item, list):
                    # Key combination (e.g., ctrl+c)
                    pyautogui.hotkey(*item)
                else:
                    return f"Invalid key format: {item}"
            return f"Successfully pressed keys sequence: {keys}"

        else:
            return "Invalid input: must be str or list"

    except Exception as e:
        return f"Error pressing keys {keys}: {str(e)}"


@mcp.tool()
def list_windows() -> List[Dict[str, Any]]:
    """List all open windows on the system."""
    try:
        windows = gw.getAllWindows()
        result = []
        for window in windows:
            if window.title:  # Only include windows with titles
                result.append(
                    {
                        "title": window.title,
                        "left": window.left,
                        "top": window.top,
                        "width": window.width,
                        "height": window.height,
                        "is_active": window.isActive,
                        "is_visible": window.visible,
                        "is_minimized": window.isMinimized,
                        "is_maximized": window.isMaximized,
                        # "screenshot": pyautogui.screenshot(
                        #     region=(
                        #         window.left,
                        #         window.top,
                        #         window.width,
                        #         window.height,
                        #     )
                        # ),
                    }
                )
        return result
    except Exception as e:
        log(f"Error listing windows: {str(e)}")
        return [{"error": str(e)}]


@mcp.tool()
def wait_milliseconds(milliseconds: int) -> str:
    """
    Wait for a specified number of milliseconds.
    
    Args:
        milliseconds: Number of milliseconds to wait
        
    Returns:
        Success message after waiting
    """
    try:
        import time
        seconds = milliseconds / 1000.0
        time.sleep(seconds)
        return f"Successfully waited for {milliseconds} milliseconds"
    except Exception as e:
        return f"Error waiting for {milliseconds} milliseconds: {str(e)}"


@mcp.tool()
def set_clipboard(text: str) -> str:
    """Set the system clipboard text. Cross-platform (Windows/Linux). Supports full unicode including emojis.

    Args:
        text: Text to place on the clipboard.

    Returns:
        Success or error message.
    """
    try:
        _set_clipboard(text)
        preview = text[:50] + ("..." if len(text) > 50 else "")
        return f"Clipboard set to: '{preview}'"
    except Exception as e:
        return f"Error setting clipboard: {str(e)}"


@mcp.tool()
def activate_window(
    title_pattern: str, use_regex: bool = False, threshold: int = 60
) -> str:
    """
    Activate a window (bring it to the foreground) by matching its title.

    Args:
        title_pattern: Pattern to match window title
        use_regex: If True, treat the pattern as a regex, otherwise use fuzzy matching
        threshold: Minimum score (0-100) required for a fuzzy match

    Returns:
        Success or error message
    """
    try:
        # Get all windows
        all_windows = gw.getAllWindows()

        # Convert to list of dictionaries for _find_matching_window
        windows = []
        for window in all_windows:
            if window.title:  # Only include windows with titles
                windows.append(
                    {
                        "title": window.title,
                        "window_obj": window,  # Store the actual window object
                    }
                )

        # Find matching window using our improved function
        matched_window_dict = _find_matching_window(
            windows, title_pattern, use_regex, threshold
        )

        if not matched_window_dict:
            log(f"No window found matching pattern: {title_pattern}")
            return f"Error: No window found matching pattern: {title_pattern}"

        # Get the actual window object
        matched_window = matched_window_dict["window_obj"]

        # Activate the window
        _force_activate_window(matched_window)

        return f"Successfully activated window: '{matched_window.title}'"
    except Exception as e:
        log(f"Error activating window: {str(e)}")
        return f"Error activating window: {str(e)}"


@mcp.tool()
async def perform_actions(
    actions: List[Dict[str, Any]],
    stop_on_error: bool = True,
) -> str:
    """Execute multiple actions in sequence in a single MCP call, reducing round-trip overhead.

    Args:
        actions: List of action dicts, each with a "type" field and relevant params.
            Supported types:
            - {"type": "click", "x": int, "y": int}
            - {"type": "move_mouse", "x": int, "y": int}
            - {"type": "type_text", "text": str}
            - {"type": "press_key", "key": str}
            - {"type": "press_keys", "keys": str | list} (same format as press_keys tool)
            - {"type": "key_down", "key": str}
            - {"type": "key_up", "key": str}
            - {"type": "mouse_down", "button": str}
            - {"type": "mouse_up", "button": str}
            - {"type": "wait", "milliseconds": int}
            - {"type": "set_clipboard", "text": str}
            - {"type": "activate_window", "title_pattern": str, "use_regex": bool, "threshold": int}
        stop_on_error: If True (default), stop executing on first error. If False, continue and collect all results.

    Returns:
        JSON string with results for each action: {"results": [...], "completed": N, "total": N}
    """
    results = []
    for i, action in enumerate(actions):
        action_type = action.get("type")
        if not action_type:
            result = {"index": i, "type": None, "success": False, "error": "Missing 'type' field"}
            results.append(result)
            if stop_on_error:
                break
            continue

        try:
            if action_type == "click":
                pyautogui.click(x=action["x"], y=action["y"])
                msg = f"Clicked at ({action['x']}, {action['y']})"
            elif action_type == "move_mouse":
                pyautogui.moveTo(x=action["x"], y=action["y"])
                msg = f"Moved mouse to ({action['x']}, {action['y']})"
            elif action_type == "type_text":
                pyautogui.typewrite(action["text"])
                msg = f"Typed text: {action['text']}"
            elif action_type == "press_key":
                pyautogui.press(action["key"])
                msg = f"Pressed key: {action['key']}"
            elif action_type == "press_keys":
                keys = action["keys"]
                if isinstance(keys, str):
                    pyautogui.press(keys)
                elif isinstance(keys, list):
                    for item in keys:
                        if isinstance(item, str):
                            pyautogui.press(item)
                        elif isinstance(item, list):
                            pyautogui.hotkey(*item)
                msg = f"Pressed keys: {keys}"
            elif action_type == "key_down":
                pyautogui.keyDown(action["key"])
                msg = f"Key down: {action['key']}"
            elif action_type == "key_up":
                pyautogui.keyUp(action["key"])
                msg = f"Key up: {action['key']}"
            elif action_type == "mouse_down":
                pyautogui.mouseDown(button=action.get("button", "left"))
                msg = f"Mouse down: {action.get('button', 'left')}"
            elif action_type == "mouse_up":
                pyautogui.mouseUp(button=action.get("button", "left"))
                msg = f"Mouse up: {action.get('button', 'left')}"
            elif action_type == "wait":
                ms = action["milliseconds"]
                await asyncio.sleep(ms / 1000.0)
                msg = f"Waited {ms}ms"
            elif action_type == "set_clipboard":
                _set_clipboard(action["text"])
                msg = f"Clipboard set to: '{action['text'][:50]}'"
            elif action_type == "activate_window":
                result_msg = activate_window(
                    title_pattern=action["title_pattern"],
                    use_regex=action.get("use_regex", False),
                    threshold=action.get("threshold", 60),
                )
                msg = result_msg
            else:
                raise ValueError(f"Unknown action type: {action_type}")

            results.append({"index": i, "type": action_type, "success": True, "message": msg})
        except Exception as e:
            results.append({"index": i, "type": action_type, "success": False, "error": str(e)})
            if stop_on_error:
                break

    return json.dumps({"results": results, "completed": len(results), "total": len(actions)})


@mcp.tool()
def check_screen_changed(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    pixel_threshold: int = 30,
    min_region_area: int = 100,
) -> str:
    """Compare current screen against last stored screenshot. Returns lightweight JSON with change info, no images.
    Much faster than taking a full screenshot — use this to check if something changed before deciding to take a screenshot.
    First call stores a baseline; subsequent calls detect changes against it.

    Args:
        title_pattern: Window to capture. None = full screen.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold for window title.
        pixel_threshold: Per-pixel difference threshold (0-255). Higher = less sensitive. Default 30.
        min_region_area: Minimum area in pixels for a changed region to be reported. Default 100.

    Returns:
        JSON: {"changed": bool, "change_percent": float, "regions": [{"left", "top", "width", "height"}, ...], "first_check": bool}
    """
    try:
        pil_img, new_array, key, _ = _take_screenshot_as_array(title_pattern, use_regex, threshold)

        if key not in _last_screenshots:
            _last_screenshots[key] = new_array
            return json.dumps({
                "changed": False,
                "change_percent": 0.0,
                "regions": [],
                "first_check": True,
                "message": "Baseline screenshot stored. Call again to detect changes.",
            })

        old_array = _last_screenshots[key]
        changed, change_pct, regions = _compute_diff_regions(
            old_array, new_array, pixel_threshold, min_region_area
        )
        _last_screenshots[key] = new_array

        return json.dumps({
            "changed": changed,
            "change_percent": change_pct,
            "regions": regions,
            "first_check": False,
        })
    except Exception as e:
        log(f"Error in check_screen_changed: {str(e)}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def check_screen_changed_with_images(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    pixel_threshold: int = 30,
    min_region_area: int = 100,
    max_regions: int = 5,
    image_format: str = "png",
    quality: int = 80,
    color_mode: str = "color",
) -> list:
    """Compare current screen against last stored screenshot. Returns JSON summary + cropped images of changed regions.
    Use when you need to see what changed. For just checking if something changed, use check_screen_changed instead.
    Agent can compute click targets from region coordinates: absolute_x = region.left + relative_x.

    Args:
        title_pattern: Window to capture. None = full screen.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold for window title.
        pixel_threshold: Per-pixel difference threshold (0-255). Default 30.
        min_region_area: Minimum area for a changed region. Default 100.
        max_regions: Maximum number of region images to return. Default 5.
        image_format: Format for region images - "png", "webp", or "jpeg".
        quality: Compression quality 1-100 for webp/jpeg.
        color_mode: "color", "grayscale", or "bw".

    Returns:
        List of [JSON summary text, Image region 1, Image region 2, ...].
    """
    try:
        pil_img, new_array, key, _ = _take_screenshot_as_array(title_pattern, use_regex, threshold)

        if key not in _last_screenshots:
            _last_screenshots[key] = new_array
            return [json.dumps({
                "changed": False,
                "change_percent": 0.0,
                "regions": [],
                "first_check": True,
                "message": "Baseline screenshot stored. Call again to detect changes.",
            })]

        old_array = _last_screenshots[key]
        changed, change_pct, regions = _compute_diff_regions(
            old_array, new_array, pixel_threshold, min_region_area
        )
        _last_screenshots[key] = new_array

        # Truncate regions
        regions = regions[:max_regions]

        summary = json.dumps({
            "changed": changed,
            "change_percent": change_pct,
            "regions": regions,
            "first_check": False,
        })

        result = [summary]

        # Crop and add region images
        if changed:
            for region in regions:
                left = region["left"]
                top = region["top"]
                width = region["width"]
                height = region["height"]
                cropped = pil_img.crop((left, top, left + width, top + height))
                try:
                    img_bytes, fmt = _process_image_for_output(
                        cropped, image_format=image_format,
                        quality=quality, color_mode=color_mode,
                    )
                    result.append(Image(data=img_bytes, format=fmt))
                except Exception as e:
                    log(f"Error processing region image: {str(e)}")

        return result
    except Exception as e:
        log(f"Error in check_screen_changed_with_images: {str(e)}")
        return [json.dumps({"error": str(e)})]


@mcp.tool()
async def wait_for_screen_change(
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    timeout_ms: int = 5000,
    poll_interval_ms: int = 200,
    stable_ms: int = 500,
    pixel_threshold: int = 30,
    min_region_area: int = 100,
) -> str:
    """Wait until the screen changes, polling internally. Eliminates the need for the agent to poll with repeated screenshots.
    After detecting a change, waits for the screen to stabilize (stop changing) before returning.

    Args:
        title_pattern: Window to watch. None = full screen.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold.
        timeout_ms: Maximum wait time in milliseconds. Default 5000. Max 60000.
        poll_interval_ms: Polling interval in milliseconds. Default 200. Min 50.
        stable_ms: After detecting change, wait this long for screen to stabilize (stop changing). Handles animations/loading. Default 500.
        pixel_threshold: Per-pixel threshold (0-255). Default 30.
        min_region_area: Min region area. Default 100.

    Returns:
        JSON: {"changed": bool, "elapsed_ms": int, "change_percent": float, "regions": [...], "timed_out": bool}
    """
    try:
        # Guard inputs
        timeout_ms = min(max(timeout_ms, 100), 60000)
        poll_interval_ms = max(poll_interval_ms, 50)
        stable_ms = max(stable_ms, 0)

        # Take baseline
        _, baseline, key, _ = _take_screenshot_as_array(title_pattern, use_regex, threshold)
        start_time = time.monotonic()

        # Main polling loop: wait for change
        while True:
            elapsed = (time.monotonic() - start_time) * 1000
            if elapsed >= timeout_ms:
                _last_screenshots[key] = baseline
                return json.dumps({
                    "changed": False, "elapsed_ms": round(elapsed),
                    "change_percent": 0.0, "regions": [], "timed_out": True,
                })

            await asyncio.sleep(poll_interval_ms / 1000.0)

            _, current, _, _ = _take_screenshot_as_array(title_pattern, use_regex, threshold)
            changed, change_pct, regions = _compute_diff_regions(
                baseline, current, pixel_threshold, min_region_area
            )

            if changed:
                # Stability sub-loop: wait for screen to stop changing
                last_stable = current
                stable_start = time.monotonic()

                while True:
                    total_elapsed = (time.monotonic() - start_time) * 1000
                    if total_elapsed >= timeout_ms:
                        break

                    stable_elapsed = (time.monotonic() - stable_start) * 1000
                    if stable_elapsed >= stable_ms:
                        break  # Screen has been stable long enough

                    await asyncio.sleep(poll_interval_ms / 1000.0)

                    _, new_check, _, _ = _take_screenshot_as_array(title_pattern, use_regex, threshold)
                    still_changing, _, _ = _compute_diff_regions(
                        last_stable, new_check, pixel_threshold, min_region_area
                    )

                    if still_changing:
                        last_stable = new_check
                        stable_start = time.monotonic()

                # Final diff against original baseline
                _, final_pct, final_regions = _compute_diff_regions(
                    baseline, last_stable, pixel_threshold, min_region_area
                )
                _last_screenshots[key] = last_stable
                final_elapsed = (time.monotonic() - start_time) * 1000

                return json.dumps({
                    "changed": True, "elapsed_ms": round(final_elapsed),
                    "change_percent": final_pct, "regions": final_regions,
                    "timed_out": final_elapsed >= timeout_ms,
                })

    except Exception as e:
        log(f"Error in wait_for_screen_change: {str(e)}")
        return json.dumps({"error": str(e)})


@mcp.tool()
def find_text(
    text: str,
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    match_threshold: int = 70,
) -> str:
    """Find all occurrences of text on screen via OCR. Returns matches with absolute screen coordinates.
    Use this to locate text before clicking, especially when multiple matches may exist.
    Pair with click_screen(x, y) to click a specific match.

    Args:
        text: The text string to search for.
        title_pattern: Optional window to search in.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold for window title.
        match_threshold: Minimum fuzzy match score (0-100) for text matching. Default 70.

    Returns:
        JSON with all matches: {"matches": [{"text", "score", "center_x", "center_y", "abs_center_x", "abs_center_y", "left", "top", "width", "height"}, ...], "total": N}
        center_x/center_y are relative to the captured region. abs_center_x/abs_center_y are absolute screen coordinates ready for click_screen.
    """
    try:
        pil_img, np_array, key, window_obj = _take_screenshot_as_array(
            title_pattern, use_regex, threshold, activate=True
        )

        offset_x = 0
        offset_y = 0
        if window_obj:
            offset_x = max(window_obj.left, 0)
            offset_y = max(window_obj.top, 0)

        cv2_img = cv2.cvtColor(np_array, cv2.COLOR_RGB2BGR)

        # Use region-splitting OCR for full-screen captures
        if not window_obj:
            boxes, txts, scores = _ocr_with_regions(cv2_img)
        else:
            output = engine(cv2_img)
            boxes, txts, scores = output.boxes, output.txts, output.scores

        if not txts or len(txts) == 0:
            return json.dumps({"matches": [], "total": 0, "error": "No text found on screen via OCR"})

        search_len = len(text)
        matches = []
        for i, ocr_text in enumerate(txts):
            if len(ocr_text) < 3:
                continue

            fuzzy_score = fuzz.partial_ratio(text, ocr_text)
            if fuzzy_score >= match_threshold:
                ocr_len = len(ocr_text)
                length_ratio = min(search_len, ocr_len) / max(search_len, ocr_len)
                combined_score = round(fuzzy_score * 0.7 + (length_ratio * 100) * 0.3)

                box = boxes[i]
                # Relative coordinates (within the captured region)
                rel_center_x = int(sum(p[0] for p in box) / 4)
                rel_center_y = int(sum(p[1] for p in box) / 4)
                rel_left = int(min(p[0] for p in box))
                rel_top = int(min(p[1] for p in box))
                rel_right = int(max(p[0] for p in box))
                rel_bottom = int(max(p[1] for p in box))
                # Absolute screen coordinates (ready for click_screen)
                abs_center_x = rel_center_x + offset_x
                abs_center_y = rel_center_y + offset_y

                matches.append({
                    "text": ocr_text,
                    "score": combined_score,
                    "center_x": rel_center_x,
                    "center_y": rel_center_y,
                    "abs_center_x": abs_center_x,
                    "abs_center_y": abs_center_y,
                    "left": rel_left,
                    "top": rel_top,
                    "width": rel_right - rel_left,
                    "height": rel_bottom - rel_top,
                })

        # Sort by score descending, then top-to-bottom, then left-to-right
        matches.sort(key=lambda m: (-m["score"], m["center_y"], m["center_x"]))

        return json.dumps({"matches": matches, "total": len(matches)})

    except Exception as e:
        log(f"Error in find_text: {str(e)}")
        return json.dumps({"matches": [], "total": 0, "error": str(e)})


# Disabled: click_text is unreliable with multiple matches on screen.
# Use find_text + click_screen instead for precise control.
# @mcp.tool()
def click_text(
    text: str,
    title_pattern: str = None,
    use_regex: bool = False,
    threshold: int = 10,
    click_position: str = "center",
    button: str = "left",
    match_threshold: int = 70,
    occurrence: int = 1,
) -> str:
    """Find text on screen via OCR and click on it in one call. Saves 2-3 round-trips compared to take_screenshot_with_ocr + click_screen.

    Args:
        text: The text string to find and click on.
        title_pattern: Optional window to search in.
        use_regex: Regex mode for window matching.
        threshold: Fuzzy match threshold for window title.
        click_position: Where to click relative to found text - "center" (default), "left", or "right".
        button: Mouse button - "left" (default) or "right".
        match_threshold: Minimum fuzzy match score (0-100) for text matching. Default 70.
        occurrence: Which occurrence to click if multiple matches are found. 1 = first (top-most), 2 = second, etc. Default 1.

    Returns:
        Success message with matched text, score, and click coordinates, or error message.
    """
    try:
        pil_img, np_array, key, window_obj = _take_screenshot_as_array(
            title_pattern, use_regex, threshold, activate=True
        )

        # Determine window offset for absolute coordinates
        offset_x = 0
        offset_y = 0
        if window_obj:
            offset_x = max(window_obj.left, 0)
            offset_y = max(window_obj.top, 0)

        # Convert RGB to BGR for OCR (RapidOCR expects BGR like cv2.imread)
        cv2_img = cv2.cvtColor(np_array, cv2.COLOR_RGB2BGR)

        # Run OCR — use region-splitting for full-screen captures
        if not window_obj:
            boxes, txts, scores = _ocr_with_regions(cv2_img)
        else:
            output = engine(cv2_img)
            boxes, txts, scores = output.boxes, output.txts, output.scores

        if not txts or len(txts) == 0:
            return f"Error: No text found on screen via OCR"

        # Find ALL matches above threshold, with their original indices.
        # Scoring: fuzzy match score adjusted by length similarity — OCR texts
        # closer in length to the search text score higher. This prevents
        # "Edit" from matching a whole sentence that happens to contain "Edit".
        search_len = len(text)
        matches = []
        for i, ocr_text in enumerate(txts):
            # Skip OCR results shorter than 3 chars (too noisy for partial matching)
            if len(ocr_text) < 3:
                continue

            fuzzy_score = fuzz.partial_ratio(text, ocr_text)
            if fuzzy_score >= match_threshold:
                # Length similarity: 1.0 when lengths are equal, decreasing as they diverge.
                # ratio = min(len_a, len_b) / max(len_a, len_b)
                ocr_len = len(ocr_text)
                length_ratio = min(search_len, ocr_len) / max(search_len, ocr_len)

                # Combined score: 70% fuzzy match + 30% length similarity
                # Both components are 0-100, so combined_score is also 0-100.
                combined_score = round(fuzzy_score * 0.7 + (length_ratio * 100) * 0.3)

                box = boxes[i]
                center_y = sum(p[1] for p in box) / 4
                center_x = sum(p[0] for p in box) / 4
                matches.append({
                    "index": i,
                    "text": ocr_text,
                    "fuzzy_score": fuzzy_score,
                    "length_ratio": round(length_ratio, 2),
                    "score": combined_score,
                    "box": box,
                    "center_y": center_y,
                    "center_x": center_x,
                })

        if not matches:
            # Show best non-qualifying match for debugging
            try:
                best = process.extractOne(text, [t for t in txts if len(t) >= 3], scorer=fuzz.partial_ratio)
                score_info = f" (best: '{best[0]}' score={best[1]})" if best else ""
            except Exception:
                score_info = ""
            return f"Error: Text '{text}' not found with sufficient confidence (threshold={match_threshold}){score_info}. Found {len(txts)} OCR texts, {len([t for t in txts if len(t) >= 3])} with len>=3."

        # Sort by combined score descending, then top-to-bottom (Y), then left-to-right (X)
        matches.sort(key=lambda m: (-m["score"], m["center_y"], m["center_x"]))

        # Validate occurrence
        if occurrence < 1 or occurrence > len(matches):
            match_list = ", ".join(f"'{m['text']}' score={m['score']}" for m in matches)
            return f"Error: Requested occurrence {occurrence} but only found {len(matches)} match(es): [{match_list}]"

        chosen = matches[occurrence - 1]
        box = chosen["box"]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]

        # Compute click coordinates from bounding box
        if click_position == "left":
            cx = (box[0][0] + box[3][0]) / 2
            cy = (box[0][1] + box[3][1]) / 2
        elif click_position == "right":
            cx = (box[1][0] + box[2][0]) / 2
            cy = (box[1][1] + box[2][1]) / 2
        else:  # center
            cx = sum(p[0] for p in box) / 4
            cy = sum(p[1] for p in box) / 4

        click_x = int(cx + offset_x)
        click_y = int(cy + offset_y)

        # Click
        pyautogui.click(x=click_x, y=click_y, button=button)

        occurrence_info = f" (occurrence {occurrence}/{len(matches)})" if len(matches) > 1 else ""
        return f"Clicked '{chosen['text']}' (score: {chosen['score']}) at ({click_x}, {click_y}) with {button} button{occurrence_info}"

    except Exception as e:
        log(f"Error in click_text: {str(e)}")
        return f"Error in click_text: {str(e)}"


@mcp.tool()
def fill_text_field(
    x: int,
    y: int,
    text: str,
    clear_existing: bool = True,
    press_enter: bool = False,
) -> str:
    """Click on a text field, optionally clear it, paste text, and optionally press Enter.
    Single tool replacing 3-4 separate tool calls. Uses clipboard paste for unicode support and speed.

    Args:
        x: X coordinate of the text field to click.
        y: Y coordinate of the text field to click.
        text: Text to enter into the field.
        clear_existing: If True (default), select all existing text before pasting (Ctrl+A).
        press_enter: If True, press Enter after pasting. Useful for search boxes. Default False (for form fields).

    Returns:
        Success or error message.
    """
    try:
        # Click to focus the text field
        pyautogui.click(x=x, y=y)
        time.sleep(0.15)

        # Clear existing text if requested
        if clear_existing:
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.05)

        # Set clipboard and paste
        _set_clipboard(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)

        # Press enter if requested
        if press_enter:
            time.sleep(0.05)
            pyautogui.press("enter")

        result = f"Filled text field at ({x}, {y}) with '{text[:50]}{'...' if len(text) > 50 else ''}'"
        if press_enter:
            result += " and pressed Enter"
        return result

    except Exception as e:
        log(f"Error in fill_text_field: {str(e)}")
        return f"Error in fill_text_field: {str(e)}"


def main():
    """Main entry point for the MCP server."""
    pyautogui.FAILSAFE = True

    if WGC_AVAILABLE:
        log("Windows Graphics Capture API is available for enhanced window capture")
        # Check if any WGC patterns are configured
        wgc_patterns = os.getenv("COMPUTER_CONTROL_MCP_WGC_PATTERNS")
        if wgc_patterns:
            patterns = [p.strip() for p in wgc_patterns.split(",") if p.strip()]
            log(f"WGC patterns configured: {patterns}")
    else:
        log("Windows Graphics Capture API not available. Using standard capture methods.")

    try:
        # Run the server
        log("Computer Control MCP Server Started...")
        mcp.run()

    except KeyboardInterrupt:
        log("Server shutting down...")
    except Exception as e:
        log(f"Error: {str(e)}")


if __name__ == "__main__":
    main()