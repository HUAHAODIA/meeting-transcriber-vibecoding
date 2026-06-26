"""音频处理模块 — MP3裁剪、WAV转换、ffmpeg发现"""

import os
import sys
import tempfile
import logging

from exceptions import AudioProcessingError, FFmpegNotFoundError

logger = logging.getLogger(__name__)

# pydub依赖ffmpeg，在模块级别初始化ffmpeg路径
_ffmpeg_initialized = False


def _find_ffmpeg() -> str:
    """查找ffmpeg可执行文件，始终返回绝对路径

    查找顺序:
      1. PyInstaller捆绑的 assets/ffmpeg.exe（优先确保一致性）
      2. 开发模式下项目目录的 assets/ffmpeg.exe
      3. 系统PATH中的ffmpeg（使用shutil.which获取绝对路径）

    Returns:
        ffmpeg可执行文件绝对路径

    Raises:
        FFmpegNotFoundError: ffmpeg未找到
    """
    # 1. 优先检查PyInstaller捆绑路径（确保打包后一致性）
    if getattr(sys, 'frozen', False):
        bundled_path = os.path.join(sys._MEIPASS, 'assets', 'ffmpeg.exe')
        if os.path.exists(bundled_path):
            logger.info(f"ffmpeg在捆绑路径中找到: {bundled_path}")
            return bundled_path

    # 2. 检查开发模式项目目录
    project_dir = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(project_dir, 'assets', 'ffmpeg.exe')
    if os.path.exists(local_path):
        logger.info(f"ffmpeg在项目目录中找到: {local_path}")
        return local_path

    # 3. 兜底：使用系统PATH中的ffmpeg（必须解析为绝对路径）
    import shutil
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        logger.info(f"ffmpeg在系统PATH中找到: {system_ffmpeg}")
        return system_ffmpeg

    # 未找到
    raise FFmpegNotFoundError(
        "未找到ffmpeg，请确保ffmpeg.exe在程序assets目录中或已安装到系统PATH"
    )


def _ensure_ffmpeg() -> None:
    """确保pydub能找到ffmpeg和ffprobe（懒加载初始化）

    关键修复: pydub的get_prober_name()和get_encoder_name()使用内置的
    which()函数搜索PATH，而非AudioSegment.converter。因此需要
    monkey-patch which()以让pydub能找到捆绑的ffmpeg/ffprobe。
    """
    global _ffmpeg_initialized
    if _ffmpeg_initialized:
        return

    try:
        ffmpeg_path = _find_ffmpeg()
        # 推导ffprobe路径（与ffmpeg同目录）
        ffprobe_path = ffmpeg_path.replace("ffmpeg.exe", "ffprobe.exe")

        import pydub
        import pydub.utils

        # 设置ffmpeg路径
        pydub.AudioSegment.converter = ffmpeg_path

        # Monkey-patch pydub的which() — 让get_prober_name/get_encoder_name
        # 能找到捆绑的ffprobe/ffmpeg，而非只搜索系统PATH
        _original_which = pydub.utils.which

        def _patched_which(program: str):
            program_lower = program.lower()
            # ffprobe → 捆绑路径
            if program_lower in ("ffprobe", "ffprobe.exe"):
                if os.path.exists(ffprobe_path):
                    return ffprobe_path
            # ffmpeg → 捆绑路径
            elif program_lower in ("ffmpeg", "ffmpeg.exe"):
                if os.path.exists(ffmpeg_path):
                    return ffmpeg_path
            # 其他程序 → 原始逻辑（搜索系统PATH）
            return _original_which(program)

        pydub.utils.which = _patched_which

        # Monkey-patch get_prober_name() — pydub的设计缺陷:
        # get_prober_name()用which()判断是否存在但返回固定字符串"ffprobe"，
        # 忽略which()返回的实际路径。必须patch以返回捆绑ffprobe的完整路径。
        _original_get_prober_name = pydub.utils.get_prober_name

        def _patched_get_prober_name():
            if os.path.exists(ffprobe_path):
                return ffprobe_path
            return _original_get_prober_name()

        pydub.utils.get_prober_name = _patched_get_prober_name

        logger.info(f"pydub ffmpeg路径: {ffmpeg_path}")
        logger.info(f"pydub ffprobe路径: {ffprobe_path}")
        _ffmpeg_initialized = True
    except FFmpegNotFoundError:
        raise
    except ImportError:
        raise AudioProcessingError("pydub模块未安装，请运行 pip install pydub")


def get_audio_info(filepath: str) -> dict:
    """获取音频文件信息（时长、格式、采样率、声道数）

    Args:
        filepath: 音频文件路径

    Returns:
        dict: {duration, format, sample_rate, channels, file_size}

    Raises:
        AudioProcessingError: 音频信息获取失败
    """
    _ensure_ffmpeg()

    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(filepath)

        info = {
            "duration": len(audio) / 1000.0,  # pydub返回毫秒
            "format": os.path.splitext(filepath)[1].lstrip('.'),
            "sample_rate": audio.frame_rate,
            "channels": audio.channels,
            "file_size": os.path.getsize(filepath),
        }
        logger.info(f"音频信息: 时长={info['duration']:.1f}s, 格式={info['format']}, "
                     f"采样率={info['sample_rate']}, 声道={info['channels']}")
        return info

    except FFmpegNotFoundError:
        raise
    except Exception as e:
        logger.error(f"获取音频信息失败: {e}")
        raise AudioProcessingError(f"获取音频信息失败: {e}")


