"""Category 5: Deep UI Discovery — 6 tools"""
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
        # Check for actual error in response
        if text:
            try:
                data = json.loads(text)
                if data.get("error") or (data.get("success") is False):
                    results.append((name, "FAIL", text[:150]))
                    print(f"  FAIL: {name}: {text[:150]}")
                    return text, data
            except:
                pass
        results.append((name, "PASS", text[:100]))
        print(f"  PASS: {name}")
        try:
            return text, json.loads(text)
        except:
            return text, {}
    except Exception as e:
        results.append((name, "FAIL", str(e)[:120]))
        print(f"  FAIL: {name}: {str(e)[:120]}")
        return "", {}

async def main():
    print("=== Category 5: Deep UI Discovery (6 tools) ===\n")

    # 1. find_ui_elements — various filters
    print("1. find_ui_elements")

    _, data = await t("find_ui_elements (no filter)", "find_ui_elements", {"limit": 5})
    print(f"   Total: {data.get('total_count', 0)} elements")

    _, data = await t("find_ui_elements (title_pattern=Thunar)", "find_ui_elements", {
        "title_pattern": "Thunar", "limit": 5
    })
    print(f"   Thunar: {data.get('total_count', 0)} elements")

    _, data = await t("find_ui_elements (title_pattern=Chrome)", "find_ui_elements", {
        "title_pattern": "Chrome", "limit": 5
    })
    print(f"   Chrome: {data.get('total_count', 0)} elements")

    _, data = await t("find_ui_elements (role_filter=push button)", "find_ui_elements", {
        "title_pattern": "Thunar", "role_filter": "push button", "limit": 5
    })
    print(f"   Thunar buttons: {data.get('total_count', 0)}")
    for el in data.get("elements", [])[:3]:
        print(f"     [{el.get('role')}] {el.get('name','')}")

    _, data = await t("find_ui_elements (text_filter)", "find_ui_elements", {
        "title_pattern": "Thunar", "text_filter": "agent|home", "limit": 5
    })
    print(f"   Thunar text 'agent|home': {data.get('total_count', 0)}")

    _, data = await t("find_ui_elements (interactable_only)", "find_ui_elements", {
        "title_pattern": "Thunar", "interactable_only": True, "limit": 5
    })
    print(f"   Thunar interactable: {data.get('total_count', 0)}")

    _, data = await t("find_ui_elements (paging offset)", "find_ui_elements", {
        "title_pattern": "Thunar", "offset": 5, "limit": 3
    })
    print(f"   Thunar offset=5 limit=3: returned={data.get('returned', 0)}, has_more={data.get('has_more')}")

    # 2. get_focused_element
    print("\n2. get_focused_element")
    # Activate Thunar first so focus is there
    await mcp.call_tool("activate_window", {"title_pattern": "Thunar"})
    await asyncio.sleep(0.5)
    _, data = await t("get_focused_element", "get_focused_element", {
        "title_pattern": "Thunar"
    })
    if data.get("element"):
        el = data["element"]
        print(f"   Focused: [{el.get('role')}] {el.get('name','')}")

    # 3. get_element_at_point — use center of Thunar window
    print("\n3. get_element_at_point")
    # Get Thunar window bounds first
    r = await mcp.call_tool("get_active_window", {})
    win_data = {}
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    try:
                        win_data = json.loads(sub.text)
                    except:
                        pass
    cx = win_data.get("left", 300) + win_data.get("width", 600) // 2
    cy = win_data.get("top", 200) + win_data.get("height", 400) // 2
    _, data = await t(f"get_element_at_point ({cx},{cy})", "get_element_at_point", {
        "x": cx, "y": cy
    })
    if data.get("element"):
        el = data["element"]
        print(f"   Element: [{el.get('role')}] {el.get('name','')} app={el.get('application','')}")

    # Save a ref for traversal tests
    saved_ref = None
    r_els = await mcp.call_tool("find_ui_elements", {
        "title_pattern": "Thunar", "role_filter": "push button", "limit": 1
    })
    for item in r_els:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    try:
                        d = json.loads(sub.text)
                        if d.get("elements"):
                            saved_ref = d["elements"][0]["ref"]
                    except:
                        pass
        elif hasattr(item, "text"):
            try:
                d = json.loads(item.text)
                if d.get("elements"):
                    saved_ref = d["elements"][0]["ref"]
            except:
                pass

    if not saved_ref:
        print("\n  WARNING: No element ref found for traversal tests!")
    else:
        btn_name = ""
        for item in r_els:
            if isinstance(item, list):
                for sub in item:
                    if hasattr(sub, "text"):
                        try:
                            d = json.loads(sub.text)
                            if d.get("elements"):
                                btn_name = d["elements"][0].get("name","")
                        except:
                            pass
            elif hasattr(item, "text"):
                try:
                    d = json.loads(item.text)
                    if d.get("elements"):
                        btn_name = d["elements"][0].get("name","")
                except:
                    pass
        print(f"\n   Using ref for button: '{btn_name}'")

        # 4. get_element_details
        print("\n4. get_element_details")
        _, data = await t("get_element_details", "get_element_details", {
            "element_ref": saved_ref
        })
        if data.get("element"):
            el = data["element"]
            print(f"   Details: [{el.get('role')}] {el.get('name','')} interfaces={el.get('interfaces',[])}")

        # 5. get_element_children
        print("\n5. get_element_children")
        # Get parent first for a meaningful children test
        _, parent_data = await t("get_element_parent (for children test)", "get_element_parent", {
            "element_ref": saved_ref
        })
        if parent_data.get("element"):
            parent_ref = parent_data["element"]["ref"]
            _, children_data = await t("get_element_children", "get_element_children", {
                "element_ref": parent_ref
            })
            kids = children_data.get("children", [])
            print(f"   Children: {len(kids)}")
            for kid in kids[:5]:
                print(f"     [{kid.get('role')}] {kid.get('name','')}")

        # 6. get_element_parent
        print("\n6. get_element_parent")
        _, data = await t("get_element_parent", "get_element_parent", {
            "element_ref": saved_ref
        })
        if data.get("element"):
            el = data["element"]
            print(f"   Parent: [{el.get('role')}] {el.get('name','')}")

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
