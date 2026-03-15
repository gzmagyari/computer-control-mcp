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

async def screenshot(name=""):
    """Take screenshot of Chrome and save, return path"""
    r = await mcp.call_tool("take_screenshot", {
        "title_pattern": "Chrome", "save_to_downloads": True, "image_format": "png"
    })
    print(f"  [{name}] Screenshot saved")

async def main():
    print("=== Real Task: Google search for NVDA, find 5th result ===\n")

    # Step 1: Activate Chrome
    print("Step 1: Activate Chrome")
    await mcp.call_tool("activate_window", {"title_pattern": "Chrome"})
    await asyncio.sleep(0.5)

    # Step 2: Click the address bar and navigate to Google
    print("Step 2: Navigate to Google")
    await mcp.call_tool("press_keys", {"keys": [["ctrl", "l"]]})
    await asyncio.sleep(0.5)
    await mcp.call_tool("type_text", {"text": "https://www.google.com"})
    await asyncio.sleep(0.3)
    await mcp.call_tool("press_keys", {"keys": "enter"})
    await asyncio.sleep(3)
    await screenshot("google loaded")

    # Step 3: Find the search box and type NVDA
    print("Step 3: Search for NVDA")
    # Google's search box — find via UI automation
    r = await mcp.call_tool("find_ui_elements", {
        "title_pattern": "Chrome", "role_filter": "entry|combo box", "limit": 10
    })
    search_ref = None
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    data = json.loads(sub.text)
                    for el in data.get("elements", []):
                        name = el.get("name", "").lower()
                        if "search" in name or "combobox" in name or "q" in name:
                            search_ref = el["ref"]
                            print(f"  Found search box: [{el.get('role')}] {el.get('name','')}")
                            break

    if not search_ref:
        # Fallback: click center of page and use keyboard
        print("  Search box not found via UIA, using OCR")
        r = await mcp.call_tool("find_text", {"text": "Search|Google"})
        # Just click the known Google search area
        await mcp.call_tool("click_screen", {"x": 600, "y": 400})
        await asyncio.sleep(0.5)
    else:
        await mcp.call_tool("invoke_element", {"element_ref": search_ref})
        await asyncio.sleep(0.5)

    await mcp.call_tool("type_text", {"text": "NVDA screen reader"})
    await asyncio.sleep(0.5)
    await mcp.call_tool("press_keys", {"keys": "enter"})
    await asyncio.sleep(4)
    await screenshot("search results")

    # Step 4: Read the search results page
    print("Step 4: Find search results")
    # Get OCR text to see results
    r = await mcp.call_tool("take_screenshot_full", {
        "title_pattern": "Chrome", "image_format": "webp", "quality": 50,
        "include_image": True, "include_ocr": True, "include_ui": False
    })
    ocr_text = ""
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    try:
                        data = json.loads(sub.text)
                        for el in data.get("ocr", {}).get("elements", []):
                            ocr_text += el.get("text", "") + "\n"
                    except:
                        pass
        elif hasattr(item, "text"):
            try:
                data = json.loads(item.text)
                for el in data.get("ocr", {}).get("elements", []):
                    ocr_text += el.get("text", "") + "\n"
            except:
                pass
    print(f"  OCR text (first 500 chars):\n{ocr_text[:500]}")

    # Step 5: Scroll down to see more results
    print("\nStep 5: Scroll down to find 5th result")
    # Find Chrome page document for scrolling
    r = await mcp.call_tool("find_ui_elements", {
        "title_pattern": "Chrome", "role_filter": "document web",
        "text_filter": "NVDA", "limit": 5
    })
    page_ref = None
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    data = json.loads(sub.text)
                    for el in data.get("elements", []):
                        if "Omnibox" not in el.get("name", ""):
                            page_ref = el["ref"]
                            break
        elif hasattr(item, "text"):
            data = json.loads(item.text)
            for el in data.get("elements", []):
                if "Omnibox" not in el.get("name", ""):
                    page_ref = el["ref"]
                    break

    if page_ref:
        await mcp.call_tool("scroll_element_container", {
            "element_ref": page_ref, "direction": "down", "amount": 1, "unit": "page"
        })
        await asyncio.sleep(1)
    else:
        # Fallback: mouse wheel scroll
        await mcp.call_tool("scroll", {"direction": "down", "amount": 5})
        await asyncio.sleep(1)

    await screenshot("after scroll")

    # Step 6: Find links in the search results
    print("\nStep 6: Find result links")
    r = await mcp.call_tool("find_ui_elements", {
        "title_pattern": "Chrome", "role_filter": "link",
        "limit": 20
    })
    links = []
    for item in r:
        if isinstance(item, list):
            for sub in item:
                if hasattr(sub, "text"):
                    data = json.loads(sub.text)
                    links = data.get("elements", [])
        elif hasattr(item, "text"):
            data = json.loads(item.text)
            links = data.get("elements", [])

    # Filter to actual search result links (skip navigation, header links)
    result_links = []
    for lnk in links:
        name = lnk.get("name", "")
        bounds = lnk.get("bounds", {})
        y = bounds.get("y", 0)
        # Search results are typically in the main content area (y > 200)
        if name and y > 200 and len(name) > 10:
            result_links.append(lnk)

    print(f"  Total links: {len(links)}, result links: {len(result_links)}")
    for i, lnk in enumerate(result_links[:10]):
        print(f"    {i+1}. '{lnk.get('name','')[:60]}' y={lnk.get('bounds',{}).get('y',0)}")

    # Step 7: Click the 5th result
    print("\nStep 7: Click 5th result")
    if len(result_links) >= 5:
        target = result_links[4]
        print(f"  Clicking: '{target.get('name','')[:60]}'")
        await mcp.call_tool("invoke_element", {"element_ref": target["ref"]})
        await asyncio.sleep(4)
        await screenshot("5th result page")

        # Step 8: Read the page content
        print("\nStep 8: Read page content")
        r = await mcp.call_tool("take_screenshot_full", {
            "title_pattern": "Chrome", "image_format": "webp", "quality": 50,
            "include_image": True, "include_ocr": True, "include_ui": False
        })
        page_text = ""
        for item in r:
            if isinstance(item, list):
                for sub in item:
                    if hasattr(sub, "text"):
                        try:
                            data = json.loads(sub.text)
                            for el in data.get("ocr", {}).get("elements", []):
                                page_text += el.get("text", "") + " "
                        except:
                            pass
            elif hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    for el in data.get("ocr", {}).get("elements", []):
                        page_text += el.get("text", "") + " "
                except:
                    pass
        print(f"  Page text (first 600 chars):\n{page_text[:600]}")
    else:
        print(f"  Only {len(result_links)} result links found, need at least 5")
        if result_links:
            print(f"  Clicking last available: '{result_links[-1].get('name','')[:60]}'")

    print("\n=== Done ===")

asyncio.run(main())
