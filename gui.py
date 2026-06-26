"""Tkinter GUI界面 — 语音转写与说话人分离工具的主界面

包含: API凭证设置、文件选择、裁剪选项、进度显示、结果展示
所有转写操作在后台线程执行，通过root.after()安全更新GUI
"""

import os
import json
import threading
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from functools import partial

import config as config_module
import api_client
import audio_processor
import result_formatter
import poll_manager
from poll_manager import PollManager
from exceptions import (
    TranscriptionError, CredentialError, FFmpegNotFoundError,
    AudioProcessingError, PollTimeoutError, PollCancelledError
)
from utils import format_duration, safe_filename, validate_time_input

logger = logging.getLogger(__name__)


class TranscriptionApp:
    """讯飞语音转写工具 — 主应用类"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("讯飞语音转写工具 v1.0")
        self.root.geometry("800x720")
        self.root.minsize(600, 500)

        # 应用状态
        self._poll_manager = None
        self._is_transcribing = False
        self._temp_files = []
        self._order_id = ""
        self._signature_random = ""
        self._result_text = ""

        # Tkinter变量
        self.var_access_key_id = tk.StringVar()
        self.var_access_key_secret = tk.StringVar()
        self.var_speaker_number = tk.StringVar(value="自动")
        self.var_file_path = tk.StringVar()
        self.var_audio_info = tk.StringVar(value="请选择音频文件")
        self.var_enable_clip = tk.BooleanVar(value=False)
        self.var_clip_start = tk.StringVar(value="0")
        self.var_clip_duration = tk.StringVar(value="")
        self.var_convert_wav = tk.BooleanVar(value=True)
        self.var_enable_diarization = tk.BooleanVar(value=True)
        self.var_progress_text = tk.StringVar(value="")
        self.var_elapsed_text = tk.StringVar(value="")

        # 加载保存的配置
        saved_config = config_module.load_config()
        self.var_access_key_id.set(saved_config.get("access_key_id", ""))
        self.var_access_key_secret.set(saved_config.get("access_key_secret", ""))
        self.var_speaker_number.set(saved_config.get("speaker_number", "自动"))
        self.var_convert_wav.set(saved_config.get("convert_to_wav", True))
        self.var_enable_diarization.set(saved_config.get("enable_diarization", True))

        # 构建界面
        self._build_gui()

    def _build_gui(self):
        """构建完整GUI布局"""
        # 主容器 — 垂直堆叠各Frame
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── 1. API设置区域 ──
        api_frame = ttk.LabelFrame(main_frame, text="API 设置", padding=10)
        api_frame.pack(fill=tk.X, pady=(0, 5))

        # AccessKeyId
        row = ttk.Frame(api_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="AccessKeyId:", width=16).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.var_access_key_id).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # AccessKeySecret（掩码显示）
        row = ttk.Frame(api_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="AccessKeySecret:", width=16).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.var_access_key_secret, show='*').pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 说话人数量 + 操作按钮
        row = ttk.Frame(api_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="说话人数量:", width=10).pack(side=tk.LEFT)
        speaker_combo = ttk.Combobox(
            row, textvariable=self.var_speaker_number,
            values=["自动", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
            width=8, state="readonly"
        )
        speaker_combo.pack(side=tk.LEFT)
        ttk.Button(row, text="保存设置", command=self._on_save_config).pack(side=tk.RIGHT, padx=5)
        ttk.Button(row, text="验证凭证", command=self._on_validate_credentials).pack(side=tk.RIGHT, padx=5)

        # ── 2. 音频文件区域 ──
        file_frame = ttk.LabelFrame(main_frame, text="音频文件", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 5))

        row = ttk.Frame(file_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Entry(row, textvariable=self.var_file_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(row, text="选择文件", command=self._on_file_select).pack(side=tk.RIGHT)

        self.lbl_audio_info = ttk.Label(file_frame, textvariable=self.var_audio_info, foreground="gray")
        self.lbl_audio_info.pack(fill=tk.X, pady=2)

        # ── 3. 裁剪设置区域 ──
        clip_frame = ttk.LabelFrame(main_frame, text="裁剪设置（可选）", padding=10)
        clip_frame.pack(fill=tk.X, pady=(0, 5))

        self.chk_enable_clip = ttk.Checkbutton(
            clip_frame, text="启用裁剪",
            variable=self.var_enable_clip,
            command=self._on_clip_toggle
        )
        self.chk_enable_clip.pack(anchor=tk.W, pady=2)

        row = ttk.Frame(clip_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text="开始时间(秒):", width=12).pack(side=tk.LEFT)
        self.entry_clip_start = ttk.Entry(row, textvariable=self.var_clip_start, width=10)
        self.entry_clip_start.pack(side=tk.LEFT, padx=5)
        self.entry_clip_start.config(state='disabled')

        ttk.Label(row, text="裁剪时长(秒):", width=12).pack(side=tk.LEFT)
        self.entry_clip_duration = ttk.Entry(row, textvariable=self.var_clip_duration, width=10)
        self.entry_clip_duration.pack(side=tk.LEFT, padx=5)
        self.entry_clip_duration.config(state='disabled')

        # 提示文字
        ttk.Label(clip_frame, text="时间格式支持: 秒数(如90)、MM:SS(如1:30)、HH:MM:SS(如0:01:30)",
                   foreground="gray").pack(anchor=tk.W, pady=(2, 0))

        # ── 4. 转写选项区域 ──
        option_frame = ttk.LabelFrame(main_frame, text="转写选项", padding=10)
        option_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Checkbutton(
            option_frame, text="转换为WAV（推荐，提升说话人识别质量）",
            variable=self.var_convert_wav
        ).pack(anchor=tk.W, pady=2)

        ttk.Checkbutton(
            option_frame, text="启用说话人分离（声纹区分）",
            variable=self.var_enable_diarization
        ).pack(anchor=tk.W, pady=2)

        # ── 5. 操作按钮 ──
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)

        self.btn_start = ttk.Button(button_frame, text="开始转写", command=self._on_start_transcription)
        self.btn_start.pack(side=tk.LEFT, expand=True, padx=20)

        self.btn_cancel = ttk.Button(button_frame, text="取消", command=self._on_cancel, state='disabled')
        self.btn_cancel.pack(side=tk.LEFT, expand=True, padx=20)

        # ── 6. 进度区域 ──
        progress_frame = ttk.LabelFrame(main_frame, text="进度", padding=10)
        progress_frame.pack(fill=tk.X, pady=(0, 5))

        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=400)
        self.progress_bar.pack(fill=tk.X, pady=2)
        self.progress_bar['value'] = 0

        self.lbl_progress = ttk.Label(progress_frame, textvariable=self.var_progress_text)
        self.lbl_progress.pack(fill=tk.X, pady=2)

        self.lbl_elapsed = ttk.Label(progress_frame, textvariable=self.var_elapsed_text, foreground="gray")
        self.lbl_elapsed.pack(fill=tk.X)

        # ── 7. 结果区域 ──
        result_frame = ttk.LabelFrame(main_frame, text="转写结果", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 文本框 + 滚动条
        text_container = ttk.Frame(result_frame)
        text_container.pack(fill=tk.BOTH, expand=True)

        self.txt_result = tk.Text(text_container, height=10, wrap=tk.WORD, state='disabled', font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(text_container, orient=tk.VERTICAL, command=self.txt_result.yview)
        self.txt_result.configure(yscrollcommand=scrollbar.set)

        self.txt_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 结果操作按钮
        btn_row = ttk.Frame(result_frame)
        btn_row.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_row, text="保存结果", command=self._on_save_result).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="复制到剪贴板", command=self._on_copy_result).pack(side=tk.LEFT, padx=5)

    # ── 事件处理方法 ──

    def _on_file_select(self):
        """选择音频文件"""
        last_dir = config_module.get_last_audio_dir()
        filepath = filedialog.askopenfilename(
            title="选择音频文件",
            initialdir=last_dir,
            filetypes=[
                ("音频文件", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma *.amr"),
                ("MP3文件", "*.mp3"),
                ("WAV文件", "*.wav"),
                ("所有文件", "*.*"),
            ]
        )

        if filepath:
            self.var_file_path.set(filepath)

            # 保存选择目录
            current_config = config_module.load_config()
            current_config["last_audio_dir"] = os.path.dirname(filepath)
            config_module.save_config(current_config)

            # 显示音频信息（如果ffmpeg可用）
            try:
                info = audio_processor.get_audio_info(filepath)
                self.var_audio_info.set(
                    f"时长: {format_duration(info['duration'])} | "
                    f"格式: {info['format'].upper()} | "
                    f"采样率: {info['sample_rate']}Hz | "
                    f"声道: {info['channels']} | "
                    f"大小: {info['file_size'] / 1024 / 1024:.1f}MB"
                )
            except FFmpegNotFoundError:
                # ffmpeg不可用时显示基本文件信息
                file_size = os.path.getsize(filepath)
                ext = os.path.splitext(filepath)[1].lstrip('.')
                self.var_audio_info.set(
                    f"格式: {ext.upper()} | 大小: {file_size / 1024 / 1024:.1f}MB (音频详情需要ffmpeg)"
                )
            except AudioProcessingError as e:
                self.var_audio_info.set(f"获取音频信息失败: {e}")

    def _on_clip_toggle(self):
        """裁剪启用/禁用切换"""
        if self.var_enable_clip.get():
            self.entry_clip_start.config(state='normal')
            self.entry_clip_duration.config(state='normal')
        else:
            self.entry_clip_start.config(state='disabled')
            self.entry_clip_duration.config(state='disabled')

    def _on_save_config(self):
        """保存API凭证配置"""
        try:
            current_config = config_module.load_config()
            current_config["access_key_id"] = self.var_access_key_id.get().strip()
            current_config["access_key_secret"] = self.var_access_key_secret.get().strip()
            current_config["speaker_number"] = self.var_speaker_number.get()
            current_config["convert_to_wav"] = self.var_convert_wav.get()
            current_config["enable_diarization"] = self.var_enable_diarization.get()
            config_module.save_config(current_config)
            messagebox.showinfo("成功", "设置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存设置失败: {e}")

    def _on_validate_credentials(self):
        """验证API凭证格式"""
        try:
            config_module.validate_credentials(
                self.var_access_key_id.get(),
                self.var_access_key_secret.get()
            )
            messagebox.showinfo("验证通过", "API凭证格式校验通过")
        except CredentialError as e:
            messagebox.showerror("验证失败", str(e))

    def _on_start_transcription(self):
        """开始转写（在后台线程执行）"""
        # ── 输入校验 ──
        try:
            config_module.validate_credentials(
                self.var_access_key_id.get(),
                self.var_access_key_secret.get()
            )
        except CredentialError as e:
            messagebox.showerror("凭证错误", str(e))
            return

        filepath = self.var_file_path.get().strip()
        if not filepath or not os.path.exists(filepath):
            messagebox.showerror("文件错误", "请选择有效的音频文件")
            return

        # 裁剪参数校验
        clip_start = None
        clip_duration = None
        if self.var_enable_clip.get():
            try:
                clip_start = validate_time_input(self.var_clip_start.get())
                if clip_start < 0:
                    raise ValueError("开始时间不能为负数")
            except ValueError as e:
                messagebox.showerror("裁剪参数错误", f"开始时间无效: {e}")
                return

            dur_str = self.var_clip_duration.get().strip()
            if dur_str:
                try:
                    clip_duration = validate_time_input(dur_str)
                    if clip_duration <= 0:
                        raise ValueError("裁剪时长必须大于0")
                except ValueError as e:
                    messagebox.showerror("裁剪参数错误", f"裁剪时长无效: {e}")
                    return

        # ── 设置界面状态 ──
        self._is_transcribing = True
        self.btn_start.config(state='disabled')
        self.btn_cancel.config(state='normal')
        self.progress_bar['value'] = 0
        self.var_progress_text.set("准备中...")
        self.var_elapsed_text.set("")

        # ── 启动后台线程 ──
        thread = threading.Thread(
            target=self._run_transcription,
            args=(filepath, clip_start, clip_duration),
            daemon=True
        )
        thread.start()

    def _run_transcription(self, filepath: str, clip_start: float, clip_duration: float):
        """后台线程执行完整转写流程

        流程: 音频处理 → 上传 → 轮询 → 获取结果 → 格式化
        所有GUI更新通过root.after()调度
        """
        try:
            # 步骤1: 音频处理
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 5, "text": "正在处理音频..."
            })

            force_wav = self.var_convert_wav.get()
            final_file, temp_files = audio_processor.prepare_audio(
                filepath, clip_start=clip_start,
                clip_duration=clip_duration, force_wav=force_wav
            )
            self._temp_files = temp_files

            # 步骤2: 上传音频
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 10, "text": "正在上传音频..."
            })

            access_key_id = self.var_access_key_id.get().strip()
            access_key_secret = self.var_access_key_secret.get().strip()
            enable_diarization = self.var_enable_diarization.get()
            speaker_number = self.var_speaker_number.get()

            # 说话人分离参数
            role_type = 1 if enable_diarization else 0
            role_num = 0
            if enable_diarization and speaker_number != "自动":
                try:
                    role_num = int(speaker_number)
                except ValueError:
                    pass

            order_id, signature_random = api_client.upload_audio(
                final_file, access_key_id, access_key_secret,
                role_type=role_type, role_num=role_num
            )
            self._order_id = order_id
            self._signature_random = signature_random

            # 步骤3: 轮询进度
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 15, "text": f"转写进行中... (orderId: {order_id})"
            })

            pm = PollManager(
                order_id, access_key_id, access_key_secret, signature_random,
                progress_callback=self._poll_progress_callback
            )
            self._poll_manager = pm
            result_info = pm.poll_until_complete()

            # 步骤4: 解析结果
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 95, "text": "正在解析结果..."
            })

            raw_data = result_info.get("raw", {})
            raw_result = raw_data.get("content", raw_data)
            # content 可能为JSON字符串（需解析）或直接为dict
            if isinstance(raw_result, str):
                try:
                    raw_result = json.loads(raw_result)
                except json.JSONDecodeError:
                    pass

            # 解析orderResult中的lattice
            parsed_segments = result_formatter.parse_result(raw_result)
            merged_segments = result_formatter.merge_speaker_segments(parsed_segments)
            formatted_text = result_formatter.format_output(merged_segments)
            self._result_text = formatted_text

            # 步骤5: 在GUI中显示结果
            self._schedule_gui_update(self._show_result, formatted_text)
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 100, "text": "转写完成!"
            })

            # 自动保存结果文件
            output_path = safe_filename(filepath, "_transcribed")
            result_formatter.save_to_file(formatted_text, output_path)
            self._schedule_gui_update(self._show_completion_message, output_path)

        except PollCancelledError:
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 0, "text": "转写已取消"
            })
            self._schedule_gui_update(messagebox.showinfo, "取消", "转写已取消")

        except PollTimeoutError as e:
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 0, "text": "转写超时"
            })
            msg = f"{e.message}\n订单ID: {self._order_id}\n可稍后在讯飞控制台查看"
            self._schedule_gui_update(messagebox.showwarning, "超时", msg)

        except FFmpegNotFoundError as e:
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 0, "text": "ffmpeg缺失"
            })
            self._schedule_gui_update(messagebox.showerror, "错误", str(e))

        except TranscriptionError as e:
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 0, "text": "转写失败"
            })
            self._schedule_gui_update(messagebox.showerror, "错误", str(e))

        except Exception as e:
            logger.exception(f"转写流程异常: {e}")
            self._schedule_gui_update(self._update_progress_display, {
                "progress": 0, "text": "发生未知错误"
            })
            self._schedule_gui_update(messagebox.showerror, "错误", f"发生未知错误: {e}")

        finally:
            # 清理临时文件
            audio_processor.cleanup_temp_files(self._temp_files)
            self._temp_files = []
            self._is_transcribing = False
            self._poll_manager = None
            self._schedule_gui_update(self._reset_buttons)

    def _on_cancel(self):
        """取消当前转写"""
        if self._poll_manager:
            self._poll_manager.cancel()

    def _on_save_result(self):
        """保存转写结果到文件"""
        if not self._result_text:
            messagebox.showwarning("提示", "暂无转写结果可保存")
            return

        filepath = self.var_file_path.get().strip()
        default_name = safe_filename(filepath, "_transcribed")

        save_path = filedialog.asksaveasfilename(
            title="保存转写结果",
            initialdir=os.path.dirname(filepath) if filepath else os.path.expanduser('~'),
            initialfile=os.path.basename(default_name),
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )

        if save_path:
            result_formatter.save_to_file(self._result_text, save_path)
            messagebox.showinfo("保存成功", f"结果已保存到:\n{save_path}")

    def _on_copy_result(self):
        """复制结果到剪贴板"""
        if not self._result_text:
            messagebox.showwarning("提示", "暂无转写结果可复制")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._result_text)
        messagebox.showinfo("成功", "结果已复制到剪贴板")

    # ── GUI更新方法（在主线程中调用） ──

    def _schedule_gui_update(self, func, *args, **kwargs):
        """安全地从后台线程调度GUI更新"""
        self.root.after(0, func, *args, **kwargs)

    def _update_progress_display(self, info: dict):
        """更新进度条和状态文本"""
        progress = info.get("progress", 0)
        text = info.get("text", "")
        self.progress_bar['value'] = progress
        self.var_progress_text.set(text)

        elapsed_text = ""
        if self._poll_manager:
            elapsed = self._poll_manager.get_elapsed_time()
            elapsed_text = f"已等待: {elapsed:.0f}秒"
        self.var_elapsed_text.set(elapsed_text)

    def _poll_progress_callback(self, progress_info: dict):
        """轮询进度回调 — 从PollManager调用"""
        desc = progress_info.get("desc", "")
        progress = progress_info.get("progress", 0)

        elapsed = ""
        if self._poll_manager:
            elapsed_seconds = self._poll_manager.get_elapsed_time()
            elapsed = f" | 已等待: {elapsed_seconds:.0f}秒"

        self._schedule_gui_update(self._update_progress_display, {
            "progress": progress,
            "text": f"{desc} (orderId: {self._order_id}){elapsed}"
        })

    def _show_result(self, formatted_text: str):
        """在文本框中显示转写结果"""
        self.txt_result.config(state='normal')
        self.txt_result.delete('1.0', tk.END)
        self.txt_result.insert('1.0', formatted_text)
        self.txt_result.config(state='disabled')

    def _show_completion_message(self, output_path: str):
        """显示完成消息"""
        messagebox.showinfo("转写完成", f"转写完成!\n结果已自动保存到:\n{output_path}")

    def _reset_buttons(self):
        """重置按钮状态"""
        self.btn_start.config(state='normal')
        self.btn_cancel.config(state='disabled')