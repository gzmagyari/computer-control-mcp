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
    r = await mcp.call_tool("take_screenshot_full", {
        "image_format": "webp", "quality": 50,
        "include_ocr": False, "include_ui": True, "ui_interactable_only": True
    })
    for item in r:
        if hasattr(item, "text"):
            data = json.loads(item.text)
            ui = data.get("ui_automation", {})
            print(f"available: {ui.get('available')}")
            print(f"error: {ui.get('error')}")
            print(f"element_count: {ui.get('element_count')}")
            apps = ui.get("applications", [])
            print(f"apps: {len(apps)}")
            for a in apps[:3]:
                print(f"  {a.get('app','')}: {len(a.get('elements',[]))} elements")

asyncio.run(main())
