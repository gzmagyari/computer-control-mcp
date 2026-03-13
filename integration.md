Yes — you can go much deeper than pixels.

On Windows, UI Automation gives you semantic control patterns like invoke, value, text, selection, toggle, expand/collapse, scroll item, transform, and window, plus focus/property/structure event hooks. On Linux, AT-SPI gives you Action, Text, EditableText, Value, Selection, Component, Document, and event listener registration. That means the next big step is not “more OCR,” it is “stable element identity + semantic actions + event/wait/watch tools.” ([Microsoft Learn][1])

One important caveat first: your Linux window-stacking/occlusion code is currently X11-specific because it shells out to `wmctrl` and `xprop`, which are X Window/X server tools. So the AT-SPI parts are good for Ubuntu, but your current Linux window-layer assumptions are really “Ubuntu on X11/Xorg,” not full Wayland parity. ([linux.die.net][2])

I’d apply this in three patch sets.

---

## Patch set 1: deep UI automation refs, introspection, traversal, and semantic actions

This adds:

* stable-ish element refs (`backend/app/window_ids/path/...`)
* deep element discovery
* focused element lookup
* hit-testing by point
* parent/child traversal
* rich element details
* semantic actions:

  * focus
  * invoke/click
  * get/set/append/clear text
  * select
  * toggle
  * expand/collapse
  * scroll into view
  * set range value
  * move/resize/set extents
  * close

The Windows side is based on `uiautomation` patterns and convenience methods that the library itself documents/examples (`GetValuePattern().SetValue`, `GetSelectionItemPattern().Select`, `GetScrollItemPattern().ScrollIntoView`, `GetWindowPattern().Close`, `GetTransformPattern().Move/Resize`, `Click`, `SendKeys`). ([GitHub][3])

