"""运维兜底：在服务器上直接重置某个用户的密码（不走 HTTP）。

用法（在 backend 目录下执行）：
    ..\\.venv\\Scripts\\python.exe -m tools.reset_password <用户名> [新密码]

不传新密码时随机生成一个并打印。执行后该用户所有已登录会话立即失效。
"""

from __future__ import annotations

import secrets
import sys

import auth
import auth_store


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m tools.reset_password <用户名> [新密码]")
        return 1
    username = sys.argv[1].strip()
    password = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(9)
    auth_store.init_db()
    user = auth_store.get_user_by_username(username)
    if user is None:
        print(f"用户不存在：{username}")
        return 1
    auth.change_password(user["user_id"], password)
    print(f"已重置 {user['username']} 的密码：{password}")
    print("该用户所有已登录会话已失效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
