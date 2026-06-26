"""结果格式化模块 — 讯飞API结果解析与结构化TXT输出"""

import json
import logging
import os

from utils import format_timestamp

logger = logging.getLogger(__name__)


def parse_result(raw_result: dict) -> list:
    """解析讯飞API返回的转写结果，提取说话人分段信息

    讯飞结果可能的结构:
      - lattice数组: 每个lattice包含json_1best，其中包含st/et/speaker/bg/ed等信息
      - 也可能直接在content中包含segments数组

    Args:
        raw_result: 讯飞getResult接口返回的内容dict

    Returns:
        分段列表: [{speaker, start_time, end_time, text}, ...]
        时间单位为秒
    """
    segments = []

    # 尝试多种可能的结果结构

    # 结构0: 新API的orderResult格式（JSON字符串，内嵌lattice数组）
    order_result = raw_result.get("orderResult", None)
    if order_result:
        if isinstance(order_result, str):
            try:
                order_result = json.loads(order_result)
            except json.JSONDecodeError:
                logger.debug(f"orderResult无法解析为JSON: {order_result[:200]}")
                order_result = None
        if isinstance(order_result, dict):
            lattice = order_result.get("lattice", None)
            if lattice:
                segments = _parse_lattice_format(lattice)
                if segments:
                    _log_speaker_stats(segments, "orderResult.lattice")
                    return segments

    # 结构1: lattice格式（直接在结果中）
    lattice = raw_result.get("lattice", None)
    if lattice:
        segments = _parse_lattice_format(lattice)
        if segments:
            _log_speaker_stats(segments, "lattice")
            return segments

    # 结构2: 直接的segments列表
    direct_segments = raw_result.get("segments", None) or raw_result.get("sentences", None)
    if direct_segments and isinstance(direct_segments, list):
        segments = _parse_direct_segments(direct_segments)
        if segments:
            _log_speaker_stats(segments, "segments/sentences")
            return segments

    # 结构3: content字段可能嵌套
    content = raw_result.get("content", None)
    if isinstance(content, str):
        try:
            content = json.loads(content)
            return parse_result(content)  # 递归解析双重编码
        except json.JSONDecodeError:
            pass
    elif isinstance(content, dict):
        return parse_result(content)  # 递归解析嵌套dict

    # 结构4: 检查data字段
    data = raw_result.get("data", None)
    if isinstance(data, dict):
        return parse_result(data)

    # 无法解析
    logger.warning(f"无法识别的结果结构，原始数据已记录")
    logger.debug(f"原始结果: {json.dumps(raw_result, ensure_ascii=False)[:2000]}")
    return []


def _log_speaker_stats(segments: list, source: str = "") -> None:
    """记录说话人统计信息到日志"""
    unique_speakers = set(seg["speaker"] for seg in segments)
    logger.info(f"[{source}] 解析到 {len(segments)} 个片段, "
                f"{len(unique_speakers)} 位说话人: {sorted(unique_speakers)}")


def _parse_lattice_format(lattice: list) -> list:
    """解析lattice格式（讯飞常见返回格式）

    每个lattice条目包含json_1best字段，其中可能有speaker信息。
    新API (ifasr_llm): json_1best.st 为dict，含 bg/ed (10ms帧) 和 rt (识别结果)。
    """
    segments = []

    for item in lattice:
        # 获取最佳识别结果
        json_1best = item.get("json_1best", None)
        if not json_1best:
            continue

        if isinstance(json_1best, str):
            try:
                json_1best = json.loads(json_1best)
            except json.JSONDecodeError:
                continue

        # 解析st (start time) / et (end time) / speaker
        st_raw = json_1best.get("st", json_1best.get("bg", None))
        et_raw = json_1best.get("et", json_1best.get("ed", None))
        # 兼容多种speaker字段名
        speaker = (json_1best.get("speaker", None)
                   or json_1best.get("spk", None)
                   or json_1best.get("speaker_id", None)
                   or json_1best.get("speakerId", None))

        # 新API格式: st 为 dict，含 bg/ed (毫秒) + rl (角色标签/说话人) + rt (识别结果)
        if isinstance(st_raw, dict):
            st = st_raw.get("bg", 0)
            ed = st_raw.get("ed", 0)
            # 毫秒 → 秒
            start_time = float(st) / 1000.0 if st is not None else 0.0
            end_time = float(ed) / 1000.0 if ed is not None else 0.0
            # 大模型API的说话人字段在 st.rl (role label) 中
            if speaker is None:
                rl = st_raw.get("rl", None)
                if rl is not None:
                    speaker = str(rl)
        else:
            # 旧格式: st/et 为毫秒数值
            try:
                start_time = float(st_raw) / 1000.0 if st_raw is not None else 0.0
                end_time = float(et_raw) / 1000.0 if et_raw is not None else 0.0
            except (ValueError, TypeError):
                start_time = 0.0
                end_time = 0.0

        # 提取文本内容
        text = _extract_text_from_lattice(json_1best)

        if text:
            # 调试：记录speaker信息
            logger.debug(f"lattice speaker={speaker}, text={text[:40]}...")
            segments.append({
                "speaker": str(speaker) if speaker is not None else "0",
                "start_time": start_time,
                "end_time": end_time,
                "text": text.strip(),
            })

    return segments


