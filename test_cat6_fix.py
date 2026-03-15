import json, os
dbus_dir = "/home/agent/.dbus/session-bus/"
if os.path.isdir(dbus_dir):
    for f in os.listdir(dbus_dir):
        with open(os.path.join(dbus_dir, f)) as fh:
            for line in fh:
                if line.startswith("DBUS_SESSION_BUS_ADDRESS="):
                    os.environ["DBUS_SESSION_BUS_ADDRESS"] = line.strip().split("=", 1)[1].strip("\"'")
                    break
        break
os.environ["DISPLAY"] = ":1"

from computer_control_mcp.core import find_ui_elements, scroll_element_into_view, expand_element, collapse_element

# 1. Check scroll_element_into_view return value
ref_data = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="push button", limit=1))
if ref_data.get("elements"):
    ref = ref_data["elements"][0]["ref"]
    r = scroll_element_into_view(element_ref=ref)
    print(f"scroll_element_into_view raw: {r}")

# 2. Find expandable elements in Thunar sidebar (tree items)
print()
ref_data = json.loads(find_ui_elements(title_pattern="Thunar", limit=100))
roles = {}
for el in ref_data.get("elements", []):
    role = el.get("role", "")
    roles[role] = roles.get(role, 0) + 1
print("Thunar roles:", sorted(roles.items(), key=lambda x: -x[1]))

# Look for tree items specifically
for el in ref_data.get("elements", []):
    role = el.get("role", "")
    name = el.get("name", "")
    if "tree" in role or "expander" in role.lower() or "combo" in role:
        print(f"  Expandable candidate: [{role}] {name}")

# 3. Try Chrome for expandable elements
print()
ref_data2 = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="tree item|combo box|disclosure triangle|group", limit=10))
print(f"Chrome expandable: {ref_data2.get('total_count', 0)}")
for el in ref_data2.get("elements", [])[:5]:
    print(f"  [{el.get('role')}] {el.get('name','')}")
