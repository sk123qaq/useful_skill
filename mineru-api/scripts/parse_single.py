#!/usr/bin/env python3
"""
Parse a single PDF/document using MinerU Cloud API

Examples:
    # Parse URL
    python parse_single.py --url https://example.com/doc.pdf
    
    # Parse with specific options
    python parse_single.py --url https://example.com/doc.pdf --table --formula --model vlm
    
    # Parse specific pages only
    python parse_single.py --url https://example.com/doc.pdf --pages "1-10,15"
"""

import os
import sys
import time
import argparse
from mineru_client import MinerUClient, MinerUError


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def progress_callback(progress: dict):
    """Print progress updates"""
    extracted = progress.get('extracted_pages', 0)
    total = progress.get('total_pages', 0)
    start_time = progress.get('start_time', '')
    print(f"  Progress: {extracted}/{total} pages ({extracted/total*100:.1f}%) - Started: {start_time}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse a single PDF/document using MinerU Cloud API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url https://example.com/paper.pdf
  %(prog)s --url https://example.com/doc.pdf --table --formula
  %(prog)s --url https://example.com/book.pdf --pages "1-50" --formats markdown docx
        """
    )
    
    parser.add_argument("--url", required=True, help="URL to the file")
    parser.add_argument("--model", default="vlm", 
                       choices=["pipeline", "vlm", "MinerU-HTML"],
                       help="Model version (default: vlm)")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR")
    parser.add_argument("--table", action="store_true", help="Enable table extraction")
    parser.add_argument("--formula", action="store_true", help="Enable formula recognition")
    parser.add_argument("--language", default="ch", help="Document language (default: ch)")
    parser.add_argument("--formats", nargs="+", choices=["markdown", "json", "docx", "html", "latex"],
                       help="Extra output formats (default: markdown+json)")
    parser.add_argument("--pages", help="Page ranges, e.g., '1-10,15,20-25'")
    parser.add_argument("--data-id", help="Custom data ID for tracking")
    parser.add_argument("--output", "-o", help="Download results to this directory")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds (default: 300)")
    parser.add_argument("--poll", type=int, default=5, help="Poll interval in seconds (default: 5)")
    parser.add_argument("--token", help="API token (or set MINERU_API_TOKEN env var)")
    
    args = parser.parse_args()
    
    # Initialize client
    try:
        client = MinerUClient(api_token=args.token)
    except MinerUError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Prepare extra formats
    extra_formats = None
    if args.formats:
        # Filter out default formats
        extra_formats = [f for f in args.formats if f not in ["markdown", "json"]]
    
    print(f"Creating parsing task...")
    print(f"  URL: {args.url}")
    print(f"  Model: {args.model}")
    print(f"  OCR: {'Yes' if args.ocr else 'No'}")
    print(f"  Table: {'Yes' if args.table else 'No'}")
    print(f"  Formula: {'Yes' if args.formula else 'No'}")
    if args.pages:
        print(f"  Pages: {args.pages}")
    if extra_formats:
        print(f"  Extra formats: {', '.join(extra_formats)}")
    
    try:
        # Create task
        result = client.parse_url(
            file_url=args.url,
            model_version=args.model,
            is_ocr=args.ocr,
            enable_table=args.table,
            enable_formula=args.formula,
            language=args.language,
            output_formats=extra_formats if extra_formats else None,
            page_ranges=args.pages,
            data_id=args.data_id
        )
        
        task_id = result["task_id"]
        print(f"\nTask created: {task_id}")
        
        # Wait for completion
        print(f"\nWaiting for completion (timeout: {args.timeout}s)...")
        start_time = time.time()
        
        task_result = client.wait_for_completion(
            task_id=task_id,
            timeout=args.timeout,
            poll_interval=args.poll,
            progress_callback=progress_callback
        )
        
        elapsed = time.time() - start_time
        print(f"\n✓ Completed in {elapsed:.1f}s")
        
        # Show results
        download_url = task_result.get("full_zip_url")
        if download_url:
            print(f"\nDownload URL: {download_url}")
            
            # Download if output specified
            if args.output:
                import os
                os.makedirs(args.output, exist_ok=True)
                
                # Extract filename from URL
                from urllib.parse import urlparse
                parsed = urlparse(args.url)
                base_name = os.path.basename(parsed.path) or "result"
                base_name = os.path.splitext(base_name)[0]
                output_file = os.path.join(args.output, f"{base_name}.zip")
                
                print(f"\nDownloading to {output_file}...")
                client.download_result(download_url, output_file)
                print(f"✓ Downloaded: {output_file}")
                
                # Try to extract
                try:
                    import zipfile
                    extract_dir = os.path.join(args.output, base_name)
                    with zipfile.ZipFile(output_file, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    print(f"✓ Extracted to: {extract_dir}")
                except Exception as e:
                    print(f"Note: Could not extract zip: {e}")
        
    except MinerUError as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
