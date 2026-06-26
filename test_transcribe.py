"""命令行测试 — 完整转写流程（新ifasr_llm API）

直接使用源码模块走通全流程，打印详细日志以定位问题。
用法: cd d:/xinxiwang_test && python test_transcribe.py
"""

import sys
import os
import json
import logging
import time
import traceback

# 确保当前目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("test_transcribe")

from utils import setup_logging, format_duration
from config import load_config, validate_credentials
import audio_processor
import api_client
import poll_manager as poll_module
import result_formatter

# 测试文件
TEST_FILE = r"D:\xinxiwang_test\AI_test.mp3"


def main():
    print("=" * 60)
    print("  讯飞语音转写（大模型）— 命令行端到端测试")
    print("=" * 60)

    # ── 步骤0: 加载凭证 ──
    print("\n[步骤0] 加载API凭证...")
    config = load_config()
    access_key_id = config.get("access_key_id", "").strip()
    access_key_secret = config.get("access_key_secret", "").strip()

    if not access_key_id or not access_key_secret:
        print("ERROR: 凭证未设置! 请先在GUI中保存AccessKeyId和AccessKeySecret")
        return 1

    print(f"  AccessKeyId: {access_key_id}")
    print(f"  AccessKeySecret: {'*' * len(access_key_secret) if access_key_secret else '(空)'}")

    # ── 步骤1: 校验文件 ──
    print(f"\n[步骤1] 检查音频文件: {TEST_FILE}")
    if not os.path.exists(TEST_FILE):
        print(f"ERROR: 文件不存在: {TEST_FILE}")
        return 1
    file_size = os.path.getsize(TEST_FILE)
    print(f"  文件大小: {file_size / 1024 / 1024:.1f} MB")

    # ── 步骤2: 音频信息 ──
    print("\n[步骤2] 获取音频信息...")
    try:
        info = audio_processor.get_audio_info(TEST_FILE)
        print(f"  时长: {format_duration(info['duration'])} ({info['duration']:.1f}s)")
        print(f"  格式: {info['format'].upper()}")
        print(f"  采样率: {info['sample_rate']}Hz, 声道: {info['channels']}")
    except Exception as e:
        print(f"ERROR: 获取音频信息失败: {e}")
        traceback.print_exc()
        return 1

    # ── 步骤3: WAV转换 ──
    print("\n[步骤3] 转换为WAV (16kHz/16bit/单声道)...")
    try:
        wav_path = audio_processor.convert_to_wav(TEST_FILE)
        print(f"  WAV文件: {wav_path}")
        print(f"  WAV大小: {os.path.getsize(wav_path) / 1024 / 1024:.1f} MB")
    except Exception as e:
        print(f"ERROR: WAV转换失败: {e}")
        traceback.print_exc()
        return 1

    # ── 步骤4: 签名测试 ──
    print("\n[步骤4] 测试HMAC-SHA1签名计算...")
    try:
        test_params = {
            "accessKeyId": access_key_id,
            "dateTime": api_client._format_datetime(),
            "signatureRandom": api_client._generate_signature_random(),
            "fileSize": "1024",
            "fileName": "test.wav",
        }
        sig = api_client.compute_signature(access_key_secret, test_params)
        print(f"  签名: {sig[:30]}...")
        print(f"  签名计算: OK")
    except Exception as e:
        print(f"ERROR: 签名计算失败: {e}")
        traceback.print_exc()
        return 1

    # ── 步骤5: 上传音频 ──
    print("\n[步骤5] 上传音频到讯飞新API...")
    print(f"  URL: {api_client.UPLOAD_URL}")
    order_id = None
    signature_random = None
    try:
        order_id, signature_random = api_client.upload_audio(
            wav_path,
            access_key_id, access_key_secret,
            role_type=1,  # 开启角色分离
            role_num=0,   # 盲分
        )
        print(f"  orderId: {order_id}")
        print(f"  signatureRandom: {signature_random}")
        print(f"  上传: OK")
    except Exception as e:
        print(f"ERROR: 上传失败: {e}")
        traceback.print_exc()
        return 1

    if not order_id:
        print("ERROR: 未获取到orderId")
        return 1

    # ── 步骤6: 轮询进度 ──
    print(f"\n[步骤6] 开始轮询进度 (orderId: {order_id})...")
    print("  (每5秒查询一次，最多等待600秒)")
    try:
        pm = poll_module.PollManager(
            order_id, access_key_id, access_key_secret, signature_random,
            interval=5, timeout=600,
            progress_callback=lambda info: print(
                f"    [{info.get('status', '?')}] {info.get('desc', '')} "
                f"(估算进度: {info.get('progress', 0)}%)"
            )
        )
        result_info = pm.poll_until_complete()
        print("  轮询: OK (转写完成!)")
    except poll_module.PollTimeoutError:
        print("WARN: 轮询超时，尝试直接获取结果...")
        # 尝试最后一次获取
        result_info = api_client.get_result(
            order_id, access_key_id, access_key_secret, signature_random
        )
    except poll_module.PollCancelledError:
        print("WARN: 轮询被取消")
        return 1
    except Exception as e:
        print(f"ERROR: 轮询异常: {e}")
        traceback.print_exc()
        return 1

    # ── 步骤7: 解析原始结果 ──
    print("\n[步骤7] 解析原始结果结构...")
    raw_data = result_info.get("raw", {})
    print(f"  raw keys: {list(raw_data.keys()) if isinstance(raw_data, dict) else type(raw_data)}")
    
    content = raw_data.get("content", raw_data)
    if isinstance(content, str):
        content = json.loads(content)
    print(f"  content keys: {list(content.keys()) if isinstance(content, dict) else type(content)}")
    
    order_info = content.get("orderInfo", {})
    print(f"  orderInfo.status: {order_info.get('status')}")
    print(f"  orderInfo.failType: {order_info.get('failType', 0)}")
    
    order_result = content.get("orderResult", None)
    if order_result:
        if isinstance(order_result, str):
            print(f"  orderResult (string, 前200字符): {order_result[:200]}")
        else:
            print(f"  orderResult type: {type(order_result)}")

    # ── 步骤8: 解析并格式化 ──
    print("\n[步骤8] 解析并格式化结果...")
    try:
        parsed = result_formatter.parse_result(content)
        print(f"  解析到 {len(parsed)} 个分段")
        if parsed:
            for i, seg in enumerate(parsed[:5]):
                print(f"    [{i}] speaker={seg['speaker']}, "
                      f"time={seg['start_time']:.1f}-{seg['end_time']:.1f}, "
                      f"text={seg['text'][:50]}...")
            if len(parsed) > 5:
                print(f"    ... 还有 {len(parsed) - 5} 个分段")
        
        merged = result_formatter.merge_speaker_segments(parsed)
        print(f"  合并后 {len(merged)} 个段落")
        formatted = result_formatter.format_output(merged)
        print(f"  输出长度: {len(formatted)} 字符")
    except Exception as e:
        print(f"ERROR: 结果解析失败: {e}")
        traceback.print_exc()
        return 1

    # ── 步骤9: 显示结果 ──
    print("\n" + "=" * 60)
    print("  转写结果")
    print("=" * 60)
    print(formatted)
    print("=" * 60)

    # 保存结果
    output_path = os.path.join(os.path.dirname(TEST_FILE), "AI_test_transcribed.txt")
    try:
        result_formatter.save_to_file(formatted, output_path)
        print(f"\n结果已保存到: {output_path}")
    except Exception as e:
        print(f"WARN: 保存结果失败: {e}")

    # 清理临时文件
    audio_processor.cleanup_temp_files([wav_path])

    print("\n测试完成!")
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
