"""iTerm2 MCP Server — 可见执行（send-only）的 iTerm2 操作工具集.

设计决策（用户拍板）:
- profile 重名时报错并列出重名项 GUID，不静默选其一
- 按 profile 建 tab 后自动把 session 名设为 profile 名
- name 匹配容忍 iTerm2 自动追加的 shell 后缀（"name (-zsh)"）
- 只提供 send 式注入，无 exec 式静默执行
"""
import asyncio
import contextlib
from typing import AsyncIterator, Optional

import iterm2
from mcp.server.fastmcp import FastMCP

# iterm2.Connection 的连接由 lifespan 建立，各工具通过模块级变量访问
_conn: Optional[iterm2.Connection] = None


@contextlib.asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    global _conn
    # 复刻 iterm2.Connection.run() 的接线：async_connect(coro) 建 WebSocket 后
    # 执行 coro 作为连接主体；RPC 响应靠 _async_dispatch_forever 分发，
    # 不启动它所有请求都会挂起。coro 里先 set ready 再常驻分发。
    conn = iterm2.Connection()
    ready = asyncio.Event()

    async def _hold_and_dispatch(c):
        ready.set()
        await conn._async_dispatch_forever(c, asyncio.get_event_loop())

    ws_task = asyncio.ensure_future(conn.async_connect(_hold_and_dispatch))
    deadline = asyncio.get_event_loop().time() + 10
    while not ready.is_set():
        if asyncio.get_event_loop().time() > deadline or ws_task.done():
            raise RuntimeError("连接 iTerm2 失败（10 秒超时），请确认已开启 Python API")
        await asyncio.sleep(0.05)
    _conn = conn
    try:
        yield {"connection": _conn}
    finally:
        _conn = None
        ws_task.cancel()


mcp = FastMCP(
    "iterm2",
    instructions=(
        "iTerm2 终端操作工具集。使用指引:\n"
        "1. 连接服务器: create_session(profile=名字)，session 自动以 profile 名注册，"
        "之后所有工具用该名字寻址（name_or_id）\n"
        "2. 执行命令: 一律用 send_command（打字可见），不要尝试任何静默执行\n"
        "3. 上传/下载文件: 用 upload_file / download_file（Mac 主动 scp，公网服务器也可用），"
        "不要用 send_command 在服务器里反向 scp\n"
        "4. 首次对某台服务器传输文件前，先对该服务器已登录 session 调用一次 distribute_key"
        "（零密码配免密），之后传输全自动\n"
        "5. server_user/server_host 一旦 distribute_key 就固定了写法：后续 upload_file / "
        "download_file / check_transfer 必须传完全相同的 user@host 字符串。"
        "严禁把 IP 换成 localhost、主机名或别名——ssh 会当成另一个条目，免密失效。"
        "传错写法时工具会直接报错并列出已登记的写法，按提示改用登记的写法即可\n"
        "6. 传输后用 check_transfer 做 md5 校验；返回 NEED_INPUT 时提示用户在 local-shell "
        "tab 手动输密码，等待用户确认后重试\n"
        "7. 命令发出后用 read_screen 查看输出；需要中断用 interrupt\n"
        "8. 切换 iTerm2 窗口聚焦用 focus_session；本地 shell 传输通道是 local-shell "
        "（失效会自动重建）"
    ),
    lifespan=app_lifespan,
)

# name -> session_id 注册表。
# 背景: shell integration 会在每条命令后用 OSC 转义序列把 session 标题重置回
# 自动名（如 "~ (-zsh)"），session.name 不可靠。寻址以本注册表为准，
# set_name 仅尽力而为地让 tab 标题可见。
import json
import os

REGISTRY_PATH = os.path.expanduser("~/.config/iterm2-mcp/registry.json")


def _registry_load() -> dict:
    """读注册表。兼容两代结构：纯 name->id 映射（旧）或含 transfer_keys 段（新）."""
    try:
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _session_registry(reg: dict) -> dict[str, str]:
    """从注册表数据里取 name->session_id 段（兼容旧扁平结构）."""
    if "transfer_keys" in reg:
        return {k: v for k, v in reg.items() if k != "transfer_keys"}
    return reg


def _registry_save(reg: dict) -> None:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


