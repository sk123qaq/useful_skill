#!/usr/bin/env python3
"""A股财报：东财 F10 四表 + 单季度拆分 + 同比/环比 + 加总校验。

用法:
    python3 fetch_a_share_financials.py 300750.SZ [--years 2024 2025 2026] [--out DIR]

口径: 接口只给累计值。单季度 = 累计(Qn) - 累计(Qn-1)；Q4 = 年报 - 三季报；
      Q1 的环比基期是上年 Q4。输出 CSV 为 utf-8-sig（Excel 直开）。
"""
import argparse
import csv
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
REPORTS = {
    "main": "RPT_F10_FINANCE_MAINFINADATA",    # 主要财务指标（累计）
    "income": "RPT_F10_FINANCE_GINCOME",       # 利润表（研发费用在这）
    "balance": "RPT_F10_FINANCE_GBALANCE",     # 资产负债表
    "cashflow": "RPT_F10_FINANCE_GCASHFLOW",   # 现金流量表
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/",
}
# (接口字段, 中文名, 取自哪张表)
METRICS = [
    ("TOTALOPERATEREVE", "营业总收入", "main"),
    ("MLR", "毛利", "main"),
    ("PARENTNETPROFIT", "归母净利润", "main"),
    ("KCFJCXSYJLR", "扣非净利润", "main"),
    ("RESEARCH_EXPENSE", "研发费用", "income"),
]
QS = ["Q1", "Q2", "Q3", "Q4"]
QE = {"Q1": "-03-31", "Q2": "-06-30", "Q3": "-09-30", "Q4": "-12-31"}


def fetch(report_name, secucode):
    query = {
        "reportName": report_name, "columns": "ALL",
        "filter": '(SECUCODE="%s")' % secucode,
        "pageNumber": "1", "pageSize": "60",
        "sortTypes": "-1", "sortColumns": "REPORT_DATE",
        "source": "HSF10", "client": "PC",
    }
    req = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(query), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not data.get("result"):
        sys.exit("[%s] 无数据: %s（接口只给累计口径，没有单季报表，不要去找 QB 接口）"
                 % (report_name, data.get("message")))
    return data["result"]["data"]


def main():
    this_year = datetime.date.today().year
    ap = argparse.ArgumentParser()
    ap.add_argument("secucode", help="代码.交易所，如 300750.SZ / 600519.SH / 830799.BJ")
    ap.add_argument("--years", nargs="+", type=int,
                    default=[this_year - 2, this_year - 1, this_year])
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    tables = {}
    for name, rn in REPORTS.items():
        rows = fetch(rn, args.secucode)
        tables[name] = {r["REPORT_DATE"][:10]: r for r in rows}
        with open(os.path.join(args.out, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        print("%s: %d 期（%s ~ %s）" % (name, len(rows), min(tables[name]), max(tables[name])))

    def val(dt, key, src):
        return (tables[src].get(dt) or {}).get(key)

    # 单季度拆分（亿元）：累计期映射一次建好，再循环差分；链条断开就跳过年内后续季度
    qd = {}
    for key, label, src in METRICS:
        row = {}
        for year in args.years:
            prev_dt, broken = None, False
            for q in QS:
                dt = "%d%s" % (year, QE[q])
                cur = val(dt, key, src) if dt in tables[src] else None
                if cur is None:
                    broken = True
                    continue
                if broken:
                    continue
                v = cur - (val(prev_dt, key, src) or 0) if prev_dt else cur
                row["%02d%s" % (year % 100, q)] = v / 1e8
                prev_dt = dt
        qd[label] = row

    labels = sorted({k for row in qd.values() for k in row},
                    key=lambda s: (int(s[:2]), s[2:]))

    def pct(a, b):
        return (a / b - 1) * 100 if b else None

    yoy, qoq = {}, {}
    for label, row in qd.items():
        yoy[label], qoq[label] = {}, {}
        for i, k in enumerate(labels):
            if k not in row:
                continue
            base = "%02d%s" % (int(k[:2]) - 1, k[2:])
            if base in row:
                yoy[label][k] = pct(row[k], row[base])
            if i and labels[i - 1] in row:
                qoq[label][k] = pct(row[k], row[labels[i - 1]])

    margins = {}
    rev = qd["营业总收入"]
    for label, num in [("毛利率", "毛利"), ("归母净利率", "归母净利润"), ("研发费用率", "研发费用")]:
        margins[label] = {k: v / rev[k] * 100 for k, v in qd[num].items() if k in rev}

    # 校验：单季度加总 == 官方累计
    bad = 0
    for key, label, src in METRICS:
        for year in args.years:
            for qs_in in (["Q1"], ["Q1", "Q2"], ["Q1", "Q2", "Q3"], QS):
                dt = "%d%s" % (year, QE[qs_in[-1]])
                cum = val(dt, key, src)
                if cum is None:
                    continue
                parts = [qd[label].get("%02d%s" % (year % 100, q)) for q in qs_in]
                if any(p is None for p in parts):
                    continue
                if abs(sum(parts) * 1e8 - cum) > 1e4:
                    bad += 1
                    print("[校验失败] %s %s: 差分加总 %.1f 亿 vs 官方 %.1f 亿"
                          % (label, dt, sum(parts), cum / 1e8))
    print("校验：%s" % ("单季度加总与官方累计一致" if not bad else "%d 处不一致，先修再交付" % bad))

    def gfm(title, rows_map, fmt):
        print("\n### %s" % title)
        print("| 指标 | " + " | ".join(labels) + " |")
        print("|" + "---|" * (len(labels) + 1))
        for _, label, _ in METRICS:
            cells = [fmt(rows_map[label][k]) if k in rows_map[label] else "-" for k in labels]
            print("| %s | %s |" % (label, " | ".join(cells)))

    gfm("单季度（亿元）", qd, lambda v: "%.1f" % v)
    gfm("同比（%）", yoy, lambda v: "%+.1f" % v)
    gfm("环比（%）", qoq, lambda v: "%+.1f" % v)
    gfm("利润率/费用率（%）", margins, lambda v: "%.1f" % v)

    for fname, rows_map, fmt in [("quarterly.csv", qd, "%.1f"),
                                 ("yoyqoq.csv", yoy, "%+.1f"),
                                 ("margins.csv", margins, "%.1f")]:
        with open(os.path.join(args.out, fname), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["指标"] + labels)
            for _, label, _ in METRICS:
                w.writerow([label] + [fmt(rows_map[label][k]) if k in rows_map[label] else ""
                                      for k in labels])
    print("\nCSV（utf-8-sig）与原始 JSON 已写入 %s" % os.path.abspath(args.out))


if __name__ == "__main__":
    main()
