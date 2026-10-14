"""集成验证：直接调用 server.py 中的工具函数（跳过 MCP 协议层，验证业务逻辑）.

验证项:
1. list_profiles（含重名标注）
2. create_session 按 profile 建 tab + 自动命名
3. create_session 重名 profile 报错列出 GUID
4. send_command 打字可见 + read_screen 读回输出
5. rename_session + 按 name 寻址
6. interrupt
7. close_session 清理
"""
import asyncio
import sys

import iterm2

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "src"))
from iterm2_mcp import server  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"{'✅' if ok else '❌'} {name}  {detail}")


async def main(conn):
    server._conn = conn

    # 1. list_profiles
    out = await server.list_profiles()
    check("list_profiles", "共 " in out and "[重名!" in out, out.split("\n")[0])

    # 找一个无重名的 profile 用于建 tab 测试
    profiles = await iterm2.Profile.async_get(conn)
    from collections import Counter
    cnt = Counter(p.name for p in profiles)
    dup_name = next(n for n, c in cnt.items() if c > 1)
    unique_name = next(n for n, c in cnt.items() if c == 1)
    print(f"   测试用: 唯一名={unique_name!r} 重名={dup_name!r}")

    # 3. 重名 profile 应报错并列 GUID（先测，免得污染环境）
    try:
        await server.create_session(profile=dup_name)
        check("重名 profile 报错", False, "居然没报错")
    except ValueError as e:
        check("重名 profile 报错", "guid=" in str(e), str(e)[:80])

    # 2. 唯一 profile 建 tab + 自动命名
    out = await server.create_session(profile=unique_name)
    check("create_session+自动命名", "已创建 session" in out and "id=" in out, out)
    sid = out.split("id=")[1].strip()

    # 4. send_command + read_screen
    marker = "MCP_E2E_8848"
    out = await server.send_command(sid, f"echo {marker}")
    check("send_command", "已发送" in out)
    await asyncio.sleep(1.5)
    screen = await server.read_screen(sid)
    check("read_screen 捕获输出", marker in screen, f"屏含 marker={marker in screen}")

    # 5. rename + name 寻址
    await server.rename_session(sid, "mcp-e2e-renamed")
    out = await server.send_command("mcp-e2e-renamed", "echo by-name")
    check("rename后按name寻址", "已发送" in out)
    await asyncio.sleep(1.2)
    screen = await server.read_screen("mcp-e2e-renamed")
    check("按name读屏", "by-name" in screen)

    # 6. interrupt: 跑一个 sleep 30 再 Ctrl+C
    await server.send_command(sid, "sleep 30")
    await asyncio.sleep(0.5)
    out = await server.interrupt(sid)
    check("interrupt", "Ctrl+C" in out)
    await asyncio.sleep(1.0)
    screen = await server.read_screen(sid)
    # 实测: Ctrl+C 后屏幕出现 "^C" 行，且新提示符带 "✘" 标记（powerlevel10k），以空格结尾
    check("Ctrl+C 生效(^C+新提示符)", "^C" in screen and "✘" in screen,
          screen.rstrip().split("\n")[-1][-40:])

    # 7. close 清理
    out = await server.close_session(sid)
    check("close_session", "已关闭" in out)
    app = await iterm2.async_get_app(conn)
    alive = [s for w in app.terminal_windows for t in w.tabs for s in t.sessions
             if s.session_id == sid]
    check("session 确实已关", len(alive) == 0)


iterm2.run_until_complete(main)
print(f"\n结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