def _registry_set(name: str, session_id: str) -> None:
    reg = _registry_load()
    sessions = _session_registry(reg)
    # 同一 session 换名时清理旧名
    sessions = {k: v for k, v in sessions.items() if v != session_id}
    sessions[name] = session_id
    _registry_write(sessions, _transfer_keys())


def _registry_id_for(name_or_id: str) -> Optional[str]:
    """注册表精确命中则返回 session_id，否则 None."""
    return _session_registry(_registry_load()).get(name_or_id)


def _registry_write(sessions: dict[str, str], transfer_keys: set[str]) -> None:
    """统一落盘：sessions 段 + （可选）transfer_keys 段."""
    data: dict = dict(sessions)
    if transfer_keys:
        data["transfer_keys"] = {k: True for k in sorted(transfer_keys)}
    _registry_save(data)


def _transfer_keys() -> set[str]:
    """已配免密的 user@host 集合."""
    reg = _registry_load()
    tk = reg.get("transfer_keys")
    return set(tk) if isinstance(tk, dict) else set()


def _transfer_key_set(user: str, host: str) -> None:
    keys = _transfer_keys()
    keys.add(user + "@" + host)
    _registry_write(_session_registry(_registry_load()), keys)


def _require_transfer_key(user: str, host: str) -> None:
    """传输前校验该 user@host 已配过免密，没配过就报错并提示已登记的写法.

    背景: distribute_key 的免密与 host key 都按调用时的精确写法生效——
    authorized_keys 是 per-user 的，known_hosts 按你敲的地址匹配。
    另一个会话用别名（localhost/主机名）传文件会静默卡在密码提示，
    这里把该故障提前变成显式报错。
    """
    known = _transfer_keys()
    if user + "@" + host in known:
        return
    listing = "\n".join(f"- {k}" for k in sorted(known)) or "（还没有任何登记）"
    raise ValueError(
        f"{user}@{host} 未配置过免密（或写法与 distribute_key 时不一致——"
        f"IP/主机名/localhost 会被 ssh 当成不同条目，请用与当时完全相同的写法）。"
        f"已登记的免密条目:\n{listing}\n"
        f"若确认是同一台机器但写法不同，请先用当时的 session 重新 distribute_key，"
        f"或对当前写法再 distribute_key 一次。"
    )




async def _get_app() -> iterm2.App:
    return await iterm2.async_get_app(_conn)


def _name_matches(session_name: str, target: str) -> bool:
    """session 名可能是 "target" 或 iTerm2 自动加后缀的 "target (xxx)"."""
    return session_name == target or session_name.startswith(target + " (")


async def _find_sessions(name_or_id: str) -> list[iterm2.Session]:
    """按注册表名 > session_id > 实时 session.name 的顺序查找，多命中时抛错."""
    app = await _get_app()
    # 1. 注册表精确命中
    reg_id = _registry_id_for(name_or_id)
    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                if session.session_id == name_or_id or (
                    reg_id and session.session_id == reg_id
                ):
                    return [session]
    # 2. 实时 session.name 兜底（用户在 iTerm2 里手动命名的场景）
    hits = []
    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                name = await session.async_get_variable("session.name")
                if _name_matches(name, name_or_id):
                    hits.append(session)
    return hits


async def _require_session(name_or_id: str) -> iterm2.Session:
    hits = await _find_sessions(name_or_id)
    if not hits:
        raise ValueError(f"未找到 session: {name_or_id!r}，请先 list_sessions 查看")
    if len(hits) > 1:
        names = [await s.async_get_variable("session.name") for s in hits]
        ids = [s.session_id for s in hits]
        listing = "\n".join(f"- name={n!r} id={i}" for n, i in zip(names, ids))
        raise ValueError(
            f"session 名 {name_or_id!r} 命中 {len(hits)} 个，请用完整 id 指定:\n{listing}"
        )
    return hits[0]