def _extract_text_from_lattice(json_1best: dict) -> str:
    """从lattice的json_1best中提取文本内容"""
    # 方式0: 新API格式 st.rt[].ws[].cw[].w
    st_obj = json_1best.get("st", None)
    if isinstance(st_obj, dict):
        rt_list = st_obj.get("rt", [])
        words = []
        for rt in rt_list:
            ws_list = rt.get("ws", [])
            for ws in ws_list:
                cw_list = ws.get("cw", [])
                for cw in cw_list:
                    w = cw.get("w", "")
                    if w:
                        words.append(w)
        if words:
            return "".join(words)

    # 方式1: 直接有text字段
    text = json_1best.get("text", None) or json_1best.get("raw", None)
    if text:
        return text

    # 方式2: 从ws(word segment)数组中拼接 (旧格式)
    ws_list = json_1best.get("ws", None)
    if ws_list and isinstance(ws_list, list):
        words = []
        for ws in ws_list:
            # 每个ws中有cw(char word)数组
            cw_list = ws.get("cw", None)
            if cw_list and isinstance(cw_list, list):
                for cw in cw_list:
                    w = cw.get("w", "")
                    if w:
                        words.append(w)
        return "".join(words)

    return ""


def _parse_direct_segments(segment_list: list) -> list:
    """解析直接的segments/sentences格式"""
    segments = []

    for seg in segment_list:
        speaker = (seg.get("speaker", None) or seg.get("speaker_id", None)
                   or seg.get("speakerId", None) or seg.get("spk", None))
        start_time = seg.get("begin_time", None) or seg.get("begin", None) or seg.get("bg", None) or seg.get("start_time", None)
        end_time = seg.get("end_time", None) or seg.get("end", None) or seg.get("ed", None) or seg.get("end_time", None)
        text = seg.get("text", None) or seg.get("raw", None)

        if not text:
            # 从words中拼接
            words = seg.get("words", None)
            if words and isinstance(words, list):
                text = "".join(w.get("text", w.get("w", "")) for w in words)

        # 时间转换
        try:
            start_sec = float(start_time) / 1000.0 if start_time is not None else 0.0
            end_sec = float(end_time) / 1000.0 if end_time is not None else 0.0
        except (ValueError, TypeError):
            start_sec = 0.0
            end_sec = 0.0

        if text:
            segments.append({
                "speaker": str(speaker) if speaker is not None else "0",
                "start_time": start_sec,
                "end_time": end_sec,
                "text": text.strip(),
            })

    return segments


def merge_speaker_segments(segments: list) -> list:
    """合并同一说话人的连续片段

    如果说话人1有多个连续片段，将它们合并为一个完整段落

    Args:
        segments: 原始分段列表 [{speaker, start_time, end_time, text}, ...]

    Returns:
        合并后的分段列表
    """
    if not segments:
        return []

    merged = []
    current = segments[0].copy()
    current["text"] = current["text"]

    for i in range(1, len(segments)):
        seg = segments[i]
        if seg["speaker"] == current["speaker"]:
            # 同一说话人：合并文本，更新结束时间
            current["text"] += seg["text"]
            current["end_time"] = seg["end_time"]
        else:
            # 不同说话人：保存当前段，开始新段
            merged.append(current)
            current = seg.copy()
            current["text"] = current["text"]

    merged.append(current)
    return merged


def format_output(parsed_segments: list) -> str:
    """将分段列表格式化为指定输出格式

    输出格式:
      HH:MM:SS - HH:MM:SS 说话人N
      说话内容

      HH:MM:SS - HH:MM:SS 说话人M
      说话内容

    Args:
        parsed_segments: 合并后的分段列表

    Returns:
        格式化的文本字符串
    """
    if not parsed_segments:
        return "（无转写结果）"

    output_lines = []
    speaker_num_map = {}
    next_speaker_num = 1

    for seg in parsed_segments:
        # 说话人编号映射 (speaker "0" → "说话人1")
        speaker_id = seg["speaker"]
        if speaker_id not in speaker_num_map:
            speaker_num_map[speaker_id] = next_speaker_num
            next_speaker_num += 1
        speaker_label = f"说话人{speaker_num_map[speaker_id]}"

        # 格式化时间戳
        start_ts = format_timestamp(seg["start_time"])
        end_ts = format_timestamp(seg["end_time"])

        # 组合行
        output_lines.append(f"{start_ts} - {end_ts} {speaker_label}")
        output_lines.append(seg["text"])
        output_lines.append("")  # 空行分隔

    # 去除末尾多余空行
    result = "\n".join(output_lines).rstrip("\n")
    return result


def save_to_file(content: str, filepath: str) -> None:
    """将格式化结果保存为TXT文件（UTF-8编码）

    Args:
        content: 格式化后的文本内容
        filepath: 输出文件路径
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"结果已保存到: {filepath}")
    except IOError as e:
        logger.error(f"保存结果失败: {e}")
        raise