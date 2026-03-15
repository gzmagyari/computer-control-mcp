import json, os, asyncio

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

async def test_full(desc, args):
    print(f"\n--- {desc} ---")
    r = await mcp.call_tool("take_screenshot_full", args)
    has_image = False
    has_text = False
    for item in r:
        if hasattr(item, "data"):
            has_image = True
            print(f"  IMAGE: format={getattr(item, 'format', '?')}, size={len(item.data)} bytes")
        elif hasattr(item, "text"):
            has_text = True
            data = json.loads(item.text)

            # Check OCR
            ocr = data.get("ocr")
            if ocr:
                texts = ocr.get("ocr_texts", [])
                print(f"  OCR: {len(texts)} text regions found")
                for t in texts[:3]:
                    print(f"    '{t.get('text','')[:50]}' at ({t.get('abs_center_x')},{t.get('abs_center_y')})")
            else:
                print(f"  OCR: not included")

            # Check UI
            ui = data.get("ui_automation")
            if ui:
                print(f"  UI: available={ui.get('available')}, elements={ui.get('element_count',0)}, error={ui.get('error')}")
                for a in ui.get("applications", [])[:3]:
                    app_name = a.get("app", "(unnamed)")
                    els = a.get("elements", [])
                    print(f"    App '{app_name}': {len(els)} elements")
                    for el in els[:3]:
                        print(f"      [{el.get('role')}] {el.get('name','')}")
            else:
                print(f"  UI: not included")

            # Check scale info
            sf = data.get("scale_factor")
            ss = data.get("screenshot_size", {})
            print(f"  Scale: factor={sf}, size={ss.get('width')}x{ss.get('height')}")

    if not has_image:
        print(f"  WARNING: No image returned!")
    if not has_text:
        print(f"  WARNING: No text/JSON returned!")

async def main():
    print("=== take_screenshot_full Detailed Test ===")

    # Test 1: All 3 layers, full screen
    await test_full("Full screen: image + OCR + UI", {
        "image_format": "webp", "quality": 50,
        "include_image": True, "include_ocr": True, "include_ui": True
    })

    # Test 2: All 3 layers, specific window (Thunar)
    await test_full("Window 'Thunar': image + OCR + UI", {
        "title_pattern": "Thunar",
        "image_format": "webp", "quality": 50,
        "include_image": True, "include_ocr": True, "include_ui": True
    })

    # Test 3: Image only, specific window
    await test_full("Window 'Thunar': image only", {
        "title_pattern": "Thunar",
        "image_format": "webp", "quality": 30,
        "include_image": True, "include_ocr": False, "include_ui": False
    })

    # Test 4: OCR only, no image
    await test_full("Full screen: OCR only (no image)", {
        "include_image": False, "include_ocr": True, "include_ui": False
    })

    # Test 5: UI only, no image
    await test_full("Full screen: UI only (no image)", {
        "include_image": False, "include_ocr": False, "include_ui": True,
        "ui_interactable_only": True
    })

    # Test 6: OCR with filter on specific window
    await test_full("Window 'Thunar': OCR filtered for 'agent'", {
        "title_pattern": "Thunar",
        "include_image": True, "include_ocr": True, "include_ui": False,
        "ocr_text_filter": "agent|home",
        "image_format": "webp", "quality": 50
    })

asyncio.run(main())