async def _resolve_profile(name: str) -> iterm2.Profile:
    """按名字解析 profile；重名时报错列出 GUID 让用户选择."""
    profiles = await iterm2.Profile.async_get(_conn)
    matches = [p for p in profiles if p.name == name]
    if not matches:
        raise ValueError(f"未找到 profile: {name!r}，请先 list_profiles 查看")
    if len(matches) > 1:
        guids = [p.guid for p in matches]
        listing = "\n".join(f"- guid={g}" for g in guids)
        raise ValueError(
            f"profile 名 {name!r} 存在重名（{len(matches)} 个），"
            f"请去 iTerm2 设置删除重名项，或用 create_session_by_guid 指定:\n{listing}"
        )
    return matches[0]


def _set_name_best_effort(session: iterm2.Session, name: str) -> None:
    """尽力设置 tab 标题。shell integration 会重置它，寻址不依赖此名字."""
    async def _do():
        try:
            await session.async_set_name(name)
        except Exception:
            pass
    asyncio.ensure_future(_do())


@mcp.tool()
async def list_profiles() -> str:
    """列出 iTerm2 所有 profile 名字，重名的会标注并列出 GUID."""
    profiles = await iterm2.Profile.async_get(_conn)
    by_name: dict[str, list[str]] = {}
    for p in profiles:
        by_name.setdefault(p.name, []).append(p.guid)
    lines = []
    for name, guids in sorted(by_name.items()):
        if len(guids) > 1:
            lines.append(f"{name}  [重名! guids: {', '.join(guids)}]")
        else:
            lines.append(name)
    return f"共 {len(profiles)} 个 profile:\n" + "\n".join(lines)


@mcp.tool()
async def list_sessions() -> str:
    """列出所有 iTerm2 窗口/tab/session，含 session id、name、所属 profile."""
    app = await _get_app()
    reg = _session_registry(_registry_load())
    id_to_reg_name = {v: k for k, v in reg.items()}
    lines = []
    for w_idx, window in enumerate(app.terminal_windows):
        for t_idx, tab in enumerate(window.tabs):
            for s in tab.sessions:
                name = await s.async_get_variable("session.name")
                profile = await s.async_get_variable("session.originalProfile")
                reg_name = id_to_reg_name.get(s.session_id)
                reg_tag = f"  mcp名={reg_name!r}" if reg_name else ""
                lines.append(
                    f"window{w_idx}/tab{t_idx}  name={name!r}{reg_tag}  "
                    f"profile={profile!r}  id={s.session_id}"
                )
    if not lines:
        return "没有打开的终端会话"
    return "\n".join(lines)


async def _create_tab(profile: str = None, guid: str = None, command: str = None) -> iterm2.Session:
    app = await _get_app()
    window = app.current_terminal_window
    if window is None:
        raise ValueError("没有已打开的 iTerm2 窗口，请先手动打开一个 iTerm2 窗口")
    tab = await window.async_create_tab(profile=profile, command=command, select=False)
    if tab is None or not tab.sessions:
        raise ValueError("tab 创建失败（返回为空）")
    return tab.sessions[0]


PASSWORD_PROMPTS = ("password:", "password：", "密码:")


async def _press_enter_on_password_prompt(session: iterm2.Session, wait: float = 8.0) -> str:
    """profile 自动键入密码后等回车确认。监测到密码提示符就补发回车（send 式可见），
    超时未出现则不动作。返回动作说明。"""
    deadline = asyncio.get_event_loop().time() + wait
    while asyncio.get_event_loop().time() < deadline:
        contents = await session.async_get_screen_contents()
        last = ""
        for i in range(contents.number_of_lines):
            text = contents.line(i).string
            if text.strip():
                last = text.lower()
        if any(p in last for p in PASSWORD_PROMPTS):
            await asyncio.sleep(0.5)  # 等密码自动键入完成
            await session.async_send_text("\r")
            return "检测到密码提示，已自动补发回车完成登录"
        await asyncio.sleep(0.3)
    return ""


@mcp.tool()
async def create_session(profile: str, command: str = "") -> str:
    """按 profile 名新建一个 tab，session 自动命名为 profile 名。

    profile 重名时会报错并列出所有重名 GUID。command 可选，为 tab 启动命令。
    若 profile 配置了自动键入密码，会在密码提示符出现后自动补发回车完成登录。
    """
    await _resolve_profile(profile)
    session = await _create_tab(profile=profile, command=command or None)
    _registry_set(profile, session.session_id)
    _set_name_best_effort(session, profile)
    login_note = await _press_enter_on_password_prompt(session)
    note = f"（{login_note}）" if login_note else ""
    return f"已创建 session: name={profile!r}  id={session.session_id}{note}"


