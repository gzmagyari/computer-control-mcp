"""Category 8: Table, Scroll & Advanced — 9 tools"""
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
    find_ui_elements, get_table_data, scroll_element_container,
    get_scroll_info, get_element_views, set_element_view,
    realize_element, get_drag_info, get_hyperlinks, activate_hyperlink,
    activate_window
)
results = []

def t(name, fn):
    try:
        r = fn()
        data = json.loads(r) if isinstance(r, str) else r
        success = data.get("success")
        err = data.get("error", "")
        if success is False:
            if "not available" in err or "not supported" in err or "Windows" in err:
                results.append((name, "EXPECTED", err[:80]))
                print(f"  EXPECTED: {name}: {err[:80]}")
            else:
                results.append((name, "FAIL", err[:80]))
                print(f"  FAIL: {name}: {err[:80]}")
        elif "error" in data and data["error"]:
            results.append((name, "FAIL", str(data["error"])[:80]))
            print(f"  FAIL: {name}: {str(data['error'])[:80]}")
        else:
            results.append((name, "PASS", ""))
            print(f"  PASS: {name}")
        return data
    except Exception as e:
        results.append((name, "FAIL", str(e)[:80]))
        print(f"  FAIL: {name}: {str(e)[:80]}")
        return {}

print("=== Category 8: Table, Scroll & Advanced (9 tools) ===\n")

activate_window(title_pattern="Thunar")
time.sleep(0.5)

# 1. get_table_data — Thunar has a table for file listing
print("1. get_table_data")
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="table", limit=3))
print(f"   Tables found: {r.get('total_count', 0)}")
if r.get("elements"):
    ref = r["elements"][0]["ref"]
    data = t("get_table_data (Thunar file list)", lambda: get_table_data(element_ref=ref, max_rows=5))
    if data.get("success") is not False:
        print(f"   Rows: {data.get('row_count')}, Cols: {data.get('column_count')}, Headers: {data.get('headers', [])}")
        for row in data.get("rows", [])[:3]:
            vals = [c.get("value", c.get("name", ""))[:20] for c in row]
            print(f"     {vals}")
else:
    print("   No table found in Thunar")
    results.append(("get_table_data", "FAIL", "no table element"))

# 2. scroll_element_container
print("\n2. scroll_element_container")
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="scroll pane|panel", limit=5))
scroll_ref = None
for el in r.get("elements", []):
    if "scroll" in el.get("role", "").lower() or "pane" in el.get("role", ""):
        scroll_ref = el["ref"]
        print(f"   Target: [{el.get('role')}] {el.get('name','')}")
        break

if scroll_ref:
    data = t("scroll_element_container (down)", lambda: scroll_element_container(
        element_ref=scroll_ref, direction="down", amount=1, unit="page"
    ))
else:
    print("   No scrollable container found — trying Chrome")
    r2 = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="scroll pane|document web|section", limit=5))
    for el in r2.get("elements", []):
        scroll_ref = el["ref"]
        print(f"   Chrome target: [{el.get('role')}] {el.get('name','')}")
        break
    if scroll_ref:
        data = t("scroll_element_container (Chrome down)", lambda: scroll_element_container(
            element_ref=scroll_ref, direction="down", amount=1, unit="page"
        ))
    else:
        results.append(("scroll_element_container", "FAIL", "no scrollable found"))
        print("   No scrollable found")

# 3. get_scroll_info
print("\n3. get_scroll_info")
if scroll_ref:
    data = t("get_scroll_info", lambda: get_scroll_info(element_ref=scroll_ref))
    if data.get("success") is not False:
        print(f"   h_scrollable={data.get('horizontally_scrollable')}, v_scrollable={data.get('vertically_scrollable')}")
        msg = data.get("message", "")
        if msg:
            print(f"   {msg}")
else:
    results.append(("get_scroll_info", "FAIL", "no scrollable ref"))

# 4. get_element_views — Windows only
print("\n4. get_element_views (Windows only)")
ref, _, _ = None, None, None
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="table", limit=1))
if r.get("elements"):
    ref = r["elements"][0]["ref"]
data = t("get_element_views", lambda: get_element_views(element_ref=ref) if ref else json.dumps({"success": False, "error": "no element"}))

# 5. set_element_view — Windows only
print("5. set_element_view (Windows only)")
data = t("set_element_view", lambda: set_element_view(element_ref=ref, view_id=0) if ref else json.dumps({"success": False, "error": "no element"}))

# 6. realize_element — Windows only
print("6. realize_element (Windows only)")
data = t("realize_element", lambda: realize_element(element_ref=ref) if ref else json.dumps({"success": False, "error": "no element"}))

# 7. get_drag_info — Windows only
print("7. get_drag_info (Windows only)")
data = t("get_drag_info", lambda: get_drag_info(element_ref=ref) if ref else json.dumps({"success": False, "error": "no element"}))

# 8. get_hyperlinks
print("\n8. get_hyperlinks")
# Find a link element in Chrome
activate_window(title_pattern="Chrome")
time.sleep(0.5)
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="link", limit=3))
print(f"   Chrome links: {r.get('total_count', 0)}")
if r.get("elements"):
    link_ref = r["elements"][0]["ref"]
    link_name = r["elements"][0].get("name", "")
    print(f"   Target: '{link_name}'")

    # Test on link element itself (self-link)
    data = t("get_hyperlinks (on link)", lambda: get_hyperlinks(element_ref=link_ref))
    if data.get("success") is not False:
        print(f"   Links: count={data.get('link_count')}, returned={len(data.get('links', []))}")
        for lnk in data.get("links", []):
            print(f"     name='{lnk.get('name','')}' uri='{lnk.get('uri','')}' self_link={lnk.get('self_link', False)}")

    # Also test on parent (should have URI)
    from computer_control_mcp.core import get_element_parent
    parent = json.loads(get_element_parent(element_ref=link_ref))
    if parent.get("element") and "hypertext" in parent["element"].get("interfaces", []):
        pref = parent["element"]["ref"]
        data2 = t("get_hyperlinks (on parent)", lambda: get_hyperlinks(element_ref=pref))
        if data2.get("success") is not False:
            for lnk in data2.get("links", [])[:3]:
                print(f"     name='{lnk.get('name','')}' uri='{lnk.get('uri','')}'")
else:
    results.append(("get_hyperlinks", "FAIL", "no link element in Chrome"))

# 9. activate_hyperlink
print("\n9. activate_hyperlink")
if r.get("elements") and parent.get("element") and "hypertext" in parent["element"].get("interfaces", []):
    data = t("activate_hyperlink(0)", lambda: activate_hyperlink(element_ref=pref, link_index=0))
else:
    # Try on the link itself
    if r.get("elements"):
        data = t("activate_hyperlink (on link)", lambda: activate_hyperlink(element_ref=link_ref, link_index=0))
    else:
        results.append(("activate_hyperlink", "FAIL", "no hypertext element"))

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
