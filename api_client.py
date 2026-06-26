"""讯飞非实时语音转写大模型 (ifasr_llm) REST API 客户端

API流程:
  1. 签名计算 (HMAC-SHA1, 排序参数 → URL编码 → 签名)
  2. 音频上传 (POST /v2/upload, application/octet-stream)
  3. 结果轮询 (POST /v2/getResult, 同一接口轮询直到status=4)

认证: accessKeyId + accessKeySecret (控制台获取)
"""

import hmac
import hashlib
import base64
import time
import os
import json
import logging
import urllib.parse
import string
import random

import requests

from exceptions import (
    SignatureError, UploadError, FileTooLargeError,
    APIError, ResultError
)

logger = logging.getLogger(__name__)

# 讯飞非实时语音转写大模型 API 地址
BASE_URL = "https://office-api-ist-dx.iflyaisol.com"
UPLOAD_URL = f"{BASE_URL}/v2/upload"
GET_RESULT_URL = f"{BASE_URL}/v2/getResult"

# 文件大小上限 (500MB)
MAX_FILE_SIZE = 500 * 1024 * 1024

# 网络请求超时
REQUEST_TIMEOUT = 30

# 上传重试次数
UPLOAD_RETRY_COUNT = 3
UPLOAD_RETRY_DELAY = 2  # 秒


