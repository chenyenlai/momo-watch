#!/usr/bin/env python3
"""戰鬥陀螺查詢頁（docs/bey.html）的資料：每週由 GitHub Actions 執行，產生 docs/bey/data.json

來源（robots.txt 都允許抓取；只抓公開頁面，每頁間隔幾秒）：
  BeybladeHub 上蓋資料庫  型號、中文／英文／日文名、類型、重量
  BeybladeHub T 表        強度分級（TIER_URL，台灣玩家依比賽環境排的）
  BEYWATCH.GG 每顆上蓋頁  全球比賽前幾名的使用率、冠軍率、排名（熱門度），以及商品型號 → 內含哪些上蓋

用法：
  python3 bey/fetch_bey.py                 抓全部，寫到 docs/bey/data.json
  python3 bey/fetch_bey.py --cache DIR     抓過的頁面存到 DIR，下次直接讀（開發用）
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'docs', 'bey', 'data.json')
UA = 'Mozilla/5.0 (bey-lookup; personal page, weekly)'
DELAY = 2  # 每頁間隔秒數，別給人家網站添麻煩

HUB = 'https://beybladehub.app'
HUB_BLADES = HUB + '/parts/blades'
TIER_URL = HUB + '/t/4Xuagf8J'  # 10 月份 T 度排行（使用者指定）；要換別張 T 表改這裡
BW = 'https://beywatch.gg'
BW_SITEMAP = BW + '/sitemaps/blades.xml'
TW = timezone(timedelta(hours=8))
CACHE = None


def get(url):
    path = None
    if CACHE:
        path = os.path.join(CACHE, re.sub(r'[^A-Za-z0-9._-]+', '_', url)[-150:])
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return f.read()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode('utf-8', 'replace')
            break
        except Exception as e:
            if attempt == 2:
                raise
            print('重試', url, type(e).__name__, file=sys.stderr)
            time.sleep(10)
    time.sleep(DELAY)
    if path:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return text


def text_of(fragment):
    s = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', fragment, flags=re.S)
    s = re.sub(r'<!-- -->', '', s)
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s))
    return re.sub(r'\s+', ' ', s).strip()


def norm(name):
    """比對英文名用：'Wizard Rod'、'WizardRod'、孩之寶的 'Hover Wyvern'（字序相反）都視為同一顆"""
    words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', re.sub(r'\(.*?\)', '', name or ''))
    return ''.join(sorted(w.lower() for w in words))

# ---------------------------------------------------------------------------
# BeybladeHub
# ---------------------------------------------------------------------------


def parse_hub_blades(page):
    """上蓋資料庫 → [{id, zh, en, ja, code, type, spin, weight}]"""
    out = []
    parts = re.split(r'<div id="blade-([A-Za-z0-9_-]+)"', page)
    for bid, body in zip(parts[1::2], parts[2::2]):
        body = body[:6000]
        zh = re.search(r'<div class="text-sm font-bold[^"]*">([^<]+)</div>', body)
        en = re.search(r'translate="no"[^>]*>([^<]+)</span>(?:\s*<span class="text-gray-500">([^<]*)</span>)?', body)
        # BX／UX 寫「代碼」；CX 的零件寫「收錄包裝」，或標在類型旁邊
        code = (re.search(r'代碼</span><span[^>]*>([^<]+)</span>', body)
                or re.search(r'收錄包裝：</span><span[^>]*>([BUC]XH?-\d+)', body)
                or re.search(r'>([BUC]XH?-\d+)</span>', body[:1500]))
        part = re.search(r'>[右左]旋(?:<!-- -->| )*[RL]</span>\s*<span[^>]*>([^<]{2,6})</span>', body)  # 鎖定紋章、主刃、輔助戰刃…
        weight = re.search(r'重量</span><span[^>]*>([\d.]+)g</span>', body)
        kind = re.search(r'>(攻擊|防守|持久|均衡)</span>', body)
        spin = re.search(r'>(右旋|左旋)', body)
        if not zh:
            continue
        out.append({
            'id': bid,
            'zh': html.unescape(zh.group(1)).strip(),
            'en': html.unescape(en.group(1)).strip() if en else '',
            'ja': html.unescape(en.group(2) or '').strip() if en else '',
            'part': part.group(1) if part and bid.startswith('cx-') else '',
            'code': code.group(1).strip() if code else '',
            'type': kind.group(1) if kind else '',
            'spin': spin.group(1) if spin else '',
            'weight': float(weight.group(1)) if weight else None,
        })
    return out


def next_payload(page):
    """Next.js 頁面裡 self.__next_f.push 的資料串起來"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page, re.S)
    return ''.join(json.loads('"' + c + '"') for c in chunks)


def parse_tier(page):
    """T 表 → {title, author, updated, rows: [{label, cards: [{id, name, parts}]}]}（只取上蓋分頁）"""
    title = re.search(r'<title>([^<|]+)', page)
    data = next_payload(page)
    i = data.find('{"board":')
    if i < 0:
        raise ValueError('T 表格式變了：找不到 board')
    board, _ = json.JSONDecoder().raw_decode(data, i)
    tab = next((t for t in board['board']['tabs'] if t.get('id', '').startswith('blade')), None)
    if not tab:
        raise ValueError('T 表沒有上蓋分頁')
    rows = [{'label': r['label'],
             'cards': [{'id': c['id'], 'name': c.get('name'), 'parts': [p['label'] for p in c.get('parts') or []]}
                       for c in r.get('cards') or []]}
            for r in tab['rows']]
    meta = text_of(page)
    author = re.search(r'玩家 T 表 .+? (\S+(?: \S+)?) 最後更新', meta)
    updated = re.search(r'最後更新 (\d{4})年(\d{1,2})月(\d{1,2})日', meta)
    return {
        'title': html.unescape(title.group(1)).strip() if title else '',
        'author': author.group(1) if author else '',
        'updated': '%s-%02d-%02d' % (updated.group(1), int(updated.group(2)), int(updated.group(3))) if updated else '',
        'rows': [r for r in rows if r['cards']],
    }

