import os, asyncio

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
    await mcp.call_tool("move_mouse", {"x": 960, "y": 540})
    r = await mcp.call_tool("get_mouse_position", {})
    print(f"Result type: {type(r)}, len: {len(r)}")
    for i, item in enumerate(r):
        t = type(item).__name__
        if hasattr(item, "text"):
            print(f"  [{i}] text: {item.text}")
        elif hasattr(item, "data"):
            print(f"  [{i}] data: {len(item.data)} bytes")
        else:
            print(f"  [{i}] {t}: {str(item)[:100]}")

asyncio.run(main())
