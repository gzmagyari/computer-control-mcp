import json, os, asyncio

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

# Test 1: Direct function call
from computer_control_mcp.core import find_ui_elements
r1 = json.loads(find_ui_elements(title_pattern="Thunar", limit=3))
print(f"Direct call: total_count={r1.get('total_count', 0)}")

# Test 2: Via mcp.call_tool
from computer_control_mcp.core import mcp

async def test_mcp():
    r = await mcp.call_tool("find_ui_elements", {"title_pattern": "Thunar", "limit": 3})
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    data = json.loads(sub.text)
                    print(f"MCP call_tool: total_count={data.get('total_count', 0)}")
                    print(f"  elements: {len(data.get('elements', []))}")
                    for el in data.get("elements", [])[:3]:
                        print(f"    [{el.get('role')}] {el.get('name','')}")
                    return
        elif hasattr(item, "text"):
            data = json.loads(item.text)
            print(f"MCP call_tool: total_count={data.get('total_count', 0)}")
            print(f"  elements: {len(data.get('elements', []))}")
            for el in data.get("elements", [])[:3]:
                print(f"    [{el.get('role')}] {el.get('name','')}")
            return
        elif isinstance(item, dict):
            result = item.get("result", "")
            if result:
                data = json.loads(result)
                print(f"MCP call_tool (dict): total_count={data.get('total_count', 0)}")
                return
    print(f"MCP call_tool: could not parse result, raw={[type(x).__name__ for x in r]}")

asyncio.run(test_mcp())
