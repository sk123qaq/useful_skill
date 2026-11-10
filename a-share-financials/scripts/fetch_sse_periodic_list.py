#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉上交所「定期报告」栏目公告名单（CSV + JSON）。

用法：
  python3 fetch_sse_periodic_list.py --type QUATER3 --begin 2026-09-01 --end 2026-10-31 --out ./q3
  python3 fetch_sse_periodic_list.py --type YEARLY --begin 2026-01-01 --end 2026-05-01 --board kcb

reportType 枚举：YEARLY / QUATER1 / QUATER2 / QUATER3 / ALL
board：all（全部板块，默认）/ main（主板）/ kcb（科创板）

输出：<out>/sse_<type>_raw.json 与同名 .csv（证券代码,证券简称,公告标题,公告日期）
响应是 JSONP，必须带 Referer，否则被拒。
"""
import argparse
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0 Safari/537.36')
REFERER = 'https://www.sse.com.cn/disclosure/listedinfo/regular/'
BASE = 'https://query.sse.com.cn/security/stock/queryCompanyBulletin.do'
BOARDS = {
    'all': '0101,120100,020100,020200,120200',  # 主板A + 科创板（含 B 股代码段）
    'main': '0101',
    'kcb': '120100,020100,020200,120200',
}


def fetch_page(page, size, args):
    q = {
        'jsonCallBack': 'cb', 'isPagination': 'true',
        'pageHelp.pageSize': str(size), 'pageHelp.pageNo': str(page),
        'pageHelp.beginPage': str(page), 'pageHelp.cacheSize': '1',
        'pageHelp.endPage': str(page), 'productId': '',
        'securityType': BOARDS[args.board],
        'reportType2': 'DQBG', 'reportType': args.type,
        'beginDate': args.begin, 'endDate': args.end,
        '_': str(int(time.time() * 1000)),
    }
    url = BASE + '?' + urllib.parse.urlencode(q, safe=',')
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': REFERER, 'Accept': '*/*'})
    txt = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
    m = re.match(r'^\s*cb\((.*)\)\s*;?\s*$', txt, re.S)
    payload = json.loads(m.group(1) if m else txt)
    return payload['pageHelp']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--type', default='QUATER3')
    ap.add_argument('--begin', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--board', default='all', choices=sorted(BOARDS))
    ap.add_argument('--out', default='.')
    ap.add_argument('--size', type=int, default=100)
    args = ap.parse_args()

    first = fetch_page(1, args.size, args)
    total = first.get('total') or 0
    rows = list(first.get('data') or [])
    pages = (total + args.size - 1) // args.size
    print('total %d pages %d' % (total, pages), flush=True)

    for p in range(2, pages + 1):
        for attempt in range(4):
            try:
                rows += fetch_page(p, args.size, args).get('data') or []
                break
            except Exception as e:  # 限流/断开就退避重试
                print('retry page %d (%s)' % (p, e), flush=True)
                time.sleep(1.5 * (attempt + 1))
        else:
            print('FAILED page %d' % p, flush=True)
        time.sleep(0.35)

    # 按代码去重（更正稿/多份公告只留首条）；打印异常标题供人工判断
    uniq, seen = [], set()
    for r in rows:
        code = r.get('SECURITY_CODE')
        if code in seen:
            continue
        seen.add(code)
        uniq.append(r)
    odd = [r['TITLE'] for r in uniq
           if '季度报告' not in (r.get('TITLE') or '') and '年度报告' not in (r.get('TITLE') or '')]
    print('rows %d unique %d' % (len(rows), len(uniq)), flush=True)
    if odd:
        print('标题不含“季度报告/年度报告”的 %d 条，抽检：' % len(odd), odd[:10], flush=True)

    os.makedirs(args.out, exist_ok=True)
    js = os.path.join(args.out, 'sse_%s_raw.json' % args.type.lower())
    json.dump(uniq, open(js, 'w'), ensure_ascii=False)
    cs = js.replace('.json', '.csv')
    with open(cs, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['证券代码', '证券简称', '公告标题', '公告日期'])
        for r in uniq:
            w.writerow([r.get('SECURITY_CODE'), r.get('SECURITY_NAME'),
                        r.get('TITLE'), r.get('SSEDATE')])
    print('saved', js, 'and', cs)


if __name__ == '__main__':
    main()
