# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Computer Control MCP is a Python MCP (Model Context Protocol) server that provides computer control capabilities (mouse, keyboard, screenshots, OCR) using PyAutoGUI, RapidOCR, and ONNXRuntime. It is published on PyPI as `computer-control-mcp`.

## Build & Development Commands

```bash
# Install in development mode (edits to source reflect immediately)
pip install -e .

# Run the MCP server
computer-control-mcp

# Run tests
python -m pytest

# Build distributable wheel (requires hatch: pip install hatch)
hatch build
```

## Architecture

### Source Layout (`src/computer_control_mcp/`)

- **core.py** — The main module. Contains all MCP tool definitions (`@mcp.tool()` decorated functions), the `FastMCP` server instance (`mcp`), screenshot logic (MSS and Windows Graphics Capture), OCR processing via RapidOCR, and window matching (fuzzy via fuzzywuzzy, regex). This is the file you'll modify most often.
- **cli.py** — CLI interface with subcommands (`server`, `click`, `type`, `screenshot`, `list-windows`, `gui`). Delegates to `core.py` tools via `mcp.call_tool()`. When no subcommand is given, runs the MCP server by default.
- **server.py** — Thin wrapper that imports and runs `main()` from `core.py`.
- **gui.py** — Tkinter-based GUI test harness for manual testing of click, type, and screenshot features.
- **`__main__.py`** — Entry point for `python -m computer_control_mcp`, delegates to CLI.

### Entry Points (defined in pyproject.toml)

- `computer-control-mcp` → `cli.py:main` (CLI with subcommands, default: run server)
- `computer-control-mcp-server` → `server.py:main` (direct server start)

### Key Patterns

- All MCP tools are registered on the module-level `mcp = FastMCP("ComputerControlMCP")` instance in `core.py`.
- Window matching uses `_find_matching_window()` which supports both fuzzy matching (fuzzywuzzy `partial_ratio`) and regex matching.
- Screenshots use `mss` library by default. On Windows, `windows-capture` (WGC) is optionally available for GPU-accelerated windows that render black with standard capture.
- WGC auto-detection is configured via the `COMPUTER_CONTROL_MCP_WGC_PATTERNS` env var (comma-separated window title substrings).
- Screenshot save directory is configurable via `COMPUTER_CONTROL_MCP_SCREENSHOT_DIR` env var, defaulting to OS downloads folder.
- Logging goes to stderr in development (`ENV=development`) and stdout in production.

### Tests (`tests/`)

Tests use pytest with `pytest-asyncio` for async tool tests. Tests create real tkinter windows and use actual `mcp.call_tool()` calls — they are integration tests that require a display/GUI environment.
