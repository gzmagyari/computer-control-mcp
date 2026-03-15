import json, os, asyncio, time

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

from computer_control_mcp.core import mcp

async def main():
    # Launch xterm
    await mcp.call_tool("launch_app", {"command": ["xterm", "-title", "KillTest"]})
    await asyncio.sleep(1)

    # Kill it
    r = await mcp.call_tool("kill_process", {"process_name": "xterm"})
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    print(f"kill_process: {sub.text}")
        elif hasattr(item, "text"):
            print(f"kill_process: {item.text}")

    # Also test the other failures with correct param names
    print()
    r = await mcp.call_tool("wait_milliseconds", {"milliseconds": 100})
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    print(f"wait_milliseconds: {sub.text}")
        elif hasattr(item, "text"):
            print(f"wait_milliseconds: {item.text}")

asyncio.run(main())
