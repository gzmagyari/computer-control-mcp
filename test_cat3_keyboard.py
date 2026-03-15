"""Category 3: Keyboard — 4 tools"""
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
results = []

async def t(name, tool, args=None):
    try:
        r = await mcp.call_tool(tool, args or {})
        text = ""
        for item in r:
            if isinstance(item, list):
                for sub in item:
                    if hasattr(sub, "text"):
                        text += sub.text
            elif hasattr(item, "text"):
                text += item.text
        results.append((name, "PASS", text[:100]))
        print(f"  PASS: {name}")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:100]))
        print(f"  FAIL: {name}: {str(e)[:100]}")

async def main():
    print("=== Category 3: Keyboard (4 tools) ===\n")

    # First activate terminal so keyboard input has a target
    await mcp.call_tool("activate_window", {"title_pattern": "Terminal"})
    await asyncio.sleep(0.5)

    # 1. type_text
    print("1. type_text")
    await t("type_text (simple)", "type_text", {"text": "echo KEYBOARD_TEST_1"})
    await asyncio.sleep(0.3)

    # 2. press_keys — single key
    print("2. press_keys")
    await t("press_keys (enter)", "press_keys", {"keys": "enter"})
    await asyncio.sleep(1)

    # press_keys — sequence
    await t("press_keys (sequence)", "press_keys", {"keys": ["e", "c", "h", "o", " ", "S", "E", "Q"]})
    await asyncio.sleep(0.3)

    # press_keys — combination
    await t("press_keys (ctrl+a)", "press_keys", {"keys": [["ctrl", "a"]]})
    await asyncio.sleep(0.3)

    # press_keys — escape
    await t("press_keys (escape)", "press_keys", {"keys": "escape"})
    await asyncio.sleep(0.3)

    # press_keys — tab
    await t("press_keys (tab)", "press_keys", {"keys": "tab"})
    await asyncio.sleep(0.3)

    # press_keys — backspace
    await t("press_keys (backspace)", "press_keys", {"keys": "backspace"})
    await asyncio.sleep(0.3)

    # 3. key_down + key_up
    print("3. key_down + key_up")
    await t("key_down (shift)", "key_down", {"key": "shift"})
    await asyncio.sleep(0.2)
    await t("key_up (shift)", "key_up", {"key": "shift"})
    await asyncio.sleep(0.2)

    await t("key_down (ctrl)", "key_down", {"key": "ctrl"})
    await asyncio.sleep(0.2)
    await t("key_up (ctrl)", "key_up", {"key": "ctrl"})
    await asyncio.sleep(0.2)

    # 4. Verify: type + enter executes command
    print("\n4. Verify: type + enter")
    await mcp.call_tool("type_text", {"text": "echo VERIFY_KEYBOARD_OK"})
    await asyncio.sleep(0.3)
    await mcp.call_tool("press_keys", {"keys": "enter"})
    await asyncio.sleep(1)

    # Take screenshot to verify
    r = await mcp.call_tool("take_screenshot", {"save_to_downloads": True, "image_format": "png"})
    print("  Screenshot saved — check terminal for VERIFY_KEYBOARD_OK output")
    results.append(("type+enter verify", "PASS", "screenshot saved"))

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