@mcp.tool()
async def create_session_by_guid(guid: str, session_name: str = "") -> str:
    """按 GUID 新建 tab（用于 profile 重名时精确指定），可选自定义 session 名."""
    profiles = await iterm2.Profile.async_get(_conn, guids=[guid])
    if not profiles:
        raise ValueError(f"未找到 guid={guid!r} 的 profile")
    session = await _create_tab(profile=profiles[0].name)
    effective_name = session_name or profiles[0].name
    _registry_set(effective_name, session.session_id)
    if session_name:
        _set_name_best_effort(session, session_name)
    return f"已创建 session: name={effective_name!r}  id={session.session_id}"


@mcp.tool()
async def focus_session(name_or_id: str) -> str:
    """把 iTerm2 窗口聚焦到指定 session（选中其所在 tab 并把窗口带到前台）."""
    session = await _require_session(name_or_id)
    await session.async_activate()
    return f"已聚焦到 session {name_or_id!r}"


@mcp.tool()
async def close_session(name_or_id: str) -> str:
    """关闭指定 session（按 name 或 session id）。"""
    session = await _require_session(name_or_id)
    await session.async_close()
    sessions = {k: v for k, v in _session_registry(_registry_load()).items()
                if v != session.session_id}
    _registry_write(sessions, _transfer_keys())
    return f"已关闭 session {name_or_id!r}"


@mcp.tool()
async def rename_session(name_or_id: str, new_name: str) -> str:
    """重命名指定 session（iTerm2 显示时会自动带 shell 后缀）."""
    session = await _require_session(name_or_id)
    _registry_set(new_name, session.session_id)
    _set_name_best_effort(session, new_name)
    return f"已重命名为 {new_name!r}（寻址已更新；tab 标题可能被 shell 重置回自动名）"


@mcp.tool()
async def send_command(name_or_id: str, command: str) -> str:
    """向指定 session 发送一行命令（自动补换行，等价于用户手敲回车，终端可见）."""
    session = await _require_session(name_or_id)
    await session.async_send_text(command + "\n")
    return f"已发送: {command!r}（1 秒后可用 read_screen 查看输出）"


@mcp.tool()
async def send_text(name_or_id: str, text: str) -> str:
    """向指定 session 发送原始文本（不补换行），用于 REPL/交互式程序的逐步输入."""
    session = await _require_session(name_or_id)
    await session.async_send_text(text)
    return f"已发送文本（{len(text)} 字符）"


@mcp.tool()
async def read_screen(name_or_id: str, max_lines: int = 40) -> str:
    """读取指定 session 当前屏幕内容（可见区域，从上到下）."""
    session = await _require_session(name_or_id)
    contents = await session.async_get_screen_contents()
    lines = []
    for i in range(contents.number_of_lines):
        text = contents.line(i).string
        if text.strip():
            lines.append(text.rstrip())
    return "\n".join(lines[-max_lines:]) if lines else "(屏幕为空)"


@mcp.tool()
async def interrupt(name_or_id: str) -> str:
    """向指定 session 发送 Ctrl+C，中断当前正在运行的命令."""
    session = await _require_session(name_or_id)
    await session.async_send_text("\x03")
    return "已发送 Ctrl+C"


# ---------- 文件传输 ----------

TRANSFER_TIMEOUT = 120  # scp 等待完成的兜底超时（秒）


def _shquote(s: str) -> str:
    """shell 单引号转义，防路径/参数里的引号、$() 等元字符闭合引号注入命令."""
    return "'" + s.replace("'", "'\\''") + "'"


def _local_pubkey() -> str:
    """读 Mac 默认公钥（优先 ed25519）."""
    home = os.path.expanduser("~")
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        path = os.path.join(home, ".ssh", name)
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    raise ValueError("未找到 SSH 公钥（~/.ssh/id_ed25519.pub），请先 ssh-keygen -t ed25519 生成")