```diff
diff --git a/src/computer_control_mcp/ui_automation.py b/src/computer_control_mcp/ui_automation.py
--- a/src/computer_control_mcp/ui_automation.py
+++ b/src/computer_control_mcp/ui_automation.py
@@
-from typing import Any, Dict, List, Optional, Tuple
+from typing import Any, Dict, List, Optional, Tuple
@@
 def _make_element(
     role: str,
     name: str = "",
     bounds: Optional[Dict[str, int]] = None,
     actions: Optional[List[str]] = None,
     depth: int = 0,
     text: str = "",
+    **extras: Any,
 ) -> Dict[str, Any]:
     """Create a normalized UI element dict with abs_center computed from bounds."""
     entry = {"role": role, "depth": depth}
     if name:
         entry["name"] = name
@@
     if actions:
         entry["actions"] = actions
+    for key, value in extras.items():
+        if value is None or value == "" or value == [] or value == {}:
+            continue
+        entry[key] = value
     return entry
@@
 def _filter_apps_by_region(all_apps: List[Dict], region: list) -> Tuple[List[Dict], int]:
@@
     return filtered_apps, removed
+
+
+def _flatten_applications(apps: List[Dict]) -> List[Dict]:
+    flat: List[Dict] = []
+    for app in apps:
+        flat.extend(app.get("elements", []))
+    return flat
+
+
+def _element_contains_point(el: Dict[str, Any], x: int, y: int) -> bool:
+    b = el.get("bounds")
+    if not b:
+        return False
+    return b["x"] <= x <= (b["x"] + b["w"]) and b["y"] <= y <= (b["y"] + b["h"])
+
+
+def _compact_dict(data: Dict[str, Any]) -> Dict[str, Any]:
+    return {
+        k: v for k, v in data.items()
+        if v is not None and v != "" and v != [] and v != {}
+    }
+
+
+def _sanitize_match_text(value: str) -> str:
+    return re.sub(r'[\u200b\u200c\u200d\ufeff]', '', (value or '')).strip().lower()
@@
 def _get_ui_elements_linux(app_filter: Optional[str] = None) -> Dict:
@@
     return {
         "available": True,
         "error": None,
         "screen": {"width": screen_w, "height": screen_h},
         "windows": windows,
@@
         },
     }
+
+
+# ── Deep UI Automation / AT-SPI Helpers ────────────────────────────────
+
+
+def _uia_pattern_names(control) -> List[str]:
+    mapping = [
+        ("invoke", "IsInvokePatternAvailable"),
+        ("value", "IsValuePatternAvailable"),
+        ("text", "IsTextPatternAvailable"),
+        ("selection", "IsSelectionPatternAvailable"),
+        ("selection_item", "IsSelectionItemPatternAvailable"),
+        ("toggle", "IsTogglePatternAvailable"),
+        ("expand_collapse", "IsExpandCollapsePatternAvailable"),
+        ("scroll", "IsScrollPatternAvailable"),
+        ("scroll_item", "IsScrollItemPatternAvailable"),
+        ("range_value", "IsRangeValuePatternAvailable"),
+        ("transform", "IsTransformPatternAvailable"),
+        ("window", "IsWindowPatternAvailable"),
+        ("legacy_iaccessible", "IsLegacyIAccessiblePatternAvailable"),
+    ]
+    out: List[str] = []
+    for name, attr in mapping:
+        try:
+            if bool(getattr(control, attr)):
+                out.append(name)
+        except Exception:
+            pass
+    return out
+
+
+def _uia_state_flags(control) -> Dict[str, Any]:
+    mapping = [
+        ("enabled", "IsEnabled"),
+        ("keyboard_focusable", "IsKeyboardFocusable"),
+        ("has_keyboard_focus", "HasKeyboardFocus"),
+        ("offscreen", "IsOffscreen"),
+        ("password", "IsPassword"),
+        ("content_element", "IsContentElement"),
+        ("control_element", "IsControlElement"),
+    ]
+    out: Dict[str, Any] = {}
+    for key, attr in mapping:
+        try:
+            out[key] = bool(getattr(control, attr))
+        except Exception:
+            pass
+    return out
+
+
+def _uia_text_value_snapshot(control, max_chars: int = 2000) -> Dict[str, Any]:
+    result: Dict[str, Any] = {}
+    try:
+        value_pattern = control.GetValuePattern()
+        if value_pattern:
+            value = getattr(value_pattern, "Value", None)
+            if value is not None:
+                result["value"] = str(value)[:max_chars]
+    except Exception:
+        pass
+    try:
+        text_pattern = control.GetTextPattern()
+        if text_pattern and getattr(text_pattern, "DocumentRange", None):
+            text = text_pattern.DocumentRange.GetText(max_chars)
+            if text:
+                result["text"] = text[:max_chars]
+    except Exception:
+        pass
+    if "text" not in result:
+        try:
+            name = control.Name or ""
+            if name:
+                result["text"] = name[:max_chars]
+        except Exception:
+            pass
+    return result
+
+
+def _atspi_interface_names(node) -> List[str]:
+    checks = [
+        ("action", "get_action_iface"),
+        ("component", "get_component_iface"),
+        ("text", "get_text_iface"),
+        ("editable_text", "get_editable_text_iface"),
+        ("value", "get_value_iface"),
+        ("selection", "get_selection_iface"),
+        ("document", "get_document_iface"),
+        ("image", "get_image_iface"),
+        ("table", "get_table_iface"),
+        ("hypertext", "get_hypertext_iface"),
+    ]
+    out: List[str] = []
+    for name, getter_name in checks:
+        try:
+            getter = getattr(node, getter_name)
+            if getter() is not None:
+                out.append(name)
+        except Exception:
+            pass
+    return out
+
+
+def _atspi_state_names(node) -> List[str]:
+    out: List[str] = []
+    try:
+        ss = node.get_state_set()
+        for st in ss.get_states():
+            value = getattr(st, "value_nick", None) or getattr(st, "value_name", None) or str(st)
+            out.append(str(value).lower())
+    except Exception:
+        pass
+    return out
+
+
+def _atspi_text_value_snapshot(node, max_chars: int = 2000) -> Dict[str, Any]:
+    result: Dict[str, Any] = {}
+    try:
+        ti = node.get_text_iface()
+        if ti:
+            count = ti.get_character_count()
+            result["text"] = ti.get_text(0, min(count, max_chars))
+    except Exception:
+        pass
+    try:
+        vi = node.get_value_iface()
+        if vi:
+            try:
+                value_text = vi.get_text()
+                if value_text:
+                    result["value"] = value_text[:max_chars]
+            except Exception:
+                result["value"] = str(vi.get_current_value())
+    except Exception:
+        pass
+    if "text" not in result:
+        try:
+            name = node.get_name() or ""
+            if name:
+                result["text"] = name[:max_chars]
+        except Exception:
+            pass
+    return result
+
+
+def _collect_uia_elements_deep(
+    control,
+    app_name: str,
+    window_ids: List[str],
+    path: Optional[List[int]] = None,
+    depth: int = 0,
+    max_depth: int = 40,
+) -> List[Dict[str, Any]]:
+    if control is None or depth > max_depth:
+        return []
+
+    path = list(path or [])
+
+    try:
+        control_type = control.ControlTypeName
+        role = _UIA_ROLE_MAP.get(control_type, control_type.replace("Control", "").lower())
+    except Exception:
+        role = "unknown"
+
+    name = ""
+    try:
+        name = control.Name or ""
+    except Exception:
+        pass
+
+    bounds = None
+    try:
+        rect = control.BoundingRectangle
+        if rect.width() > 0 and rect.height() > 0 and rect.left >= 0 and rect.top >= 0:
+            bounds = {
+                "x": int(rect.left),
+                "y": int(rect.top),
+                "w": int(rect.width()),
+                "h": int(rect.height()),
+            }
+    except Exception:
+        pass
+
+    children = []
+    try:
+        children = control.GetChildren() or []
+    except Exception:
+        children = []
+
+    states = _uia_state_flags(control)
+    patterns = _uia_pattern_names(control)
+    snapshot = _uia_text_value_snapshot(control)
+
+    element_ref = _compact_dict({
+        "backend": "uia",
+        "app": app_name,
+        "window_ids": window_ids,
+        "path": path,
+        "role": role,
+        "name": name,
+        "bounds": bounds,
+    })
+
+    element = _make_element(
+        role=role,
+        name=name,
+        bounds=bounds,
+        actions=patterns or None,
+        depth=depth,
+        text=snapshot.get("text", ""),
+        value=snapshot.get("value"),
+        backend="uia",
+        application=app_name,
+        window_ids=window_ids,
+        ref=element_ref,
+        patterns=patterns,
+        states=states,
+        child_count=len(children),
+        automation_id=getattr(control, "AutomationId", None),
+        class_name=getattr(control, "ClassName", None),
+        framework_id=getattr(control, "FrameworkId", None),
+        process_id=getattr(control, "ProcessId", None),
+        native_window_handle=getattr(control, "NativeWindowHandle", None),
+        description=getattr(control, "HelpText", None),
+        keyboard_shortcut=(getattr(control, "AccessKey", None) or getattr(control, "AcceleratorKey", None)),
+        localized_control_type=getattr(control, "LocalizedControlType", None),
+    )
+
+    elements = [element]
+    for idx, child in enumerate(children):
+        elements.extend(
+            _collect_uia_elements_deep(
+                child,
+                app_name=app_name,
+                window_ids=window_ids,
+                path=path + [idx],
+                depth=depth + 1,
+                max_depth=max_depth,
+            )
+        )
+    return elements
+
+
+def _collect_atspi_elements_deep(
+    node,
+    app_name: str,
+    window_ids: List[str],
+    path: Optional[List[int]] = None,
+    depth: int = 0,
+    max_depth: int = 40,
+) -> List[Dict[str, Any]]:
+    if node is None or depth > max_depth:
+        return []
+
+    path = list(path or [])
+
+    try:
+        role = node.get_role_name()
+    except Exception:
+        role = "unknown"
+
+    try:
+        name = node.get_name() or ""
+    except Exception:
+        name = ""
+
+    bounds = None
+    try:
+        comp = node.get_component_iface()
+        if comp is not None:
+            r = comp.get_extents(Atspi.CoordType.SCREEN)
+            if r.width > 0 and r.height > 0 and r.x >= 0 and r.y >= 0:
+                bounds = {"x": r.x, "y": r.y, "w": r.width, "h": r.height}
+    except Exception:
+        pass
+
+    snapshot = _atspi_text_value_snapshot(node)
+    states = _atspi_state_names(node)
+    interfaces = _atspi_interface_names(node)
+
+    actions: List[str] = []
+    try:
+        ai = node.get_action_iface()
+        if ai:
+            for i in range(ai.get_n_actions()):
+                try:
+                    actions.append(ai.get_action_name(i))
+                except Exception:
+                    continue
+    except Exception:
+        pass
+
+    child_count = 0
+    try:
+        child_count = node.get_child_count()
+    except Exception:
+        pass
+
+    description = None
+    try:
+        description = node.get_description() or None
+    except Exception:
+        pass
+
+    element_ref = _compact_dict({
+        "backend": "atspi",
+        "app": app_name,
+        "window_ids": window_ids,
+        "path": path,
+        "role": role,
+        "name": name,
+        "bounds": bounds,
+    })
+
+    element = _make_element(
+        role=role,
+        name=name,
+        bounds=bounds,
+        actions=actions or None,
+        depth=depth,
+        text=snapshot.get("text", ""),
+        value=snapshot.get("value"),
+        backend="atspi",
+        application=app_name,
+        window_ids=window_ids,
+        ref=element_ref,
+        interfaces=interfaces,
+        states=states,
+        child_count=child_count,
+        description=description,
+    )
+
+    elements = [element]
+    for i in range(child_count):
+        try:
+            child = node.get_child_at_index(i)
+        except Exception:
+            continue
+        elements.extend(
+            _collect_atspi_elements_deep(
+                child,
+                app_name=app_name,
+                window_ids=window_ids,
+                path=path + [i],
+                depth=depth + 1,
+                max_depth=max_depth,
+            )
+        )
+    return elements
+
+
+def _get_deep_ui_elements_win32(
+    app_filter: Optional[str] = None,
+    include_hidden: bool = False,
+    max_depth: int = 40,
+) -> Dict[str, Any]:
+    import pyautogui
+
+    try:
+        import ctypes
+        ctypes.windll.ole32.CoInitialize(None)
+    except Exception:
+        pass
+
+    screen_w, screen_h = pyautogui.size()
+    t0 = time.perf_counter()
+
+    windows = _get_windows_stacking_order_win32()
+    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)
+
+    all_apps = []
+    total_before = 0
+    total_after = 0
+    app_filter_lower = _sanitize_match_text(app_filter) if app_filter else None
+
+    try:
+        root = auto.GetRootControl()
+        top_level_windows = root.GetChildren()
+
+        for uia_window in (top_level_windows or []):
+            try:
+                app_name = uia_window.Name or "unknown"
+            except Exception:
+                app_name = "unknown"
+
+            if app_filter_lower and app_filter_lower not in _sanitize_match_text(app_name):
+                continue
+
+            win_ids = _match_uia_window_to_stacking(uia_window, windows)
+            elements = _collect_uia_elements_deep(
+                uia_window,
+                app_name=app_name,
+                window_ids=win_ids,
+                path=[],
+                depth=0,
+                max_depth=max_depth,
+            )
+            total_before += len(elements)
+
+            if include_hidden:
+                filtered = elements
+            else:
+                filtered = []
+                all_regions = []
+                for wid in win_ids:
+                    all_regions.extend(visible_regions.get(wid, []))
+                if not all_regions:
+                    all_regions = [(0, 0, screen_w, screen_h)]
+                for el in elements:
+                    b = el.get("bounds")
+                    if not b:
+                        continue
+                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
+                        filtered.append(el)
+
+            if filtered:
+                all_apps.append({
+                    "application": app_name,
+                    "window_ids": win_ids,
+                    "elements": filtered,
+                })
+                total_after += len(filtered)
+    except Exception as e:
+        return {
+            "available": True,
+            "backend": "uia",
+            "error": f"Error collecting deep UIA elements: {str(e)}",
+            "screen": {"width": screen_w, "height": screen_h},
+            "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
+            "ui_elements": {
+                "time_s": round(time.perf_counter() - t0, 3),
+                "element_count": 0,
+                "filtered_out": 0,
+                "applications": [],
+            },
+        }
+
+    return {
+        "available": True,
+        "backend": "uia",
+        "error": None,
+        "screen": {"width": screen_w, "height": screen_h},
+        "windows": [{k: v for k, v in w.items() if k != "hwnd"} for w in windows],
+        "ui_elements": {
+            "time_s": round(time.perf_counter() - t0, 3),
+            "element_count": total_after,
+            "filtered_out": total_before - total_after,
+            "applications": all_apps,
+        },
+    }
+
+
+def _get_deep_ui_elements_linux(
+    app_filter: Optional[str] = None,
+    include_hidden: bool = False,
+    max_depth: int = 40,
+) -> Dict[str, Any]:
+    screen_w, screen_h = _get_screen_size_linux()
+    t0 = time.perf_counter()
+
+    windows = _get_windows_stacking_order_linux()
+    visible_regions = _compute_visible_regions(windows, screen_w, screen_h)
+
+    all_apps = []
+    total_before = 0
+    total_after = 0
+    app_filter_lower = _sanitize_match_text(app_filter) if app_filter else None
+
+    try:
+        desktop = Atspi.get_desktop(0)
+
+        for i in range(desktop.get_child_count()):
+            try:
+                app = desktop.get_child_at_index(i)
+                app_name = app.get_name() or f"app_{i}"
+            except Exception:
+                continue
+
+            if app_filter_lower and app_filter_lower not in _sanitize_match_text(app_name):
+                continue
+
+            elements = _collect_atspi_elements_deep(
+                app,
+                app_name=app_name,
+                window_ids=[],
+                path=[],
+                depth=0,
+                max_depth=max_depth,
+            )
+            total_before += len(elements)
+
+            win_ids = _match_app_to_windows_linux(app_name, elements, windows)
+
+            if include_hidden:
+                filtered = elements
+            else:
+                filtered = []
+                all_regions = []
+                for wid in win_ids:
+                    all_regions.extend(visible_regions.get(wid, []))
+                if not all_regions:
+                    all_regions = [(0, 0, screen_w, screen_h)]
+                for el in elements:
+                    b = el.get("bounds")
+                    if not b:
+                        continue
+                    if _rect_mostly_in_regions(b["x"], b["y"], b["w"], b["h"], all_regions, threshold=0.6):
+                        filtered.append(el)
+
+            if filtered:
+                for el in filtered:
+                    el["window_ids"] = win_ids
+                    if "ref" in el:
+                        el["ref"]["window_ids"] = win_ids
+                all_apps.append({
+                    "application": app_name,
+                    "window_ids": win_ids,
+                    "elements": filtered,
+                })
+                total_after += len(filtered)
+    except Exception as e:
+        return {
+            "available": True,
+            "backend": "atspi",
+            "error": f"Error collecting deep AT-SPI elements: {str(e)}",
+            "screen": {"width": screen_w, "height": screen_h},
+            "windows": windows,
+            "ui_elements": {
+                "time_s": round(time.perf_counter() - t0, 3),
+                "element_count": 0,
+                "filtered_out": 0,
+                "applications": [],
+            },
+        }
+
+    return {
+        "available": True,
+        "backend": "atspi",
+        "error": None,
+        "screen": {"width": screen_w, "height": screen_h},
+        "windows": windows,
+        "ui_elements": {
+            "time_s": round(time.perf_counter() - t0, 3),
+            "element_count": total_after,
+            "filtered_out": total_before - total_after,
+            "applications": all_apps,
+        },
+    }
+
+
+def _uia_follow_path(control, path: List[int]):
+    current = control
+    for idx in path:
+        try:
+            children = current.GetChildren() or []
+        except Exception:
+            return None
+        if idx < 0 or idx >= len(children):
+            return None
+        current = children[idx]
+    return current
+
+
+def _atspi_follow_path(node, path: List[int]):
+    current = node
+    for idx in path:
+        try:
+            current = current.get_child_at_index(idx)
+        except Exception:
+            return None
+    return current
+
+
+def _resolve_uia_element(ref: Dict[str, Any]) -> Dict[str, Any]:
+    target_app = _sanitize_match_text(ref.get("app", ""))
+    target_ids = set(ref.get("window_ids") or [])
+    target_path = list(ref.get("path") or [])
+
+    windows = _get_windows_stacking_order_win32()
+    try:
+        root = auto.GetRootControl()
+        for top in (root.GetChildren() or []):
+            app_name = getattr(top, "Name", "") or ""
+            app_name_clean = _sanitize_match_text(app_name)
+            if target_app and target_app not in app_name_clean and app_name_clean not in target_app:
+                continue
+            candidate_ids = set(_match_uia_window_to_stacking(top, windows))
+            if target_ids and not (candidate_ids & target_ids):
+                continue
+            node = _uia_follow_path(top, target_path)
+            if node is None:
+                continue
+            return {
+                "success": True,
+                "backend": "uia",
+                "node": node,
+                "app_name": app_name,
+                "window_ids": list(candidate_ids or target_ids),
+            }
+    except Exception as e:
+        return {"success": False, "backend": "uia", "error": str(e)}
+    return {"success": False, "backend": "uia", "error": "Element reference could not be resolved"}
+
+
+def _resolve_atspi_element(ref: Dict[str, Any]) -> Dict[str, Any]:
+    target_app = _sanitize_match_text(ref.get("app", ""))
+    target_path = list(ref.get("path") or [])
+
+    try:
+        desktop = Atspi.get_desktop(0)
+        for i in range(desktop.get_child_count()):
+            try:
+                app = desktop.get_child_at_index(i)
+                app_name = app.get_name() or f"app_{i}"
+            except Exception:
+                continue
+            app_name_clean = _sanitize_match_text(app_name)
+            if target_app and target_app not in app_name_clean and app_name_clean not in target_app:
+                continue
+            node = _atspi_follow_path(app, target_path)
+            if node is None:
+                continue
+            return {
+                "success": True,
+                "backend": "atspi",
+                "node": node,
+                "app_name": app_name,
+                "window_ids": ref.get("window_ids") or [],
+            }
+    except Exception as e:
+        return {"success": False, "backend": "atspi", "error": str(e)}
+    return {"success": False, "backend": "atspi", "error": "Element reference could not be resolved"}
+
+
+def _resolve_ui_element(ref: Dict[str, Any]) -> Dict[str, Any]:
+    backend = ref.get("backend")
+    if backend == "uia":
+        return _resolve_uia_element(ref)
+    if backend == "atspi":
+        return _resolve_atspi_element(ref)
+    return {"success": False, "error": f"Unsupported element ref backend: {backend}"}
+
+
+def _pick_atspi_named_action(node, candidates: List[str]) -> Optional[Tuple[Any, int, str]]:
+    try:
+        ai = node.get_action_iface()
+        if not ai:
+            return None
+        for i in range(ai.get_n_actions()):
+            try:
+                name = (ai.get_action_name(i) or "").strip().lower()
+            except Exception:
+                continue
+            for candidate in candidates:
+                if name == candidate or candidate in name:
+                    return ai, i, name
+    except Exception:
+        pass
+    return None
+
+
+def find_ui_elements_deep(
+    app_filter: Optional[str] = None,
+    region: Optional[list] = None,
+    name_filter: Optional[str] = None,
+    role_filter: Optional[str] = None,
+    interactable_only: bool = False,
+    include_hidden: bool = False,
+    max_depth: int = 40,
+) -> Dict[str, Any]:
+    if sys.platform == "win32":
+        if not UI_AUTOMATION_AVAILABLE:
+            return {
+                "available": False,
+                "backend": "uia",
+                "error": "uiautomation/pywin32 not installed",
+                "elements": [],
+                "windows": [],
+                "screen": {"width": 0, "height": 0},
+            }
+        result = _get_deep_ui_elements_win32(app_filter=app_filter, include_hidden=include_hidden, max_depth=max_depth)
+    else:
+        if not ATSPI_AVAILABLE:
+            return {
+                "available": False,
+                "backend": "atspi",
+                "error": "AT-SPI not available",
+                "elements": [],
+                "windows": [],
+                "screen": {"width": 0, "height": 0},
+            }
+        result = _get_deep_ui_elements_linux(app_filter=app_filter, include_hidden=include_hidden, max_depth=max_depth)
+
+    if not result.get("available"):
+        result["elements"] = []
+        return result
+
+    if region and result.get("ui_elements", {}).get("applications"):
+        apps = result["ui_elements"]["applications"]
+        filtered_apps, removed = _filter_apps_by_region(apps, region)
+        result["ui_elements"]["applications"] = filtered_apps
+        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + removed
+        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in filtered_apps)
+
+    if (name_filter or role_filter or interactable_only) and result.get("ui_elements", {}).get("applications"):
+        new_apps = []
+        removed_total = 0
+        for app in result["ui_elements"]["applications"]:
+            original_count = len(app["elements"])
+            kept = _filter_elements(app["elements"], name_filter, role_filter, interactable_only)
+            removed_total += original_count - len(kept)
+            if kept:
+                new_apps.append({
+                    "application": app["application"],
+                    "window_ids": app.get("window_ids", []),
+                    "elements": kept,
+                })
+        result["ui_elements"]["applications"] = new_apps
+        result["ui_elements"]["filtered_out"] = result["ui_elements"].get("filtered_out", 0) + removed_total
+        result["ui_elements"]["element_count"] = sum(len(a["elements"]) for a in new_apps)
+
+    flat = _flatten_applications(result["ui_elements"]["applications"])
+    flat.sort(key=lambda e: (
+        (e.get("bounds") or {}).get("y", 10**9),
+        (e.get("bounds") or {}).get("x", 10**9),
+        e.get("depth", 0),
+    ))
+    result["elements"] = flat
+    return result
+
+
+def get_focused_ui_element_deep(
+    app_filter: Optional[str] = None,
+    region: Optional[list] = None,
+    max_depth: int = 40,
+) -> Dict[str, Any]:
+    result = find_ui_elements_deep(
+        app_filter=app_filter,
+        region=region,
+        include_hidden=True,
+        max_depth=max_depth,
+    )
+    if not result.get("available"):
+        return result
+
+    candidates = []
+    for el in result.get("elements", []):
+        if el.get("backend") == "uia":
+            if el.get("states", {}).get("has_keyboard_focus"):
+                candidates.append(el)
+        else:
+            if "focused" in (el.get("states") or []):
+                candidates.append(el)
+
+    if not candidates:
+        return {
+            "available": True,
+            "backend": result.get("backend"),
+            "found": False,
+            "element": None,
+        }
+
+    candidates.sort(key=lambda e: (
+        -(e.get("depth", 0)),
+        ((e.get("bounds") or {}).get("w", 10**9) * (e.get("bounds") or {}).get("h", 10**9)),
+    ))
+    return {
+        "available": True,
+        "backend": result.get("backend"),
+        "found": True,
+        "element": candidates[0],
+    }
+
+
+def get_ui_element_at_point_deep(
+    x: int,
+    y: int,
+    app_filter: Optional[str] = None,
+    max_depth: int = 40,
+) -> Dict[str, Any]:
+    result = find_ui_elements_deep(
+        app_filter=app_filter,
+        include_hidden=False,
+        max_depth=max_depth,
+    )
+    if not result.get("available"):
+        return result
+
+    matches = [el for el in result.get("elements", []) if _element_contains_point(el, x, y)]
+    if not matches:
+        return {
+            "available": True,
+            "backend": result.get("backend"),
+            "found": False,
+            "element": None,
+        }
+
+    matches.sort(key=lambda e: (
+        ((e.get("bounds") or {}).get("w", 10**9) * (e.get("bounds") or {}).get("h", 10**9)),
+        -(e.get("depth", 0)),
+    ))
+    return {
+        "available": True,
+        "backend": result.get("backend"),
+        "found": True,
+        "element": matches[0],
+    }
+
+
+def get_ui_element_details(element_ref: Dict[str, Any]) -> Dict[str, Any]:
+    resolved = _resolve_ui_element(element_ref)
+    if not resolved.get("success"):
+        return {"found": False, "error": resolved.get("error")}
+
+    if resolved["backend"] == "uia":
+        el = _collect_uia_elements_deep(
+            resolved["node"],
+            app_name=resolved["app_name"],
+            window_ids=resolved["window_ids"],
+            path=list(element_ref.get("path") or []),
+            depth=0,
+            max_depth=0,
+        )[0]
+    else:
+        el = _collect_atspi_elements_deep(
+            resolved["node"],
+            app_name=resolved["app_name"],
+            window_ids=resolved["window_ids"],
+            path=list(element_ref.get("path") or []),
+            depth=0,
+            max_depth=0,
+        )[0]
+    return {"found": True, "element": el}
+
+
+def get_ui_element_parent(element_ref: Dict[str, Any]) -> Dict[str, Any]:
+    resolved = _resolve_ui_element(element_ref)
+    if not resolved.get("success"):
+        return {"found": False, "error": resolved.get("error")}
+
+    parent_path = list(element_ref.get("path") or [])[:-1]
+    if resolved["backend"] == "uia":
+        try:
+            parent = resolved["node"].GetParentControl()
+        except Exception as e:
+            return {"found": False, "error": str(e)}
+        if not parent:
+            return {"found": False, "error": "No parent element"}
+        element = _collect_uia_elements_deep(
+            parent,
+            app_name=resolved["app_name"],
+            window_ids=resolved["window_ids"],
+            path=parent_path,
+            depth=0,
+            max_depth=0,
+        )[0]
+    else:
+        try:
+            parent = resolved["node"].get_parent()
+        except Exception as e:
+            return {"found": False, "error": str(e)}
+        if not parent:
+            return {"found": False, "error": "No parent element"}
+        element = _collect_atspi_elements_deep(
+            parent,
+            app_name=resolved["app_name"],
+            window_ids=resolved["window_ids"],
+            path=parent_path,
+            depth=0,
+            max_depth=0,
+        )[0]
+    return {"found": True, "element": element}
+
+
+def get_ui_element_children(element_ref: Dict[str, Any], max_depth: int = 1) -> Dict[str, Any]:
+    resolved = _resolve_ui_element(element_ref)
+    if not resolved.get("success"):
+        return {"found": False, "error": resolved.get("error")}
+
+    max_depth = max(1, max_depth)
+    base_path = list(element_ref.get("path") or [])
+    elements: List[Dict[str, Any]] = []
+
+    if resolved["backend"] == "uia":
+        try:
+            children = resolved["node"].GetChildren() or []
+        except Exception as e:
+            return {"found": False, "error": str(e)}
+        for idx, child in enumerate(children):
+            elements.extend(
+                _collect_uia_elements_deep(
+                    child,
+                    app_name=resolved["app_name"],
+                    window_ids=resolved["window_ids"],
+                    path=base_path + [idx],
+                    depth=1,
+                    max_depth=max_depth,
+                )
+            )
+    else:
+        try:
+            child_count = resolved["node"].get_child_count()
+        except Exception as e:
+            return {"found": False, "error": str(e)}
+        for idx in range(child_count):
+            try:
+                child = resolved["node"].get_child_at_index(idx)
+            except Exception:
+                continue
+            elements.extend(
+                _collect_atspi_elements_deep(
+                    child,
+                    app_name=resolved["app_name"],
+                    window_ids=resolved["window_ids"],
+                    path=base_path + [idx],
+                    depth=1,
+                    max_depth=max_depth,
+                )
+            )
+
+    return {"found": True, "element_count": len(elements), "elements": elements}
+
+
+def _perform_uia_action(
+    control,
+    action: str,
+    text: Optional[str] = None,
+    value: Optional[float] = None,
+    x: Optional[int] = None,
+    y: Optional[int] = None,
+    width: Optional[int] = None,
+    height: Optional[int] = None,
+) -> Dict[str, Any]:
+    try:
+        if action == "focus":
+            try:
+                control.SetFocus()
+            except Exception:
+                control.SetActive()
+            return {"success": True, "message": "Focused element"}
+
+        if action in ("invoke", "click"):
+            try:
+                control.GetInvokePattern().Invoke()
+                return {"success": True, "message": "Invoked element"}
+            except Exception:
+                control.Click()
+                return {"success": True, "message": "Clicked element"}
+
+        if action == "get_text":
+            return {"success": True, **_uia_text_value_snapshot(control, max_chars=4000)}
+
+        if action in ("set_text", "append_text", "clear_text"):
+            target = text or ""
+            if action == "append_text":
+                snap = _uia_text_value_snapshot(control, max_chars=4000)
+                target = (snap.get("value") or snap.get("text") or "") + target
+            elif action == "clear_text":
+                target = ""
+            try:
+                control.GetValuePattern().SetValue(target)
+                return {"success": True, "message": f"{action} via ValuePattern"}
+            except Exception:
+                try:
+                    control.SetFocus()
+                except Exception:
+                    try:
+                        control.Click()
+                    except Exception:
+                        pass
+                try:
+                    control.SendKeys('{Ctrl}a{Del}')
+                except Exception:
+                    pass
+                if target:
+                    control.SendKeys(target)
+                return {"success": True, "message": f"{action} via SendKeys fallback"}
+
+        if action == "select":
+            try:
+                control.GetSelectionItemPattern().Select()
+            except Exception:
+                control.Select()
+            return {"success": True, "message": "Selected element"}
+
+        if action == "toggle":
+            control.GetTogglePattern().Toggle()
+            return {"success": True, "message": "Toggled element"}
+
+        if action == "expand":
+            control.GetExpandCollapsePattern().Expand()
+            return {"success": True, "message": "Expanded element"}
+
+        if action == "collapse":
+            control.GetExpandCollapsePattern().Collapse()
+            return {"success": True, "message": "Collapsed element"}
+
+        if action == "scroll_into_view":
+            control.GetScrollItemPattern().ScrollIntoView()
+            return {"success": True, "message": "Scrolled element into view"}
+
+        if action == "set_range_value":
+            if value is None:
+                return {"success": False, "error": "value is required for set_range_value"}
+            control.GetRangeValuePattern().SetValue(float(value))
+            return {"success": True, "message": f"Set range value to {value}"}
+
+        if action in ("move", "resize", "set_extents"):
+            tp = control.GetTransformPattern()
+            if action == "move":
+                if x is None or y is None:
+                    return {"success": False, "error": "x and y are required for move"}
+                tp.Move(x, y)
+                return {"success": True, "message": f"Moved element to ({x}, {y})"}
+            if action == "resize":
+                if width is None or height is None:
+                    return {"success": False, "error": "width and height are required for resize"}
+                tp.Resize(width, height)
+                return {"success": True, "message": f"Resized element to {width}x{height}"}
+            if x is None or y is None or width is None or height is None:
+                return {"success": False, "error": "x, y, width, height are required for set_extents"}
+            tp.Move(x, y)
+            tp.Resize(width, height)
+            return {"success": True, "message": f"Set element extents to ({x}, {y}, {width}, {height})"}
+
+        if action == "close":
+            try:
+                control.GetWindowPattern().Close()
+            except Exception:
+                control.GetTopLevelControl().GetWindowPattern().Close()
+            return {"success": True, "message": "Closed element/window"}
+
+        return {"success": False, "error": f"Unsupported UIA action: {action}"}
+    except Exception as e:
+        return {"success": False, "error": str(e)}
+
+
+def _perform_atspi_action(
+    node,
+    action: str,
+    text: Optional[str] = None,
+    value: Optional[float] = None,
+    x: Optional[int] = None,
+    y: Optional[int] = None,
+    width: Optional[int] = None,
+    height: Optional[int] = None,
+) -> Dict[str, Any]:
+    try:
+        if action == "focus":
+            comp = node.get_component_iface()
+            if not comp:
+                return {"success": False, "error": "Component interface not available"}
+            ok = comp.grab_focus()
+            return {"success": bool(ok), "message": "Focused element" if ok else "Could not focus element"}
+
+        if action in ("invoke", "click"):
+            picked = _pick_atspi_named_action(node, ["click", "press", "activate", "open", "jump"])
+            if not picked:
+                return {"success": False, "error": "No actionable AT-SPI action found"}
+            ai, index, name = picked
+            ok = ai.do_action(index)
+            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+
+        if action == "get_text":
+            return {"success": True, **_atspi_text_value_snapshot(node, max_chars=4000)}
+
+        if action in ("set_text", "append_text", "clear_text"):
+            editable = node.get_editable_text_iface()
+            if not editable:
+                return {"success": False, "error": "EditableText interface not available"}
+            if action == "clear_text":
+                ok = editable.set_text_contents("")
+                return {"success": bool(ok), "message": "Cleared text"}
+            if action == "set_text":
+                ok = editable.set_text_contents(text or "")
+                return {"success": bool(ok), "message": "Set text"}
+            ti = node.get_text_iface()
+            if not ti:
+                return {"success": False, "error": "Text interface not available for append_text"}
+            count = ti.get_character_count()
+            payload = text or ""
+            ok = editable.insert_text(count, payload, len(payload.encode("utf-8")))
+            return {"success": bool(ok), "message": "Appended text"}
+
+        if action == "select":
+            picked = _pick_atspi_named_action(node, ["select", "activate", "click"])
+            if picked:
+                ai, index, name = picked
+                ok = ai.do_action(index)
+                return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+            try:
+                parent = node.get_parent()
+                sel = parent.get_selection_iface() if parent else None
+                idx = node.get_index_in_parent()
+                if sel and idx >= 0:
+                    ok = sel.select_child(idx)
+                    return {"success": bool(ok), "message": "Selected element via Selection iface"}
+            except Exception:
+                pass
+            return {"success": False, "error": "No selection mechanism available"}
+
+        if action == "toggle":
+            picked = _pick_atspi_named_action(node, ["toggle", "press", "click", "activate"])
+            if not picked:
+                return {"success": False, "error": "No toggle-like AT-SPI action found"}
+            ai, index, name = picked
+            ok = ai.do_action(index)
+            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+
+        if action == "expand":
+            picked = _pick_atspi_named_action(node, ["expand", "open"])
+            if not picked:
+                return {"success": False, "error": "No expand-like AT-SPI action found"}
+            ai, index, name = picked
+            ok = ai.do_action(index)
+            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+
+        if action == "collapse":
+            picked = _pick_atspi_named_action(node, ["collapse", "close"])
+            if not picked:
+                return {"success": False, "error": "No collapse-like AT-SPI action found"}
+            ai, index, name = picked
+            ok = ai.do_action(index)
+            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+
+        if action == "scroll_into_view":
+            comp = node.get_component_iface()
+            if not comp:
+                return {"success": False, "error": "Component interface not available"}
+            ok = comp.scroll_to(Atspi.ScrollType.ANYWHERE)
+            return {"success": bool(ok), "message": "Scrolled element into view"}
+
+        if action == "set_range_value":
+            if value is None:
+                return {"success": False, "error": "value is required for set_range_value"}
+            vi = node.get_value_iface()
+            if not vi:
+                return {"success": False, "error": "Value interface not available"}
+            ok = vi.set_current_value(float(value))
+            return {"success": bool(ok), "message": f"Set range value to {value}"}
+
+        if action in ("move", "resize", "set_extents"):
+            comp = node.get_component_iface()
+            if not comp:
+                return {"success": False, "error": "Component interface not available"}
+            if action == "move":
+                if x is None or y is None:
+                    return {"success": False, "error": "x and y are required for move"}
+                ok = comp.set_position(x, y, Atspi.CoordType.SCREEN)
+                return {"success": bool(ok), "message": f"Moved element to ({x}, {y})"}
+            if action == "resize":
+                if width is None or height is None:
+                    return {"success": False, "error": "width and height are required for resize"}
+                ok = comp.set_size(width, height)
+                return {"success": bool(ok), "message": f"Resized element to {width}x{height}"}
+            if x is None or y is None or width is None or height is None:
+                return {"success": False, "error": "x, y, width, height are required for set_extents"}
+            ok = comp.set_extents(x, y, width, height, Atspi.CoordType.SCREEN)
+            return {"success": bool(ok), "message": f"Set element extents to ({x}, {y}, {width}, {height})"}
+
+        if action == "close":
+            picked = _pick_atspi_named_action(node, ["close"])
+            if not picked:
+                return {"success": False, "error": "No close-like AT-SPI action found"}
+            ai, index, name = picked
+            ok = ai.do_action(index)
+            return {"success": bool(ok), "message": f"Ran AT-SPI action: {name}"}
+
+        return {"success": False, "error": f"Unsupported AT-SPI action: {action}"}
+    except Exception as e:
+        return {"success": False, "error": str(e)}
+
+
+def perform_ui_action(
+    element_ref: Dict[str, Any],
+    action: str,
+    text: Optional[str] = None,
+    value: Optional[float] = None,
+    x: Optional[int] = None,
+    y: Optional[int] = None,
+    width: Optional[int] = None,
+    height: Optional[int] = None,
+) -> Dict[str, Any]:
+    resolved = _resolve_ui_element(element_ref)
+    if not resolved.get("success"):
+        return {"success": False, "error": resolved.get("error")}
+
+    if resolved["backend"] == "uia":
+        result = _perform_uia_action(
+            resolved["node"],
+            action=action,
+            text=text,
+            value=value,
+            x=x,
+            y=y,
+            width=width,
+            height=height,
+        )
+    else:
+        result = _perform_atspi_action(
+            resolved["node"],
+            action=action,
+            text=text,
+            value=value,
+            x=x,
+            y=y,
+            width=width,
+            height=height,
+        )
+
+    result["backend"] = resolved["backend"]
+    result["action"] = action
+    result["ref"] = element_ref
+    return result
```

