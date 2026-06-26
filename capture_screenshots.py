"""截取讯飞语音转写工具各界面截图"""

import subprocess
import time
import os
import sys

import win32gui
import win32ui
import win32con
from PIL import Image

OUTPUT_DIR = r"d:\xinxiwang_test\screenshots"
EXE_PATH = r"D:\xinxiwang_test\dist\XfyunTranscriber.exe"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def find_window_by_title(title_contains: str):
    """查找包含指定标题的窗口"""
    result = []

    def enum_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_contains in text:
                result.append((hwnd, text))

    win32gui.EnumWindows(enum_callback, None)
    return result[0] if result else (None, None)


def capture_window(hwnd, output_path: str):
    """截取指定窗口截图"""
    if not hwnd:
        print(f"  WARN: hwnd为空, 跳过")
        return False

    # 获取窗口尺寸
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    height = bottom - top

    # 截取窗口
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

    # 转换为PIL Image
    bmp_info = bitmap.GetInfo()
    bmp_str = bitmap.GetBitmapBits(True)
    img = Image.frombuffer('RGB', (bmp_info['bmWidth'], bmp_info['bmHeight']),
                           bmp_str, 'raw', 'BGRX', 0, 1)

    # 清理
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    img.save(output_path)
    print(f"  截图已保存: {output_path} ({width}x{height})")
    return True


def main():
    # 关闭已有实例
    os.system('taskkill /f /im XfyunTranscriber.exe 2>nul')
    time.sleep(1)

    # 1. 启动程序 — 截取主界面
    print("[1] 启动程序...")
    proc = subprocess.Popen([EXE_PATH])
    time.sleep(4)

    hwnd, title = find_window_by_title("讯飞语音转写工具")
    if hwnd:
        print(f"  窗口找到: {title}")
        capture_window(hwnd, os.path.join(OUTPUT_DIR, "01_main_window.png"))
    else:
        print("  WARN: 未找到窗口!")

    # 关闭
    proc.terminate()
    time.sleep(1)

    print("\n截图完成!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