def convert_to_wav(filepath: str, output_dir: str = None) -> str:
    """将音频文件转换为WAV格式（16kHz, 16bit, 单声道）

    Args:
        filepath: 输入音频文件路径
        output_dir: 输出目录（默认为临时目录）

    Returns:
        转换后的WAV文件路径

    Raises:
        AudioProcessingError: 转换失败
    """
    _ensure_ffmpeg()

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="xfyun_transcriber_")

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    output_path = os.path.join(output_dir, f"{base_name}_converted.wav")

    try:
        from pydub import AudioSegment
        logger.info(f"开始转换: {filepath} → {output_path}")

        audio = AudioSegment.from_file(filepath)
        # 转换为16kHz, 16bit, 单声道
        audio = audio.set_frame_rate(16000)
        audio = audio.set_sample_width(2)  # 16bit = 2 bytes
        audio = audio.set_channels(1)      # 单声道

        audio.export(output_path, format="wav")
        logger.info(f"WAV转换完成: {output_path}")
        return output_path

    except FFmpegNotFoundError:
        raise
    except Exception as e:
        logger.error(f"WAV转换失败: {e}")
        raise AudioProcessingError(f"WAV转换失败: {e}")


def clip_audio(
    filepath: str,
    start_time: float,
    duration: float = None,
    output_dir: str = None,
) -> str:
    """裁剪音频文件（提取指定时间段的片段）

    Args:
        filepath: 输入音频文件路径
        start_time: 起始时间（秒）
        duration: 裁剪时长（秒），None表示裁剪到文件末尾
        output_dir: 输出目录（默认为临时目录）

    Returns:
        裁剪后的文件路径

    Raises:
        AudioProcessingError: 裁剪失败
    """
    _ensure_ffmpeg()

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="xfyun_transcriber_")

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    output_path = os.path.join(output_dir, f"{base_name}_clipped.wav")

    try:
        from pydub import AudioSegment
        logger.info(f"开始裁剪: {filepath}, 起始={start_time}s, 时长={duration}s")

        audio = AudioSegment.from_file(filepath)

        start_ms = int(start_time * 1000)

        if duration is not None and duration > 0:
            end_ms = start_ms + int(duration * 1000)
            # 确保不超过音频总长度
            end_ms = min(end_ms, len(audio))
            clipped = audio[start_ms:end_ms]
        else:
            # 裁剪到末尾
            clipped = audio[start_ms:]

        # 裁剪后转换为标准WAV格式
        clipped = clipped.set_frame_rate(16000)
        clipped = clipped.set_sample_width(2)
        clipped = clipped.set_channels(1)

        clipped.export(output_path, format="wav")
        logger.info(f"裁剪完成: {output_path} ({len(clipped)/1000:.1f}s)")
        return output_path

    except FFmpegNotFoundError:
        raise
    except Exception as e:
        logger.error(f"音频裁剪失败: {e}")
        raise AudioProcessingError(f"音频裁剪失败: {e}")


def prepare_audio(
    filepath: str,
    clip_start: float = None,
    clip_duration: float = None,
    force_wav: bool = True,
) -> tuple:
    """音频处理管线 — 组合裁剪和转换操作

    Args:
        filepath: 输入音频文件路径
        clip_start: 裁剪起始时间（秒），None表示不裁剪
        clip_duration: 裁剪时长（秒），None表示裁剪到末尾
        force_wav: 是否强制转换为WAV（推荐开启，提升说话人分离质量）

    Returns:
        (final_filepath, temp_files) 元组
        - final_filepath: 最终待上传的文件路径
        - temp_files: 需要在完成后清理的临时文件列表
    """
    temp_files = []
    current_file = filepath

    try:
        # 步骤1: 裁剪（如果需要）
        if clip_start is not None and clip_start >= 0:
            clipped_path = clip_audio(current_file, clip_start, clip_duration)
            temp_files.append(clipped_path)
            current_file = clipped_path

        # 步骤2: WAV转换（如果需要）
        if force_wav:
            wav_path = convert_to_wav(current_file)
            if wav_path != current_file:
                temp_files.append(wav_path)
                current_file = wav_path

        logger.info(f"音频处理完成，最终文件: {current_file}")
        return current_file, temp_files

    except Exception:
        # 出错时也清理临时文件
        cleanup_temp_files(temp_files)
        raise


def cleanup_temp_files(file_paths: list) -> None:
    """清理临时文件

    Args:
        file_paths: 需要删除的文件路径列表
    """
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"清理临时文件: {path}")
                # 尝试清理父目录（如果是临时目录且为空）
                parent_dir = os.path.dirname(path)
                if parent_dir.startswith(tempfile.gettempdir()):
                    try:
                        if not os.listdir(parent_dir):
                            os.rmdir(parent_dir)
                    except OSError:
                        pass
        except OSError as e:
            logger.warning(f"清理临时文件失败: {path}, 错误: {e}")