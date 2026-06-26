"""讯飞语音转写工具 — 应用入口

启动日志系统，创建Tkinter根窗口，启动GUI主循环
"""

import sys
import logging

from utils import setup_logging
from gui import TranscriptionApp


def main():
    """主函数 — 应用启动入口"""
    # 初始化日志
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("讯飞语音转写工具启动")

    # 创建Tkinter根窗口
    import tkinter as tk
    root = tk.Tk()

    # 设置窗口图标（可选）
    try:
        from utils import get_resource_path
        icon_path = get_resource_path("assets/icon.ico")
        if icon_path and icon_path.endswith('.ico'):
            root.iconbitmap(icon_path)
    except Exception:
        logger.debug("未设置窗口图标")

    # 创建并运行主应用
    app = TranscriptionApp(root)
    root.mainloop()

    logger.info("讯飞语音转写工具退出")


if __name__ == "__main__":
    main()