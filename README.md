# iterm2-mcp

一个「可见执行」理念的 iTerm2 MCP server：所有命令都以**打字方式（send text）**注入终端 session，与用户手敲完全一致，全程肉眼可监督。**不提供任何 exec / 静默执行类工具。**

灵感来自 electerm 的 MCP 集成与 [ferrislucas/iterm-mcp](https://github.com/ferrislucas/iterm-mcp)，但面向「多服务器 profile 管理」场景做了定制。

## 特性

- **连接 iTerm2 保存的 profiles**：按 profile 名（或 GUID）新建 tab；profile 重名时报错列出 GUID，绝不静默选错机器
- **可见执行**：`send_command` 等价于用户手敲命令并回车；`send_text` 用于 REPL / 交互式程序的逐步输入。没有绕过终端屏幕的执行通道
- **按名寻址**：建 tab 后 session 自动以 profile 名注册，agent 可随时重命名，之后所有工具用名字操作
- **自动登录**：profile 配置了自动键入密码时，检测到密码提示符自动补发回车完成登录
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

所有支持 name 寻址的工具同时接受 session id，`name_or_id` 参数自动识别。

## 环境要求

- macOS + iTerm2 ≥ 3.5（在 Settings → General → Magic → Enable Python API 开启）
- Python 3.12+

## 安装

```bash
pip install iterm2 "mcp[cli]"
# homebrew Python 需加 --user --break-system-packages
```

## 注册

JSON 配置方式（Claude Desktop / .mcp.json 通用）：

```json
{
  "mcpServers": {
    "iterm2": {
      "command": "/path/to/python3.12",
      "args": ["/path/to/server.py"]
    }
  }
}
```

Claude Code 命令行方式：

```bash
claude mcp add iterm2 -- /path/to/python3.12 /path/to/server.py
```

## 设计决策

1. **profile 重名防呆**：按名字建 tab 时若命中多个 profile，报错并列出所有重名 profile 的 GUID，由用户选择或去 iTerm2 删除重名项；另提供按 GUID 建立的工具
2. **建 tab 自动命名**：通过 profile 建 tab 后，session 自动命名为 profile 名，后续按 name 寻址
3. **name 寻址以 MCP 维护的注册表为准**（`~/.config/iterm2-mcp/registry.json`）——实测发现 shell integration 会在每条命令后用 OSC 转义序列把 session 标题重置回自动名（`~ (-zsh)`），`session.name` 不可靠，所以 `set_name` 仅尽力让 tab 标题可见，寻址不受影响；注册表未命中时兜底做实时 `session.name` 前缀匹配
4. **只 send，不 exec**：工具集里不存在绕过终端屏幕的执行通道

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
