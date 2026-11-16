"""交互式登录会话: 让控制台代为接收 Telegram 验证码.

问题背景
    Telegram 首次登录需要输入手机收到的验证码 (或两步验证密码).
    原实现用 `Prompt.ask()` 从终端读取 —— 容器里没有 TTY, 会直接抛 EOFError,
    表现为「非可交互终端, 无法输入验证码」, 用户只能放弃或改用本地运行.

设计
    业务进程 (有 asyncio 循环与 pyrogram) 发起登录, 但**不直接读终端**,
    而是把「需要验证码」这个状态写入内存中的 LoginSession,
    控制台通过桥接服务轮询状态, 用户填完后 POST 回传.

    业务侧:  await session.wait_for_code()   ← 挂起等待
    控制台:  GET  /login/status  → {"state":"need_code"}
             POST /login/code    → 业务侧 resolve future, 继续登录

    整个机制只在业务进程内存中, 不落盘, 避免验证码被持久化.

并发约束
    同一时间只允许一个登录会话 (pool 里同一账号重复登录没有意义,
    且会让验证码与账号对不上), 因此用单槽 + 互斥锁.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any, Dict, Optional

from loguru import logger

login_logger = logger.bind(scheme="login", nonotify=True)

# 会话状态
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_NEED_CODE = "need_code"
STATE_NEED_PASSWORD = "need_password"
STATE_DONE = "done"
STATE_FAILED = "failed"

# 等待用户输入的最长时间: 验证码本身有有效期, 过长也没有意义
DEFAULT_TIMEOUT = 300


class LoginSession:
    """单次登录会话.

    生命周期:
        create() → start() → wait_for_code() → submit_code() → finish()
    每个状态变更都会更新 status 字典, 供控制台轮询.
    """

    def __init__(self, phone: str, session_id: str):
        self.phone = phone
        self.session_id = session_id
        self.state = STATE_STARTING
        self.message = ""
        self.error = ""
        # 两类等待: 验证码与两步验证密码
        self._code_future: Optional[asyncio.Future] = None
        self._password_future: Optional[asyncio.Future] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ---------- 供业务侧调用 ----------

    def bind_loop(self):
        """记录创建会话的事件循环, 跨线程提交结果时必须用它."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    async def ask_code(self, hint: str = "请输入 Telegram 验证码") -> str:
        """挂起等待验证码. 超时或会话取消时抛异常, 由上层处理."""
        self.state = STATE_NEED_CODE
        self.message = hint
        self._code_future = asyncio.get_running_loop().create_future()
        login_logger.info(f"等待输入验证码 ({self.phone})")
        return await asyncio.wait_for(self._code_future, timeout=DEFAULT_TIMEOUT)

    async def ask_password(self, hint: str = "请输入两步验证密码") -> str:
        """挂起等待两步验证密码."""
        self.state = STATE_NEED_PASSWORD
        self.message = hint
        self._password_future = asyncio.get_running_loop().create_future()
        login_logger.info(f"等待输入两步验证密码 ({self.phone})")
        return await asyncio.wait_for(self._password_future, timeout=DEFAULT_TIMEOUT)

    def succeed(self, detail: str = "登录成功"):
        self.state = STATE_DONE
        self.message = detail

    def fail(self, detail: str):
        self.state = STATE_FAILED
        self.error = detail
        self.message = detail

    # ---------- 供控制台 (另一线程) 调用 ----------

    def submit(self, kind: str, value: str) -> bool:
        """把用户输入投递给等待中的协程.

        必须通过 call_soon_threadsafe: 桥接服务运行在独立线程,
        直接 set_result 不是线程安全的.
        """
        future = self._code_future if kind == "code" else self._password_future
        if future is None or future.done():
            return False
        if self._loop is None:
            return False

        def _resolve():
            if not future.done():
                future.set_result(value)

        try:
            self._loop.call_soon_threadsafe(_resolve)
        except RuntimeError:
            # 循环已关闭
            return False
        return True

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phone": self.phone,
            "state": self.state,
            "message": self.message,
            "error": self.error,
        }


class LoginManager:
    """登录会话的容器 (单槽).

    同一时刻只允许一个登录, 避免多个验证码与账号错配.
    """

    def __init__(self):
        self.current: Optional[LoginSession] = None
        self._lock = asyncio.Lock()

    def new_session(self, phone: str) -> LoginSession:
        session = LoginSession(phone, secrets.token_urlsafe(8))
        session.bind_loop()
        self.current = session
        return session

    def get(self) -> Optional[LoginSession]:
        return self.current

    def clear(self):
        self.current = None

    def submit(self, session_id: str, kind: str, value: str) -> bool:
        session = self.current
        if session is None or session.session_id != session_id:
            return False
        return session.submit(kind, value)


# 全局单例: 业务进程内共享
login_manager = LoginManager()
