#!/usr/bin/env python3
"""戰鬥陀螺查詢頁（docs/bey.html）的資料：每週由 GitHub Actions 執行，產生 docs/bey/data.json

來源（robots.txt 都允許抓取；只抓公開頁面，每頁間隔幾秒）：
  BeybladeHub 上蓋資料庫  型號、中文／英文／日文名、類型、重量
  BeybladeHub T 表        強度分級（TIER_URL，台灣玩家依比賽環境排的）
  BeybladeHub 商品頁      中文商品名、台灣售價、發售日；抽抽包（隨機強化組）有哪幾款、官方稀有款
  BEYWATCH.GG 每顆上蓋頁  全球比賽前幾名的使用率、冠軍率、排名（熱門度），以及商品型號 → 內含哪些上蓋
  BEYWATCH.GG 固鎖、軸心頁 使用率（熱門的固鎖／軸心）；稀有度由「出現在幾個商品」算出
  stan-yao 的 Beyblade X 天梯（公開 Google 試算表）  每個型號（含套組裡每一顆）的原裝固鎖、軸心；
                          台灣另一套中文譯名（例如 幻獸刺心＝獨角刺心），當成別名讓網頁搜得到；
                          賽事統計（Combo Summary）：每顆上蓋得獎最多的固鎖＋軸心組合

用法：
  python3 bey/fetch_bey.py                 抓全部，寫到 docs/bey/data.json
  python3 bey/fetch_bey.py --cache DIR     抓過的頁面存到 DIR，下次直接讀（開發用）
  python3 bey/fetch_bey.py --sheet-only    只重抓 stan-yao 試算表，補進現有的 data.json
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
HUB_SITEMAP = HUB + '/sitemap.xml'
TIER_URL = HUB + '/t/4Xuagf8J'  # 10 月份 T 度排行（使用者指定）；要換別張 T 表改這裡
BW = 'https://beywatch.gg'
BW_SITEMAP = BW + '/sitemaps/blades.xml'
BW_PARTS = BW + '/sitemaps/parts.xml'
SHEET = 'https://docs.google.com/spreadsheets/d/1TBHOpcsv25bBfWERq14CBIy4P1G7j-qpPhmclx_nTWI/gviz/tq?tqx=out:csv'
COMBO_SHEET = 'https://docs.google.com/spreadsheets/d/18eTJLjyNmqDz5MH0-VD03TX4wobUCdHdrRMyo4uojDo/gviz/tq?tqx=out:csv&sheet=Combo%20Summary'
SHEET_PAGE = 'https://stan-yao.github.io/beyblade_x_tier/'
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
    def rows_of(prefix):
        tab = next((t for t in board['board']['tabs'] if t.get('id', '').startswith(prefix)), None)
        if not tab:
            return []
        rows = [{'label': r['label'],
                 'cards': [{'id': c['id'], 'name': c.get('name'), 'parts': [p['label'] for p in c.get('parts') or []]}
                           for c in r.get('cards') or []]}
                for r in tab['rows']]
        return [r for r in rows if r['cards']]
    rows = rows_of('blade_atomic') or rows_of('blade')
    if not rows:
        raise ValueError('T 表沒有上蓋分頁')
    meta = text_of(page)
    author = re.search(r'玩家 T 表 .+? (\S+(?: \S+)?) 最後更新', meta)
    updated = re.search(r'最後更新 (\d{4})年(\d{1,2})月(\d{1,2})日', meta)
    return {
        'title': html.unescape(title.group(1)).strip() if title else '',
        'author': author.group(1) if author else '',
        'updated': '%s-%02d-%02d' % (updated.group(1), int(updated.group(2)), int(updated.group(3))) if updated else '',
        'rows': rows, 'ratchets': rows_of('ratchet'), 'bits': rows_of('bit'),
    }


def split_config(cfg):
    """'4-60D' → (None, '4-60', 'D')；CX 'W5-80WB' → ('W', '5-80', 'WB')；'ATr'（固鎖一體軸心）→ ('A', None, 'Tr')"""
    cfg = re.sub(r'（.*?）|\(.*?\)', '', cfg or '').strip()
    m = re.match(r'^([A-Z]{0,2}?)(M-\d{2}|\d-\d{2})([A-Z][A-Za-z]*)$', cfg)
    if m:
        return m.group(1) or None, m.group(2), m.group(3)
    m = re.match(r'^([A-Z])([A-Z][a-z]+)$', cfg)
    if m:
        return m.group(1), None, m.group(2)
    return None, None, None

def parse_hub_product(page):
    """BeybladeHub 商品頁（/parts/combos/型號）→ 商品資料；抽抽包另外列出每一款"""
    # 標題有兩種：「名稱（型號）｜…」和「型號 名稱｜…」
    t = re.search(r'<title>(.+?)（([^）]+)）｜', page)
    t2 = re.search(r'<title>([BUC]XH?-[\w-]+) (.+?)｜', page)
    if t:
        zh, code = t.group(1), t.group(2)
    elif t2:
        zh, code = t2.group(2), t2.group(1)
    else:
        return None
    s = text_of(page)
    m = lambda rx: re.search(rx, s)
    kind = m(r'([BUC]X \S+線) ・ (\S+)')
    price = m(r'台灣 NT\$ ([\d,]+)')
    release = m(r'發售日 (\d{4}-\d{2}-\d{2})')
    config = m(r'原裝配置 (\S+)')
    blade = m(r'規格速覽.*?上蓋 (\S+?)（')
    variants = []
    i = page.find('包含款式')
    if i >= 0:
        block = page[i:page.find('回完整陀螺列表', i)]
        for item in re.split(r'<span translate="no"[^>]*>\d{2}</span>', block)[1:]:
            divs = [text_of(x) for x in re.findall(r'<div[^>]*>([^<]*)</div>', item)]
            divs = [x for x in divs if x]
            if not divs:
                continue
            note = divs[2] if len(divs) > 2 else ''
            variants.append({'name': divs[0], 'en': divs[1] if len(divs) > 1 else '', 'note': note,
                             'rare': bool(re.search(r'<span[^>]*>R</span>', item[:300])) or 'RARE' in note or '籤王' in note})
    return {
        'zh': html.unescape(zh).strip(), 'code': code.strip(),
        'line': kind.group(1) if kind else '', 'kind': kind.group(2) if kind else '',
        'price': int(price.group(1).replace(',', '')) if price else None,
        'release': release.group(1) if release else '', 'config': config.group(1) if config else '',
        'blade': blade.group(1) if blade else '', 'variants': variants,
        # 說明裡出現的所有配置（一盒多顆的套組、CX 沒有「原裝配置」欄位時用來算零件稀有度）
        'configs': sorted(set(re.findall(r'(?<![\w-])([A-Z]{0,2}(?:\d|M)-\d{2}[A-Z][A-Za-z]{0,2})(?![\w-])',
                                         s.split('相關商品')[0]))),
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


def parse_bw_part(page):
    """BEYWATCH 固鎖／軸心頁 → {kind, name, abbr, grade, rank, usage, first, cuts}"""
    s = text_of(page)
    head = re.search(r'Parts / (Ratchets|Bits) / (.+?) \2(?: \(([^)]+)\))? (\S+) (?:Ratchet|Bit)', s)
    if not head:
        return None
    m = lambda rx: re.search(rx, s)
    rank, first, usage, cuts = m(r'Rank #(\d+)'), m(r'1st Place Rate i ([\d.]+)%'), m(r'Usage i ([\d.]+)%'), m(r'Top Cuts ([\d,]+)')
    return {
        'kind': 'ratchet' if head.group(1) == 'Ratchets' else 'bit',
        'name': head.group(2), 'abbr': head.group(3) or head.group(2), 'grade': head.group(4),
        'rank': int(rank.group(1)) if rank else None,
        'usage': pct(usage.group(1)) if usage else None,
        'first': pct(first.group(1)) if first else None,
        'cuts': int(cuts.group(1).replace(',', '')) if cuts else None,
    }


def bw_through(page):
    d = re.search(r'from [\d,]+ tournaments through (\w{3} \d{1,2}, \d{4})', text_of(page))
    return d.group(1) if d else ''

# ---------------------------------------------------------------------------


def base_name(n):
    """「蒼龍爆刃 金屬塗層:紫」「魔導神杖(綠)」→ 去掉顏色、版本"""
    return re.sub(r'\s*(金屬塗層|特別版|火紅版).*|\(.*?\)|（.*?）', '', n).strip()


def add_sheet(data):
    """stan-yao 試算表：原裝固鎖、軸心（orig）和別名（blade['alias']）。失敗只印警告，不影響其他資料"""
    import csv, io
    try:
        rows = list(csv.reader(io.StringIO(get(SHEET))))[1:]
    except Exception as e:
        print('stan-yao 試算表抓不到', type(e).__name__, file=sys.stderr)
        return
    rows = [x for x in rows if len(x) > 11 and x[2] == 'blade' and x[0]]
    if len(rows) < 100:
        print('stan-yao 試算表只有 %d 列，格式可能變了，先不用' % len(rows), file=sys.stderr)
        return
    bits = {k.lower(): k for k in data['parts']['bit']}
    orig = {}
    for x in rows:
        r, b = x[6].strip(), bits.get(x[8].strip().lower(), x[8].strip())
        if not (r or b):
            continue
        sub = re.sub(r'-\d\d$', '', x[0])
        for code in {x[0], sub}:   # 套組 BX-20-01 也算進 BX-20
            if code == sub and code != x[0] and data['products'].get(code, {}).get('random'):
                continue           # 抽抽包抽到哪顆由網頁記錄，這裡不全部算
            lst = orig.setdefault(code, [])
            if [r, b] not in lst:
                lst.append([r, b])
    data['orig'] = orig
    # 別名：名字一樣直接對；不一樣用型號／商品對到唯一一顆
    blades, P = data['blades'], data['products']
    by_zh = {b['zh']: b for b in blades}
    by_code = {}
    for b in blades:
        if b['code'] and not b.get('part'):
            by_code.setdefault(b['code'], []).append(b)
    # 圖片：BeybladeHub 的圖有防盜連，改用 stan-yao 放在 imgbb 的圖（優先同型號那張，再來是原版顏色）
    best, names = {}, {}
    for x in rows:
        name = base_name(x[1])
        img = x[12].strip() if x[12].startswith('https://') else ''
        if img and (name not in names or x[1].strip() == name):
            names[name] = img
        if name in by_zh:
            b = by_zh[name]
            score = (x[0] != b['code']) * 2 + (x[1].strip() != name)   # 同型號優先（BX-34 寫成「蒼穹龍騎士(左)」）
            if img and (b['id'] not in best or score < best[b['id']][0]):
                best[b['id']] = (score, img)
            continue
        hit = by_code.get(x[0], [])
        if len(hit) != 1:
            pb = [i for i in P.get(x[0], {}).get('blades', []) if i]
            hit = [b for b in blades if b['id'] in pb and not b.get('part')] if len(pb) == 1 else []
        if len(hit) != 1:   # 抽抽包 BX-50-01：用原裝固鎖＋軸心對到是哪一款
            pk = P.get(re.sub(r'-\d\d$', '', x[0]), {})
            r, bt = x[6].strip(), bits.get(x[8].strip().lower(), x[8].strip())
            ids = {v['blade'] for v in pk.get('variants') or [] if v.get('blade') and ' ' in v['name']
                   and split_config(v['name'].split(' ', 1)[1])[1:] == (r or None, bt or None)}
            hit = [b for b in blades if b['id'] in ids]
        if len(hit) == 1:
            al = hit[0].setdefault('alias', [])
            if name not in al:
                al.append(name)
            if img and not hit[0].get('part') and (hit[0]['id'] not in best or best[hit[0]['id']][0] > 3):
                best[hit[0]['id']] = (4, img)
    for b in blades:
        b.pop('img', None)
        alt = names.get(b['zh'].replace(' 2.0', ' 版本2.0')) if not b.get('part') else None   # 蒼龍神劍 2.0 ↔ 版本2.0
        if b['id'] in best or alt:
            b['img'] = best[b['id']][1] if b['id'] in best else alt
    # CX 組合名（蒼龍勇氣）的整顆圖，網頁的列表用
    data['cxImg'] = {n: u for n, u in names.items() if n not in by_zh}
    data['sheet'] = {'url': SHEET_PAGE, 'n': len(rows)}
    add_combos(data, bits)
    print('stan-yao 試算表 %d 列：原裝配置 %d 個型號，別名 %d 顆，圖片 %d 顆' % (
        len(rows), len(orig), sum(1 for b in blades if b.get('alias')), len(best)))


def add_combos(data, bits):
    """賽事統計：每顆上蓋前 5 名組合 → blade['combos'] = [[固鎖, 軸心, 得獎次數, 冠軍次數, 冠軍率%, 近90天次數], ...]"""
    import csv, io
    try:
        rows = list(csv.DictReader(io.StringIO(get(COMBO_SHEET))))
    except Exception as e:
        print('stan-yao 賽事統計抓不到', type(e).__name__, file=sys.stderr)
        return
    if len(rows) < 200 or 'site_blade_name' not in rows[0]:
        print('stan-yao 賽事統計只有 %d 列，格式可能變了，先不用' % len(rows), file=sys.stderr)
        return
    blades = data['blades']
    idx = {}
    for b in blades:
        idx.setdefault(b['zh'], b)
        for a in b.get('alias', []):
            idx.setdefault(a, b)
    by_code = {}
    for b in blades:
        if b['code'] and not b.get('part'):
            by_code.setdefault(b['code'], []).append(b)
    chips = sorted((b['zh'] for b in blades if b.get('part') == '鎖定紋章'), key=len, reverse=True)
    mains = sorted((b for b in blades if b.get('part') in ('主刃', '金屬戰刃')), key=lambda b: -len(b['zh']))

    def find(name, code):
        name = base_name(name)
        if name in idx:
            return idx[name]
        if len(by_code.get(code, [])) == 1:
            return by_code[code][0]
        for c in chips:   # CX：紋章＋主刃（天馬爆擊 → 爆擊）
            if name.startswith(c):
                return next((m for m in mains if name[len(c):].startswith(m['zh'])), None)
        return None

    def num(v, f=int):
        try:
            return f(v)
        except (TypeError, ValueError):
            return 0
    got = {}
    for r in sorted(rows, key=lambda r: num(r.get('site_recommendation_rank'), int) or 10 ** 9):
        b = find(r.get('site_blade_name', ''), r.get('site_blade_id', ''))
        if not b:
            continue
        lst = got.setdefault(b['id'], [])
        key = [r['ratchet'].strip(), bits.get(r['bit'].strip().lower(), r['bit'].strip())]
        old = next((c for c in lst if c[:2] == key), None)
        if old:   # 同一顆不同版本（左右旋、CX 不同紋章）合併
            old[2] += num(r['total_wins']); old[3] += num(r['first_count']); old[5] += num(r['recent_90_count'])
            old[4] = round(old[3] * 100 / old[2]) if old[2] else 0
        elif len(lst) < 5:
            lst.append(key + [num(r['total_wins']), num(r['first_count']),
                              round(num(r['champion_rate'], float) * 100), num(r['recent_90_count'])])
    for b in blades:
        b.pop('combos', None)
        if b['id'] in got:
            b['combos'] = got[b['id']]
    data['sheet']['combos'] = sum(num(r['total_wins']) for r in rows)
    print('賽事統計 %d 組合，對到 %d 顆上蓋' % (len(rows), len(got)))


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

    # BeybladeHub 商品頁：中文、台灣售價、抽抽包內容（有的話蓋過 BEYWATCH 的商品資料）
    by_zh = {}
    for b in blades:
        by_zh.setdefault(b['zh'], b)
    cx_main = [b for b in blades if b.get('part') in ('主刃', '金屬戰刃')]
    def blade_of(name):
        word = re.sub(r'（.*?）', '', name.split(' ')[0])
        if word in by_zh:
            return by_zh[word]['id']
        # CX 的名字是「紋章＋主刃」（魔犬＋烈焰）：用主刃對
        main = next((b for b in sorted(cx_main, key=lambda b: -len(b['zh'])) if word.endswith(b['zh'])), None)
        return main['id'] if main else None
    urls = [u for u in re.findall(r'<loc>([^<]+)</loc>', get(HUB_SITEMAP)) if '/parts/combos/' in u and '/en/' not in u]
    hub_n = 0
    for url in urls:
        try:
            p = parse_hub_product(get(url))
        except Exception as e:
            print('商品頁解析失敗', url, type(e).__name__, file=sys.stderr)
            continue
        if not p or not re.match(r'[BUC]XH?-\d', p['code']):
            continue
        hub_n += 1
        for v in p['variants']:
            v['blade'] = blade_of(v['name'])
        old = products.get(p['code'], {})
        ids = [v['blade'] for v in p['variants'] if v['blade']] or ([blade_of(p['blade'])] if blade_of(p['blade']) else [])
        products[p['code']] = {
            'name': p['zh'], 'en': old.get('name', ''), 'maker': 'Takara Tomy', 'line': p['line'], 'kind': p['kind'],
            'price': p['price'], 'release': p['release'], 'config': p['config'],
            'blades': list(dict.fromkeys(ids + old.get('blades', []))),
            'random': len(p['variants']) > 1, 'variants': p['variants'], 'url': url, 'configs': p['configs'],
        }
    if hub_n < 50:
        raise SystemExit('BeybladeHub 商品頁只解析到 %d 個，格式可能變了' % hub_n)

    # 固鎖、軸心：BEYWATCH 使用率＋T 表的軸心分級＋出現在哪些商品（越少越稀有）
    parts = {'ratchet': {}, 'bit': {}}
    for url in re.findall(r'<loc>([^<]+)</loc>', get(BW_PARTS)):
        if not re.search(r'/parts/(ratchet|bit)-', url):
            continue
        try:
            pt = parse_bw_part(get(url))
        except Exception as e:
            print('零件頁解析失敗', url, type(e).__name__, file=sys.stderr)
            continue
        if pt:
            parts[pt['kind']][pt['abbr']] = {k: pt[k] for k in ('name', 'grade', 'rank', 'usage', 'first', 'cuts')}
            parts[pt['kind']][pt['abbr']]['in'] = []
    for kind in ('ratchet', 'bit'):
        n = len(tier[kind + 's'])
        for i, row in enumerate(tier[kind + 's']):
            for c in row['cards']:
                d = parts[kind].setdefault(c['id'], {'name': c['id'], 'in': []})
                d.setdefault('tier', {'label': row['label'], 'level': i, 'of': n})
    for code, p in products.items():
        configs = [v['name'].split(' ', 1)[1] for v in p.get('variants') or [] if ' ' in v['name']]
        for cfg in configs + [p.get('config')] + p.pop('configs', []):
            _, r, b = split_config(cfg)
            for kind, key in (('ratchet', r), ('bit', b)):
                if key:
                    d = parts[kind].setdefault(key, {'name': key, 'in': []})
                    if code not in d['in']:
                        d['in'].append(code)

    return {
        'updated': datetime.now(TW).strftime('%Y-%m-%d %H:%M'),
        'tier': {'title': tier['title'], 'author': tier['author'], 'updated': tier['updated'], 'url': TIER_URL,
                 'labels': [r['label'] for r in tier['rows']], 'bitLabels': [r['label'] for r in tier['bits']]},
        'usage': {'url': BW, 'through': through},
        'blades': blades,
        'parts': parts,
        'products': {k: v for k, v in products.items() if re.match(r'[BUC]XH?-\d', k)},  # 只留日版型號
    }


def main():
    global CACHE
    if '--cache' in sys.argv:
        CACHE = sys.argv[sys.argv.index('--cache') + 1]
        os.makedirs(CACHE, exist_ok=True)
    if '--sheet-only' in sys.argv:
        with open(OUT, encoding='utf-8') as f:
            data = json.load(f)
        for b in data['blades']:
            b.pop('alias', None)
    else:
        data = build()
    add_sheet(data)
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
