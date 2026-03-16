#!/usr/bin/env python3
"""
快速解析本地 PDF 文件（单文件版本）
支持指定页码范围，直接输出 Markdown 内容

使用方法:
    # 解析整个文件
    python parse_local.py /path/to/file.pdf
    
    # 解析指定页码范围
    python parse_local.py /path/to/file.pdf --pages "5-6"
    
    # 启用表格和公式识别
    python parse_local.py /path/to/file.pdf --pages "1-10" --table --formula
    
    # 保存结果到文件
    python parse_local.py /path/to/file.pdf --output result.md
"""

import sys
import os
import time
import requests
import zipfile
import io
import argparse

# Add script directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from mineru_client import MinerUClient, MinerUError


def parse_local_file(
    file_path: str,
    page_ranges: str = None,
    enable_table: bool = True,
    enable_formula: bool = True,
    is_ocr: bool = False,
    model_version: str = "vlm",
    output_file: str = None,
    quiet: bool = False
) -> str:
    """
    解析本地 PDF 文件并返回 Markdown 内容
    
    Args:
        file_path: 本地文件路径
        page_ranges: 页码范围，如 "5-6" 或 "1,3-5"
        enable_table: 启用表格识别
        enable_formula: 启用公式识别
        is_ocr: 启用 OCR
        model_version: 模型版本 ("pipeline", "vlm", "MinerU-HTML")
        output_file: 保存结果到文件的路径
        quiet: 静默模式，不输出进度
    
    Returns:
        提取的 Markdown 内容
    """
    # 验证文件
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    if not quiet:
        print(f"正在解析文件: {file_path}")
        if page_ranges:
            print(f"页码范围: {page_ranges}")
    
    # 创建客户端
    client = MinerUClient()
    
    # 准备文件元数据
    file_name = os.path.basename(file_path)
    files = [{
        'name': file_name,
        'data_id': f'parse-{int(time.time())}',
        'is_ocr': is_ocr
    }]
    if page_ranges:
        files[0]['page_ranges'] = page_ranges
    
    # 上传并解析
    if not quiet:
        print("正在上传文件...")
    
    result = client.batch_upload_parse(
        files=files,
        file_paths=[file_path],
        model_version=model_version,
        enable_table=enable_table,
        enable_formula=enable_formula,
        language='ch'
    )
    
    batch_id = result['batch_id']
    
    if not quiet:
        print(f"任务已提交 (Batch ID: {batch_id})")
        print("等待任务完成...")
    
    # 等待任务完成
    while True:
        task_result = client.get_batch_result(batch_id)
        extract_result = task_result.get('extract_result', [])
        
        if not extract_result:
            time.sleep(2)
            continue
        
        file_task = extract_result[0]
        state = file_task['state']
        
        if state == 'done':
            if not quiet:
                print("任务完成！")
            
            # 下载并解压
            zip_url = file_task['full_zip_url']
            zip_response = requests.get(zip_url)
            
            markdown_content = ""
            
            with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zip_ref:
                for name in zip_ref.namelist():
                    if name.endswith('.md'):
                        with zip_ref.open(name) as f:
                            markdown_content = f.read().decode('utf-8')
                            break
            
            # 保存到文件
            if output_file and markdown_content:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                if not quiet:
                    print(f"结果已保存到: {output_file}")
            
            return markdown_content
        
        elif state == 'failed':
            err_msg = file_task.get('err_msg', '未知错误')
            raise MinerUError(f"任务失败: {err_msg}")
        
        else:
            if not quiet:
                progress = file_task.get('extract_progress', {})
                current = progress.get('extracted_pages', 0)
                total = progress.get('total_pages', 0)
                print(f"\r状态: {state}, 进度: {current}/{total}", end='', flush=True)
            time.sleep(3)


def main():
    parser = argparse.ArgumentParser(
        description="快速解析本地 PDF 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s report.pdf
  %(prog)s report.pdf --pages "5-6"
  %(prog)s report.pdf --pages "1-10" --table --formula
  %(prog)s report.pdf --output result.md
        """
    )
    
    parser.add_argument("file", help="本地 PDF 文件路径")
    parser.add_argument("--pages", help="页码范围，如 \"5-6\" 或 \"1,3-5\"")
    parser.add_argument("--table", action="store_true", default=True, help="启用表格识别（默认启用）")
    parser.add_argument("--no-table", action="store_false", dest="table", help="禁用表格识别")
    parser.add_argument("--formula", action="store_true", default=True, help="启用公式识别（默认启用）")
    parser.add_argument("--no-formula", action="store_false", dest="formula", help="禁用公式识别")
    parser.add_argument("--ocr", action="store_true", help="启用 OCR")
    parser.add_argument("--model", default="vlm",
                       choices=["pipeline", "vlm", "MinerU-HTML"],
                       help="模型版本（默认：vlm）")
    parser.add_argument("--output", "-o", help="保存结果到文件")
    parser.add_argument("--quiet", "-q", action="store_true", help="静默模式，仅输出 Markdown")
    
    args = parser.parse_args()
    
    try:
        content = parse_local_file(
            file_path=args.file,
            page_ranges=args.pages,
            enable_table=args.table,
            enable_formula=args.formula,
            is_ocr=args.ocr,
            model_version=args.model,
            output_file=args.output,
            quiet=args.quiet
        )
        
        # 如果是静默模式，直接输出内容
        if args.quiet:
            print(content)
        
    except MinerUError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
