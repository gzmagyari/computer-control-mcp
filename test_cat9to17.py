"""Categories 9-17: Clipboard, Text Interaction, Scrolling, Process, System, Change Detection, File Watch, Wait, Utilities"""
import json, os, asyncio, time

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
                        text = sub.text
            elif hasattr(item, "text"):
                text = item.text
            elif isinstance(item, dict) and "result" in item:
                text = item["result"]
        # Check for real errors
        if text:
            try:
                data = json.loads(text)
                if isinstance(data, dict) and data.get("error"):
                    results.append((name, "FAIL", str(data["error"])[:80]))
                    print(f"  FAIL: {name}: {str(data['error'])[:80]}")
                    return
            except:
                pass
        results.append((name, "PASS", ""))
        print(f"  PASS: {name}")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:80]))
        print(f"  FAIL: {name}: {str(e)[:80]}")

async def main():
    # === Category 9: Clipboard ===
    print("=== Category 9: Clipboard (2 tools) ===")
    await t("set_clipboard", "set_clipboard", {"text": "Linux clipboard test 123"})
    await t("get_clipboard", "get_clipboard", {})

    # === Category 10: Text Interaction ===
    print("\n=== Category 10: Text Interaction (3 tools) ===")
    await t("find_text", "find_text", {"text": "Thunar"})
    # click_text needs visible text
    await t("click_text", "click_text", {"text": "Applications"})
    await asyncio.sleep(0.5)
    # fill_text_field — click on Thunar address bar area and type
    await mcp.call_tool("activate_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.3)
    await t("fill_text_field", "fill_text_field", {
        "x": 500, "y": 217, "text": "/home/agent"
    })

    # === Category 11: Scrolling ===
    print("\n=== Category 11: Scrolling (1 tool) ===")
    await mcp.call_tool("activate_window", {"title_pattern": "Chrome"})
    await asyncio.sleep(0.3)
    await t("scroll (down)", "scroll", {"direction": "down", "amount": 3})
    await asyncio.sleep(0.3)
    await t("scroll (up)", "scroll", {"direction": "up", "amount": 3})

    # === Category 12: Process & App Management ===
    print("\n=== Category 12: Process & App Management (5 tools) ===")
    await t("launch_app (xterm)", "launch_app", {"command": ["xterm", "-title", "TestTerm"]})
    await asyncio.sleep(1)
    await t("is_app_running (xterm)", "is_app_running", {"app_name": "xterm"})
    await t("get_app_info (xterm)", "get_app_info", {"app_name": "xterm"})
    await t("list_processes", "list_processes", {})
    await t("kill_process (xterm)", "kill_process", {"process_name": "xterm"})
    await asyncio.sleep(0.5)

    # === Category 13: System & Screen Info ===
    print("\n=== Category 13: System & Screen Info (3+1 tools) ===")
    await t("get_system_info", "get_system_info", {})
    await t("get_screen_size", "get_screen_size", {})
    await t("get_monitors", "get_monitors", {})
    # get_cursor_position — Windows only
    await t("get_cursor_position (Windows only)", "get_cursor_position", {})

    # === Category 14: Change Detection ===
    print("\n=== Category 14: Change Detection (5 tools) ===")
    # Take baseline
    await t("check_screen_changed (baseline)", "check_screen_changed", {})
    # Make a change
    await mcp.call_tool("click_screen", {"x": 500, "y": 500})
    await asyncio.sleep(0.5)
    await t("check_screen_changed (after click)", "check_screen_changed", {})
    await t("check_screen_changed_full", "check_screen_changed_full", {})
    await t("check_screen_changed_with_images", "check_screen_changed_with_images", {})
    await t("check_ocr_changed (baseline)", "check_ocr_changed", {})
    await t("check_ui_automation_changed (baseline)", "check_ui_automation_changed", {})

    # === Category 15: File Watching ===
    print("\n=== Category 15: File Watching (4 tools) ===")
    os.makedirs("/tmp/linux-watch-test", exist_ok=True)
    await t("start_file_watch", "start_file_watch", {"paths": "/tmp/linux-watch-test"})
    # Create a file
    with open("/tmp/linux-watch-test/testfile.txt", "w") as f:
        f.write("hello linux")
    await asyncio.sleep(0.5)

    # Get the watch_id from start result
    r = await mcp.call_tool("start_file_watch", {"paths": "/tmp/linux-watch-test2"})
    wid = ""
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    try:
                        wid = json.loads(sub.text).get("watch_id", "")
                    except:
                        pass
        elif hasattr(item, "text"):
            try:
                wid = json.loads(item.text).get("watch_id", "")
            except:
                pass
    os.makedirs("/tmp/linux-watch-test2", exist_ok=True)
    with open("/tmp/linux-watch-test2/f.txt", "w") as f:
        f.write("x")
    await asyncio.sleep(0.5)
    if wid:
        await t("get_file_watch_events", "get_file_watch_events", {"watch_id": wid})
        await t("stop_file_watch", "stop_file_watch", {"watch_id": wid})
    else:
        print("  SKIP: no watch_id")

    await t("wait_for_file_change", "wait_for_file_change", {
        "paths": "/tmp/linux-watch-test", "timeout_ms": 100
    })

    # === Category 16: Wait & Sync ===
    print("\n=== Category 16: Wait & Sync (5+1 tools) ===")
    await t("wait_for_window (Thunar)", "wait_for_window", {
        "title_pattern": "Thunar", "timeout_ms": 3000
    })
    await t("wait_for_focused_element", "wait_for_focused_element", {
        "title_pattern": "Thunar", "timeout_ms": 3000
    })
    await t("wait_for_text (Thunar)", "wait_for_text", {
        "text": "Thunar", "timeout_ms": 5000
    })
    await t("wait_for_element", "wait_for_element", {
        "title_pattern": "Thunar", "role_filter": "push button", "timeout_ms": 3000
    })
    await t("wait_milliseconds", "wait_milliseconds", {"ms": 100})
    await t("wait_for_screen_change", "wait_for_screen_change", {"timeout_ms": 100})

    # === Category 17: Utilities ===
    print("\n=== Category 17: Utilities (3 tools) ===")
    await t("perform_actions", "perform_actions", {
        "actions": [
            {"tool": "get_mouse_position", "args": {}},
            {"tool": "get_screen_size", "args": {}}
        ]
    })
    await t("get_agent_guide", "get_agent_guide", {})
    await t("fill_file_dialog (no dialog)", "fill_file_dialog", {
        "file_path": "/tmp/test.txt", "timeout_ms": 500
    })

    # === Summary ===
    print(f"\n{'='*50}")
    print(f"=== FINAL RESULTS ===")
    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    print(f"PASSED: {passed}/{len(results)}")
    if failed:
        print(f"FAILED: {failed}")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"  - {name}: {detail}")

asyncio.run(main())
