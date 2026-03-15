import json, os

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

from computer_control_mcp.core import find_ui_elements, get_element_details, get_element_children

# Search for scroll bar elements across all apps
print("=== Looking for scroll bars ===\n")

# Thunar
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="scroll bar", limit=10))
print(f"Thunar scroll bars: {r.get('total_count', 0)}")
for el in r.get("elements", []):
    name = el.get("name", "")
    ifaces = el.get("interfaces", [])
    bounds = el.get("bounds", {})
    print(f"  [{el.get('role')}] name='{name}' ifaces={ifaces} bounds={bounds}")

    # Get full details to check value interface
    details = json.loads(get_element_details(element_ref=el["ref"]))
    det = details.get("element", {})
    print(f"    value: {det.get('value')}")
    print(f"    states: {det.get('states', {})}")

    # Check children (scroll bars often have buttons + slider)
    children = json.loads(get_element_children(element_ref=el["ref"]))
    for kid in children.get("children", []):
        print(f"    child: [{kid.get('role')}] name='{kid.get('name','')}' ifaces={kid.get('interfaces',[])}")

# Chrome
print()
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="scroll bar", limit=10))
print(f"Chrome scroll bars: {r.get('total_count', 0)}")
for el in r.get("elements", []):
    name = el.get("name", "")
    ifaces = el.get("interfaces", [])
    print(f"  [{el.get('role')}] name='{name}' ifaces={ifaces}")
    details = json.loads(get_element_details(element_ref=el["ref"]))
    det = details.get("element", {})
    print(f"    value: {det.get('value')}")

# Also look for any element with "value" interface that could be a scrollbar
print()
r = json.loads(find_ui_elements(title_pattern="Thunar", limit=100))
value_els = [e for e in r.get("elements", []) if "value" in e.get("interfaces", [])]
print(f"Thunar elements with 'value' interface: {len(value_els)}")
for el in value_els:
    print(f"  [{el.get('role')}] name='{el.get('name','')}' ifaces={el.get('interfaces',[])}")
    details = json.loads(get_element_details(element_ref=el["ref"]))
    det = details.get("element", {})
    print(f"    value: {det.get('value')}")
