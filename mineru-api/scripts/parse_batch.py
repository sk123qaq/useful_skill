#!/usr/bin/env python3
"""
Batch parse local PDFs/documents using MinerU Cloud API

Examples:
    # Parse multiple files
    python parse_batch.py file1.pdf file2.pdf file3.docx
    
    # Parse with specific options
    python parse_batch.py *.pdf --table --formula --output ./results
    
    # Parse with custom data IDs
    python parse_batch.py report.pdf slides.pptx --ids "report_2024" "presentation_q1"
"""

import os
import sys
import time
import json
import argparse
from typing import List
from mineru_client import MinerUClient, MinerUError


def print_progress(current: int, total: int, prefix: str = "Progress"):
    """Print progress bar"""
    percent = current / total * 100
    bar_length = 40
    filled = int(bar_length * current / total)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(f"\r{prefix}: |{bar}| {current}/{total} ({percent:.1f}%)", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Batch parse local PDFs/documents using MinerU Cloud API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document1.pdf document2.pdf
  %(prog)s *.pdf --table --formula --output ./results
  %(prog)s report.pdf --pages "1-20" --model pipeline
        """
    )
    
    parser.add_argument("files", nargs="+", help="Local files to parse")
    parser.add_argument("--model", default="vlm",
                       choices=["pipeline", "vlm", "MinerU-HTML"],
                       help="Model version (default: vlm)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR")
    parser.add_argument("--table", action="store_true", help="Enable table extraction")
    parser.add_argument("--formula", action="store_true", help="Enable formula recognition")
    parser.add_argument("--language", default="ch", help="Document language (default: ch)")
    parser.add_argument("--formats", nargs="+",
                       choices=["markdown", "json", "docx", "html", "latex"],
                       help="Extra output formats (default: markdown+json)")
    parser.add_argument("--pages", help="Page ranges for all files, e.g., '1-10,15'")
    parser.add_argument("--ids", nargs="+", help="Custom data IDs (one per file)")
    parser.add_argument("--output", "-o", default="./mineru-batch-results",
                       help="Output directory (default: ./mineru-batch-results)")
    parser.add_argument("--timeout", type=int, default=600,
                       help="Timeout per file in seconds (default: 600)")
    parser.add_argument("--poll", type=int, default=10,
                       help="Poll interval in seconds (default: 10)")
    parser.add_argument("--token", help="API token (or set MINERU_API_TOKEN env var)")
    parser.add_argument("--save-json", action="store_true",
                       help="Save results summary to JSON file")
    
    args = parser.parse_args()
    
    # Validate files
    valid_files = []
    for f in args.files:
        if os.path.exists(f):
            valid_files.append(f)
        else:
            print(f"Warning: File not found: {f}")
    
    if not valid_files:
        print("Error: No valid files to process")
        sys.exit(1)
    
    if len(valid_files) > 200:
        print(f"Error: Too many files ({len(valid_files)}). Maximum is 200.")
        sys.exit(1)
    
    # Validate IDs if provided
    if args.ids and len(args.ids) != len(valid_files):
        print("Error: --ids must have same number of items as files")
        sys.exit(1)
    
    # Initialize client
    try:
        client = MinerUClient(api_token=args.token)
    except MinerUError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Prepare extra formats
    extra_formats = None
    if args.formats:
        extra_formats = [f for f in args.formats if f not in ["markdown", "json"]]
    
    # Prepare file metadata
    file_metadata = []
    for i, file_path in enumerate(valid_files):
        name = os.path.basename(file_path)
        data = {
            "name": name,
            "is_ocr": args.ocr
        }
        if args.ids:
            data["data_id"] = args.ids[i]
        if args.pages:
            data["page_ranges"] = args.pages
        file_metadata.append(data)
    
    print(f"Batch uploading {len(valid_files)} files...")
    print(f"  Model: {args.model}")
    print(f"  OCR: {'Yes' if args.ocr else 'No'}")
    print(f"  Table: {'Yes' if args.table else 'No'}")
    print(f"  Formula: {'Yes' if args.formula else 'No'}")
    if extra_formats:
        print(f"  Extra formats: {', '.join(extra_formats)}")
    print()
    
    # Create output directory
    os.makedirs(args.output, exist_ok=True)
    
    try:
        # Upload and create tasks
        print("Uploading files...")
        result = client.batch_upload_parse(
            files=file_metadata,
            file_paths=valid_files,
            model_version=args.model,
            enable_table=args.table,
            enable_formula=args.formula,
            language=args.language,
            output_formats=extra_formats
        )
        
        batch_id = result["batch_id"]
        print(f"\nBatch created: {batch_id}")
        print(f"\nWaiting for all tasks to complete...")
        print("(This may take several minutes depending on file sizes)")
        print()
        
        # Poll for results
        start_time = time.time()
        completed = set()
        failed = set()
        results_summary = []
        
        while len(completed) + len(failed) < len(valid_files):
            batch_result = client.get_batch_result(batch_id)
            extract_results = batch_result.get("extract_result", [])
            
            # Update status
            current_completed = set()
            current_failed = set()
            
            for item in extract_results:
                file_name = item.get("file_name")
                state = item.get("state")
                
                if state == "done":
                    current_completed.add(file_name)
                elif state == "failed":
                    current_failed.add(file_name)
            
            # Print updates
            newly_done = current_completed - completed
            newly_failed = current_failed - failed
            
            for f in newly_done:
                print(f"  ✓ {f}")
            for f in newly_failed:
                item = next((x for x in extract_results if x["file_name"] == f), {})
                print(f"  ✗ {f} - {item.get('err_msg', 'Unknown error')}")
            
            completed = current_completed
            failed = current_failed
            
            # Print progress
            done_count = len(completed) + len(failed)
            print_progress(done_count, len(valid_files), "Overall")
            
            # Check if all done
            if done_count >= len(valid_files):
                break
            
            # Check timeout
            if time.time() - start_time > args.timeout * len(valid_files):
                print("\n\nWarning: Timeout reached")
                break
            
            time.sleep(args.poll)
        
        print()  # Newline after progress bar
        
        # Download results
        print("\nDownloading results...")
        batch_result = client.get_batch_result(batch_id)
        
        for item in batch_result.get("extract_result", []):
            file_name = item.get("file_name")
            state = item.get("state")
            download_url = item.get("full_zip_url")
            err_msg = item.get("err_msg", "")
            data_id = item.get("data_id", "")
            
            result_entry = {
                "file_name": file_name,
                "state": state,
                "data_id": data_id
            }
            
            if state == "done" and download_url:
                base_name = os.path.splitext(file_name)[0]
                output_file = os.path.join(args.output, f"{base_name}.zip")
                
                try:
                    client.download_result(download_url, output_file)
                    print(f"  ✓ {file_name}")
                    result_entry["downloaded"] = output_file
                    
                    # Try to extract
                    try:
                        import zipfile
                        extract_dir = os.path.join(args.output, base_name)
                        with zipfile.ZipFile(output_file, 'r') as zip_ref:
                            zip_ref.extractall(extract_dir)
                        result_entry["extracted"] = extract_dir
                    except Exception as e:
                        result_entry["extract_error"] = str(e)
                        
                except Exception as e:
                    print(f"  ✗ {file_name} - Download failed: {e}")
                    result_entry["error"] = str(e)
            elif state == "failed":
                print(f"  ✗ {file_name} - {err_msg}")
                result_entry["error"] = err_msg
            
            results_summary.append(result_entry)
        
        # Print summary
        total = len(valid_files)
        success = len([r for r in results_summary if r["state"] == "done"])
        fail = len([r for r in results_summary if r["state"] == "failed"])
        
        print(f"\n{'='*50}")
        print(f"Summary: {success}/{total} succeeded, {fail}/{total} failed")
        print(f"Output directory: {os.path.abspath(args.output)}")
        
        # Save JSON summary
        if args.save_json:
            json_path = os.path.join(args.output, "results_summary.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "batch_id": batch_id,
                    "total_files": total,
                    "succeeded": success,
                    "failed": fail,
                    "results": results_summary
                }, f, indent=2, ensure_ascii=False)
            print(f"Results saved to: {json_path}")
        
    except MinerUError as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print(f"Batch ID: {batch_id} (you can check status later)")
        sys.exit(130)


if __name__ == "__main__":
    main()
