# momo-watch

監測 MOMO 上 FUNBOX（funbox toys 品牌館）的戰鬥陀螺：有新品上架、或預購商品快開賣時，推播到手機（ntfy）。

- 排程：GitHub Actions 每 5 分鐘執行 `momo_watch.py`（`.github/workflows/momo-watch.yml`）
- 推播頻道：倉庫 Secret `NTFY_TOPIC`
- `seen.json`：看過的商品與即將開賣清單，由排程自動更新
