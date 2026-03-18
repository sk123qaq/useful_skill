# Data Analysis Skill

这是一个面向结构化数据分析的技能目录，覆盖数据读取、清洗、EDA、建模、因果分析、实验分析、报表导出与研究辅助。

## 快速开始

```bash
cd /path/to/data_analysis
python3 -m pip install -r requirements.txt
python3 scripts/check_environment.py
python3 scripts/run_pipeline.py --help
```

如果需要高级模型、交互式仪表盘或额外数据库驱动：

```bash
cd /path/to/data_analysis
python3 -m pip install -r requirements-optional.txt
```

## 常用入口

- `SKILL.md`：完整工作流与使用规则
- `scripts/check_environment.py`：检查依赖与运行环境
- `scripts/run_pipeline.py`：统一 CLI 入口
- `scripts/source_research_adapter.py`：外部研究辅助
- `references/`：方法、环境、图表、报告规范
- `templates/`：正式报告模板

## 典型命令

```bash
# 仅做环境检查
python3 scripts/check_environment.py

# 先只生成规划与环境产物
python3 scripts/run_pipeline.py --plan-only

# 常规分析（默认同时导出 report_dashboard.html + report_process.html）
python3 scripts/run_pipeline.py --input-path /path/to/data.csv --task regression --target y

# 如需关闭全流程报告，仅保留 dashboard
python3 scripts/run_pipeline.py --input-path /path/to/data.csv --task regression --target y --no-process-report

# 运行 WDI 数据集适配器
python3 scripts/run_pipeline.py --dataset wdi --input-path /path/to/WDI_csv.zip
```

## 说明

- `assets/` 用于本地样例或临时数据，仓库默认只保留空目录占位
- `outputs/` 用于保存运行产物，仓库默认只保留空目录占位
- `requirements.txt` 提供默认安装基线
- `requirements-optional.txt` 只在任务需要时安装
