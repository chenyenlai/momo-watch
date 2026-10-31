#!/usr/bin/env python3
"""MOMO 戰鬥陀螺新品監測：FUNBOX（funbox toys 品牌館）有新陀螺上架就推播到手機（ntfy）。

只用 Python 內建模組，NAS / Docker / 一般電腦都能跑。

    python3 momo_watch.py              檢查一次（給排程用）
    python3 momo_watch.py --loop 300   每 300 秒檢查一次，一直跑（給 Docker 用）
    python3 momo_watch.py --test       送一則測試推播
    python3 momo_watch.py --dry-run    只印結果，不推播、不記錄
    python3 momo_watch.py --list       把即將開賣清單推播一次

第一次執行只會把目前所有商品記下來（送一則「開始監測」），之後出現沒看過的商品才會通知。
FUNBOX 的預購商品會記下開賣時間，開賣前 REMIND_BEFORE 分鐘再提醒一次。
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# ===== 設定 =====
NTFY_TOPIC = os.environ.get('NTFY_TOPIC', '')  # 手機 ntfy App 訂閱的名稱；GitHub 上放在 Secret，不寫在程式裡
NTFY_SERVER = os.environ.get('NTFY_SERVER', 'https://ntfy.sh')

# 監測來源：(搜尋關鍵字, 額外網址參數)。都用「新上市」排序（searchType=5）
FEEDS = [
    ('BEYBLADE', ''),
    ('戰鬥陀螺', '&brand=TAKARA%20TOMY&brandNo=20190717104950516'),
]
PAGES = 2  # 每個來源看前幾頁（每頁 12 件）

# 標題要包含其中一個（不分大小寫），且不能包含排除字
INCLUDE = ['戰鬥陀螺', 'beyblade', 'takara tomy']
EXCLUDE = ['鑰匙扣', '鑰匙圈', '掛件', '掛飾', '貼紙', '博博小鋪']

# 只通知商品分類路徑含這個字的（funbox toys 品牌館）；改成 '' 就是任何賣家都通知
SELLER = 'funbox'

REMIND_BEFORE = int(os.environ.get('REMIND_BEFORE', '15'))  # 開賣前幾分鐘提醒；0 = 不提醒

STATE_FILE = os.environ.get('STATE_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'seen.json'))
FAIL_ALERT_AFTER = 6  # 連續失敗幾次就推播警告
# ================

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'


def log(*a):
    # 固定用台灣時間，NAS / 容器常常沒設時區
    print(time.strftime('[%Y-%m-%d %H:%M:%S]', time.gmtime(time.time() + 8 * 3600)), *a, flush=True)


def fetch_feed(keyword, extra, page):
    url = 'https://www.momoshop.com.tw/search/%s?searchType=5&curPage=%d&cateLevel=0&_isFuzzy=0%s' % (
        urllib.parse.quote(keyword), page, extra)
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-TW,zh;q=0.9'})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
    items = []
    # 搜尋頁內嵌的 JSON-LD 商品清單
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        data = json.loads(block)
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data
        for node in nodes:
            if node.get('@type') == 'ItemList':
                items.extend(node.get('itemListElement', []))
    return items


def short_url(code, url):
    return 'https://www.momoshop.com.tw/product/' + code if code.isdigit() else url


def short_name(name):
    name = re.sub(r'^【TAKARA TOMY】\s*', '', name.strip())
    return re.sub(r'^(BEYBLADE X\s*)?(戰鬥陀螺X?\s*)', '', name).strip() or name


def sale_when(ms):
    t = time.gmtime(ms / 1000 + 8 * 3600)
    return '%d/%d(%s) %02d:%02d' % (t.tm_mon, t.tm_mday, '一二三四五六日'[t.tm_wday], t.tm_hour, t.tm_min)


def upcoming_text(state):
    rows = sorted(state.get('upcoming', {}).items(), key=lambda kv: kv[1]['on_sale'])
    return '\n\n'.join('%s\n%s\n%s' % (sale_when(u['on_sale']), short_name(u['name']), short_url(k, u['url']))
                       for k, u in rows) or '（目前沒有）'


def normalize(item):
    url = item.get('url', '').strip()
    m = re.search(r'i_code=(\d+)', url)
    if m:
        key, link = m.group(1), 'https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code=' + m.group(1)
    else:
        m = re.search(r'goodsDetail/(TP\w+)', url)
        key, link = (m.group(1) if m else url), url
    offers = item.get('offers') or {}
    return {
        'id': key,
        'name': item.get('name', '').strip(),
        'price': offers.get('price'),
        'stock': (offers.get('availability') or '').rsplit('/', 1)[-1],
        'url': link,
    }


def breadcrumb(url):
    """商品頁的分類路徑，例如「品牌旗艦 > funbox toys > 館長推薦 > 新品搶先看」"""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-TW,zh;q=0.9'})
    html = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'replace')
    paths = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        nodes = data.get('@graph', [data]) if isinstance(data, dict) else data
        for node in nodes:
            if isinstance(node, dict) and node.get('@type') == 'BreadcrumbList':
                paths.append(' > '.join(i.get('name', '') for i in node.get('itemListElement', [])))
    if not paths:
        # MOMO 偶爾回傳沒有分類的頁面，當成失敗下次重試，免得把目標商品誤判略過
        raise RuntimeError('頁面沒有分類路徑')
    return ' | '.join(paths)


def sale_info(code):
    """商品即時資訊：開賣時間（毫秒，0 = 已開賣或沒設定）、開賣說明、是否有庫存"""
    body = {'goodsCode': code, 'fsCode': '', 'hour': '', 'addressData': {}, 'categoryCode': '', 'host': 'momoshop'}
    req = urllib.request.Request('https://www.momoshop.com.tw/api/moecapp/getGoodsRealTimeInfo',
                                 data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json', 'User-Agent': UA,
                                          'Origin': 'https://www.momoshop.com.tw',
                                          'Referer': 'https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code=' + code})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8')).get('rtnGoodsData') or {}
    return {
        'on_sale': int(data.get('onSaleTimestamp') or 0),
        'desc': data.get('goodsPaymentDescription') or '',
        'stock': data.get('goodsStock') == '1',
        'limit': data.get('purchaseText') or '',
    }


def status_text(info):
    if info['on_sale'] > time.time() * 1000:
        return info['desc'] or '尚未開賣'
    return '開賣中' if info['stock'] else '售完'


def track_upcoming(state, it, info):
    if REMIND_BEFORE and info['on_sale'] > time.time() * 1000:
        state.setdefault('upcoming', {})[it['id']] = {
            'name': it['name'], 'url': it['url'], 'on_sale': info['on_sale'], 'desc': info['desc'], 'reminded': False}


def send_reminders(state):
    now = time.time() * 1000
    upcoming = state.get('upcoming', {})
    for code, u in list(upcoming.items()):
        left = u['on_sale'] - now
        if left < -3600 * 1000:
            del upcoming[code]
        # 排程可能延遲，所以開賣後 10 分鐘內沒提醒過也補發
        elif -600 * 1000 < left <= REMIND_BEFORE * 60 * 1000 and not u['reminded']:
            title = '%d 分鐘後開賣！' % round(left / 60000) if left > 0 else '已經開賣了！'
            notify(title, '%s\n%s\n%s' % (sale_when(u['on_sale']), short_name(u['name']), short_url(code, u['url'])),
                   click=short_url(code, u['url']), tags=['alarm_clock'], priority=5)
            u['reminded'] = True
            log('開賣提醒：', code, u['name'])


def wanted(name):
    low = name.lower()
    return any(k in low for k in INCLUDE) and not any(k in low for k in EXCLUDE)


def collect():
    found = {}
    for keyword, extra in FEEDS:
        for page in range(1, PAGES + 1):
            for raw in fetch_feed(keyword, extra, page):
                it = normalize(raw)
                if it['name'] and wanted(it['name']):
                    found.setdefault(it['id'], it)
            time.sleep(2)  # 對 MOMO 客氣一點
    return found


def notify(title, message, click=None, tags=None, button='開啟商品頁', priority=3):
    if not NTFY_TOPIC:
        raise RuntimeError('沒有設定 NTFY_TOPIC（GitHub：Settings → Secrets → Actions）')
    body = {'topic': NTFY_TOPIC, 'title': title, 'message': message, 'priority': priority}
    if click:
        body['click'] = click
        body['actions'] = [{'action': 'view', 'label': button, 'url': click}]
    if tags:
        body['tags'] = tags
    req = urllib.request.Request(NTFY_SERVER, data=json.dumps(body).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=30).read()


def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_state(state):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def check(dry_run=False):
    state = load_state()
    if state is not None and not dry_run:
        send_reminders(state)
        save_state(state)
    try:
        found = collect()
        if not found:
            raise RuntimeError('一件商品都沒抓到，可能 MOMO 改版或擋連線')
    except Exception as e:
        log('檢查失敗：', e)
        if state is not None and not dry_run:
            state['fails'] = state.get('fails', 0) + 1
            if state['fails'] == FAIL_ALERT_AFTER:
                notify('MOMO 監測異常', '已連續 %d 次抓不到資料：%s' % (state['fails'], e), tags=['warning'])
            save_state(state)
        return

    if dry_run:
        for it in found.values():
            log('%s  $%s  %s  %s' % (it['id'], it['price'], it['stock'], it['name']))
        log('共 %d 件（dry-run，不推播）' % len(found))
        return

    if state is None:
        state = {'seen': {k: v['name'] for k, v in found.items()}, 'fails': 0, 'upcoming': {}}
        # 找出目前已上架、還沒開賣的目標商品，之後才能提醒
        for it in found.values():
            if it['id'].startswith('TP'):
                continue
            try:
                if SELLER and SELLER not in breadcrumb(it['url']).lower():
                    continue
                track_upcoming(state, it, sale_info(it['id']))
            except Exception as e:
                log('讀取失敗，略過：', it['id'], e)
            time.sleep(2)
        save_state(state)
        notify('監測已啟動｜FUNBOX 即將開賣 %d 款' % len(state['upcoming']), upcoming_text(state), tags=['eyes'])
        log('第一次執行，記錄 %d 件商品，即將開賣 %d 件' % (len(found), len(state['upcoming'])))
        return

    if state.get('fails', 0) >= FAIL_ALERT_AFTER:
        notify('MOMO 監測恢復', '又抓得到資料了。', tags=['white_check_mark'])
    state['fails'] = 0

    new = [it for k, it in found.items() if k not in state['seen']]
    hits = 0
    for it in new:
        try:
            path = breadcrumb(it['url']) if SELLER else ''
        except Exception as e:
            log('讀不到分類路徑，下次再試：', it['id'], e)
            continue
        time.sleep(2)
        state['seen'][it['id']] = it['name']
        if SELLER and SELLER not in path.lower():
            log('新品（非目標賣家，略過）：', it['id'], it['name'], '｜', path)
            continue
        hits += 1
        selling = False
        try:
            info = sale_info(it['id'])
            selling = info['stock'] and info['on_sale'] <= time.time() * 1000
            status = status_text(info)
            if info['limit']:
                status += '｜' + info['limit']
            track_upcoming(state, it, info)
        except Exception as e:
            log('讀不到開賣資訊：', it['id'], e)
            status = '有貨' if it['stock'] == 'InStock' else it['stock']
        link = short_url(it['id'], it['url'])
        msg = '%s\n$%s｜%s\n%s' % (short_name(it['name']), it['price'], status, link)
        if selling:  # 上架就能買：最高優先度，手機會長震動
            notify('FUNBOX 新陀螺開賣中！快搶', msg, click=link, tags=['rotating_light'], priority=5)
        else:
            notify('FUNBOX 新陀螺上架！', msg, click=link, tags=['tada'], priority=4)
        log('新品：', it['id'], it['name'], '｜', path)
    save_state(state)
    log('檢查完成：%d 件，新品 %d 件，通知 %d 件' % (len(found), len(new), hits))


def main():
    args = sys.argv[1:]
    if '--test' in args:
        notify('MOMO 監測測試', '收到這則代表推播設定成功！', click='https://www.momoshop.com.tw/', tags=['bell'])
        log('已送出測試推播到', NTFY_TOPIC)
        return
    if '--list' in args:
        state = load_state() or {}
        notify('FUNBOX 即將開賣 %d 款' % len(state.get('upcoming', {})), upcoming_text(state), tags=['calendar'])
        log('已送出即將開賣清單')
        return
    if '--loop' in args:
        interval = int(args[args.index('--loop') + 1])
        while True:
            try:
                check()
            except Exception as e:  # 推播失敗等，不要讓迴圈停掉
                log('錯誤：', e)
            time.sleep(interval)
    check(dry_run='--dry-run' in args)


if __name__ == '__main__':
    main()
