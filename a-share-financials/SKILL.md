---
name: a-share-financials
description: "Use when 查A股财报：指标、三大报表、单季同环比、批量名单出表。"
version: 0.1.0
author: sk123qaq, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [a股, 财报, 财务指标, 东方财富, 同比环比]
    related_skills: [agent-reach, china-futures-data]
---

# A股财报数据（东方财富 F10 datacenter）

覆盖：任一 A 股上市公司的财务数据——主要财务指标（EPS/ROE/毛利率/周转天数/偿债能力）、利润表、资产负债表、现金流量表，以及单季度拆分与同比/环比。回答用中文。

## When to Use

触发问句形如「查宁德一季度/半年报/三季报主要财务指标」「按季度的同环比」「拿一下茅台的财报」「XX 的营收利润」「某公司各期财务指标」；批量形态如「某交易所/某报告期已披露公司名单，按行业分 Excel，按市值降序」。

两类任务走不同路径：**单家公司**用 Step 1-5；**批量横截面**（名单 → 全市场 → 分组出表）用 Step 6。

不适用：实时行情与盘口（用 `agent-reach` skill 的 references/finance.md）、期货（用 `china-futures-data`）、港美股。

## Step 1 — 直连取数，不装库不开代理

东财 datacenter F10 接口国内直连、无 token、无登录态要求。**不要为此装 akshare/tushare，也不要挂代理**——直连即可，装库只会浪费时间。

```bash
curl -s 'https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter=(SECUCODE%3D%22300750.SZ%22)&pageNumber=1&pageSize=40&sortTypes=-1&sortColumns=REPORT_DATE&source=HSF10&client=PC' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36' \
  -H 'Referer: https://emweb.securities.eastmoney.com/' -o main.json
```

- `SECUCODE` = `代码.交易所`：深 `.SZ`、沪 `.SH`、北 `.BJ`。filter 里引号编码为 `%22`、等号 `%3D`。
- `Referer: https://emweb.securities.eastmoney.com/` 必须带，缺头会被拒。
- 四个 reportName（一律 `columns=ALL` 全字段取回，再按需挑列，几百个字段）：

  | 报表 | reportName |
  |---|---|
  | 主要财务指标（累计口径） | `RPT_F10_FINANCE_MAINFINADATA` |
  | 利润表 | `RPT_F10_FINANCE_GINCOME` |
  | 资产负债表 | `RPT_F10_FINANCE_GBALANCE` |
  | 现金流量表 | `RPT_F10_FINANCE_GCASHFLOW` |

- **接口只给累计口径，没有单季报表**：任何带 `QB` 的名字（如 `RPT_F10_FINANCE_GINCOMEQB`）返回 `{"success":false,"message":"报表配置不存在","code":9501}`。单季度永远靠差分自己算（Step 3），不要去找单季接口。
- 原始 JSON 先落盘再处理——改口径、补指标、重跑都不重新请求。

## Step 2 — 解析

- 报告期唯一键 = `r['REPORT_DATE'][:10]`（原值形如 `2026-09-30 00:00:00`）。建好 dict **先打印全部报告期核对**，再按键取值：报告期集合随披露进度变化（三季报披露后才有 09-30），直接索引会 KeyError。
- `success:true` 时 `count` 可能为 `null`，行数看 `len(result.data)`。
- 常用字段是英文缩写，不是中文：`TOTALOPERATEREVE` 营业总收入、`MLR` 毛利、`PARENTNETPROFIT` 归母净利润、`KCFJCXSYJLR` 扣非净利润、`EPSJB`、`ROEJQ` 加权ROE、`XSMLL` 毛利率、`XSJLL` 净利率、`ZCFZL` 资产负债率、`LD`/`SD` 流动/速动比率、`CHZZTS`/`YSZKZZTS` 存货/应收周转天数；利润表另有 `RESEARCH_EXPENSE` 研发费用。
- **研发费用从利润表取**：主指标接口的 `RDEXPEND` 只在中报/年报披露，一季报/三季报是 `-`，按季度取会静默缺失。
- 内部键格式统一（要么全 `2025Q1` 要么全 `25Q1`）——混用时错误只在最后汇总才炸，前面全白跑。

## Step 3 — 单季度拆分与同环比

- 累计期映射一次建好再循环差分，不要在循环里现拼日期：`Q1 = 累计(Q1)`；`Qn = 累计(Qn) − 累计(Qn−1)`；`Q4 = 年报 − 三季报`。某一期缺失就断开链条、跳过本年后续季度——**不要把累计值当单季交付**。
- 同比 = 本季 ÷ 去年同季 − 1；环比 = 本季 ÷ 上一季 − 1，**Q1 的环比基期是去年 Q4**（必须由年报减出来，跳过就没有一季度环比）。
- **利润率/费用率单独写 `ratio(a,b)=a/b*100`**，不要复用同比的 `pct(a,b)=a/b−1`——复用一次，毛利率就变成 −75% 这种数量级错误，而且表里看起来"像个数"，极难发现。
- 金额换算成亿元（`/1e8`）再进表；同比/环比保留 1 位小数并带符号。

## Step 4 — 交付前校验

- **单季度加总必须等于官方累计值**（逐期对 `TOTALOPERATEREVE`/`PARENTNETPROFIT`）；不等就是日期映射或差分基数错了，先修再交付。
- 累计口径同比与接口自带 `TOTALOPERATEREVETZ`/`PARENTNETPROFITTZ` 对照一次，能确认没取错行。

