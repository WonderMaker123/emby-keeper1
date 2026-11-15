"""运行时服务: 将签到/保活的编排逻辑从 CLI 中解耦, 供 CLI 与 Web 共同复用.

设计目的:
    - CLI 与 Web 端共用同一套模块启停逻辑, 避免两处实现漂移;
    - 对外提供 snapshot() / trigger() 等接口, 使 Web 端能读取运行状态并手动触发任务;
    - 状态变更通过监听器回调推送, 不直接依赖 Flask/SocketIO.
"""

import asyncio
from typing import Callable, Dict, List, Optional

from loguru import logger

from .config import config
from .runinfo import RunContext, RunStatus
from .utils import AsyncTaskPool, show_exception

logger = logger.bind(scheme="runtime")


class RuntimeService:
    """模块运行时.

    用法:
        runtime = RuntimeService(checkiner=True, emby=True, subsonic=True)
        await runtime.start(instant=True, once=False)
        ...
        await runtime.stop()
    """

    def __init__(self, checkiner: bool = True, emby: bool = True, subsonic: bool = True):
        self.enabled = {"checkiner": checkiner, "emby": emby, "subsonic": subsonic}
        self.checkin_man = None
        self.emby_man = None
        self.subsonic_man = None
        self.pool: Optional[AsyncTaskPool] = None
        self.streams = None
        self._running = False
        self._manual_running = False
        self._finished = asyncio.Event()
        self._listeners: List[Callable[[List[dict]], None]] = []
        self._main_task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self._running

    def add_listener(self, callback: Callable[[List[dict]], None]):
        """注册状态变更监听器, 用于向 Web 端推送快照."""
        self._listeners.append(callback)

    def _notify(self):
        """向所有监听器推送当前快照, 单个监听器异常不影响其他监听器."""
        if not self._listeners:
            return
        snapshot = self.snapshot()
        for callback in list(self._listeners):
            try:
                callback(snapshot)
            except Exception as e:
                logger.debug(f"状态监听器执行失败: {e.__class__.__name__}: {e}")

    def snapshot(self) -> dict:
        """返回可跨线程安全传递的运行时快照."""
        managers = {}
        for name, manager in (
            ("checkiner", self.checkin_man),
            ("emby", self.emby_man),
            ("subsonic", self.subsonic_man),
        ):
            managers[name] = {
                "enabled": self.enabled.get(name, False),
                "loaded": manager is not None,
            }
        return {
            "running": self._running,
            "managers": managers,
            "tasks": RunContext.snapshot(include_logs=True),
        }

    def _build_managers(self):
        """按开关构建各模块管理器."""
        if self.enabled["checkiner"]:
            from .telegram.checkin_main import CheckinerManager

            self.checkin_man = CheckinerManager()
        if self.enabled["emby"]:
            from .emby.main import EmbyManager

            self.emby_man = EmbyManager()
        if self.enabled["subsonic"]:
            from .subsonic.main import SubsonicManager

            self.subsonic_man = SubsonicManager()

    async def run_all(self, instant: bool = False):
        """立即执行一次全部任务 (对应 CLI 的 --instant)."""
        pool = AsyncTaskPool()
        if self.checkin_man:
            pool.add(self.checkin_man.run_all(instant=True), "站点签到")
        if self.emby_man:
            pool.add(self.emby_man.run_all(instant=True), "Emby 保活")
        if self.subsonic_man:
            pool.add(self.subsonic_man.run_all(instant=True), "Subsonic 保活")
        await pool.wait()

    async def run_once(self) -> dict:
        """立即执行一次全部任务, 供 Web 端「立即运行」按钮调用.

        与 run_all 的区别:
            - run_all 在 start() 内部调用, 处于启动阶段, 管理器尚在构建;
            - run_once 在已运行状态下调用, 不阻塞既有计划任务, 也不会重复构建管理器.
        并发保护: 若已有一次手动执行在进行, 直接返回稍后重试, 避免重复冲击站点.
        """
        if not self._running:
            return {"ok": False, "message": "运行时尚未启动"}
        if self._manual_running:
            return {"ok": False, "message": "已有一次手动执行正在进行, 请稍后"}

        self._manual_running = True
        try:
            logger.info("收到手动触发: 开始立即执行一次全部任务.")
            pool = AsyncTaskPool()
            if self.checkin_man:
                pool.add(self.checkin_man.run_all(instant=True), "手动站点签到")
            if self.emby_man:
                pool.add(self.emby_man.run_all(instant=True), "手动 Emby 保活")
            if self.subsonic_man:
                pool.add(self.subsonic_man.run_all(instant=True), "手动 Subsonic 保活")
            await pool.wait()
            logger.info("手动触发: 全部任务执行完毕.")
            self._notify()
            return {"ok": True, "message": "执行完毕"}
        except Exception as e:
            show_exception(e, regular=False)
            return {"ok": False, "message": f"执行出错: {e}"}
        finally:
            self._manual_running = False

    async def start(self, instant: bool = False, once: bool = False):
        """启动运行时, 阻塞直到所有任务结束.

        参数:
            instant: 启动时立刻执行一次任务
            once: 只执行一次而不进入计划任务模式
        """
        self._build_managers()
        self._running = True
        self.pool = AsyncTaskPool()

        try:
            if instant and not config.debug_cron:
                await self.run_all(instant=True)
                logger.debug("启动时立刻执行签到和保活: 已完成.")

            if (not once) or config.noexit:
                from .notify import start_notifier

                self.streams = await start_notifier()

            if not once:
                if self.checkin_man:
                    self.pool.add(self.checkin_man.schedule_all(), "站点签到")
                if self.emby_man:
                    self.pool.add(self.emby_man.schedule_all(), "Emby 保活")
                if self.subsonic_man:
                    self.pool.add(self.subsonic_man.schedule_all(), "Subsonic 保活")

            if config.noexit:
                logger.info("处于长期监控模式, 当没有账号时将继续监控等待新配置.")
                self.pool.add(asyncio.Event().wait(), "账号配置文件监控")

            self._notify()
            async for task in self.pool.as_completed():
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug(f"任务 {task.get_name()} 被取消.")
                except Exception as e:
                    logger.debug(f"任务 {task.get_name()} 出现错误, 模块可能停止运行.")
                    show_exception(e, regular=False)
                    if not config.nofail:
                        raise
                else:
                    logger.debug(f"任务 {task.get_name()} 成功结束.")
                self._notify()
        finally:
            await self._cleanup()

    async def _cleanup(self):
        """结束时的清理: 收敛通知流并取消所有运行中任务."""
        if self.streams:
            try:
                await asyncio.gather(*[stream.join() for stream in self.streams])
            except Exception as e:
                logger.debug(f"等待通知流结束失败: {e.__class__.__name__}: {e}")
            self.streams = None
        RunContext.cancel_all()
        self._running = False
        self._notify()
        self._finished.set()

    async def stop(self, timeout: float = 10):
        """请求停止运行时, 用于 Web 端手动停止."""
        if not self._running:
            return
        logger.info("正在停止运行时服务.")
        for manager in (self.checkin_man, self.emby_man, self.subsonic_man):
            if manager is None:
                continue
            # 管理器若提供 stop_all 则优先调用, 否则依赖 RunContext 取消
            stop_all = getattr(manager, "stop_all", None)
            if callable(stop_all):
                try:
                    result = stop_all()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.debug(f"停止管理器失败: {e.__class__.__name__}: {e}")
        RunContext.cancel_all()
        if self._main_task:
            self._main_task.cancel()
            try:
                await asyncio.wait_for(self._main_task, timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info("运行时服务已停止.")

    async def trigger(self, site: str, account: str = None) -> dict:
        """手动触发单个站点的签到, 供 Web 端调用.

        返回 {ok: bool, message: str}.
        """
        if not self.enabled["checkiner"]:
            return {"ok": False, "message": "签到模块未启用"}
        if self.checkin_man is None:
            return {"ok": False, "message": "签到管理器尚未启动"}

        runner = getattr(self.checkin_man, "run_site", None)
        if not callable(runner):
            return {"ok": False, "message": "当前签到管理器不支持单站点手动触发"}

        ctx = RunContext.prepare(description=f"手动触发 {site}")
        ctx.start(RunStatus.RUNNING)
        try:
            result = await runner(site, account=account)
        except Exception as e:
            ctx.finish(RunStatus.ERROR, "触发异常")
            show_exception(e, regular=False)
            self._notify()
            return {"ok": False, "message": f"触发异常: {e}"}
        ctx.finish(RunStatus.SUCCESS if result else RunStatus.FAIL, "手动触发完成")
        self._notify()
        return {"ok": bool(result), "message": "已执行"}
