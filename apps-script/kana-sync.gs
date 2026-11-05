/**
 * 50 音練習的雲端紀錄（Google 試算表 + Apps Script）
 * 用法：在試算表「擴充功能 → Apps Script」整段貼上，部署成網頁應用程式（執行身分：我；誰可以存取：所有人）。
 *
 * 試算表會有兩個分頁：
 *   作答紀錄：每一題一列（網頁用這份重算每個字的熟練度）
 *   設定：每台裝置開放的行、清除紀錄的時間
 *
 * 網頁呼叫方式：
 *   GET  ?k=密碼&since=列數          → 回傳從第 since 筆以後的作答紀錄＋設定
 *   POST {k, since, ev:[...], open:{hira:[], kata:[]}, reset:{hira:時間, kata:時間}}
 *        → 新的作答寫進去（同一個 id 不會重複寫），設定合併，回傳同 GET
 */
const KEY = 'V0fNiZTXgSPpvJHi';
const LOG = '作答紀錄', CFG = '設定';
const HEAD = ['id', '時間', '平/片', '字', '題型', '選的字', '對錯', '秒數', '模式', 'key', '選的 key'];
const TYPE = { see: '看字選音', hear: '聽音選字', romaji: '看拼音選字' };
const MODE = { round: '練習', review: '錯題複習', test: '快速檢測' };

function sheet_(name, head) {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); if (head) { sh.appendRow(head); sh.setFrozenRows(1); sh.getRange(1, 1, 1, head.length).setFontWeight('bold'); } }
  return sh;
}
const kata_ = (s) => s ? s.replace(/[ぁ-ゖ]/g, c => String.fromCharCode(c.charCodeAt(0) + 0x60)) : '';
const out_ = (o) => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);

function cfg_() {
  const v = sheet_(CFG).getRange('A1').getValue();
  try { const c = JSON.parse(v); if (c && c.open) return c; } catch (e) {}
  return { open: { hira: ['g0', 'g1'], kata: ['g0', 'g1'] }, reset: { hira: 0, kata: 0 } };
}

function read_(since) {
  const sh = sheet_(LOG, HEAD), n = sh.getLastRow() - 1;
  since = Math.max(0, Math.min(n, +since || 0));
  const rows = n > since ? sh.getRange(since + 2, 1, n - since, HEAD.length).getValues() : [];
  // 網頁用的精簡格式：[id, 時間(ms), 平/片, key, 題型, 選的 key, 對錯, 毫秒, 模式]
  const ev = rows.map(r => [String(r[0]), new Date(r[1]).getTime(), r[2] === '片' ? 'kata' : 'hira', r[9],
    Object.keys(TYPE).find(k => TYPE[k] === r[4]) || r[4], r[10] || null, r[6] === '⭕', Math.round(r[7] * 1000),
    Object.keys(MODE).find(k => MODE[k] === r[8]) || r[8]]);
  return { ok: true, n: n, ev: ev, cfg: cfg_() };
}

function doGet(e) {
  if ((e.parameter || {}).k !== KEY) return out_({ ok: false, err: 'key' });
  return out_(read_(e.parameter.since));
}

function doPost(e) {
  let b; try { b = JSON.parse(e.postData.contents); } catch (x) { return out_({ ok: false, err: 'json' }); }
  if (!b || b.k !== KEY) return out_({ ok: false, err: 'key' });
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const sh = sheet_(LOG, HEAD), n = sh.getLastRow() - 1;
    const have = new Set(n > 0 ? sh.getRange(2, 1, n, 1).getValues().map(r => String(r[0])) : []);
    const rows = (b.ev || []).filter(v => v && !have.has(String(v[0]))).map(v => {
      const sc = v[2] === 'kata' ? '片' : '平', show = (h) => (sc === '片' ? kata_(h) : (h || ''));
      return [String(v[0]), new Date(v[1]), sc, show(v[3]), TYPE[v[4]] || v[4], show(v[5]), v[6] ? '⭕' : '❌', Math.round(v[7]) / 1000, MODE[v[8]] || v[8], v[3], v[5] || ''];
    });
    if (rows.length) sh.getRange(n + 2, 1, rows.length, HEAD.length).setValues(rows);
    // 設定：開放的行取聯集，清除時間取最新
    const c = cfg_();
    ['hira', 'kata'].forEach(s => {
      const r = Math.max(c.reset[s] || 0, ((b.reset || {})[s]) || 0);
      if (r > (c.reset[s] || 0)) c.open[s] = ['g0', 'g1'];   // 有新的「清除紀錄」：開放的行也重來
      c.reset[s] = r;
      if ((((b.reset || {})[s]) || 0) >= r) c.open[s] = [...new Set(c.open[s].concat(((b.open || {})[s]) || []))];
    });
    sheet_(CFG).getRange('A1').setValue(JSON.stringify(c));
  } finally { lock.releaseLock(); }
  return out_(read_(b.since));
}
