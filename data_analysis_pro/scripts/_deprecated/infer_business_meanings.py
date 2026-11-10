#!/usr/bin/env python3
import argparse
import json
import pandas as pd
from pathlib import Path
import sys

# Add current directory to path for metadata_manager
sys.path.append(str(Path(__file__).parent))
from metadata_manager import MetadataManager

def infer_meanings(df, sample_size=5):
    """
    Infers business meanings for columns based on names and sample data.
    In a real scenario, this might call an LLM API. 
    Here, we implement the 'Analysis Expert' logic.
    """
    meanings = {}
    for col in df.columns:
        col_lower = col.lower()
        sample_vals = df[col].head(sample_size).tolist()
        
        # Logic for Credit Card Fraud Dataset V1-V28
        if col.startswith('V') and col[1:].isdigit():
            v_num = int(col[1:])
            if 1 <= v_num <= 28:
                meanings[col] = {
                    "business_name": f"去隐私化行为特征 V{v_num}",
                    "description": f"经过PCA处理的第{v_num}个核心行为分量，代表了交易行为中的某种潜在模式（如地理位置、终端类型、时间频次等）。"
                }
                continue

        # Common Financial/Business fields
        if "amount" in col_lower:
            meanings[col] = {"business_name": "交易金额", "description": "本次交易的原始金额。"}
        elif "time" in col_lower:
            meanings[col] = {"business_name": "交易时间步", "description": "相对于数据集中第一笔交易流逝的秒数。"}
        elif "class" in col_lower or "label" in col_lower or "target" in col_lower:
            meanings[col] = {"business_name": "欺诈标签", "description": "0表示正常交易，1表示欺诈交易。"}
        else:
            # Generic inference
            meanings[col] = {
                "business_name": col.replace("_", " ").title(),
                "description": f"原始字段 {col}，包含数据样例: {sample_vals[:2]}"
            }
            
    return meanings

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--registry-path", default="metadata_registry.json")
    args = parser.parse_args()

    df = pd.read_csv(args.input_path, nrows=5)
    manager = MetadataManager(storage_path=args.registry_path)
    
    inferred = infer_meanings(df)
    
    for col, meta in inferred.items():
        manager.register_column(col, meta["business_name"], meta["description"])
        
    print(f"Successfully inferred and registered {len(inferred)} columns to {args.registry_path}")

if __name__ == "__main__":
    main()