And wrap it in `core.py`:

```diff
diff --git a/src/computer_control_mcp/core.py b/src/computer_control_mcp/core.py
--- a/src/computer_control_mcp/core.py
+++ b/src/computer_control_mcp/core.py
@@
 import json
 import ctypes
 import shutil
 import sys
 import os
 import time
 import subprocess
+from collections import deque
 from typing import Dict, Any, List, Optional, Tuple
@@
-from computer_control_mcp.ui_automation import get_ui_elements
+from computer_control_mcp.ui_automation import (
+    get_ui_elements,
+    find_ui_elements_deep,
+    get_focused_ui_element_deep,
+    get_ui_element_at_point_deep,
+    get_ui_element_details as _get_ui_element_details_deep,
+    get_ui_element_children as _get_ui_element_children_deep,
+    get_ui_element_parent as _get_ui_element_parent_deep,
+    perform_ui_action as _perform_ui_action_deep,
+)
@@
 try:
     from windows_capture import WindowsCapture, Frame, InternalCaptureControl
     WGC_AVAILABLE = True
 except ImportError:
     WGC_AVAILABLE = False
+
+try:
+    from watchdog.observers import Observer
+    from watchdog.events import FileSystemEventHandler
+    WATCHDOG_AVAILABLE = True
+except ImportError:
+    WATCHDOG_AVAILABLE = False
@@
 _last_screenshots: Dict[str, Any] = {}
 _last_ocr_results: Dict[str, Any] = {}
 _last_ui_elements: Dict[str, Any] = {}
+_file_watchers: Dict[str, Any] = {}
+_file_watch_lock = threading.Lock()
@@
 def _get_window_obj(title_pattern: str, use_regex: bool = False, threshold: int = 60):
@@
     if not matched:
         return None, f"Error: No window found matching pattern: {title_pattern}"
     return matched["window_obj"], None
+
+
+def _resolve_window_title_pattern(
+    title_pattern: str = None,
+    use_regex: bool = False,
+    threshold: int = 60,
+) -> Optional[str]:
+    """Resolve a fuzzy/regex title pattern to an exact current window title."""
+    if not title_pattern:
+        return None
+    all_windows = gw.getAllWindows()
+    windows = [{"title": w.title, "window_obj": w} for w in all_windows if w.title]
+    matched = _find_matching_window(windows, title_pattern, use_regex, threshold)
+    return matched["title"] if matched else title_pattern
+
+
+def _matches_pipe_filter(value: str, filter_value: str) -> bool:
+    if not filter_value:
+        return True
+    value_lower = (value or "").lower()
+    for term in filter_value.split("|"):
+        term = term.strip().lower()
+        if term and term in value_lower:
+            return True
+    return False
+
+
+class _QueuedFileWatchHandler(FileSystemEventHandler):
+    def __init__(self, queue: deque, allowed_types: Optional[set] = None):
+        super().__init__()
+        self.queue = queue
+        self.allowed_types = allowed_types
+
+    def _push(self, event_type: str, event):
+        if self.allowed_types and event_type not in self.allowed_types:
+            return
+        payload = {
+            "event_type": event_type,
+            "src_path": getattr(event, "src_path", None),
+            "dest_path": getattr(event, "dest_path", None),
+            "is_directory": bool(getattr(event, "is_directory", False)),
+            "timestamp": datetime.datetime.now().isoformat(),
+        }
+        self.queue.append(payload)
+
+    def on_created(self, event):
+        self._push("created", event)
+
+    def on_modified(self, event):
+        self._push("modified", event)
+
+    def on_deleted(self, event):
+        self._push("deleted", event)
+
+    def on_moved(self, event):
+        self._push("moved", event)
+
+    def on_closed(self, event):
+        self._push("closed", event)
+
+
+def _normalize_watch_paths(paths: Union[str, List[str]]) -> List[str]:
+    if isinstance(paths, str):
+        paths = [paths]
+    return [str(p) for p in (paths or []) if str(p).strip()]
+
+
+def _normalize_watch_event_types(event_types: Optional[Union[str, List[str]]]) -> Optional[set]:
+    if not event_types:
+        return None
+    if isinstance(event_types, str):
+        event_types = event_types.split("|")
+    out = {str(t).strip().lower() for t in event_types if str(t).strip()}
+    return out or None
@@
 @mcp.tool()
 def take_screenshot_with_ui_automation(
@@
         return json.dumps({"error": str(e), "available": False})
+
+
+@mcp.tool()
+def find_ui_elements(
+    title_pattern: str = None,
+    use_regex: bool = False,
+    threshold: int = 60,
+    region: list = None,
+    name_filter: str = None,
+    role_filter: str = None,
+    interactable_only: bool = False,
+    include_hidden: bool = False,
+    max_depth: int = 40,
+) -> str:
+    """Find deep UI automation elements with stable-ish refs and semantic metadata."""
+    try:
+        app_filter = _resolve_window_title_pattern(title_pattern, use_regex, threshold)
+        result = find_ui_elements_deep(
+            app_filter=app_filter,
+            region=region,
+            name_filter=name_filter,
+            role_filter=role_filter,
+            interactable_only=interactable_only,
+            include_hidden=include_hidden,
+            max_depth=max_depth,
+        )
+        return json.dumps(result, default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_focused_element(
+    title_pattern: str = None,
+    use_regex: bool = False,
+    threshold: int = 60,
+    region: list = None,
+    max_depth: int = 40,
+) -> str:
+    """Get the currently keyboard-focused accessible element."""
+    try:
+        app_filter = _resolve_window_title_pattern(title_pattern, use_regex, threshold)
+        result = get_focused_ui_element_deep(
+            app_filter=app_filter,
+            region=region,
+            max_depth=max_depth,
+        )
+        return json.dumps(result, default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_element_at_point(
+    x: int,
+    y: int,
+    title_pattern: str = None,
+    use_regex: bool = False,
+    threshold: int = 60,
+    max_depth: int = 40,
+) -> str:
+    """Hit-test the accessibility tree at a screen point."""
+    try:
+        app_filter = _resolve_window_title_pattern(title_pattern, use_regex, threshold)
+        result = get_ui_element_at_point_deep(
+            x=x,
+            y=y,
+            app_filter=app_filter,
+            max_depth=max_depth,
+        )
+        return json.dumps(result, default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_element_details(element_ref: Dict[str, Any]) -> str:
+    """Get rich details for a previously returned deep UI element ref."""
+    try:
+        return json.dumps(_get_ui_element_details_deep(element_ref), default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_element_children(element_ref: Dict[str, Any], max_depth: int = 1) -> str:
+    """Get child/descendant elements for a previously returned deep UI element ref."""
+    try:
+        return json.dumps(_get_ui_element_children_deep(element_ref, max_depth=max_depth), default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_element_parent(element_ref: Dict[str, Any]) -> str:
+    """Get the parent accessible element for a previously returned deep UI element ref."""
+    try:
+        return json.dumps(_get_ui_element_parent_deep(element_ref), default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def ui_action(
+    element_ref: Dict[str, Any],
+    action: str,
+    text: str = None,
+    value: float = None,
+    x: int = None,
+    y: int = None,
+    width: int = None,
+    height: int = None,
+) -> str:
+    """Perform a semantic UI automation / AT-SPI action on an element ref."""
+    try:
+        result = _perform_ui_action_deep(
+            element_ref=element_ref,
+            action=action,
+            text=text,
+            value=value,
+            x=x,
+            y=y,
+            width=width,
+            height=height,
+        )
+        return json.dumps(result, default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def focus_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="focus")
+
+
+@mcp.tool()
+def invoke_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="invoke")
+
+
+@mcp.tool()
+def set_element_text(element_ref: Dict[str, Any], text: str, append: bool = False) -> str:
+    return ui_action(
+        element_ref=element_ref,
+        action="append_text" if append else "set_text",
+        text=text,
+    )
+
+
+@mcp.tool()
+def get_element_text(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="get_text")
+
+
+@mcp.tool()
+def toggle_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="toggle")
+
+
+@mcp.tool()
+def select_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="select")
+
+
+@mcp.tool()
+def expand_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="expand")
+
+
+@mcp.tool()
+def collapse_element(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="collapse")
+
+
+@mcp.tool()
+def scroll_element_into_view(element_ref: Dict[str, Any]) -> str:
+    return ui_action(element_ref=element_ref, action="scroll_into_view")
+
+
+@mcp.tool()
+def set_element_range_value(element_ref: Dict[str, Any], value: float) -> str:
+    return ui_action(element_ref=element_ref, action="set_range_value", value=value)
+
+
+@mcp.tool()
+def move_element_ui(element_ref: Dict[str, Any], x: int, y: int) -> str:
+    return ui_action(element_ref=element_ref, action="move", x=x, y=y)
+
+
+@mcp.tool()
+def resize_element_ui(element_ref: Dict[str, Any], width: int, height: int) -> str:
+    return ui_action(element_ref=element_ref, action="resize", width=width, height=height)
+
+
+@mcp.tool()
+def set_element_extents(element_ref: Dict[str, Any], x: int, y: int, width: int, height: int) -> str:
+    return ui_action(
+        element_ref=element_ref,
+        action="set_extents",
+        x=x,
+        y=y,
+        width=width,
+        height=height,
+    )
+
+
+@mcp.tool()
+def get_active_window() -> str:
+    """Get the current foreground/active window."""
+    try:
+        window = gw.getActiveWindow()
+        if not window:
+            return json.dumps({"found": False, "error": "No active window"})
+        return json.dumps({
+            "found": True,
+            "title": window.title,
+            "left": window.left,
+            "top": window.top,
+            "width": window.width,
+            "height": window.height,
+            "is_minimized": window.isMinimized,
+            "is_maximized": window.isMaximized,
+        })
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+async def wait_for_window(
+    title_pattern: str,
+    mode: str = "appear",
+    use_regex: bool = False,
+    threshold: int = 60,
+    timeout_ms: int = 10000,
+    poll_interval_ms: int = 250,
+) -> str:
+    """Wait for a window to appear, disappear, or become active."""
+    try:
+        timeout_ms = min(max(timeout_ms, 100), 60000)
+        poll_interval_ms = max(poll_interval_ms, 50)
+        if mode not in ("appear", "disappear", "active"):
+            return json.dumps({"error": f"mode must be 'appear', 'disappear', or 'active', got '{mode}'"})
+
+        start = time.monotonic()
+        polls = 0
+        while True:
+            polls += 1
+            window, _ = _get_window_obj(title_pattern, use_regex, threshold)
+            found = window is not None
+            active = bool(found and getattr(window, "isActive", False))
+            elapsed_ms = round((time.monotonic() - start) * 1000)
+
+            if mode == "appear" and found:
+                return json.dumps({
+                    "found": True,
+                    "active": active,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": False,
+                    "title": window.title,
+                })
+            if mode == "disappear" and not found:
+                return json.dumps({
+                    "found": False,
+                    "active": False,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": False,
+                })
+            if mode == "active" and active:
+                return json.dumps({
+                    "found": True,
+                    "active": True,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": False,
+                    "title": window.title,
+                })
+
+            if elapsed_ms >= timeout_ms:
+                return json.dumps({
+                    "found": found,
+                    "active": active,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": True,
+                })
+
+            await asyncio.sleep(poll_interval_ms / 1000.0)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+async def wait_for_focused_element(
+    title_pattern: str = None,
+    use_regex: bool = False,
+    threshold: int = 60,
+    name_filter: str = None,
+    role_filter: str = None,
+    timeout_ms: int = 10000,
+    poll_interval_ms: int = 250,
+    max_depth: int = 40,
+) -> str:
+    """Wait until the currently focused accessible element matches name/role filters."""
+    try:
+        timeout_ms = min(max(timeout_ms, 100), 60000)
+        poll_interval_ms = max(poll_interval_ms, 50)
+        app_filter = _resolve_window_title_pattern(title_pattern, use_regex, threshold)
+
+        start = time.monotonic()
+        polls = 0
+        while True:
+            polls += 1
+            result = get_focused_ui_element_deep(app_filter=app_filter, max_depth=max_depth)
+            element = result.get("element")
+            matched = False
+            if element:
+                matched = (
+                    _matches_pipe_filter(element.get("name", ""), name_filter) and
+                    _matches_pipe_filter(element.get("role", ""), role_filter)
+                )
+            elapsed_ms = round((time.monotonic() - start) * 1000)
+
+            if matched:
+                return json.dumps({
+                    "found": True,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": False,
+                    "element": element,
+                }, default=str)
+
+            if elapsed_ms >= timeout_ms:
+                return json.dumps({
+                    "found": False,
+                    "elapsed_ms": elapsed_ms,
+                    "polls": polls,
+                    "timed_out": True,
+                    "element": element,
+                }, default=str)
+
+            await asyncio.sleep(poll_interval_ms / 1000.0)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
```