## Step 5 — 交付格式（既定形状）

- 三张表分开给，且各自标明口径：
  1. 今年各期**累计口径**主要财务指标（营收+同比、归母+同比、扣非、毛利、研发、EPS、每股净资产、加权ROE、毛利率、净利率、资产负债率、流动/速动比率……按用户问的取舍）；
  2. **单季度拆分**（今年各季 + 去年同季做基数），注明"单季度由累计差分得出"；
  3. 单季度**同比/环比**（yoy、qoq 分列，不要混在一列）。
- 表后可附单季度毛利率/净利率/研发费用率一行，趋势比绝对值更能说明问题。
- 表后跟 2-4 条解读要点（剪刀差、拐点、边际变化、异常项），不要只堆数字。
- 末尾给原始 JSON 路径，并说明可继续导 Excel / 补资产负债表与现金流指标。

## Step 6 — 批量横截面：报告期名单 → 分组 Excel

1. **名单以交易所披露栏目为准**，不用第三方榜单。上交所：`https://query.sse.com.cn/security/stock/queryCompanyBulletin.do`，参数 `reportType2=DQBG&reportType=QUATER3|QUATER2|QUATER1|YEARLY`、`securityType=0101,120100,020100,020200,120200`（0101 主板A股、020100 科创板）、`beginDate/endDate`、`pageHelp.pageSize=100`；响应是 `cb({...})` 包一层的 JSONP，正则剥壳再 `json.loads`。必须带 `Referer: https://www.sse.com.cn/disclosure/listedinfo/regular/`。现成脚本：`scripts/fetch_sse_periodic_list.py`。
   - 不确定参数时，在披露页跑 `performance.getEntriesByType('resource')` 找 `query.sse.com.cn` 的真实请求 URL，参数照抄；下拉框的 `option.value` 就是枚举值。
   - 从 `www.sse.com.cn` 页面里 `fetch('https://query.sse.com.cn/...')` 会因跨域直接失败；改本地 curl/urllib 直连带 Referer。
2. **名单与东财业绩报表对账**：`RPT_LICO_FN_CPD?filter=(REPORTDATE%3D'<期末日>')` 一次拉全市场（约 3700 家），按 `SECUCODE` 后缀切交易所。差集里出现 900xxx 是 A+B 双重上市公司的 B 股代码（同一公司两个代码），不是漏抓；真正缺的在两边各自列出来单独看。
3. **市值+行业一次拉全市场**：不要用 `push2.eastmoney.com/api/qt/clist/get` 逐页翻 2500 只——大批量连打会被限流，返回空响应、断连，越重试越慢。改用 datacenter 估值表 `reportName=RPT_VALUEANALYSIS_DET&pageSize=500&filter=(TRADE_DATE%3D'<最近交易日>')`，12 页拿 5500+ 只，字段 `TOTAL_MARKET_CAP`（总市值，元）、`BOARD_NAME`（东财细分行业）。少数缺失（新上市、纯 B 股）用腾讯补：`https://qt.gtimg.cn/q=sh600017`（GBK 解码，`split('~')[45]` 总市值亿元、`[44]` 流通市值）。
4. **逐家拉利润表**：每家公司一次 `RPT_F10_FINANCE_GINCOME`（`pageSize=8` 覆盖近 8 期），`ThreadPoolExecutor(10)` + 结果落盘 `raw/<code>.json`，单请求 3-4 次退避重试；千余家 1-2 分钟跑完，中断后按文件存在性断点续跑。
5. **行业分组**：东财 `BOARD_NAME` 有 119 个细分，直接分 sheet 太多；映射到申万一级 31 类再分表，映射表见 `references/industry-mapping-sw.md`，明细里同时保留细分行业列（用户要能追到原始颗粒度）。
6. **Excel 形状**：`说明与口径` → `行业汇总`（按营收合计降序，带市值占比与合计行）→ `全部公司` → 每个行业一表，明细一律按总市值降序；金额统一亿元、比率百分数 1 位小数、负值红正值绿、首行冻结加筛选。完整列清单与说明页条目见 `references/batch-market-scan.md`。

批量任务的三个硬规则：

- **基数 ≤ 0 一律写 `n.m.`**（Not Meaningful）并在备注列写明是哪一项，不要出版本失真的百分比。
- **金融股不修正**：保险、券商的营业总收入受新准则与并表口径重述影响，单季同比出现 −50% 甚至 −90% 是报表原值；表内在说明页注明口径，不要在表里"修"。
- **交叉校验必做**：累计营收/归母与 `RPT_LICO_FN_CPD` 逐家比对（应 0 偏差），累计同比与 `YSTZ` 对照；东财 `SJLTZ` 对个别公司与自算值不一致，以利润表原值自算为准并在说明页列明。

## 可复用脚本

`scripts/fetch_a_share_financials.py`——给定 SECUCODE，拉四张表、拆单季度、算同环比、做加总校验，stdout 打印 GFM 表并输出 CSV（utf-8-sig，Excel 直开）。`--years` 换窗口，`--out` 指定目录。脚本报错时以 Step 1-4 的内联流程为准。

`scripts/fetch_sse_periodic_list.py`——按报告类型与日期范围拉上交所定期报告公告名单（CSV+JSON、去重、打印统计）。`--type QUATER3 --begin 2026-09-01 --end 2026-10-31`。