async def _is_local_session(s: iterm2.Session) -> bool:
    """判定本地 shell session: profile 的启动命令不是 ssh（SSH profile 的 Command 是 "ssh user@host"）."""
    try:
        prof = await s.async_get_profile()
        cmd = prof._simple_get("Command") or ""
        return not cmd.strip().lower().startswith("ssh")
    except Exception:
        return False


async def _find_local_session() -> iterm2.Session:
    """找一个本地 shell session（非 SSH 的 tab），用于 Mac 主动发起 scp.

    判定: session profile 的 Command 不是 ssh 开头（实测 session.host / session.tty
    都无法区分本地与 SSH tab，profile Command 是唯一可靠信号）。
    """
    app = await _get_app()
    sessions = [s for w in app.terminal_windows for t in w.tabs for s in t.sessions]
    # 优先: 注册表登记的 id 仍然存活且是本地 session
    reg_id = _session_registry(_registry_load()).get("local-shell")
    for s in sessions:
        if s.session_id == reg_id:
            return s
    # 兜底: 第一个本地 session
    for s in sessions:
        if await _is_local_session(s):
            return s
    raise ValueError("没有本地 shell session（将自动创建）")


async def _ensure_local_session() -> iterm2.Session:
    """获取可用的本地 session；注册表指向的已关闭则自动重建并重新登记."""
    try:
        return await _find_local_session()
    except ValueError:
        pass
    session = await _create_tab(profile="Default")
    _registry_set("local-shell", session.session_id)
    return session


@mcp.tool()
async def create_local_session() -> str:
    """新建一个本地 shell tab，注册为 'local-shell'，用于文件传输时 Mac 主动发起 scp."""
    session = await _create_tab(profile="Default")
    _registry_set("local-shell", session.session_id)
    return f"已创建本地 shell session: id={session.session_id}（注册名 local-shell）"


async def _prime_clean_screen(session: iterm2.Session, timeout: float = 6.0) -> str:
    """传输前把屏幕清干净，返回空串表示就绪，否则返回阻塞原因说明.

    直接发 clear 是不够的：若 screen 上还挂着一个交互式密码提示（上一次传输
    失败留下的），clear 会作为「密码」被吃掉，之后的 scp 命令与旧输出混在一屏，
    使 _wait_transfer_done 的状态判定失真。这里先 Ctrl+C 打断任何挂起进程、
    强制清屏，再等到屏幕稳定成单个提示符才继续。
    """
    # 1. 打断任何挂起的前台进程（挂着的密码提示、未结束的 scp）
    await session.async_send_text("\x03")
    await asyncio.sleep(0.4)
    # 2. 强制清屏并归位光标（不依赖 clear 命令是否被 shell 正常解释）
    await session.async_send_text("printf '\\033[2J\\033[H'\n")
    await asyncio.sleep(0.4)
    # 3. 等到屏幕不再变化（提示符重绘完成）
    deadline = asyncio.get_event_loop().time() + timeout
    last = None
    stable_since = None
    while asyncio.get_event_loop().time() < deadline:
        contents = await session.async_get_screen_contents()
        lines = [contents.line(i).string.rstrip() for i in range(contents.number_of_lines)
                 if contents.line(i).string.strip()]
        screen = "\n".join(lines)
        if screen != last:
            last = screen
            stable_since = None
        else:
            if stable_since is None:
                stable_since = asyncio.get_event_loop().time()
            elif asyncio.get_event_loop().time() - stable_since >= 0.5:
                return ""
        await asyncio.sleep(0.25)
    return "TIMEOUT: 无法取得干净的 local-shell 屏幕（可能有前台进程占着终端）"


async def _wait_transfer_done(session: iterm2.Session, timeout: float = TRANSFER_TIMEOUT) -> str:
    """等待 scp 传输结束：提示符回归（屏幕最后一行不再变化且含主机名提示）或出现错误."""
    deadline = asyncio.get_event_loop().time() + timeout
    last_screen = ""
    stable_since = None
    while asyncio.get_event_loop().time() < deadline:
        contents = await session.async_get_screen_contents()
        lines = [contents.line(i).string.rstrip() for i in range(contents.number_of_lines)
                 if contents.line(i).string.strip()]
        screen = "\n".join(lines)
        if screen != last_screen:
            last_screen = screen
            stable_since = None
        else:
            if stable_since is None:
                stable_since = asyncio.get_event_loop().time()
            elif asyncio.get_event_loop().time() - stable_since >= 2.0:
                last = lines[-1] if lines else ""
                low = last.lower()
                if "password" in low or "yes/no" in low:
                    return "NEED_INPUT: " + last
                if "denied" in low or "not found" in low or "no such file" in low:
                    return "ERROR: " + last
                return "DONE\n" + screen[-500:]
        await asyncio.sleep(0.5)
    return "TIMEOUT: 传输超过 " + str(int(timeout)) + " 秒仍未结束"


