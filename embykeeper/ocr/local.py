"""本地 ddddocr 识别服务 (子进程模型)."""

import asyncio
import time
import uuid
from io import BytesIO
from multiprocessing import Process, Queue
from typing import Optional, Union

from loguru import logger

from ..data import get_datas
from .common import CharRange, build_image_variants, parse_probability_result

logger = logger.bind(scheme="ocr")


class OCRService:
    """本地 ddddocr 识别服务.

    ddddocr 初始化重、推理是 CPU 密集型, 因此放在独立子进程运行, 避免阻塞事件循环.
    按 (ocr_name, char_range) 池化实例, 多账号共用同一份模型.
    """

    _pool = {}
    _pool_lock = asyncio.Lock()

    @classmethod
    async def get(
        cls,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ):
        # 创建用于标识唯一实例的键
        key = (ocr_name, char_range)
        async with cls._pool_lock:
            # 检查池中是否存在相同配置的实例
            if key in cls._pool:
                return cls._pool[key]
            instance = cls(ocr_name, char_range)
            cls._pool[key] = instance
            return instance

    def __init__(
        self,
        ocr_name: str = None,
        char_range: Optional[Union[CharRange, str]] = None,
    ) -> None:
        self.ocr_name = ocr_name
        self.char_range = char_range

        self._process = None
        self._queue_in = None  # 发送图片数据的队列
        self._queue_out = None  # 接收识别结果的队列
        self._subscribers = 0
        self._last_active = time.time()
        self._stop_event = None
        self._monitor_task = None
        self._pending_requests = {}  # 存储待处理的请求

    async def start(self):
        """启动OCR进程"""
        if self._process and self._process.is_alive():
            return

        self._queue_in = Queue()
        self._queue_out = Queue()
        self._stop_event = asyncio.Event()

        self._process = Process(
            target=self._process_main,
            args=(
                self._queue_in,
                self._queue_out,
                self.ocr_name,
                self.char_range,
            ),
            daemon=True,
        )
        self._process.start()

        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor())

    async def stop(self, force: bool = False):
        """停止OCR进程"""
        if force:
            await self.force_stop()
        else:
            self._subscribers = 0  # 这将触发监控任务在空闲超时后关闭进程

    async def force_stop(self):
        """强制停止OCR进程"""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # 处理所有未完成的请求
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(Exception("OCR进程已停止"))
        self._pending_requests.clear()

        if self._process and self._process.is_alive():
            self._queue_in.put(("stop", None))
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join()

        self._process = None
        self._queue_in = None
        self._queue_out = None
        self._stop_event = None

    async def recognize(
        self,
        image_bytes: bytes,
        gif: bool = False,
        timeout: int = 60,
        min_confidence: float = 0.0,
    ) -> tuple:
        """识别图片, 返回 (文本, 置信度).

        min_confidence 传入子进程用于决定是否触发变体重识别; 它不影响是否返回结果,
        阈值判断统一由调用方处理, 便于路由层拿到真实置信度后自行决定是否降级到 AI.
        """
        if not self._process or not self._process.is_alive():
            await self.start()

        # 生成唯一请求ID
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            self._last_active = time.time()
            self._queue_in.put(("process", (request_id, image_bytes, gif, min_confidence)))
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_requests.pop(request_id, None)

    async def run(
        self, image_data: BytesIO, timeout: int = 60, gif: bool = False, min_confidence: float = 0.0
    ) -> str:
        """发送图片到OCR进程并等待结果, 置信度低于 min_confidence 时返回空字符串"""
        result, confidence = await self.recognize(
            image_data.getvalue(), gif=gif, timeout=timeout, min_confidence=min_confidence
        )
        if confidence < min_confidence:
            # 输出实际置信度, 便于在 -d 调试模式下调整阈值
            logger.debug(
                f'OCR 置信度不足 ({confidence:.3f} < {min_confidence:.3f}), 识别结果 "{result}" 将被丢弃.'
            )
            return ""
        logger.debug(f'OCR 识别结果 "{result}" (置信度 {confidence:.3f}).')
        return result

    def subscribe(self):
        """增加使用者计数"""
        self._subscribers += 1
        self._last_active = time.time()

    def unsubscribe(self):
        """减少使用者计数"""
        self._subscribers = max(0, self._subscribers - 1)
        self._last_active = time.time()

    async def _monitor(self):
        """监控进程状态和空闲时间, 同时处理返回结果"""
        while True:
            try:
                # 检查进程状态和空闲超时
                if self._subscribers == 0 and time.time() - self._last_active > 300:
                    await self.force_stop()
                    break

                if self._process and not self._process.is_alive():
                    await self.force_stop()
                    break

                # 非阻塞方式检查结果队列
                try:
                    status, (request_id, result) = await asyncio.get_event_loop().run_in_executor(
                        None, self._queue_out.get_nowait
                    )

                    # 找到对应的future并设置结果
                    if request_id in self._pending_requests:
                        future = self._pending_requests[request_id]
                        if status == "error":
                            future.set_exception(Exception(result))
                        else:
                            future.set_result(result)
                except (asyncio.CancelledError, Exception):
                    pass

                await asyncio.sleep(0.1)  # 短暂休眠避免CPU占用过高

            except asyncio.CancelledError:
                break

    @staticmethod
    def _process_main(*args, **kw):
        return asyncio.run(OCRService._async_process_main(*args, **kw))

    @staticmethod
    async def _async_process_main(
        queue_in: Queue,
        queue_out: Queue,
        ocr_name: str,
        char_range: Optional[Union[CharRange, str]],
    ):
        model = None
        use_probability = False

        try:
            from ddddocr import DdddOcr
            from onnxruntime.capi.onnxruntime_pybind11_state import InvalidProtobuf
            from PIL import Image
            from io import BytesIO

            # 加载模型
            if not ocr_name:
                model = DdddOcr(beta=True, show_ad=False)
                # 注意: 不能使用 if char_range 判断, CharRange.NUMBER 为 0 会被误判为未设置
                if char_range is not None:
                    use_probability = True
                    # IntEnum 需转 int 以命中 ddddocr 的数字快捷字符集, 自定义字符串范围则原样传入
                    model.set_ranges(char_range if isinstance(char_range, str) else int(char_range))
            else:
                data = []
                files = (f"{ocr_name}.onnx", f"{ocr_name}.json")
                async for p in get_datas(files, caller="OCR"):
                    if p is None:
                        queue_out.put(("error", "无法下载所需文件"))
                        return
                    data.append(p)
                try:
                    model = DdddOcr(show_ad=False, import_onnx_path=str(data[0]), charsets_path=str(data[1]))
                except InvalidProtobuf:
                    queue_out.put(("error", "文件下载不完全"))
                    return

            def process_single_image(image_bytes, use_probability):
                """识别单张图片, 返回 (识别文本, 置信度)."""
                if use_probability:
                    return parse_probability_result(model.classification(image_bytes, probability=True))
                return model.classification(image_bytes), 1.0

            def process_image_with_retry(image_bytes, use_probability, min_confidence):
                """首次识别置信度不足时, 尝试多个图像变体, 取置信度最高者."""
                result = process_single_image(image_bytes, use_probability)
                if not use_probability or not min_confidence or result[1] >= min_confidence:
                    return result
                best = result
                for variant in build_image_variants(image_bytes):
                    candidate = process_single_image(variant, use_probability)
                    if candidate[1] > best[1]:
                        best = candidate
                    if best[1] >= min_confidence:
                        break
                return best

            def flatten_gif(gif_data):
                """将 GIF 多帧叠加为单张 PNG 字节, 便于后续统一走变体重识别流程."""
                gif = Image.open(BytesIO(gif_data))
                frame_count = getattr(gif, "n_frames", 1)

                if frame_count <= 1:
                    gif.seek(0)
                    buf = BytesIO()
                    gif.convert("RGB").save(buf, format="PNG")
                    return buf.getvalue()

                # Calculate how many frames to use (up to 5)
                num_frames = min(5, frame_count)
                frame_indices = [i * (frame_count - 1) // (num_frames - 1) for i in range(num_frames)]

                # Get the first frame to determine size
                gif.seek(0)
                base_frame = gif.copy().convert("RGBA")

                # Create a blank transparent image
                composite = Image.new("RGBA", base_frame.size, (0, 0, 0, 0))

                # Calculate alpha for each frame
                alpha_per_frame = 255 // num_frames

                for idx in frame_indices:
                    gif.seek(idx)
                    frame = gif.copy().convert("RGBA")
                    # Apply partial transparency
                    frame.putalpha(alpha_per_frame)
                    composite = Image.alpha_composite(composite, frame)

                # Convert final image to RGB for OCR
                final_bytes = BytesIO()
                composite.convert("RGB").save(final_bytes, format="PNG")
                return final_bytes.getvalue()

            # 处理请求循环
            while True:
                try:
                    cmd, data = queue_in.get()
                except KeyboardInterrupt:
                    break
                if cmd == "stop":
                    break

                request_id, image_data, is_gif, min_confidence = data
                try:
                    if is_gif:
                        image_data = flatten_gif(image_data)
                    result = process_image_with_retry(image_data, use_probability, min_confidence)
                    queue_out.put(("success", (request_id, result)))
                except Exception as e:
                    queue_out.put(("error", (request_id, str(e))))

        finally:
            if model:
                del model

    def __enter__(self):
        """上下文管理器入口"""
        self.subscribe()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.unsubscribe()
        return False  # 返回False允许异常正常传播
