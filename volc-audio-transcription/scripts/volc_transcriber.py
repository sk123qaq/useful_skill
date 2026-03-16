#!/usr/bin/env python3
"""
Volc Engine Audio Transcription API Client
火山引擎录音文件识别 API 客户端
"""

import json
import uuid
import time
import os
import requests
from typing import Optional, Dict, Any, List

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class VolcAudioTranscriber:
    """火山引擎录音文件识别客户端"""
    
    SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
    
    # Resource IDs
    RESOURCE_BIGASR = "volc.bigasr.auc"  # 豆包录音文件识别模型1.0
    RESOURCE_SEEDASR = "volc.seedasr.auc"  # 豆包录音文件识别模型2.0
    
    def __init__(self, app_key: str = None, access_key: str = None, resource_id: str = None, env_file: str = None):
        """
        初始化客户端
        
        Args:
            app_key: APP ID (火山引擎控制台获取), 可从环境变量 VOLC_APP_KEY 获取
            access_key: Access Token (火山引擎控制台获取), 可从环境变量 VOLC_ACCESS_KEY 获取
            resource_id: 资源ID，默认 volc.bigasr.auc
            env_file: .env 文件路径，默认查找脚本所在目录的 .env
        """
        from pathlib import Path
        
        # 尝试从 .env 文件加载
        if env_file is None:
            # 默认查找脚本所在目录的 .env
            script_dir = Path(__file__).parent.resolve()
            env_file = script_dir / ".env"
            
            # 如果脚本目录的 .env 不存在，尝试 skill 根目录
            if not env_file.exists():
                env_file = script_dir.parent / ".env"
        
        if load_dotenv and Path(env_file).exists():
            load_dotenv(env_file)
        
        self.app_key = app_key or os.environ.get("VOLC_APP_KEY")
        self.access_key = access_key or os.environ.get("VOLC_ACCESS_KEY")
        
        if not self.app_key:
            raise ValueError("APP_KEY 未设置，请传入或设置环境变量 VOLC_APP_KEY")
        if not self.access_key:
            raise ValueError("ACCESS_KEY 未设置，请传入或设置环境变量 VOLC_ACCESS_KEY")
        
        self.resource_id = resource_id or self.RESOURCE_SEEDASR
        self._sequence = -1
    
    def _get_headers(self, request_id: str) -> Dict[str, str]:
        """生成请求头"""
        return {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": str(self._sequence),
            "Content-Type": "application/json"
        }
    
    def submit_task(
        self,
        audio_url: str,
        format: str = "mp3",
        language: Optional[str] = None,
        uid: Optional[str] = None,
        codec: Optional[str] = None,
        rate: Optional[int] = None,
        bits: Optional[int] = None,
        channel: Optional[int] = None,
        model_name: str = "bigmodel",
        model_version: Optional[str] = None,
        enable_itn: bool = True,
        enable_punc: bool = False,
        enable_ddc: bool = False,
        enable_speaker_info: bool = False,
        enable_channel_split: bool = False,
        show_utterances: bool = False,
        show_speech_rate: bool = False,
        show_volume: bool = False,
        enable_lid: bool = False,
        enable_emotion_detection: bool = False,
        enable_gender_detection: bool = False,
        vad_segment: bool = False,
        end_window_size: Optional[int] = None,
        sensitive_words_filter: Optional[str] = None,
        enable_poi_fc: bool = False,
        enable_music_fc: bool = False,
        corpus: Optional[Dict] = None,
        callback: Optional[str] = None,
        callback_data: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        提交转写任务
        
        Args:
            audio_url: 音频链接 (必填)
            format: 音频容器格式 (必填): raw / wav / mp3 / ogg
            language: 指定语言，如 "zh-CN", "en-US", "ja-JP" 等
            uid: 用户标识
            codec: 音频编码: raw / opus
            rate: 采样率，默认 16000
            bits: 采样位数，默认 16
            channel: 声道数，默认 1
            model_name: 模型名称，默认 "bigmodel"
            model_version: 模型版本，如 "400"
            enable_itn: 启用ITN，默认 True
            enable_punc: 启用标点，默认 False
            enable_ddc: 启用顺滑，默认 False
            enable_speaker_info: 启用说话人分离，默认 False
            enable_channel_split: 启用双声道识别，默认 False
            show_utterances: 输出分句信息，默认 False
            show_speech_rate: 输出语速，默认 False
            show_volume: 输出音量，默认 False
            enable_lid: 启用语种识别，默认 False
            enable_emotion_detection: 启用情绪检测，默认 False
            enable_gender_detection: 启用性别检测，默认 False
            vad_segment: 使用VAD分句，默认 False
            end_window_size: 强制判停时间 (ms)
            sensitive_words_filter: 敏感词过滤配置
            enable_poi_fc: 开启POI function call，默认 False
            enable_music_fc: 开启音乐 function call，默认 False
            corpus: 语料/干预词配置
            callback: 回调地址
            callback_data: 回调信息
            
        Returns:
            包含 task_id 的字典
        """
        request_id = str(uuid.uuid4())
        
        # 构建请求体
        payload = {
            "user": {},
            "audio": {
                "url": audio_url,
                "format": format
            },
            "request": {
                "model_name": model_name,
                "enable_itn": enable_itn
            }
        }
        
        # 添加可选参数
        if uid:
            payload["user"]["uid"] = uid
        
        if language:
            payload["audio"]["language"] = language
        
        if codec:
            payload["audio"]["codec"] = codec
        
        if rate:
            payload["audio"]["rate"] = rate
        
        if bits:
            payload["audio"]["bits"] = bits
        
        if channel:
            payload["audio"]["channel"] = channel
        
        # Request 可选参数
        req_opts = payload["request"]
        
        if model_version:
            req_opts["model_version"] = model_version
        
        if enable_punc:
            req_opts["enable_punc"] = enable_punc
        
        if enable_ddc:
            req_opts["enable_ddc"] = enable_ddc
        
        if enable_speaker_info:
            req_opts["enable_speaker_info"] = enable_speaker_info
        
        if enable_channel_split:
            req_opts["enable_channel_split"] = enable_channel_split
        
        if show_utterances:
            req_opts["show_utterances"] = show_utterances
        
        if show_speech_rate:
            req_opts["show_speech_rate"] = show_speech_rate
        
        if show_volume:
            req_opts["show_volume"] = show_volume
        
        if enable_lid:
            req_opts["enable_lid"] = enable_lid
        
        if enable_emotion_detection:
            req_opts["enable_emotion_detection"] = enable_emotion_detection
        
        if enable_gender_detection:
            req_opts["enable_gender_detection"] = enable_gender_detection
        
        if vad_segment:
            req_opts["vad_segment"] = vad_segment
        
        if end_window_size:
            req_opts["end_window_size"] = end_window_size
        
        if sensitive_words_filter:
            req_opts["sensitive_words_filter"] = sensitive_words_filter
        
        if enable_poi_fc or enable_music_fc or corpus:
            fc_config = {}
            if enable_poi_fc:
                fc_config["enable_poi_fc"] = True
            if enable_music_fc:
                fc_config["enable_music_fc"] = True
            if corpus:
                fc_config["corpus"] = corpus
            req_opts.update(fc_config)
        
        if callback:
            payload["callback"] = callback
        
        if callback_data:
            payload["callback_data"] = callback_data
        
        # 发送请求
        headers = self._get_headers(request_id)
        
        response = requests.post(
            self.SUBMIT_URL,
            headers=headers,
            json=payload
        )
        
        # 解析响应
        result = {
            "request_id": request_id,
            "status_code": response.headers.get("X-Api-Status-Code"),
            "message": response.headers.get("X-Api-Message"),
            "logid": response.headers.get("X-Tt-Logid")
        }
        
        return result
    
    def query_result(self, request_id: str) -> Dict[str, Any]:
        """
        查询转写结果
        
        Args:
            request_id: 提交任务时返回的 request_id
            
        Returns:
            包含识别结果的字典
        """
        headers = self._get_headers(request_id)
        
        response = requests.post(
            self.QUERY_URL,
            headers=headers,
            json={"request_id": request_id}
        )
        
        result = {
            "status_code": response.headers.get("X-Api-Status-Code"),
            "message": response.headers.get("X-Api-Message"),
            "logid": response.headers.get("X-Tt-Logid")
        }
        
        if response.status_code == 200:
            try:
                result.update(response.json())
            except:
                pass
        
        return result
    
    def wait_for_result(
        self,
        request_id: str,
        max_retries: int = 30,
        interval: float = 1.0
    ) -> Dict[str, Any]:
        """
        轮询等待转写结果
        
        Args:
            request_id: 任务ID
            max_retries: 最大重试次数
            interval: 轮询间隔(秒)
            
        Returns:
            转写结果
        """
        for _ in range(max_retries):
            result = self.query_result(request_id)
            status_code = result.get("status_code")
            
            if status_code == "20000000":
                # 成功
                return result
            elif status_code in ["20000001", "20000002"]:
                # 处理中或排队中，继续等待
                time.sleep(interval)
            elif status_code == "20000003":
                # 静音音频
                result["error"] = "Silent audio"
                return result
            else:
                # 其他错误
                return result
        
        return {
            "status_code": "timeout",
            "message": "Max retries exceeded",
            "result": None
        }


# 便捷函数
def transcribe(
    audio_url: str,
    app_key: str = None,
    access_key: str = None,
    format: str = "mp3",
    language: str = "zh-CN",
    **kwargs
) -> Dict[str, Any]:
    """
    便捷转写函数
    
    Args:
        audio_url: 音频链接
        app_key: APP ID (可从环境变量 VOLC_APP_KEY 获取)
        access_key: Access Token (可从环境变量 VOLC_ACCESS_KEY 获取)
        format: 音频格式
        language: 语言
        **kwargs: 其他参数
        
    Returns:
        转写结果
    """
    client = VolcAudioTranscriber(app_key, access_key)
    
    # 提交任务
    submit_result = client.submit_task(
        audio_url=audio_url,
        format=format,
        language=language,
        **kwargs
    )
    
    request_id = submit_result.get("request_id")
    
    # 等待结果
    return client.wait_for_result(request_id)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="火山引擎录音文件识别")
    parser.add_argument("--url", required=True, help="音频文件URL")
    parser.add_argument("--app-key", help="APP Key（也可使用环境变量 VOLC_APP_KEY）")
    parser.add_argument("--access-key", help="Access Key（也可使用环境变量 VOLC_ACCESS_KEY）")
    parser.add_argument("--format", default="mp3", help="音频格式")
    parser.add_argument("--language", default="zh-CN", help="语言")
    parser.add_argument("--poll", action="store_true", help="轮询等待结果")
    
    args = parser.parse_args()
    
    client = VolcAudioTranscriber(args.app_key, args.access_key)
    
    # 提交任务
    print("提交任务...")
    result = client.submit_task(
        audio_url=args.url,
        format=args.format,
        language=args.language
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    if args.poll and result.get("status_code") == "20000000":
        request_id = result.get("request_id")
        print(f"\n任务ID: {request_id}")
        print("等待转写结果...")
        
        final_result = client.wait_for_result(request_id)
        print("\n转写结果:")
        print(json.dumps(final_result, indent=2, ensure_ascii=False))
