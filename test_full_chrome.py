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

async def main():
    print("=== take_screenshot_full on Chrome window ===\n")

    # All 3 layers on Chrome
    r = await mcp.call_tool("take_screenshot_full", {
        "title_pattern": "Chrome",
        "image_format": "webp", "quality": 50,
        "include_image": True, "include_ocr": True, "include_ui": True,
        "ui_interactable_only": True
    })

    has_image = False
    for item in r:
        if hasattr(item, "data"):
            has_image = True
            print(f"IMAGE: {len(item.data)} bytes")
        elif hasattr(item, "text"):
            data = json.loads(item.text)

            # Scale
            sf = data.get("scale_factor")
            ss = data.get("screenshot_size", {})
            print(f"Scale: factor={sf}, size={ss.get('width')}x{ss.get('height')}")

            # OCR
            ocr = data.get("ocr", {})
            ocr_els = ocr.get("elements", [])
            print(f"\nOCR: {len(ocr_els)} text regions")
            for t in ocr_els[:5]:
                print(f"  '{t.get('text','')[:60]}' conf={t.get('confidence',0):.2f} at ({t.get('abs_center_x')},{t.get('abs_center_y')})")

            # UI
            ui = data.get("ui_automation", {})
            print(f"\nUI: available={ui.get('available')}, elements={ui.get('element_count',0)}, error={ui.get('error')}")
            for a in ui.get("applications", []):
                app_name = a.get("app", "(unnamed)")
                els = a.get("elements", [])
                print(f"  App '{app_name}': {len(els)} elements")
                roles = {}
                for el in els:
                    role = el.get("role", "?")
                    roles[role] = roles.get(role, 0) + 1
                for role, count in sorted(roles.items(), key=lambda x: -x[1])[:8]:
                    print(f"    {role}: {count}")

    if not has_image:
        print("WARNING: No image returned!")

asyncio.run(main())
