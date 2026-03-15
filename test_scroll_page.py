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
    find_ui_elements, scroll_element_container, activate_window, take_screenshot
)

activate_window(title_pattern="Chrome")
time.sleep(0.5)

# Take BEFORE
take_screenshot(title_pattern="Chrome", save_to_downloads=True, image_format="png")
print("Before saved")

# Find the ACTUAL page document (deepest one, name != Omnibox)
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="document web", limit=10))
page_ref = None
for el in r.get("elements", []):
    name = el.get("name", "")
    if "Omnibox" not in name and name:
        page_ref = el["ref"]
        print(f"Target: [{el.get('role')}] {name} bounds={el.get('bounds')}")
        break

if page_ref:
    result = json.loads(scroll_element_container(element_ref=page_ref, direction="down", amount=2, unit="page"))
    print(f"Scroll: {result.get('message')}")
    time.sleep(1)
    take_screenshot(title_pattern="Chrome", save_to_downloads=True, image_format="png")
    print("After saved")
else:
    print("No page document found!")
