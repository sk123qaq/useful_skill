#!/usr/bin/env python3
"""
火山引擎音频转写 - 一键转写本地音频文件
自动启动 HTTP 服务器和 ngrok 穿透
"""

import os
import sys
import time
import requests
import uuid
import argparse
import subprocess
import shutil

class VolcTranscriberLocal:
    def __init__(self, app_key: str, access_key: str):
        self.app_key = app_key
        self.access_key = access_key
        self.resource_id = "volc.seedasr.auc"
        self.http_server_process = None
        self.ngrok_process = None
        
    def start_services(self, port: int, audio_dir: str):
        """启动 HTTP 服务器和 ngrok"""
        if not shutil.which("ngrok"):
            raise RuntimeError("未找到 ngrok，请先安装并确保其在 PATH 中")

        # 启动 HTTP 服务器
        print(f"启动 HTTP 服务器在端口 {port}...")
        self.http_server_process = subprocess.Popen(
            ["python3", "-m", "http.server", str(port)],
            cwd=audio_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # 启动 ngrok
        print("启动 ngrok 穿透...")
        self.ngrok_process = subprocess.Popen(
            ["ngrok", "http", str(port), "--log", "stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # 等待 ngrok 启动并获取 URL
        print("等待 ngrok 连接...")
        for _ in range(30):
            time.sleep(1)
            try:
                resp = requests.get("http://127.0.0.1:4040/api/tunnels")
                tunnels = resp.json().get("tunnels", [])
                if tunnels:
                    public_url = tunnels[0]["public_url"]
                    print(f"公网 URL: {public_url}")
                    return public_url
            except:
                pass
        raise Exception("ngrok 启动失败")
    
    def stop_services(self):
        """停止服务"""
        if self.http_server_process:
            self.http_server_process.terminate()
        if self.ngrok_process:
            self.ngrok_process.terminate()
    
    def transcribe(self, audio_path: str, language: str = "zh-CN", format: str = "mp3"):
        """转写音频"""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        audio_dir = os.path.dirname(audio_path)
        audio_filename = os.path.basename(audio_path)
        
        # 启动服务
        public_url = self.start_services(8888, audio_dir)
        audio_url = f"{public_url}/{audio_filename}"
        
        # 提交任务
        print(f"提交转写任务: {audio_url}")
        request_id = str(uuid.uuid4())
        headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json"
        }
        
        submit_data = {
            "audio": {"url": audio_url, "format": format},
            "request": {"model_name": "bigmodel", "enable_itn": True}
        }
        
        resp = requests.post(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            headers=headers,
            json=submit_data
        )
        
        req_id = resp.headers.get("X-Api-Request-Id")
        print(f"任务ID: {req_id}")
        
        # 轮询结果
        print("等待转写结果...")
        for i in range(120):
            time.sleep(2)
            q_resp = requests.post(
                "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
                headers=headers,
                json={"request_id": req_id}
            )
            status = q_resp.headers.get("X-Api-Status-Code")
            
            if status == "20000000":
                result = q_resp.json()
                texts = [s.get("text", "") for s in result.get("result", {}).get("utterances", [])]
                return "".join(texts)
            elif status not in ["20000001", "20000002"]:
                print(f"错误: {q_resp.headers.get('X-Api-Message')}")
                return None
        
        return None


def main():
    parser = argparse.ArgumentParser(description="火山引擎音频转写 - 本地文件版")
    parser.add_argument("--file", required=True, help="本地音频文件路径")
    parser.add_argument("--app-key", help="VOLC_APP_KEY（也可使用环境变量）")
    parser.add_argument("--access-key", help="VOLC_ACCESS_KEY（也可使用环境变量）")
    parser.add_argument("--language", default="zh-CN", help="语言")
    parser.add_argument("--format", default="mp3", help="音频格式")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    app_key = args.app_key or os.environ.get("VOLC_APP_KEY")
    access_key = args.access_key or os.environ.get("VOLC_ACCESS_KEY")
    if not app_key or not access_key:
        print("错误: 请通过参数或环境变量提供 VOLC_APP_KEY 和 VOLC_ACCESS_KEY", file=sys.stderr)
        sys.exit(1)

    transcriber = VolcTranscriberLocal(app_key, access_key)
    
    try:
        text = transcriber.transcribe(args.file, args.language, args.format)
        
        if text:
            print(f"\n转写完成! 文本长度: {len(text)} 字符")
            
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"已保存到: {args.output}")
            else:
                print(f"\n文本:\n{text}")
        else:
            print("转写失败")
    finally:
        transcriber.stop_services()


if __name__ == "__main__":
    main()
