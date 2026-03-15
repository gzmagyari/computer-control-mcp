"""Helper to run MCP tool calls from the command line.
Usage: python run_mcp.py <tool_name> '<json_args>'
"""
import json, os, sys, asyncio

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

tool = sys.argv[1]
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

async def main():
    r = await mcp.call_tool(tool, args)
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    print(sub.text)
                elif hasattr(sub, "data"):
                    print(f"[Image: {len(sub.data)} bytes]")
        elif isinstance(item, dict):
            if "result" in item:
                print(item["result"])
        elif hasattr(item, "text"):
            print(item.text)
        elif hasattr(item, "data"):
            print(f"[Image: {len(item.data)} bytes]")

asyncio.run(main())
