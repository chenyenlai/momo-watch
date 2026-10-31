# momo-watch

監測 FUNBOX 的戰鬥陀螺，推播到手機（ntfy）：

- MOMO 上的 funbox toys 品牌館：新品上架、預購商品開賣前提醒
- FUNBOX 官網（shop.funbox.com.tw）：新品上架、庫存從 0 補貨

- 排程：GitHub Actions 每 5 分鐘執行 `momo_watch.py`（`.github/workflows/momo-watch.yml`）
- 推播頻道：倉庫 Secret `NTFY_TOPIC`
- `seen.json`：看過的商品與即將開賣清單，由排程自動更新
