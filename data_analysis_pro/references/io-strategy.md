# I/O 策略

## 当前适用范围

本文件只描述 `io_router.py` 当前真实支持的文件输入能力。

不要把它理解成数据库接入、SQL 查询路由或自动大数据执行引擎的说明书。当前 `data_analysis_pro` 没有稳定的数据库读取 CLI，也没有 `db_smoke_test.py`。

## 当前支持的输入格式

`io_router.py` 当前直接识别：

- `.csv`
- `.tsv`
- `.xlsx`
- `.xlsm`
- `.xls`
- `.xlsb`
- `.parquet`
- `.feather`
- `.json`
- `.jsonl`

同时支持一些常见压缩后缀：

- `.gz`
- `.bz2`
- `.xz`

以及 `.zip` 容器。

## 当前容器处理规则

### 目录输入

如果输入是目录，`io_router.py` 会递归搜索其中的受支持文件，然后默认选择“体积最大的候选文件”。

这只是启发式，不是业务语义理解。

因此：

- 如果目录里有多张表，不要默认认为自动选中的就是主表。
- 最好先看一眼 `warnings`，确认自动选择是否合理。

### ZIP 输入

如果输入是 `.zip`，当前逻辑会在压缩包内找受支持文件，并默认选择文件体积最大的成员。

这同样只是启发式。

## 当前输出的读取计划

`io_router.py` 会输出一个轻量的读取计划，常见字段包括：

- `path`
- `exists`
- `supported`
- `kind`
- `format`
- `compression`
- `size_bytes`
- `size_mb`
- `recommended_backend`
- `requires`
- `preview_available`
- 对目录或 ZIP，还可能有：
  - `warnings`
  - `member_name`
  - `member_size_bytes`

## 当前 backend recommendation 的真实含义

`recommended_backend` 是建议，不是已经执行的引擎切换。

当前真实情况是：

- `build_file_read_plan()` 会给出类似 `pandas`、`pandas_excel`、`pandas_or_polars`、`polars_or_duckdb` 的建议
- 但 `load_dataframe()` 目前实际仍然走 `pandas`

所以：

- 不要把 `recommended_backend = polars_or_duckdb` 误读成“代码已经自动切到 polars 或 duckdb”
- 对大文件，这个字段更像风险提示

## 大小启发式

当前建议阈值是：

- 150 MB 以下：通常 `pandas` 足够
- 150 MB 到 1.5 GB：从分析设计上应考虑更轻的读取策略
- 1.5 GB 以上：不应想当然地全量直接读进内存

但再次强调：这些是建议阈值，不是当前脚本已经自动执行的分流逻辑。

## 采样与预览

`load_dataframe(input_path, sample_rows=...)` 支持按行数做轻量采样读取。

适合的场景：

- 先看文件结构
- 先验证字段名
- 先做小样本画像

不适合的场景：

- 需要精确统计全量缺失率
- 需要依赖全量分布做建模判断

## Excel 规则

Excel 适合小规模或中等规模表格，不适合作为超大数据集的运行时格式。

如果用户描述的是“超大 Excel”：

- 优先建议导出成 CSV
- 或转成 Parquet
- 不要假设当前 skill 已经提供专门的 Excel 大文件优化路径

## 当前不支持或不应默认承诺的能力

- 数据库 URL 直连
- SQL 查询执行
- 自动把过滤和聚合下推到数据库
- 数据库驱动探测
- `db_smoke_test.py`

## 防护准则

- 先确认读对了文件，再继续分析。
- 如果输入是目录或 ZIP，务必检查自动选择是否合理。
- 如果文件很大，不要因为 `io_router.py` 给出了建议 backend，就误以为系统已经自动完成了性能优化。
- 如果读取策略本身就存在高风险，应在分析开始前明确告诉用户，而不是等到后面再补救。
