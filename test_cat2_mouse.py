"""Category 2: Mouse — 6 tools"""
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

async def test(name, tool, args=None):
    try:
        r = await mcp.call_tool(tool, args or {})
        text = ""
        for item in r:
            if hasattr(item, "text"):
                text += item.text
        results.append((name, "PASS", text[:120]))
        print(f"  PASS: {name} -> {text[:100]}")
    except Exception as e:
        results.append((name, "FAIL", str(e)[:120]))
        print(f"  FAIL: {name}: {str(e)[:120]}")

async def main():
    print("=== Category 2: Mouse (6 tools) ===\n")

    # 1. move_mouse
    print("1. move_mouse")
    await test("move_mouse (500,500)", "move_mouse", {"x": 500, "y": 500})
    await asyncio.sleep(0.3)

    # 2. get_mouse_position
    print("2. get_mouse_position")
    await test("get_mouse_position", "get_mouse_position", {})

    # 3. click_screen — single click
    print("3. click_screen")
    await test("click_screen (single)", "click_screen", {"x": 500, "y": 500})
    await asyncio.sleep(0.3)

    # click_screen — right click
    await test("click_screen (right)", "click_screen", {"x": 500, "y": 500, "button": "right"})
    await asyncio.sleep(0.3)

    # click_screen — double click
    await test("click_screen (double)", "click_screen", {"x": 500, "y": 500, "num_clicks": 2})
    await asyncio.sleep(0.3)

    # 4. drag_mouse
    print("4. drag_mouse")
    await test("drag_mouse", "drag_mouse", {
        "from_x": 200, "from_y": 200, "to_x": 400, "to_y": 400, "duration": 0.5
    })
    await asyncio.sleep(0.5)

    # 5. mouse_down + mouse_up
    print("5. mouse_down + mouse_up")
    await test("mouse_down (left)", "mouse_down", {"button": "left"})
    await asyncio.sleep(0.2)
    await test("mouse_up (left)", "mouse_up", {"button": "left"})
    await asyncio.sleep(0.2)

    # Verify mouse position after move
    print("\n6. Verify: move then check position")
    await mcp.call_tool("move_mouse", {"x": 960, "y": 540})
    await asyncio.sleep(0.3)
    r = await mcp.call_tool("get_mouse_position", {})
    pos_text = ""
    for item in r:
        if hasattr(item, "text"):
            pos_text = item.text
    print(f"  Position after move(960,540): {pos_text}")
    if "960" in pos_text and "540" in pos_text:
        results.append(("move+verify position", "PASS", pos_text))
        print(f"  PASS: position matches")
    else:
        results.append(("move+verify position", "FAIL", pos_text))
        print(f"  FAIL: position mismatch")

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