---

## Patch set 2: real filesystem watch/listen support

This adds:

* `start_file_watch`
* `get_file_watch_events`
* `stop_file_watch`
* `wait_for_file_change`

`watchdog` gives you a cross-platform filesystem event API, and its event model covers create/modify/delete/move/close style events. ([python-watchdog.readthedocs.io][4])

```diff
diff --git a/src/computer_control_mcp/core.py b/src/computer_control_mcp/core.py
--- a/src/computer_control_mcp/core.py
+++ b/src/computer_control_mcp/core.py
@@
 @mcp.tool()
 def get_system_info() -> str:
@@
     return json.dumps(info)
+
+
+@mcp.tool()
+def start_file_watch(
+    paths: Union[str, List[str]],
+    recursive: bool = True,
+    event_types: Union[str, List[str]] = None,
+    max_events: int = 500,
+) -> str:
+    """Start a persistent filesystem watch and return a watch_id."""
+    try:
+        if not WATCHDOG_AVAILABLE:
+            return json.dumps({"error": "watchdog is not installed"})
+
+        normalized_paths = _normalize_watch_paths(paths)
+        if not normalized_paths:
+            return json.dumps({"error": "No valid paths provided"})
+
+        allowed_types = _normalize_watch_event_types(event_types)
+        queue = deque(maxlen=max(10, max_events))
+        observer = Observer()
+        handler = _QueuedFileWatchHandler(queue=queue, allowed_types=allowed_types)
+
+        scheduled = []
+        for path in normalized_paths:
+            if not os.path.exists(path):
+                continue
+            observer.schedule(handler, path, recursive=recursive)
+            scheduled.append(path)
+
+        if not scheduled:
+            return json.dumps({"error": "None of the provided paths exist"})
+
+        observer.start()
+        watch_id = str(uuid.uuid4())
+        with _file_watch_lock:
+            _file_watchers[watch_id] = {
+                "observer": observer,
+                "queue": queue,
+                "paths": scheduled,
+                "recursive": recursive,
+                "event_types": sorted(list(allowed_types)) if allowed_types else None,
+                "created_at": datetime.datetime.now().isoformat(),
+            }
+
+        return json.dumps({
+            "started": True,
+            "watch_id": watch_id,
+            "paths": scheduled,
+            "recursive": recursive,
+            "event_types": sorted(list(allowed_types)) if allowed_types else None,
+        })
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def get_file_watch_events(
+    watch_id: str,
+    clear: bool = True,
+    max_events: int = 100,
+) -> str:
+    """Read queued events from a persistent file watch."""
+    try:
+        with _file_watch_lock:
+            watch = _file_watchers.get(watch_id)
+        if not watch:
+            return json.dumps({"error": f"Unknown watch_id: {watch_id}"})
+
+        queue = watch["queue"]
+        events = []
+        if clear:
+            while queue and len(events) < max_events:
+                events.append(queue.popleft())
+        else:
+            events = list(queue)[:max_events]
+
+        return json.dumps({
+            "watch_id": watch_id,
+            "event_count": len(events),
+            "events": events,
+            "remaining": len(queue),
+        }, default=str)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+def stop_file_watch(watch_id: str) -> str:
+    """Stop a persistent filesystem watch."""
+    try:
+        with _file_watch_lock:
+            watch = _file_watchers.pop(watch_id, None)
+        if not watch:
+            return json.dumps({"stopped": False, "error": f"Unknown watch_id: {watch_id}"})
+
+        observer = watch["observer"]
+        observer.stop()
+        observer.join(timeout=5)
+        return json.dumps({"stopped": True, "watch_id": watch_id})
+    except Exception as e:
+        return json.dumps({"error": str(e)})
+
+
+@mcp.tool()
+async def wait_for_file_change(
+    paths: Union[str, List[str]],
+    recursive: bool = True,
+    event_types: Union[str, List[str]] = None,
+    timeout_ms: int = 10000,
+) -> str:
+    """Wait once for the next filesystem change on one or more paths."""
+    try:
+        if not WATCHDOG_AVAILABLE:
+            return json.dumps({"error": "watchdog is not installed"})
+
+        normalized_paths = _normalize_watch_paths(paths)
+        if not normalized_paths:
+            return json.dumps({"error": "No valid paths provided"})
+
+        allowed_types = _normalize_watch_event_types(event_types)
+        queue = deque(maxlen=100)
+        event_flag = threading.Event()
+
+        class _OneShotHandler(_QueuedFileWatchHandler):
+            def _push(self, event_type: str, event):
+                super()._push(event_type, event)
+                event_flag.set()
+
+        observer = Observer()
+        handler = _OneShotHandler(queue=queue, allowed_types=allowed_types)
+
+        scheduled = []
+        for path in normalized_paths:
+            if not os.path.exists(path):
+                continue
+            observer.schedule(handler, path, recursive=recursive)
+            scheduled.append(path)
+
+        if not scheduled:
+            return json.dumps({"error": "None of the provided paths exist"})
+
+        observer.start()
+        try:
+            changed = await asyncio.to_thread(event_flag.wait, timeout_ms / 1000.0)
+            events = list(queue)
+            return json.dumps({
+                "changed": bool(changed),
+                "timed_out": not bool(changed),
+                "paths": scheduled,
+                "event_count": len(events),
+                "events": events,
+            }, default=str)
+        finally:
+            observer.stop()
+            observer.join(timeout=5)
+    except Exception as e:
+        return json.dumps({"error": str(e)})
```

