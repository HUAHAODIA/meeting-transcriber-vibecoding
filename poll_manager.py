"""轮询管理模块 — 轮询讯飞转写结果，支持进度回调与取消

新API (ifasr_llm) 通过 /v2/getResult 同一接口轮询进度和获取结果，
无需单独的 getProgress 接口。
"""

import time
import logging
import json

from exceptions import PollTimeoutError, PollCancelledError, APIError

logger = logging.getLogger(__name__)

# 默认轮询间隔（秒）
DEFAULT_POLL_INTERVAL = 5

# 默认超时上限（秒） — 5小时音频约需10分钟处理
DEFAULT_POLL_TIMEOUT = 600


class PollManager:
    """讯飞转写结果轮询管理器

    通过getResult接口持续轮询，直到转写完成(orderInfo.status=4)或超时/取消。
    """

    def __init__(
        self,
        order_id: str,
        access_key_id: str,
        access_key_secret: str,
        signature_random: str,
        interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_POLL_TIMEOUT,
        progress_callback=None,
    ):
        self.order_id = order_id
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.signature_random = signature_random
        self.interval = interval
        self.timeout = timeout
        self.progress_callback = progress_callback
        self._cancelled = False
        self._start_time = None

    def poll_until_complete(self) -> dict:
        """开始轮询，直到转写完成

        Returns:
            最终状态dict: {status: 3, desc: "转写完成", progress: 100, raw: {...}}

        Raises:
            PollTimeoutError: 超过超时上限
            PollCancelledError: 用户取消
        """
        import api_client

        self._start_time = time.time()
        logger.info(f"开始轮询 orderId={self.order_id}, 间隔={self.interval}s, 超时={self.timeout}s")

        # 首次等待（上传后API需要准备时间）
        time.sleep(self.interval)

        while True:
            # 检查取消标志
            if self._cancelled:
                logger.info("轮询已被用户取消")
                raise PollCancelledError()

            # 检查超时
            elapsed = time.time() - self._start_time
            if elapsed > self.timeout:
                logger.warning(f"轮询超时（已等待{elapsed:.0f}秒）")
                raise PollTimeoutError()

            # 查询结果（同时获取进度）
            try:
                progress_info = api_client.get_result(
                    self.order_id,
                    self.access_key_id,
                    self.access_key_secret,
                    self.signature_random,
                )
            except Exception as e:
                logger.warning(f"结果查询异常: {e}，继续轮询")
                progress_info = {"status": 0, "desc": "查询异常，继续等待...", "progress": 0, "raw": {}}

            # 调用进度回调
            if self.progress_callback:
                try:
                    self.progress_callback(progress_info)
                except Exception as e:
                    logger.warning(f"进度回调异常: {e}")

            # 检查是否完成 (status=3 对应 API status=4)
            if progress_info.get("status") == 3:
                logger.info(f"转写完成! orderId={self.order_id}")
                return progress_info

            # 检查是否出错
            if progress_info.get("status") == -1:
                raise APIError(progress_info.get("desc", "转写失败"))

            # 继续等待
            logger.debug(f"当前状态: {progress_info.get('status')}, 已等待{elapsed:.0f}秒")
            time.sleep(self.interval)

    def cancel(self) -> None:
        """设置取消标志（从GUI线程调用）"""
        self._cancelled = True
        logger.info("取消标志已设置")

    def get_elapsed_time(self) -> float:
        """获取已等待时间（秒）"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time
