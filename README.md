# iterm2-mcp

[![PyPI version](https://img.shields.io/pypi/v/iterm2-mcp-zanlan.svg)](https://pypi.org/project/iterm2-mcp-zanlan/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://pypi.org/project/iterm2-mcp-zanlan/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**English** | [简体中文](README.zh-CN.md)

An iTerm2 MCP server built around **visible execution**: every command is injected into a terminal session as **typed text (send text)** — exactly as if the user typed it — so everything stays on screen and under your supervision. **There is no exec / silent-execution tool of any kind.**

Inspired by electerm's MCP integration and [ferrislucas/iterm-mcp](https://github.com/ferrislucas/iterm-mcp), customized for multi-server profile management.

## Features

- **Connect via saved iTerm2 profiles**: open a new tab by profile name (or GUID); duplicate profile names raise an error listing all GUIDs — it never silently connects to the wrong machine
- **Visible execution**: `send_command` is equivalent to typing a command and pressing Enter; `send_text` feeds input step by step for REPLs / interactive programs. There is no execution channel that bypasses the terminal screen
- **Address sessions by name**: after a tab is created, its session is automatically registered under the profile name; the agent can rename it at any time, and all other tools address sessions by name
- **Auto-login**: when a profile auto-types its password, the server detects the password prompt and sends the confirming Enter for you
- Multi-session management: list / focus (switch tab) / close

## Tools

| Tool | Description |
|---|---|
| `list_profiles` | List all iTerm2 profile names (duplicates flagged) |
| `list_sessions` | List all window/tab/session entries (id, name, MCP name) |
| `create_session` | Open a new tab by profile name; session auto-named after the profile |
| `create_session_by_guid` | Open a tab by profile GUID (for disambiguating duplicate names) |
| `focus_session` | Focus the iTerm2 window on a session (select its tab and bring to front) |
| `close_session` | Close a session (by name or id) |
| `rename_session` | Rename a session |
| `send_command` | Send one line of command to a session (auto `\n`, visible as typed) |
| `send_text` | Send raw text/keystrokes to a session (for REPLs; no trailing newline) |
| `read_screen` | Read a session's current screen contents (line by line) |
| `interrupt` | Send Ctrl+C to a session |

Every tool that accepts a name also accepts a session id — the `name_or_id` parameter auto-detects.

## Requirements

- macOS + iTerm2 ≥ 3.5, with Settings → General → Magic → Enable Python API turned on
- Python 3.12+

## Install & Register

### Prerequisite: pipx or uv (pick one, if not installed yet)

Method 1 / Method 2 depend on the `pipx` / `uvx` commands. Install one first (via Homebrew on macOS):

```bash
brew install pipx          # https://pipx.pypa.io
# or
brew install uv            # https://docs.astral.sh/uv/ (provides uvx)
```

On machines without Homebrew, use the official installers at the links above — or skip ahead to Method 3.

### Method 1: pipx (recommended, isolated environment)

```bash
pipx install iterm2-mcp-zanlan
```

Then register (Claude Desktop / .mcp.json JSON config):

```json
{
  "mcpServers": {
    "iterm2": {
      "command": "iterm2-mcp"
    }
  }
}
```

One-liner for Claude Code:

```bash
claude mcp add iterm2 -- iterm2-mcp
```

### Method 2: uvx, zero install

```json
{
  "mcpServers": {
    "iterm2": {
      "command": "uvx",
      "args": ["iterm2-mcp-zanlan"]
    }
  }
}
```

### Method 3: from source

```bash
git clone https://github.com/Zane-lan/iterm2-mcp.git
cd iterm2-mcp
pip install iterm2 "mcp[cli]>=1,<2"   # homebrew Python: add --user --break-system-packages
```

```json
{
  "mcpServers": {
    "iterm2": {
      "command": "/path/to/python3.12",
      "args": ["/path/to/iterm2-mcp/src/iterm2_mcp/server.py"]
    }
  }
}
```

## Design decisions

1. **Duplicate-profile protection**: opening a tab by name that matches multiple profiles raises an error listing every GUID — the user picks one (or deletes the duplicates in iTerm2); a GUID-based tool is provided as the escape hatch
2. **Auto-naming on creation**: a tab opened via a profile is registered under the profile name, so later tools can address it by name
3. **Name addressing uses an MCP-maintained registry** (`~/.config/iterm2-mcp/registry.json`) — in practice, shell integration resets the session title back to an automatic name (e.g. `~ (-zsh)`) after every command via OSC escape sequences, so `session.name` is unreliable; `set_name` is still attempted for a readable tab title, but addressing never depends on it; a live `session.name` prefix match serves as fallback when the registry misses
4. **Send-only, no exec**: no tool in the set bypasses the terminal screen

## Verification

The end-to-end integration test runs against a real iTerm2 (opens tabs, sends commands, Ctrl+C, closes tabs):

```bash
python3.12 test_e2e.py
```

## Implementation notes (pitfalls found the hard way)

- iTerm2 3.6.x no longer listens on TCP 1912; the Python API moved to a Unix Domain Socket (`~/Library/Application Support/iTerm2/private/socket`), which the official `iterm2` package auto-detects
- When driving the iterm2 package from a custom event loop, you must also start the `Connection._async_dispatch_forever` dispatch loop — otherwise every RPC hangs forever
- `iterm2` 2.30: entry point is `iterm2.run_until_complete(coro)`; `ScreenContents` uses the `line(i)` method; `App.current_session` is gone
- FastMCP's lifespan must be passed to the `FastMCP(...)` constructor; setting `settings.lifespan` afterwards has no effect

## License

MIT
