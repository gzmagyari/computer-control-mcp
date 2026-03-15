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
    # Test take_screenshot_with_ocr directly (this was PASS earlier)
    print("=== take_screenshot_with_ocr ===")
    r = await mcp.call_tool("take_screenshot_with_ocr", {})
    for item in r:
        if hasattr(item, "text"):
            text = item.text
            if text.startswith("{"):
                data = json.loads(text)
                texts = data.get("ocr_texts", [])
                print(f"ocr_texts: {len(texts)}")
                for t in texts[:5]:
                    print(f"  '{t.get('text','')[:60]}'")
            else:
                print(f"Text: {text[:200]}")

    # Test take_screenshot_full with OCR
    print("\n=== take_screenshot_full with OCR ===")
    r = await mcp.call_tool("take_screenshot_full", {
        "include_image": False, "include_ocr": True, "include_ui": False
    })
    for item in r:
        if hasattr(item, "text"):
            data = json.loads(item.text)
            ocr = data.get("ocr", {})
            print(f"ocr key present: {'ocr' in data}")
            print(f"ocr content: {json.dumps(ocr)[:300]}")

asyncio.run(main())