@mcp.tool()
async def upload_file(session_name: str, local_path: str, remote_path: str,
                      server_user: str, server_host: str) -> str:
    """上传本地文件到服务器（推荐方式；Mac 主动发起 scp，任何网络拓扑可用，含公网服务器）.

    不要用 send_command 发送 scp——请直接调用本工具。
    服务器应已通过 distribute_key 配置免密；若返回 NEED_INPUT，提示用户在 local-shell
    tab 里手动输入服务器密码。传输完成自动校验本地文件是否生成。

    Args:
        session_name: 仅作标识，实际传输统一走 local-shell
        local_path: Mac 上的源文件绝对路径
        remote_path: 服务器上的目标路径（目录以 / 结尾）
        server_user: 服务器登录用户名
        server_host: 服务器地址（IP 或域名）
    """
    if not os.path.exists(local_path):
        raise ValueError(f"本地文件不存在: {local_path}")
    _require_transfer_key(server_user, server_host)
    local = await _ensure_local_session()
    blocked = await _prime_clean_screen(local)
    if blocked:
        return f"传输未开始：{blocked}"
    await local.async_send_text(
        f"scp {_shquote(local_path)} {_shquote(server_user + '@' + server_host + ':' + remote_path)}\n"
    )
    result = await _wait_transfer_done(local)
    if result.startswith("NEED_INPUT"):
        return f"scp 已发出，等待认证。请在 local-shell tab 里输入服务器密码: {result[11:]}"
    if result.startswith("ERROR"):
        return f"传输失败: {result[6:]}"
    if result.startswith("TIMEOUT"):
        return result
    return f"上传完成: {local_path} -> {server_user}@{server_host}:{remote_path}\n终端输出:\n{result[5:]}"


@mcp.tool()
async def download_file(session_name: str, remote_path: str, local_path: str,
                        server_user: str, server_host: str) -> str:
    """从服务器下载文件到本地（推荐方式；Mac 主动发起 scp，任何网络拓扑可用，含公网服务器）.

    不要在服务器 session 里用 send_command 发 scp 反向拉取——服务器可能路由不到 Mac。
    请直接调用本工具。服务器应已通过 distribute_key 配置免密；若返回 NEED_INPUT，
    提示用户在 local-shell tab 里手动输入服务器密码。

    Args:
        session_name: 仅作标识，实际传输统一走 local-shell
        remote_path: 服务器上的源文件绝对路径
        local_path: Mac 上的目标路径（目录则自动补文件名）
        server_user: 服务器登录用户名
        server_host: 服务器地址（IP 或域名）
    """
    _require_transfer_key(server_user, server_host)
    local = await _ensure_local_session()
    if os.path.isdir(local_path):
        local_path = os.path.join(local_path, os.path.basename(remote_path))
    blocked = await _prime_clean_screen(local)
    if blocked:
        return f"传输未开始：{blocked}"
    await local.async_send_text(
        f"scp {_shquote(server_user + '@' + server_host + ':' + remote_path)} {_shquote(local_path)}\n"
    )
    result = await _wait_transfer_done(local)
    if result.startswith("NEED_INPUT"):
        return f"scp 已发出，等待认证。请在 local-shell tab 里输入服务器密码: {result[11:]}"
    if result.startswith("ERROR"):
        return f"传输失败: {result[6:]}"
    if result.startswith("TIMEOUT"):
        return result
    exists = os.path.exists(local_path)
    return (f"下载完成: {server_user}@{server_host}:{remote_path} -> {local_path}"
            f"（本地文件{'已生成' if exists else '未找到!'}）\n终端输出:\n{result[5:]}")


