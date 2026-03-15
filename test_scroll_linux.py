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

from computer_control_mcp.core import find_ui_elements, get_element_children, scroll_element_container, get_scroll_info

# Find scroll bars in Chrome (scrollable page)
print("=== Looking for scrollable elements ===\n")

# Check Chrome for scroll bars
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="scroll bar|scroll pane", limit=10))
print(f"Chrome scroll elements: {r.get('total_count', 0)}")
for el in r.get("elements", []):
    name = el.get("name", "")
    role = el.get("role", "")
    ifaces = el.get("interfaces", [])
    print(f"  [{role}] name='{name}' ifaces={ifaces}")
    if "value" in ifaces:
        print(f"    Has value interface! Can use set_element_range_value for scrolling")

# Check Thunar
print()
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="scroll bar|scroll pane", limit=10))
print(f"Thunar scroll elements: {r.get('total_count', 0)}")
for el in r.get("elements", []):
    name = el.get("name", "")
    role = el.get("role", "")
    ifaces = el.get("interfaces", [])
    print(f"  [{role}] name='{name}' ifaces={ifaces}")

# Try scroll_element_container on Chrome's document
print("\n=== Testing scroll_element_container on Chrome document ===")
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="document web", limit=1))
if r.get("elements"):
    ref = r["elements"][0]["ref"]
    print(f"Target: [{r['elements'][0].get('role')}] {r['elements'][0].get('name','')}")

    result = json.loads(scroll_element_container(element_ref=ref, direction="down", amount=1, unit="page"))
    print(f"scroll down: success={result.get('success')}, msg={result.get('message','')}, err={result.get('error','')}")

# Try on a scroll pane if available
print("\n=== Testing on scroll_pane ===")
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="scroll pane|section", limit=5))
for el in r.get("elements", []):
    ref = el["ref"]
    ifaces = el.get("interfaces", [])
    print(f"Target: [{el.get('role')}] {el.get('name','')} ifaces={ifaces}")
    result = json.loads(scroll_element_container(element_ref=ref, direction="down", amount=1, unit="page"))
    print(f"  scroll: success={result.get('success')}, err={result.get('error','')}")
    break
