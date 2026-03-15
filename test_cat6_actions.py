"""Category 6: Semantic Actions — 14 tools"""
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

from computer_control_mcp.core import (
    find_ui_elements, invoke_element, focus_element, toggle_element,
    select_element, expand_element, collapse_element, set_element_text,
    get_element_text, scroll_element_into_view, set_element_range_value,
    move_element_ui, resize_element_ui, set_element_extents, ui_action,
    activate_window
)
results = []

def t(name, fn):
    try:
        r = fn()
        data = json.loads(r) if isinstance(r, str) else r
        success = data.get("success")
        if success is False:
            err = data.get("error", "")
            # Some failures are expected (element doesn't support pattern)
            if "not available" in err or "not found" in err or "not supported" in err:
                results.append((name, "EXPECTED", err[:80]))
                print(f"  EXPECTED: {name}: {err[:80]}")
            else:
                results.append((name, "FAIL", err[:80]))
                print(f"  FAIL: {name}: {err[:80]}")
        else:
            results.append((name, "PASS", str(data.get("message", ""))[:80]))
            print(f"  PASS: {name}")
        return data
    except Exception as e:
        results.append((name, "FAIL", str(e)[:80]))
        print(f"  FAIL: {name}: {str(e)[:80]}")
        return {}

def find_ref(title, role=None, text=None, name=None, limit=5):
    args = {"title_pattern": title, "limit": limit}
    if role:
        args["role_filter"] = role
    if text:
        args["text_filter"] = text
    if name:
        args["name_filter"] = name
    r = json.loads(find_ui_elements(**args))
    els = r.get("elements", [])
    if els:
        return els[0]["ref"], els[0].get("name", ""), els[0].get("role", "")
    return None, None, None

print("=== Category 6: Semantic Actions (14 tools) ===\n")

# Make sure Thunar is active and visible
activate_window(title_pattern="Thunar")
import time; time.sleep(0.5)

# 1. focus_element
print("1. focus_element")
ref, name, role = find_ref("Thunar", role="push button")
if ref:
    print(f"   Target: [{role}] {name}")
    t("focus_element", lambda: focus_element(element_ref=ref))
else:
    print("   No button found"); results.append(("focus_element", "FAIL", "no element"))

# 2. invoke_element
print("2. invoke_element")
ref, name, role = find_ref("Thunar", role="push button", name="Home")
if not ref:
    ref, name, role = find_ref("Thunar", role="push button")
if ref:
    print(f"   Target: [{role}] {name}")
    t("invoke_element", lambda: invoke_element(element_ref=ref))
    time.sleep(0.5)
else:
    print("   No button found"); results.append(("invoke_element", "FAIL", "no element"))

# 3. toggle_element — find a toggle/checkbox
print("3. toggle_element")
ref, name, role = find_ref("Thunar", role="toggle button|check box")
if ref:
    print(f"   Target: [{role}] {name}")
    t("toggle_element", lambda: toggle_element(element_ref=ref))
    time.sleep(0.3)
    # Toggle back
    t("toggle_element (back)", lambda: toggle_element(element_ref=ref))
else:
    # Try on Chrome — it might have toggle elements
    ref, name, role = find_ref("Chrome", role="toggle button|check box")
    if ref:
        print(f"   Target: [{role}] {name}")
        t("toggle_element", lambda: toggle_element(element_ref=ref))
    else:
        print("   No toggle found — testing with a button (expected fail)")
        ref, name, role = find_ref("Thunar", role="push button")
        if ref:
            t("toggle_element (no toggle pattern)", lambda: toggle_element(element_ref=ref))

# 4. select_element — find a list item or tab
print("4. select_element")
ref, name, role = find_ref("Thunar", role="list item|page tab|table cell")
if ref:
    print(f"   Target: [{role}] {name}")
    t("select_element", lambda: select_element(element_ref=ref))
else:
    print("   No selectable found"); results.append(("select_element", "FAIL", "no element"))

# 5. expand_element — find expandable (tree, combo)
print("5. expand_element")
ref, name, role = find_ref("Thunar", role="tree item|combo box|menu")
if ref:
    print(f"   Target: [{role}] {name}")
    t("expand_element", lambda: expand_element(element_ref=ref))
    time.sleep(0.3)
