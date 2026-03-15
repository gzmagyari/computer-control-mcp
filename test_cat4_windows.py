"""Category 4: Window Management — 10 tools"""
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
            elif isinstance(item, dict):
                text += json.dumps(item)[:200]
            elif hasattr(item, "text"):
                text += item.text
        results.append((name, "PASS", text[:120]))
        print(f"  PASS: {name}")
        return text
    except Exception as e:
        results.append((name, "FAIL", str(e)[:120]))
        print(f"  FAIL: {name}: {str(e)[:120]}")
        return ""

async def main():
    print("=== Category 4: Window Management (10 tools) ===\n")

    # 1. list_windows
    print("1. list_windows")
    text = await t("list_windows", "list_windows", {})
    if text:
        try:
            data = json.loads(text)
            windows = data if isinstance(data, list) else data.get("windows", [])
            print(f"   Found {len(windows)} windows")
            for w in windows[:5]:
                title = w.get("title", "")
                if title:
                    print(f"     '{title}'")
        except:
            pass

    # 2. get_active_window
    print("2. get_active_window")
    text = await t("get_active_window", "get_active_window", {})
    if text:
        try:
            data = json.loads(text)
            print(f"   Active: '{data.get('title', '')}' at ({data.get('left')},{data.get('top')})")
        except:
            pass

    # 3. activate_window
    print("3. activate_window")
    await t("activate_window (Thunar)", "activate_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)

    # Verify it's now active
    r = await mcp.call_tool("get_active_window", {})
    active_text = ""
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    active_text += sub.text
        elif hasattr(item, "text"):
            active_text += item.text
    if "Thunar" in active_text or "thunar" in active_text.lower():
        print(f"   Verified: Thunar is active")
    else:
        print(f"   Active window: {active_text[:80]}")

    await t("activate_window (Chrome)", "activate_window", {"title_pattern": "Chrome"})
    await asyncio.sleep(0.5)

    # 4. move_window
    print("4. move_window")
    await t("move_window (Thunar to 100,100)", "move_window", {
        "title_pattern": "Thunar", "x": 100, "y": 100
    })
    await asyncio.sleep(0.3)

    # 5. resize_window
    print("5. resize_window")
    await t("resize_window (Thunar 800x600)", "resize_window", {
        "title_pattern": "Thunar", "width": 800, "height": 600
    })
    await asyncio.sleep(0.3)

    # 6. maximize_window
    print("6. maximize_window")
    await t("maximize_window (Thunar)", "maximize_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)

    # 7. restore_window
    print("7. restore_window")
    await t("restore_window (Thunar)", "restore_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)

    # 8. minimize_window
    print("8. minimize_window")
    await t("minimize_window (Thunar)", "minimize_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)

    # 9. snap_window — restore first
    await mcp.call_tool("restore_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)
    print("9. snap_window")
    await t("snap_window (Thunar left)", "snap_window", {
        "title_pattern": "Thunar", "position": "left"
    })
    await asyncio.sleep(0.5)

    # 10. close_window — open a throwaway window first
    print("10. close_window")
    os.system("DISPLAY=:1 xterm -title 'CloseMe' &")
    await asyncio.sleep(1)
    await t("close_window (CloseMe)", "close_window", {"title_pattern": "CloseMe"})
    await asyncio.sleep(0.5)

    # Verify it's gone
    r = await mcp.call_tool("list_windows", {})
    list_text = ""
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    list_text += sub.text
        elif hasattr(item, "text"):
            list_text += item.text
    if "CloseMe" not in list_text:
        print(f"   Verified: CloseMe window is gone")
        results.append(("close_window verify", "PASS", "window closed"))
    else:
        print(f"   CloseMe still in window list!")
        results.append(("close_window verify", "FAIL", "window still exists"))

    # Restore Thunar to normal
    await mcp.call_tool("restore_window", {"title_pattern": "Thunar"})

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