---

## Patch set 3: small but important Linux support warning

Because your Linux window-layer is currently X11-oriented, I would also add a warning in `ui_automation.py` when running on Wayland so agents know when geometry/stacking/occlusion data is less trustworthy. `wmctrl` is documented as an X Window manager tool and `xprop` as an X server window/font property tool. ([linux.die.net][2])

```diff
diff --git a/src/computer_control_mcp/ui_automation.py b/src/computer_control_mcp/ui_automation.py
--- a/src/computer_control_mcp/ui_automation.py
+++ b/src/computer_control_mcp/ui_automation.py
@@
 def _get_windows_stacking_order_linux() -> List[Dict]:
     """Get windows with geometry from wmctrl, ordered by stacking (bottom to top)."""
+    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
+        return []
     env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":1")}
@@
 def _get_screen_size_linux() -> Tuple[int, int]:
     """Get screen dimensions on Linux via xdpyinfo or fallback."""
+    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
+        try:
+            import mss
+            with mss.mss() as sct:
+                mon = sct.monitors[0]
+                return mon["width"], mon["height"]
+        except Exception:
+            pass
     try:
         env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":1")}
@@
 def _get_ui_elements_linux(app_filter: Optional[str] = None) -> Dict:
@@
     return {
         "available": True,
         "error": None,
+        "warning": (
+            "Wayland session detected; AT-SPI is available, but X11-based window stacking/"
+            "occlusion data may be incomplete."
+            if (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"))
+            else None
+        ),
         "screen": {"width": screen_w, "height": screen_h},
         "windows": windows,
```