async def _preset_host_key(local: iterm2.Session, server_host: str) -> bool:
    """在本地 session 里预扫描目标服务器 host key 写入 known_hosts，消除首连指纹确认.

    已知主机则跳过。返回是否新扫描了。
    """
    proc = await asyncio.create_subprocess_exec(
        "ssh-keygen", "-lF", server_host,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    if proc.returncode == 0:
        return False
    scan = await asyncio.create_subprocess_exec(
        "ssh-keyscan", "-T", "5", server_host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    keys, _ = await scan.communicate()
    valid = [l for l in keys.decode().splitlines() if l and not l.startswith("#")]
    if not valid:
        return False
    home = os.path.expanduser("~")
    with open(os.path.join(home, ".ssh", "known_hosts"), "a") as f:
        f.write("\n".join(valid) + "\n")
    return True


@mcp.tool()
async def distribute_key(name_or_id: str, server_user: str, server_host: str) -> str:
    """向已登录的服务器 session 分发 Mac 公钥（send 注入 authorized_keys，无需密码）.

    同时预扫描服务器 host key 到本地 known_hosts，消除之后 scp 的首连指纹确认。
    一次性配置；之后该服务器对 Mac 免密，scp/ssh 全自动。

    使用时机: 首次要对某台服务器 upload_file/download_file 之前，先对本服务器的
    已登录 session 调用一次本工具。全程零密码。

    注意: server_user/server_host 会被登记为该服务器的免密写法，之后传输工具
    必须用完全相同的写法（known_hosts 按 host 写法精确匹配）。
    """
    session = await _require_session(name_or_id)
    pubkey = _local_pubkey()
    escaped = pubkey.replace("'", "'\\''")
    await session.async_send_text(
        f"mkdir -p ~/.ssh && echo '{escaped}' >> ~/.ssh/authorized_keys "
        f"&& chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys && echo KEY_DISTRIBUTED\n"
    )
    await asyncio.sleep(2)
    contents = await session.async_get_screen_contents()
    screen = "".join(contents.line(i).string for i in range(contents.number_of_lines))
    scanned = ""
    try:
        local = await _ensure_local_session()
        if await _preset_host_key(local, server_host):
            scanned = "，并已预扫描 host key（之后 scp 无首次指纹确认）"
    except ValueError:
        pass  # 没有本地 session 时跳过预扫描，不阻塞公钥分发
    if "KEY_DISTRIBUTED" in screen:
        _transfer_key_set(server_user, server_host)
        return f"公钥已分发到 {name_or_id}{scanned}。之后对 {server_user}@{server_host} 的 scp/ssh 免密（免密写法已登记为 {server_user}@{server_host}，传输时请用相同写法）"
    return f"分发命令已发出，请用 read_screen 确认结果{scanned}"


@mcp.tool()
async def check_transfer(session_name: str, remote_path: str, local_path: str,
                         server_user: str, server_host: str) -> str:
    """传输后完整性校验：对比远端 md5sum 与本地 md5."""
    import hashlib
    def _md5(p):
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    if not os.path.exists(local_path):
        return f"本地文件不存在: {local_path}"
    _require_transfer_key(server_user, server_host)
    local_md5 = _md5(local_path)
    local = await _ensure_local_session()
    blocked = await _prime_clean_screen(local)
    if blocked:
        return f"校验未开始：{blocked}"
    # 远端路径要过两层 shell：本地引号保证完整送达远端命令行，再对远端 shell 转义一次
    remote_cmd = "md5sum " + _shquote(remote_path)
    await local.async_send_text(
        f"ssh {_shquote(server_user + '@' + server_host)} {_shquote(remote_cmd)}\n"
    )
    result = await _wait_transfer_done(local, timeout=30)
    if result.startswith("NEED_INPUT"):
        return f"等待认证。请在 local-shell tab 里输入服务器密码: {result[11:]}"
    remote_line = result
    import re
    m = re.search(r"([0-9a-f]{32})", remote_line)
    if not m:
        return f"未解析到远端 md5。终端输出:\n{result[-300:]}"
    remote_md5 = m.group(1)
    ok = remote_md5 == local_md5
    return f"本地 {local_md5} / 远端 {remote_md5} -> {'✅ 一致' if ok else '❌ 不一致'}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
