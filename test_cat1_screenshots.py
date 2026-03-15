"""Category 1: Screenshot & Visual — 6 tools"""
import json, os, time, asyncio

dbus_dir = "/home/agent/.dbus/session-bus/"
if os.path.isdir(dbus_dir):
    for f in os.listdir(dbus_dir):
        path = os.path.join(dbus_dir, f)
        with open(path) as fh:
            for line in fh:
                if line.startswith("DBUS_SESSION_BUS_ADDRESS="):
                    val = line.strip().split("=", 1)[1].strip("\"'")
                    os.environ["DBUS_SESSION_BUS_ADDRESS"] = val
                    break
        break

os.environ["DISPLAY"] = ":1"

from computer_control_mcp.core import mcp

results = []

async def test(name, tool, args=None):
    try:
        r = await mcp.call_tool(tool, args or {})
        # Check for error in response
        text = ""
        for item in r:
            if hasattr(item, "text"):
                text += item.text
        if "error" in text.lower() and "Error" not in name:
            results.append((name, "FAIL", text[:150]))
            print(f"  FAIL: {name}: {text[:150]}")
        else:
            results.append((name, "PASS", text[:100]))
            print(f"  PASS: {name}")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:150]))
        print(f"  FAIL: {name}: {str(e)[:150]}")

async def main():
    print("=== Category 1: Screenshot & Visual (6 tools) ===\n")

    # 1. take_screenshot — full screen
    print("1. take_screenshot")
    await test("take_screenshot (full screen)", "take_screenshot", {
        "image_format": "webp", "quality": 50
    })

    # 2. take_screenshot — with title_pattern (window capture)
    await test("take_screenshot (window)", "take_screenshot", {
        "title_pattern": "Thunar", "image_format": "webp", "quality": 50
    })

    # 3. take_screenshot — with region
    await test("take_screenshot (region)", "take_screenshot", {
        "region": [0, 0, 500, 500], "image_format": "webp", "quality": 50
    })

    # 4. take_screenshot — grayscale
    await test("take_screenshot (grayscale)", "take_screenshot", {
        "image_format": "webp", "quality": 30, "color_mode": "grayscale"
    })

    # 5. take_screenshot — save to downloads
    await test("take_screenshot (save)", "take_screenshot", {
        "save_to_downloads": True, "image_format": "png"
    })

    # 6. take_screenshot_full — image + OCR + UI
    print("\n2. take_screenshot_full")
    await test("take_screenshot_full (image only)", "take_screenshot_full", {
        "image_format": "webp", "quality": 50,
        "include_ocr": False, "include_ui": False
    })

    await test("take_screenshot_full (image + OCR)", "take_screenshot_full", {
        "image_format": "webp", "quality": 50,
        "include_ocr": True, "include_ui": False
    })

    await test("take_screenshot_full (image + UI)", "take_screenshot_full", {
        "image_format": "webp", "quality": 50,
        "include_ocr": False, "include_ui": True, "ui_interactable_only": True
    })

    await test("take_screenshot_full (with title_pattern)", "take_screenshot_full", {
        "title_pattern": "Thunar",
        "image_format": "webp", "quality": 50,
        "include_ocr": False, "include_ui": False
    })

    # 7. take_screenshot_with_ocr
    print("\n3. take_screenshot_with_ocr")
    await test("take_screenshot_with_ocr (full)", "take_screenshot_with_ocr", {})

    await test("take_screenshot_with_ocr (filtered)", "take_screenshot_with_ocr", {
        "ocr_text_filter": "Thunar|Desktop"
    })

    await test("take_screenshot_with_ocr (window)", "take_screenshot_with_ocr", {
        "title_pattern": "Thunar"
    })

    # 8. take_screenshot_with_ui_automation
    print("\n4. take_screenshot_with_ui_automation")
    await test("take_screenshot_with_ui_automation (full)", "take_screenshot_with_ui_automation", {})

    await test("take_screenshot_with_ui_automation (window)", "take_screenshot_with_ui_automation", {
        "title_pattern": "Thunar"
    })

    await test("take_screenshot_with_ui_automation (filtered)", "take_screenshot_with_ui_automation", {
        "title_pattern": "Thunar", "role_filter": "push button", "interactable_only": True
    })

    # 9. capture_region_around
    print("\n5. capture_region_around")
    await test("capture_region_around (basic)", "capture_region_around", {
        "x": 500, "y": 500, "radius": 100, "image_format": "webp", "quality": 50
    })

    await test("capture_region_around (with rulers)", "capture_region_around", {
        "x": 500, "y": 500, "radius": 100,
        "show_rulers": True, "ruler_tick_interval": 25,
        "image_format": "webp", "quality": 50
    })

    await test("capture_region_around (with marker)", "capture_region_around", {
        "x": 500, "y": 500, "radius": 80,
        "mark_center": True, "show_rulers": True,
        "image_format": "webp", "quality": 50
    })

    await test("capture_region_around (no rulers)", "capture_region_around", {
        "x": 500, "y": 500, "radius": 80,
        "show_rulers": False, "mark_center": True,
        "image_format": "webp", "quality": 50
    })

    # 10. hover_and_capture
    print("\n6. hover_and_capture")
    await test("hover_and_capture (basic)", "hover_and_capture", {
        "x": 500, "y": 500, "wait_ms": 200, "radius": 100,
        "image_format": "webp", "quality": 50
    })

    await test("hover_and_capture (with OCR)", "hover_and_capture", {
        "x": 500, "y": 500, "wait_ms": 200, "radius": 100,
        "include_ocr": True, "image_format": "webp", "quality": 50
    })

    # Summary
    print(f"\n=== Results ===")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"PASSED: {passed}/{len(results)}")
    if failed:
        print(f"FAILED: {failed}")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"  - {name}: {detail}")

asyncio.run(main())
