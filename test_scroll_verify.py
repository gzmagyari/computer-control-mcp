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
    find_ui_elements, scroll_element_container, activate_window,
    launch_app, take_screenshot
)

# Open a long page in Chrome
activate_window(title_pattern="Chrome")
time.sleep(0.5)

# Navigate to Wikipedia which has a long scrollable page
# First take before screenshot
take_screenshot(title_pattern="Chrome", save_to_downloads=True, image_format="png")
print("Before screenshot saved")

# Find the document element
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="document web", limit=1))
if r.get("elements"):
    ref = r["elements"][0]["ref"]
    print(f"Scrolling: [{r['elements'][0].get('role')}] {r['elements'][0].get('name','')}")

    # Scroll down 3 times
    for i in range(3):
        result = json.loads(scroll_element_container(element_ref=ref, direction="down", amount=1, unit="page"))
        print(f"  Scroll {i+1}: success={result.get('success')}")
        time.sleep(0.3)

    time.sleep(0.5)
    take_screenshot(title_pattern="Chrome", save_to_downloads=True, image_format="png")
    print("After screenshot saved")
else:
    print("No document element found")
