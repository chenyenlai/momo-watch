/**
 * 戰鬥陀螺查詢頁（bey.html）的「買過紀錄」雲端同步（Google 試算表 + Apps Script）
 * 用法：開一份新的 Google 試算表 →「擴充功能 → Apps Script」整段貼上 →
 *       部署 → 新增部署作業 → 類型「網頁應用程式」，執行身分：我，誰可以存取：所有人 →
 *       把網址貼到 bey.html 的 SYNC_URL。
 *
 * 試算表的「買過紀錄」分頁每筆購買一列，可以直接在試算表看；刪除只把「狀態」標成「已刪除」，不會真的刪掉。
 *
 * 網頁呼叫方式：
 *   GET  ?k=密碼                         → {ok, recs:[...]}（沒刪除的全部紀錄）
 *   POST {k, add:[紀錄...], del:[id...]} → 寫入後回傳同 GET（同一個 id 不會重複寫）
 *   紀錄：{id, t:時間(ms), code:型號, name:名稱, blades:[上蓋代號], price:價格, note:備註}
 */
const KEY = 'RtGRJnX8lM1vqnXf';
const SHEET = '買過紀錄';
const HEAD = ['id', '時間', '型號', '名稱', '上蓋代號', '價格', '備註', '狀態'];

function sheet_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(SHEET);
  if (!sh) {
    sh = ss.insertSheet(SHEET);
    sh.appendRow(HEAD); sh.setFrozenRows(1); sh.getRange(1, 1, 1, HEAD.length).setFontWeight('bold');
  }
  return sh;
}
const out_ = (o) => ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);

function rows_() {
  const sh = sheet_(), n = sh.getLastRow() - 1;
  return n > 0 ? sh.getRange(2, 1, n, HEAD.length).getValues() : [];
}

function read_() {
  const recs = rows_().filter(r => r[0] && r[7] !== '已刪除').map(r => ({
    id: String(r[0]), t: new Date(r[1]).getTime(), code: String(r[2] || ''), name: String(r[3] || ''),
    blades: String(r[4] || '').split(',').filter(String), price: r[5] === '' ? null : Number(r[5]), note: String(r[6] || '')
  }));
  return { ok: true, recs: recs };
}

function doGet(e) {
  if ((e.parameter || {}).k !== KEY) return out_({ ok: false, err: 'key' });
  return out_(read_());
}

function doPost(e) {
  let b; try { b = JSON.parse(e.postData.contents); } catch (x) { return out_({ ok: false, err: 'json' }); }
  if (!b || b.k !== KEY) return out_({ ok: false, err: 'key' });
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const sh = sheet_(), all = rows_();
    const have = new Set(all.map(r => String(r[0])));
    const add = (b.add || []).filter(r => r && r.id && !have.has(String(r.id))).map(r => [
      String(r.id), new Date(r.t || Date.now()), r.code || '', r.name || '', (r.blades || []).join(','),
      r.price == null || r.price === '' ? '' : Number(r.price), r.note || '', ''
    ]);
    if (add.length) sh.getRange(all.length + 2, 1, add.length, HEAD.length).setValues(add);
    const del = new Set((b.del || []).map(String));
    if (del.size) all.forEach((r, i) => { if (del.has(String(r[0]))) sh.getRange(i + 2, 8).setValue('已刪除'); });
  } finally { lock.releaseLock(); }
  return out_(read_());
}