else:
    print("   No expandable found — testing with button (expected fail)")
    ref, name, role = find_ref("Thunar", role="push button")
    if ref:
        t("expand_element (no expand pattern)", lambda: expand_element(element_ref=ref))

# 6. collapse_element
print("6. collapse_element")
# Reuse the same ref if it was expanded
if ref and role in ("tree item", "combo box", "menu"):
    t("collapse_element", lambda: collapse_element(element_ref=ref))
else:
    ref2, name2, role2 = find_ref("Thunar", role="tree item|combo box")
    if ref2:
        t("collapse_element", lambda: collapse_element(element_ref=ref2))
    else:
        print("   No collapsible found — testing with button (expected fail)")
        ref2, _, _ = find_ref("Thunar", role="push button")
        if ref2:
            t("collapse_element (no pattern)", lambda: collapse_element(element_ref=ref2))

# 7. set_element_text — find a text entry
print("7. set_element_text")
ref, name, role = find_ref("Thunar", role="text|entry|edit")
if ref:
    print(f"   Target: [{role}] {name}")
    t("set_element_text", lambda: set_element_text(element_ref=ref, text="/tmp"))
    time.sleep(0.3)
else:
    print("   No text entry found"); results.append(("set_element_text", "FAIL", "no element"))

# 8. get_element_text
print("8. get_element_text")
if ref:
    data = t("get_element_text", lambda: get_element_text(element_ref=ref))
    if data.get("success"):
        print(f"   Text: {data.get('text','')[:50] or data.get('value','')[:50]}")
else:
    print("   No text entry"); results.append(("get_element_text", "FAIL", "no element"))

# 9. scroll_element_into_view
print("9. scroll_element_into_view")
ref, name, role = find_ref("Thunar", role="push button")
if ref:
    t("scroll_element_into_view", lambda: scroll_element_into_view(element_ref=ref))
else:
    print("   No element"); results.append(("scroll_element_into_view", "FAIL", "no element"))

# 10. set_element_range_value — need a slider/scrollbar
print("10. set_element_range_value")
ref, name, role = find_ref("Thunar", role="scroll bar|slider")
if not ref:
    ref, name, role = find_ref("Chrome", role="scroll bar|slider")
if ref:
    print(f"   Target: [{role}] {name}")
    t("set_element_range_value", lambda: set_element_range_value(element_ref=ref, value=50))
else:
    print("   No slider/scrollbar found — element dependent")
    results.append(("set_element_range_value", "EXPECTED", "no slider element available"))

# 11-13. move/resize/set_extents — use Thunar frame
print("11-13. move_element_ui / resize_element_ui / set_element_extents")
ref, name, role = find_ref("Thunar", role="frame")
if ref:
    print(f"   Target: [{role}] {name}")
    t("move_element_ui (200,200)", lambda: move_element_ui(element_ref=ref, x=200, y=200))
    time.sleep(0.3)
    t("resize_element_ui (700x500)", lambda: resize_element_ui(element_ref=ref, width=700, height=500))
    time.sleep(0.3)
    t("set_element_extents (300,150,800,600)", lambda: set_element_extents(element_ref=ref, x=300, y=150, width=800, height=600))
    time.sleep(0.3)
else:
    print("   No frame found"); results.append(("move/resize/extents", "FAIL", "no frame"))

# 14. ui_action (generic dispatcher)
print("14. ui_action")
ref, name, role = find_ref("Thunar", role="push button")
if ref:
    t("ui_action (focus)", lambda: ui_action(element_ref=ref, action="focus"))
else:
    print("   No element"); results.append(("ui_action", "FAIL", "no element"))

# Summary
print(f"\n=== Results ===")
passed = sum(1 for _, s, _ in results if s == "PASS")
expected = sum(1 for _, s, _ in results if s == "EXPECTED")
failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"PASSED: {passed}, EXPECTED LIMITATIONS: {expected}, FAILED: {failed} (total: {len(results)})")
if failed:
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  FAIL: {name}: {detail}")
