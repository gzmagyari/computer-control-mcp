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

from computer_control_mcp.core import find_ui_elements

# Dump ALL roles from both apps to find scroll-related ones
for app in ["Thunar", "Chrome"]:
    r = json.loads(find_ui_elements(title_pattern=app, limit=0, max_depth=40))
    roles = {}
    value_els = []
    for el in r.get("elements", []):
        role = el.get("role", "")
        roles[role] = roles.get(role, 0) + 1
        if "value" in el.get("interfaces", []):
            value_els.append(el)
        if "scroll" in role.lower() or "slider" in role.lower():
            print(f"  {app} scroll-like: [{role}] name='{el.get('name','')}' ifaces={el.get('interfaces',[])}")

    print(f"\n{app}: {r.get('total_count', 0)} elements, {len(roles)} roles")
    scroll_roles = {k:v for k,v in roles.items() if "scroll" in k.lower() or "slider" in k.lower() or "bar" in k.lower()}
    if scroll_roles:
        print(f"  Scroll-related roles: {scroll_roles}")
    if value_els:
        print(f"  Elements with value interface: {len(value_els)}")
        for el in value_els:
            print(f"    [{el.get('role')}] {el.get('name','')}")
    print()
