# momo-watch

## 網頁

- 🏠 [首頁](https://chenyenlai.github.io/momo-watch/)
- 🚗 [國1 通勤路況](https://chenyenlai.github.io/momo-watch/traffic.html)
- 🌀 [戰鬥陀螺開賣表](https://chenyenlai.github.io/momo-watch/funbox.html)
- 📶 [Wi-Fi 技術入門](https://chenyenlai.github.io/momo-watch/wifi.html)

## 說明

監測 FUNBOX 的戰鬥陀螺，推播到手機（ntfy）：

- MOMO 上的 funbox toys 品牌館：新品上架、預購商品開賣前提醒
- FUNBOX 官網（shop.funbox.com.tw）：新品上架（補貨通知預設關閉，見 SHOP_RESTOCK）

- 排程：在家裡 NAS 的 Docker 每分鐘執行 `momo_watch.py`（GitHub Actions 排程已停用）
- `seen.json`：看過的商品與即將開賣清單
