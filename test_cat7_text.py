"""Category 7: Text Manipulation — 7 tools"""
import json, os, time

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
    find_ui_elements, set_element_text, select_text_range, select_text_by_search,
    get_text_selection, get_text_caret_offset, set_text_caret_offset,
    get_text_at_offset, get_text_bounds, activate_window
)
results = []

def t(name, fn):
    try:
        r = fn()
        data = json.loads(r) if isinstance(r, str) else r
        success = data.get("success")
        if success is False:
            results.append((name, "FAIL", data.get("error", "")[:100]))
            print(f"  FAIL: {name}: {data.get('error', '')[:100]}")
        else:
            results.append((name, "PASS", ""))
            print(f"  PASS: {name}")
        return data
    except Exception as e:
        results.append((name, "FAIL", str(e)[:100]))
        print(f"  FAIL: {name}: {str(e)[:100]}")
        return {}

print("=== Category 7: Text Manipulation (7 tools) ===\n")

# Setup: use Thunar's address bar as text element
activate_window(title_pattern="Thunar")
time.sleep(0.5)

# Set known text first
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="text", limit=5))
text_els = [e for e in r.get("elements", []) if "text" in e.get("interfaces", [])]
if not text_els:
    # Try entry role
    r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="entry", limit=5))
    text_els = r.get("elements", [])

if not text_els:
    print("ERROR: No text element found in Thunar!")
    print(f"  Total elements: {r.get('total_count', 0)}")
    exit(1)

ref = text_els[0]["ref"]
print(f"Using: [{text_els[0].get('role')}] interfaces={text_els[0].get('interfaces',[])} text='{text_els[0].get('text','')}'")

# Set a known value
set_element_text(element_ref=ref, text="/home/agent/test")
time.sleep(0.5)

# Re-find the element (text change may invalidate ref)
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="text", limit=5))
text_els = [e for e in r.get("elements", []) if "text" in e.get("interfaces", [])]
if text_els:
    ref = text_els[0]["ref"]
    current_text = text_els[0].get("text", "")
    print(f"Current text: '{current_text}'\n")

# 1. select_text_range
print("1. select_text_range")
data = t("select_text_range(0, 5)", lambda: select_text_range(element_ref=ref, start=0, end=5))
if data.get("success"):
    print(f"   Selected: '{data.get('text', '')}'")

# 2. get_text_selection
print("2. get_text_selection")
data = t("get_text_selection", lambda: get_text_selection(element_ref=ref))
if data.get("success"):
    sels = data.get("selections", [])
    print(f"   Selections: {len(sels)}")
    for s in sels:
        print(f"     [{s.get('start')}-{s.get('end')}] '{s.get('text', '')}'")

# 3. select_text_by_search
print("3. select_text_by_search")
data = t("select_text_by_search('agent')", lambda: select_text_by_search(element_ref=ref, search_text="agent"))
if data.get("success"):
    print(f"   Found at [{data.get('start')}-{data.get('end')}]")

# Verify with get_text_selection
data = t("get_text_selection (verify search)", lambda: get_text_selection(element_ref=ref))
if data.get("success") and data.get("selections"):
    print(f"   Selected: '{data['selections'][0].get('text', '')}'")

# 4. get_text_caret_offset
print("4. get_text_caret_offset")
data = t("get_text_caret_offset", lambda: get_text_caret_offset(element_ref=ref))
if data.get("success"):
    print(f"   Offset: {data.get('offset')}, text_length: {data.get('text_length')}")

# 5. set_text_caret_offset
print("5. set_text_caret_offset")
data = t("set_text_caret_offset(3)", lambda: set_text_caret_offset(element_ref=ref, offset=3))

# Verify
data = t("get_text_caret_offset (verify)", lambda: get_text_caret_offset(element_ref=ref))
if data.get("success"):
    print(f"   Offset after set(3): {data.get('offset')}")

# 6. get_text_at_offset
print("6. get_text_at_offset")
for unit in ["char", "word", "line"]:
    data = t(f"get_text_at_offset(0, '{unit}')", lambda u=unit: get_text_at_offset(element_ref=ref, offset=0, unit=u))
    if data.get("success"):
        print(f"   {unit}: '{data.get('text', '')}'")

# 7. get_text_bounds
print("7. get_text_bounds")
data = t("get_text_bounds(0, 5)", lambda: get_text_bounds(element_ref=ref, start=0, end=5))
if data.get("success"):
    bounds = data.get("bounds", [])
    print(f"   Bounds: {len(bounds)} rects")
    for b in bounds[:3]:
        print(f"     ({b.get('x')},{b.get('y')}) {b.get('width')}x{b.get('height')}")

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