---

## Packages I would add

I’d add:

* `watchdog`
* keep your current Windows stack: `uiautomation` + `pywin32`
* on Ubuntu/X11: keep `python3-gi`, `gir1.2-atspi-2.0`, `at-spi2-core`, plus the X11 utilities your current code already depends on (`wmctrl`, `xprop`, `xdpyinfo`)

`watchdog` is the only new Python package I’d treat as strongly worth adding immediately. ([python-watchdog.readthedocs.io][4])

---

## What this gives you

After these patches, the MCP stops being mainly “screen bot” and starts becoming:

* a semantic desktop automation layer
* a tree/query/navigation layer
* an element action layer
* a filesystem watch layer
* a better waiting/orchestration layer

That is the right foundation for hard targets like VS Code, Electron apps, browser shells, rich native dialogs, tree views, list views, combo boxes, sliders, and document-like controls. The native accessibility models were designed to expose these behaviors and metadata programmatically. ([Microsoft Learn][1])

I would **not** put true long-lived native UI event subscriptions into the same patch yet. Both platforms support them — UI Automation has focus/property/structure/general event handlers, and AT-SPI exposes `EventListener.register` for focus, window, object, text, selection, and more — but getting lifecycle/threading right in a long-running MCP is a separate hardening pass. Ship the ref/action/introspection/watch layer first, then add native event subscriptions as phase 2. ([Microsoft Learn][5])

The one place I’m least certain is exact AT-SPI Python binding behavior for every method signature across Ubuntu versions; the APIs are right, but I would smoke-test those calls on your target image after patching.

[1]: https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview?utm_source=chatgpt.com "UI Automation Overview - Win32 apps"
[2]: https://linux.die.net/man/1/wmctrl?utm_source=chatgpt.com "wmctrl(1) - Linux man page"
[3]: https://github.com/yinkaisheng/Python-UIAutomation-for-Windows "https://github.com/yinkaisheng/Python-UIAutomation-for-Windows"
[4]: https://python-watchdog.readthedocs.io/?utm_source=chatgpt.com "Watchdog — watchdog 2.1.5 documentation"
[5]: https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/ui-automation-events-for-clients?utm_source=chatgpt.com "UI Automation Events for Clients - .NET Framework"