# ---------------------------------------------------------------------------
# BEYWATCH
# ---------------------------------------------------------------------------


def pct(s):
    return float(s.replace(',', '')) if s else None


def parse_bw_blade(page):
    """BEYWATCH 上蓋頁 → 統計＋商品"""
    s = text_of(page)
    name = re.search(r'Blade Tier List / (.+?) \1', s)
    m = lambda rx: re.search(rx, s)
    rank = m(r'Rank #(\d+)')
    first = m(r'1st Place Rate i ([\d.]+)%')
    usage = m(r'Usage i ([\d.]+)%')
    cuts = m(r'Top Cuts ([\d,]+)')
    recent = m(r'Last 90 days: ([\d.]+)% 1st place rate over ([\d,]+) top cuts , ranked #(\d+) of (\d+) blades')
    products = []
    # 「Where to Buy」：型號 商品名 廠商 Includes: 上蓋…
    for code, title, maker, inc in re.findall(
            r'\b([BUC]XH?-\d{2,3}|G\d{4}|F\d{4})\s+(.+?)\s+(Takara Tomy|Hasbro)\s+Includes:\s+(.+?)(?=\s+(?:Beys & Bricks|Amazon|Walmart|Target|eBay|[BUC]XH?-\d|G\d{4}|F\d{4})\b)', s):
        products.append({'code': code, 'name': title, 'maker': maker, 'includes': [x.strip() for x in inc.split(',')]})
    return {
        'name': name.group(1) if name else None,
        'rank': int(rank.group(1)) if rank else None,
        'first': pct(first.group(1)) if first else None,
        'usage': pct(usage.group(1)) if usage else None,
        'cuts': int(cuts.group(1).replace(',', '')) if cuts else None,
        'recent': {'first': pct(recent.group(1)), 'cuts': int(recent.group(2).replace(',', '')),
                   'rank': int(recent.group(3)), 'of': int(recent.group(4))} if recent else None,
        'products': products,
    }


def bw_through(page):
    d = re.search(r'from [\d,]+ tournaments through (\w{3} \d{1,2}, \d{4})', text_of(page))
    return d.group(1) if d else ''

# ---------------------------------------------------------------------------


def build():
    blades = parse_hub_blades(get(HUB_BLADES))
    if len(blades) < 50:
        raise SystemExit('BeybladeHub 上蓋資料庫只解析到 %d 款，格式可能變了' % len(blades))
    by_id = {b['id']: b for b in blades}
    by_en = {norm(b['en']): b for b in blades if b['en']}

    tier = parse_tier(get(TIER_URL))
    n = len(tier['rows'])
    for i, row in enumerate(tier['rows']):
        for c in row['cards']:
            b = by_id.get(c['id'])
            if b and 'tier' not in b:  # 同一顆出現在好幾級：取最高的
                b['tier'] = {'label': row['label'], 'level': i, 'of': n, 'parts': c['parts']}

    products, through, missing = {}, '', []
    urls = re.findall(r'<loc>([^<]+)</loc>', get(BW_SITEMAP))
    for url in urls:
        page = get(url)
        st = parse_bw_blade(page)
        through = through or bw_through(page)
        b = by_en.get(norm(st['name'])) or by_en.get(norm(url.rsplit('/', 1)[-1]))
        for p in st['products']:
            products.setdefault(p['code'], {'name': p['name'], 'maker': p['maker'], 'includes': []})
            for x in p['includes']:
                if x not in products[p['code']]['includes']:
                    products[p['code']]['includes'].append(x)
        if not b:
            missing.append(st['name'] or url)
            continue
        b['stats'] = {k: st[k] for k in ('rank', 'first', 'usage', 'cuts', 'recent')}
        b['bw'] = url
    # 商品內含的上蓋名稱 → BeybladeHub 的 id，網頁才能連過去
    for p in products.values():
        p['blades'] = [by_en[norm(x)]['id'] for x in p['includes'] if norm(x) in by_en]
        del p['includes']
    if missing:
        print('BEYWATCH 有、BeybladeHub 對不到的上蓋：', '、'.join(missing), file=sys.stderr)

    return {
        'updated': datetime.now(TW).strftime('%Y-%m-%d %H:%M'),
        'tier': {'title': tier['title'], 'author': tier['author'], 'updated': tier['updated'], 'url': TIER_URL,
                 'labels': [r['label'] for r in tier['rows']]},
        'usage': {'url': BW, 'through': through},
        'blades': blades,
        'products': {k: v for k, v in products.items() if re.match(r'[BUC]XH?-\d', k)},  # 只留日版型號
    }


def main():
    global CACHE
    if '--cache' in sys.argv:
        CACHE = sys.argv[sys.argv.index('--cache') + 1]
        os.makedirs(CACHE, exist_ok=True)
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    rated = sum(1 for b in data['blades'] if 'tier' in b)
    stats = sum(1 for b in data['blades'] if 'stats' in b)
    print('上蓋 %d 款（T 表 %d、比賽統計 %d），商品 %d 個 → %s' % (
        len(data['blades']), rated, stats, len(data['products']), os.path.relpath(OUT)))


if __name__ == '__main__':
    main()
