#!/usr/bin/env python3
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import sys

# Add scripts to path for common
sys.path.append(str(Path(__file__).parent.parent.parent / "scripts"))
import common

# Configure matplotlib for Chinese
common._configure_runtime_environment()
# Find and set font
import matplotlib
for font in common.CJK_FONT_CANDIDATES:
    if font in [f.name for f in matplotlib.font_manager.fontManager.ttflist]:
        plt.rcParams['font.sans-serif'] = [font]
        break
plt.rcParams['axes.unicode_minus'] = False

def get_label(key, default):
    return common.DEFAULT_CHINESE_FIELD_LABELS.get(key, common.COMMON_TOKEN_TRANSLATIONS.get(key, default))

def get_value_label(val):
    return common.DEFAULT_CHINESE_VALUE_LABELS.get(str(val).lower(), str(val))

def plot_obesity_by_feature(df, feature, output_path):
    plt.figure(figsize=(10, 6))
    
    # Calculate obesity rate per group
    # Ensure obese is numeric
    df['obese'] = pd.to_numeric(df['obese'], errors='coerce')
    
    # Group by feature and calculate mean
    stats = df.groupby(feature)['obese'].agg(['mean', 'count']).reset_index()
    stats = stats.sort_values(by='mean', ascending=False)
    
    # Translate feature values for display
    stats['display_label'] = stats[feature].apply(get_value_label)
    
    # Plot
    sns.barplot(data=stats, x='display_label', y='mean', palette='viridis')
    
    # Labels and title
    feature_label = get_label(feature, feature)
    plt.title(f'按{feature_label}划分的肥胖率', fontsize=15)
    plt.xlabel(feature_label, fontsize=12)
    plt.ylabel('肥胖率', fontsize=12)
    plt.ylim(0, 1) # Obesity rate is 0 to 1
    
    # Add values on top of bars
    for i, row in stats.iterrows():
        plt.text(i, row['mean'] + 0.01, f'{row["mean"]:.1%}', ha='center')
        plt.text(i, row['mean'] / 2, f'n={row["count"]}', ha='center', color='white')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()

if __name__ == "__main__":
    input_path = "/Users/sk/program/useful_skill/data_analysis/assets/external/brfss_2024/brfss_2024_obesity_modeling_full.csv"
    output_dir = Path("data_analysis_pro/outputs/obesity_analysis")
    
    # Load data
    df = pd.read_csv(input_path)
    
    # Key features to plot
    features = ['general_health', 'diabetes_status', 'age_group', 'exercise_past_30d']
    
    for feature in features:
        print(f"Plotting for {feature}...")
        output_path = output_dir / f"obesity_by_{feature}.png"
        plot_obesity_by_feature(df, feature, output_path)
    
    print("All plots generated.")