def _generate_signature_random() -> str:
    """生成16位随机字符串（大小写字母+数字）"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(16))


def _format_datetime() -> str:
    """生成当前时间戳，格式: yyyy-MM-dd'T'HH:mm:ss+0800"""
    now = time.localtime()
    tz_offset = '+0800'  # 东八区
    return time.strftime('%Y-%m-%dT%H:%M:%S', now) + tz_offset


def compute_signature(access_key_secret: str, params: dict) -> str:
    """计算HMAC-SHA1签名

    签名流程:
      1. 排除 signature 字段
      2. 按参数名自然排序 (TreeMap排序规则)
      3. 对每个参数的key和value分别进行URL编码
      4. 排除空值
      5. 用 & 连接: encoded_key=encoded_value&...
      6. HMAC-SHA1加密 → Base64编码

    Args:
        access_key_secret: 讯飞AccessKeySecret
        params: 待签名的参数字典 (不含signature本身)

    Returns:
        Base64签名字符串
    """
    try:
        # 1. 排除signature，排除空值
        filtered = {k: v for k, v in params.items()
                    if k != "signature" and v is not None and v != ""}

        # 2. 自然排序 (ASCII排序，与Java TreeMap一致)
        sorted_keys = sorted(filtered.keys())

        # 3. 构建baseString: URL编码后的 key=value 对
        parts = []
        for key in sorted_keys:
            value = filtered[key]
            encoded_key = urllib.parse.quote(str(key), safe='')
            encoded_value = urllib.parse.quote(str(value), safe='')
            parts.append(f"{encoded_key}={encoded_value}")

        base_string = "&".join(parts)
        logger.debug(f"签名baseString: {base_string}")

        # 4. HMAC-SHA1加密
        signature_bytes = hmac.new(
            access_key_secret.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha1
        ).digest()

        # 5. Base64编码
        signature = base64.b64encode(signature_bytes).decode('utf-8')
        logger.debug(f"签名结果: {signature}")
        return signature

    except Exception as e:
        logger.error(f"签名计算失败: {e}")
        raise SignatureError(f"签名计算失败: {e}")


def upload_audio(
    filepath: str,
    access_key_id: str,
    access_key_secret: str,
    role_type: int = 0,
    role_num: int = 0,
    language: str = "autodialect",
) -> str:
    """上传音频文件到讯飞非实时语音转写大模型API

    使用 application/octet-stream 裸二进制上传。

    Args:
        filepath: 音频文件路径 (需确保已转换为16kHz/16bit/单声道 WAV)
        access_key_id: 讯飞AccessKeyId
        access_key_secret: 讯飞AccessKeySecret
        role_type: 角色分离: 0=不开启, 1=通用角色分离, 3=声纹角色分离
        role_num: 说话人数, 0=盲分

    Returns:
        orderId 字符串
    """
    # 校验文件大小
    file_size = os.path.getsize(filepath)
    if file_size > MAX_FILE_SIZE:
        raise FileTooLargeError()

    file_name = os.path.basename(filepath)
    logger.info(f"准备上传文件: {file_name} ({file_size} bytes)")

    # 构建请求参数
    signature_random = _generate_signature_random()

    params = {
        "accessKeyId": access_key_id,
        "dateTime": _format_datetime(),
        "signatureRandom": signature_random,
        "fileSize": str(file_size),
        "fileName": file_name,
        "durationCheckDisable": "true",  # 关闭时长校验
        "language": language,
    }

    # 角色分离参数
    if role_type > 0:
        params["roleType"] = str(role_type)
        params["roleNum"] = str(role_num)  # 0=盲分(自动)，必须显式发送

    # 计算签名
    signature = compute_signature(access_key_secret, params)

    # 构建URL (参数需URL编码)
    query_parts = []
    for key in sorted(params.keys()):
        value = params[key]
        encoded_key = urllib.parse.quote(key, safe='')
        encoded_value = urllib.parse.quote(value, safe='')
        query_parts.append(f"{encoded_key}={encoded_value}")
    url = f"{UPLOAD_URL}?{'&'.join(query_parts)}"

    # 请求头
    headers = {
        "Content-Type": "application/octet-stream",
        "signature": signature,
    }

    # 读取文件数据
    with open(filepath, 'rb') as f:
        file_data = f.read()

    # 上传请求（带重试）
    for attempt in range(1, UPLOAD_RETRY_COUNT + 1):
        try:
            logger.info(f"上传请求 (第{attempt}次), url={url[:100]}...")
            response = requests.post(
                url,
                data=file_data,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            result = response.json()
            logger.debug(f"上传响应: {json.dumps(result, ensure_ascii=False)}")

            # 检查响应 — code为字符串"000000"或整数0表示成功
            code = result.get("code", "")
            if str(code) not in ("000000", "0"):
                error_msg = result.get("descInfo", result.get("message", "未知错误"))
                logger.error(f"API错误: code={code}, msg={error_msg}")
                raise APIError(error_msg, error_code=str(code))

            # 提取orderId
            content = result.get("content", {})
            if isinstance(content, str):
                content = json.loads(content)
            order_id = content.get("orderId", "")
            if not order_id:
                raise UploadError("上传成功但未获取到orderId")

            logger.info(f"上传成功, orderId: {order_id}")
            return order_id, signature_random

        except APIError:
            raise
        except requests.exceptions.RequestException as e:
            logger.warning(f"上传网络错误 (第{attempt}次): {e}")
            if attempt == UPLOAD_RETRY_COUNT:
                raise UploadError(f"网络连接失败，已重试{UPLOAD_RETRY_COUNT}次: {e}")
            time.sleep(UPLOAD_RETRY_DELAY * attempt)
        except (json.JSONDecodeError, KeyError) as e:
            raise UploadError(f"上传响应解析失败: {e}")

    raise UploadError("上传失败，未知原因")


def get_result(
    order_id: str,
    access_key_id: str,
    access_key_secret: str,
    signature_random: str,
    result_type: str = "transfer",
) -> dict:
    """查询转写结果/进度（POST /v2/getResult）

    新API通过同一个接口轮询进度和获取结果：
    - orderInfo.status=0: 已创建
    - orderInfo.status=3: 处理中
    - orderInfo.status=4: 已完成
    - failType!=0: 各种失败状态

    Returns:
        {
            "status": 0|3|4|-1,  # 兼容轮询格式
            "desc": str,
            "progress": int,
            "raw": dict  # 完整原始响应
        }
    """
    params = {
        "accessKeyId": access_key_id,
        "dateTime": _format_datetime(),
        "signatureRandom": signature_random,
        "orderId": order_id,
        "resultType": result_type,
    }

    signature = compute_signature(access_key_secret, params)

    # 构建URL
    query_parts = []
    for key in sorted(params.keys()):
        value = params[key]
        encoded_key = urllib.parse.quote(key, safe='')
        encoded_value = urllib.parse.quote(value, safe='')
        query_parts.append(f"{encoded_key}={encoded_value}")
    url = f"{GET_RESULT_URL}?{'&'.join(query_parts)}"

    headers = {
        "Content-Type": "application/json",
        "signature": signature,
    }

    try:
        response = requests.post(
            url,
            json={},  # 空JSON body
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        result = response.json()
        logger.debug(f"结果查询响应: {json.dumps(result, ensure_ascii=False)[:500]}")

        # 检查响应
        code = result.get("code", "")
        if str(code) not in ("000000", "0"):
            error_msg = result.get("descInfo", result.get("message", "未知错误"))
            raise APIError(error_msg, error_code=str(code))

        content = result.get("content", {})
        if isinstance(content, str):
            content = json.loads(content)

        order_info = content.get("orderInfo", {})

        # 处理失败状态
        fail_type = order_info.get("failType", 0)
        if fail_type != 0:
            fail_messages = {
                1: "音频上传失败",
                2: "音频转码失败",
                3: "音频识别失败",
                4: "音频时长超限（最大5小时）",
                5: "音频校验失败",
                6: "静音文件",
                7: "翻译失败",
                8: "账号无翻译权限",
                9: "转写质检失败",
                10: "转写质检未匹配出关键词",
                11: "未开启质检或翻译能力",
                12: "音频语种分析失败",
                99: "其他错误",
            }
            fail_msg = fail_messages.get(fail_type, f"未知异常(failType={fail_type})")
            return {
                "status": -1,
                "desc": fail_msg,
                "progress": 0,
                "raw": result,
            }

        api_status = order_info.get("status", 0)

        # 状态映射
        status_map = {0: 0, 3: 2, 4: 3}
        desc_map = {
            0: "订单已创建，等待处理...",
            3: "语音转写中...",
            4: "转写完成",
        }
        progress_map = {0: 10, 3: 60, 4: 100}

        mapped_status = status_map.get(api_status, 0)
        desc = desc_map.get(api_status, f"未知状态: {api_status}")
        progress = progress_map.get(api_status, 0)

        return {
            "status": mapped_status,
            "desc": desc,
            "progress": progress,
            "raw": result,
        }

    except APIError:
        raise
    except requests.exceptions.RequestException as e:
        logger.warning(f"结果查询网络错误: {e}")
        raise ResultError(f"结果查询网络错误: {e}")
    except (json.JSONDecodeError, KeyError) as e:
        raise ResultError(f"结果查询响应解析失败: {e}")
