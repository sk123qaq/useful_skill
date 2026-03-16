#!/usr/bin/env python3
"""
MinerU Cloud API Python Client

Usage:
    from mineru_client import MinerUClient
    
    client = MinerUClient(api_token="your_token")
    
    # Parse URL
    result = client.parse_url("https://example.com/file.pdf")
    task_result = client.wait_for_completion(result["task_id"])
    
    # Batch upload
    batch = client.batch_upload_parse(
        files=[{"name": "doc.pdf"}],
        file_paths=["/path/to/doc.pdf"]
    )
"""

import os
import time
import hashlib
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Load from script directory or parent directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_paths = [
        os.path.join(script_dir, '.env'),
        os.path.join(os.path.dirname(script_dir), '.env'),
        '.env'
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
except ImportError:
    pass


class MinerUError(Exception):
    """MinerU API Error"""
    pass


class MinerUClient:
    """MinerU Cloud API Client"""
    
    BASE_URL = "https://mineru.net/api/v4"
    
    # Error code messages
    ERROR_CODES = {
        "A0202": "Token 错误 - 检查 Token 格式是否有 Bearer 前缀",
        "A0211": "Token 过期 - 更换新 Token",
        "-500": "传参错误 - 请确保参数类型及 Content-Type 正确",
        "-10001": "服务异常 - 请稍后再试",
        "-10002": "请求参数错误 - 检查请求参数格式",
        "-60001": "生成上传 URL 失败 - 请稍后再试",
        "-60002": "文件格式不支持 - 确保文件名有正确后缀",
        "-60003": "文件读取失败 - 请检查文件是否损坏",
        "-60004": "空文件 - 请上传有效文件",
        "-60005": "文件大小超出限制 - 最大支持 200MB",
        "-60006": "文件页数超过限制 - 请拆分文件",
        "-60007": "模型服务暂时不可用 - 请稍后重试",
        "-60008": "文件读取超时 - 检查 URL 是否可访问",
        "-60009": "任务提交队列已满 - 请稍后再试",
        "-60010": "解析失败 - 请稍后再试",
        "-60018": "每日解析任务数量已达上限 - 明日再试",
    }
    
    def __init__(self, api_token: Optional[str] = None):
        """
        Initialize MinerU client
        
        Args:
            api_token: MinerU API token. If not provided, reads from MINERU_API_TOKEN env var.
        """
        self.api_token = api_token or os.environ.get("MINERU_API_TOKEN")
        if not self.api_token:
            raise MinerUError("API token required. Set MINERU_API_TOKEN env var or pass api_token parameter.")
        
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}"
        }
    
    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle API response and check for errors"""
        try:
            data = response.json()
        except Exception:
            raise MinerUError(f"Invalid JSON response: {response.text}")
        
        if data.get("code") != 0:
            code = str(data.get("code"))
            msg = data.get("msg", "Unknown error")
            error_msg = self.ERROR_CODES.get(code, msg)
            raise MinerUError(f"API Error [{code}]: {error_msg}")
        
        return data.get("data", {})
    
    def parse_url(
        self,
        file_url: str,
        model_version: str = "vlm",
        is_ocr: bool = False,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        output_formats: Optional[List[str]] = None,
        page_ranges: Optional[str] = None,
        data_id: Optional[str] = None,
        callback: Optional[str] = None,
        seed: Optional[str] = None,
        no_cache: bool = False,
        cache_tolerance: int = 900
    ) -> Dict[str, Any]:
        """
        Create a parsing task from URL
        
        Args:
            file_url: URL to the file (pdf, doc, ppt, image, html)
            model_version: Model version - 'pipeline', 'vlm', or 'MinerU-HTML'
            is_ocr: Enable OCR
            enable_formula: Enable formula recognition
            enable_table: Enable table extraction
            language: Document language (default: 'ch')
            output_formats: Extra output formats ['docx', 'html', 'latex']
            page_ranges: Page ranges like '1-10,15,20-25'
            data_id: Custom data ID for tracking
            callback: Callback URL for notifications
            seed: Random seed for callback verification
            no_cache: Bypass cache
            cache_tolerance: Cache tolerance in seconds
            
        Returns:
            Dict containing task_id
        """
        url = f"{self.BASE_URL}/extract/task"
        
        data = {
            "url": file_url,
            "model_version": model_version,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "no_cache": no_cache,
            "cache_tolerance": cache_tolerance
        }
        
        if output_formats:
            data["extra_formats"] = output_formats
        if page_ranges:
            data["page_ranges"] = page_ranges
        if data_id:
            data["data_id"] = data_id
        if callback:
            data["callback"] = callback
        if seed:
            data["seed"] = seed
            
        response = requests.post(url, headers=self.headers, json=data)
        return self._handle_response(response)
    
    def get_task_result(self, task_id: str) -> Dict[str, Any]:
        """
        Get task result by task_id
        
        Args:
            task_id: The task ID
            
        Returns:
            Task result dict with state, full_zip_url, etc.
        """
        url = f"{self.BASE_URL}/extract/task/{task_id}"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)
    
    def wait_for_completion(
        self,
        task_id: str,
        timeout: int = 300,
        poll_interval: int = 5,
        progress_callback=None
    ) -> Dict[str, Any]:
        """
        Poll task until completion
        
        Args:
            task_id: The task ID
            timeout: Maximum wait time in seconds
            poll_interval: Seconds between polls
            progress_callback: Optional callback function(progress_dict)
            
        Returns:
            Final task result
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            result = self.get_task_result(task_id)
            state = result.get("state")
            
            if state == "done":
                return result
            elif state == "failed":
                raise MinerUError(f"Task failed: {result.get('err_msg', 'Unknown error')}")
            elif state in ["pending", "running", "converting"]:
                if progress_callback and "extract_progress" in result:
                    progress_callback(result["extract_progress"])
                time.sleep(poll_interval)
            else:
                raise MinerUError(f"Unknown state: {state}")
        
        raise MinerUError(f"Timeout waiting for task {task_id}")
    
    def batch_url_parse(
        self,
        files: List[Dict[str, Any]],
        model_version: str = "vlm",
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        output_formats: Optional[List[str]] = None,
        callback: Optional[str] = None,
        seed: Optional[str] = None,
        no_cache: bool = False
    ) -> Dict[str, Any]:
        """
        Batch parse files from URLs
        
        Args:
            files: List of file dicts with 'url', 'data_id', 'is_ocr', 'page_ranges'
            model_version: Model version
            enable_formula: Enable formula recognition
            enable_table: Enable table extraction
            language: Document language
            output_formats: Extra output formats
            callback: Callback URL
            seed: Random seed for callback
            no_cache: Bypass cache
            
        Returns:
            Dict containing batch_id
        """
        url = f"{self.BASE_URL}/extract/task/batch"
        
        data = {
            "files": files,
            "model_version": model_version,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "no_cache": no_cache
        }
        
        if output_formats:
            data["extra_formats"] = output_formats
        if callback:
            data["callback"] = callback
        if seed:
            data["seed"] = seed
            
        response = requests.post(url, headers=self.headers, json=data)
        return self._handle_response(response)
    
    def batch_upload_parse(
        self,
        files: List[Dict[str, Any]],
        file_paths: List[str],
        model_version: str = "vlm",
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        output_formats: Optional[List[str]] = None,
        callback: Optional[str] = None,
        seed: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload local files and parse them
        
        Args:
            files: List of file metadata dicts with 'name', 'data_id', 'is_ocr', 'page_ranges'
            file_paths: List of local file paths corresponding to files
            model_version: Model version
            enable_formula: Enable formula recognition
            enable_table: Enable table extraction
            language: Document language
            output_formats: Extra output formats
            callback: Callback URL
            seed: Random seed
            
        Returns:
            Dict containing batch_id
        """
        if len(files) != len(file_paths):
            raise MinerUError("files and file_paths must have same length")
        
        if len(files) > 200:
            raise MinerUError("Maximum 200 files per batch")
        
        # Step 1: Get upload URLs
        url = f"{self.BASE_URL}/file-urls/batch"
        
        data = {
            "files": files,
            "model_version": model_version,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language
        }
        
        if output_formats:
            data["extra_formats"] = output_formats
        if callback:
            data["callback"] = callback
        if seed:
            data["seed"] = seed
        
        response = requests.post(url, headers=self.headers, json=data)
        result = self._handle_response(response)
        
        batch_id = result["batch_id"]
        upload_urls = result["file_urls"]
        
        # Step 2: Upload files
        for i, (file_path, upload_url) in enumerate(zip(file_paths, upload_urls)):
            if not os.path.exists(file_path):
                raise MinerUError(f"File not found: {file_path}")
            
            with open(file_path, 'rb') as f:
                upload_response = requests.put(upload_url, data=f)
                if upload_response.status_code != 200:
                    raise MinerUError(f"Failed to upload {file_path}: {upload_response.status_code}")
        
        return {"batch_id": batch_id}
    
    def get_batch_result(self, batch_id: str) -> Dict[str, Any]:
        """
        Get batch task results
        
        Args:
            batch_id: The batch ID
            
        Returns:
            Dict with extract_result list
        """
        url = f"{self.BASE_URL}/extract-results/batch/{batch_id}"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)
    
    def download_result(self, download_url: str, output_path: str) -> str:
        """
        Download result zip file
        
        Args:
            download_url: The full_zip_url from task result
            output_path: Local path to save the file
            
        Returns:
            Path to downloaded file
        """
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return output_path
    
    @staticmethod
    def verify_callback(checksum: str, uid: str, seed: str, content: str) -> bool:
        """
        Verify callback request is from MinerU
        
        Args:
            checksum: Checksum from callback request
            uid: User ID from personal center
            seed: Seed used in request
            content: Content from callback request
            
        Returns:
            True if verified
        """
        expected = hashlib.sha256(f"{uid}{seed}{content}".encode()).hexdigest()
        return checksum == expected


def main():
    """CLI example"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MinerU Cloud API Client")
    parser.add_argument("action", choices=["parse-url", "get-task", "batch-url", "batch-status"])
    parser.add_argument("--url", help="File URL to parse")
    parser.add_argument("--task-id", help="Task ID to query")
    parser.add_argument("--batch-id", help="Batch ID to query")
    parser.add_argument("--model", default="vlm", help="Model version")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR")
    parser.add_argument("--table", action="store_true", help="Enable table extraction")
    parser.add_argument("--formula", action="store_true", help="Enable formula recognition")
    
    args = parser.parse_args()
    
    client = MinerUClient()
    
    if args.action == "parse-url":
        if not args.url:
            print("Error: --url required")
            return
        result = client.parse_url(
            file_url=args.url,
            model_version=args.model,
            is_ocr=args.ocr,
            enable_table=args.table,
            enable_formula=args.formula
        )
        print(f"Task created: {result['task_id']}")
        
    elif args.action == "get-task":
        if not args.task_id:
            print("Error: --task-id required")
            return
        result = client.get_task_result(args.task_id)
        print(f"State: {result.get('state')}")
        if result.get('full_zip_url'):
            print(f"Download: {result['full_zip_url']}")
            
    elif args.action == "batch-url":
        # Example batch parsing
        files = [{"url": args.url, "data_id": "test"}] if args.url else []
        result = client.batch_url_parse(files=files, model_version=args.model)
        print(f"Batch created: {result['batch_id']}")
        
    elif args.action == "batch-status":
        if not args.batch_id:
            print("Error: --batch-id required")
            return
        result = client.get_batch_result(args.batch_id)
        for item in result.get("extract_result", []):
            print(f"{item['file_name']}: {item['state']}")


if __name__ == "__main__":
    main()
