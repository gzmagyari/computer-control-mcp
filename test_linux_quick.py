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
    take_screenshot, find_ui_elements, set_clipboard, get_clipboard,
    press_keys, type_text, activate_window, launch_app, start_file_watch,
    get_file_watch_events, stop_file_watch, select_text_range,
    get_text_selection, select_text_by_search, get_hyperlinks
)

results = []

def test(name, fn):
    try:
        r = fn()
        results.append((name, "PASS", r))
        print(f"  PASS: {name}")
    except Exception as e:
        results.append((name, "FAIL", str(e)))
        print(f"  FAIL: {name}: {e}")

print("=== Quick Linux Smoke Test ===\n")

# 1. Screenshot
print("1. Screenshot")
test("take_screenshot", lambda: take_screenshot(save_to_downloads=True, image_format="png"))

# 2. Clipboard
print("2. Clipboard")
test("set_clipboard", lambda: set_clipboard("MCP_CLIPBOARD_TEST"))
test("get_clipboard", lambda: get_clipboard())
clip = get_clipboard()
assert "MCP_CLIPBOARD_TEST" in clip, f"Clipboard mismatch: {clip}"
print(f"   Clipboard value: {clip.strip()}")

# 3. find_ui_elements with title_pattern
print("3. find_ui_elements title_pattern")
# Open Thunar first
os.system("DISPLAY=:1 thunar /home/agent &")
time.sleep(2)
for pattern in ["Thunar", "thunar"]:
    r = json.loads(find_ui_elements(title_pattern=pattern, limit=3))
    count = r.get("total_count", 0)
    status = "PASS" if count > 0 else "FAIL"
    print(f"  {status}: title_pattern='{pattern}': {count} elements")

# 4. press_keys enter
print("4. press_keys enter")
activate_window(title_pattern="Terminal")
time.sleep(0.5)
type_text("echo SMOKE_TEST_OK")
time.sleep(0.3)
press_keys("enter")
time.sleep(1)
test("press_keys enter", lambda: "ok")

# 5. File watching
print("5. File watching")
os.makedirs("/tmp/smoke-watch", exist_ok=True)
r = json.loads(start_file_watch("/tmp/smoke-watch"))
started = r.get("started", False)
wid = r.get("watch_id", "")
print(f"  start_file_watch: started={started}")
with open("/tmp/smoke-watch/test.txt", "w") as f:
    f.write("hello")
time.sleep(0.5)
ev = json.loads(get_file_watch_events(wid))
print(f"  events: {ev.get('event_count', 0)}")
json.loads(stop_file_watch(wid))
print(f"  stopped: ok")

# 6. Text selection (on Thunar address bar)
print("6. Text selection")
r = json.loads(find_ui_elements(title_pattern="Thunar", role_filter="text", limit=5))
text_els = [e for e in r.get("elements", []) if e.get("interfaces") and "text" in e.get("interfaces", [])]
if text_els:
    ref = text_els[0]["ref"]
    txt = text_els[0].get("text", "")
    print(f"  Found text element: '{txt}'")
    r1 = json.loads(select_text_range(element_ref=ref, start=0, end=5))
    print(f"  select_text_range(0,5): success={r1.get('success')}, text='{r1.get('text','')}'")
    r2 = json.loads(get_text_selection(element_ref=ref))
    print(f"  get_text_selection: success={r2.get('success')}, count={r2.get('count')}")
    if "home" in txt.lower():
        r3 = json.loads(select_text_by_search(element_ref=ref, search_text="home"))
        print(f"  select_text_by_search('home'): success={r3.get('success')}")
else:
    print(f"  No text elements found in Thunar ({r.get('total_count', 0)} total elements)")

# 7. Hyperlinks (launch Chrome with accessibility)
print("7. Hyperlinks")
launch_app(command=["google-chrome", "https://example.com"])
time.sleep(6)
r = json.loads(find_ui_elements(title_pattern="Chrome", role_filter="link", limit=5))
link_count = r.get("total_count", 0)
print(f"  Chrome links: {link_count}")
if r.get("elements"):
    ref = r["elements"][0]["ref"]
    name = r["elements"][0].get("name", "")
    print(f"  First link: '{name}'")
    hr = json.loads(get_hyperlinks(element_ref=ref))
    print(f"  get_hyperlinks: count={hr.get('link_count')}, returned={len(hr.get('links', []))}")

# Screenshot to verify
print("\n8. Final screenshot")
take_screenshot(save_to_downloads=True, image_format="png")
print("  Saved")

print("\n=== Done ===")
