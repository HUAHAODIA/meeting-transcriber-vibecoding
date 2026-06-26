# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller打包配置 — 讯飞语音转写工具

将Python项目打包为独立的Windows .exe可执行文件
包含ffmpeg.exe二进制资源，确保非技术人员无需额外安装
"""

import os
import sys

block_cipher = None

# 项目根目录 — 使用os.getcwd()确保从项目目录运行时路径正确
# 如果从其他目录运行，请设置PROJECT_ROOT为项目绝对路径
PROJECT_ROOT = r'd:\xinxiwang_test'

# ffmpeg/ffprobe路径 — 打包时需确保assets/中存在
ffmpeg_path = os.path.join(PROJECT_ROOT, 'assets', 'ffmpeg.exe')
ffprobe_path = os.path.join(PROJECT_ROOT, 'assets', 'ffprobe.exe')

# 捆绑资源文件列表
datas = []
if os.path.exists(ffmpeg_path):
    datas.append(('assets/ffmpeg.exe', 'assets'))
    print(f"[INFO] ffmpeg.exe 已找到: {ffmpeg_path}")
else:
    print(f"[WARNING] ffmpeg.exe 未找到: {ffmpeg_path}")
    print("[WARNING] 打包后将无法处理音频文件，请将ffmpeg.exe放入assets目录")

if os.path.exists(ffprobe_path):
    datas.append(('assets/ffprobe.exe', 'assets'))
    print(f"[INFO] ffprobe.exe 已找到: {ffprobe_path}")
else:
    print(f"[WARNING] ffprobe.exe 未找到: {ffprobe_path}")
    print("[WARNING] 打包后将无法获取音频信息，请将ffprobe.exe放入assets目录")

# 图标文件（可选）
icon_path = os.path.join(PROJECT_ROOT, 'assets', 'icon.ico')
if not os.path.exists(icon_path):
    icon_path = None

# 需要显式包含的隐藏导入
hiddenimports = [
    'pydub',
    'pydub.audio_segment',
    'pydub.effects',
    'requests',
    'urllib3',
    'hmac',
    'hashlib',
    'base64',
]

# 所有Python源文件
source_files = [
    'main.py',
    'gui.py',
    'api_client.py',
    'audio_processor.py',
    'result_formatter.py',
    'poll_manager.py',
    'config.py',
    'exceptions.py',
    'utils.py',
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'main.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大型模块以减小体积
        'matplotlib', 'numpy', 'pandas', 'scipy',
        'PIL', 'tkinter.test', 'unittest',
        'xmlrpc', 'multiprocessing',
        'pydoc', 'doctest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='XfyunTranscriber',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口（GUI应用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)