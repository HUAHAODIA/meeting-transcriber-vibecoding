"""自定义异常体系 — 语音转写工具"""


class TranscriptionError(Exception):
    """转写相关异常基类"""

    def __init__(self, message="", error_code=None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class CredentialError(TranscriptionError):
    """API凭证缺失或无效"""

    def __init__(self, message="请检查API凭证是否正确填写"):
        super().__init__(message)


class SignatureError(TranscriptionError):
    """HMAC-SHA1签名计算失败"""

    def __init__(self, message="签名计算失败"):
        super().__init__(message)


class UploadError(TranscriptionError):
    """文件上传失败"""

    def __init__(self, message="文件上传失败", error_code=None):
        super().__init__(message, error_code)


class FileTooLargeError(UploadError):
    """音频文件超过大小限制"""

    def __init__(self, message="文件过大（超过500MB），请裁剪后重试"):
        super().__init__(message)


class PollTimeoutError(TranscriptionError):
    """轮询超时"""

    def __init__(self, message="转写超时，可稍后在讯飞控制台查看任务状态"):
        super().__init__(message)


class PollCancelledError(TranscriptionError):
    """用户取消轮询"""

    def __init__(self, message="转写已取消"):
        super().__init__(message)


class ResultError(TranscriptionError):
    """结果获取或解析失败"""

    def __init__(self, message="结果获取或解析失败"):
        super().__init__(message)


class AudioProcessingError(TranscriptionError):
    """音频处理失败"""

    def __init__(self, message="音频处理失败"):
        super().__init__(message)


class FFmpegNotFoundError(AudioProcessingError):
    """ffmpeg未找到"""

    def __init__(self, message="未找到ffmpeg，请确保ffmpeg.exe在程序目录中或已安装到系统"):
        super().__init__(message)


class APIError(TranscriptionError):
    """讯飞API返回错误码

    新ifasr_llm API的错误码 (code字段为int或string):
      - "000000"/0: 成功
      - 100003: 参数格式错误（如dateTime格式）
      - 10201: 签名错误
    """

    ERROR_CODE_MAP = {
        "000002": "AccessKeyId不存在或已禁用，请检查AccessKeyId和AccessKeySecret是否正确",
        "100003": "请求参数格式错误，请检查参数",
        "10201": "签名校验失败，请检查AccessKeyId和AccessKeySecret",
        "10106": "无效参数，请检查请求参数",
        "10107": "非法参数，请检查请求参数格式",
        "10110": "无授权，请检查AccessKeyId是否正确",
        "11200": "授权错误，请检查AccessKeyId和密钥是否正确",
        "11201": "授权超时，请重新发起请求",
        "11202": "授权无效，请检查签名计算是否正确",
    }

    def __init__(self, message="", error_code=None):
        code_str = str(error_code) if error_code else ""
        if code_str and code_str in self.ERROR_CODE_MAP:
            message = self.ERROR_CODE_MAP[code_str]
        elif not message:
            message = f"API错误（错误码: {error_code})"
        super().__init__(message, error_code)
