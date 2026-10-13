"""验证外部 Python 进程能否通过 WebSocket 操作 iTerm2 Python API"""
import asyncio
import sys

import iterm2


async def main(conn):
    print("1. 已连接 iTerm2 (localhost:1912)")
    app = await iterm2.async_get_app(conn)
    win = app.current_terminal_window
    if not win:
        print("   没有可用的 iTerm2 窗口")
        sys.exit(1)

    print(f"2. 列出会话: {len(win.tabs)} 个 tab")
    sessions = []
    for tab in win.tabs:
        for s in tab.sessions:
            sessions.append(s)
            name = await s.async_get_variable("session.name")
            print(f"   - session {s.session_id[:8]}... name={name!r}")

    session = sessions[-1] if sessions else None
    if session is None:
        session = sessions[0]
    print(f"3. 向当前会话写入文本 echo ...")

    marker = "ITERM_MCP_VERIFY_OK"
    await session.async_send_text(f"echo {marker}\n")

    # 等待 echo 完成，再直接读屏幕内容
    await asyncio.sleep(1)
    got = []
    # 也可以直接读屏幕内容
    contents = await session.async_get_screen_contents()
    lines = [contents.line(i).string for i in range(contents.number_of_lines)
             if contents.line(i).string.strip()]
    print(f"5. 屏幕内容最后 5 行:")
    for l in lines[-5:]:
        print(f"   | {l}")

    ok = any(marker in "".join(got) for _ in [0]) or any(marker in l for l in lines)
    print(f"\n验证结果: {'✅ 全链路通' if ok else '❌ 未捕获到 echo 输出，检查上面各步'}")

asyncio.run(iterm2.run_until_complete(main))
