# Discord 選課小幫手 Bot

這個 Bot 可以協助你查詢課程、追蹤課程狀態，並將追蹤名單儲存在 Supabase。

## 需求

- Python 3.10+
- `discord.py`
- `aiohttp`
- `python-dotenv`
- `supabase`

## 設定方式

1. 建立 `.env` 檔案，放在專案根目錄
2. 填入以下環境變數：

```env
DISCORD_TOKEN=你的 Discord Bot Token
SUPABASE_URL=你的 Supabase URL
SUPABASE_KEY=你的 Supabase Key
```

3. 安裝套件

```bash
pip install discord.py aiohttp python-dotenv supabase
```

## 啟動

```bash
python main.py
```

## 檔案結構

- `main.py` - Bot 啟動入口
- `bot.py` - Discord 指令與事件處理
- `monitor.py` - 自動追蹤名額通知任務
- `course_api.py` - 查課 API 請求與課程 payload 建構
- `database.py` - Supabase 讀寫邏輯
- `config.py` - 環境變數與設定

## 指令說明

- `$hello`
  - 測試 Bot 是否回應
- `$指令`
  - 顯示所有可用指令
- `$查課 <關鍵字>`
  - 根據課程名稱或關鍵字查詢課程
  - 範例：`$查課 排球`
- `$加追蹤 <課號>`
  - 將指定課號加入目前使用者的追蹤清單
- `$我的追蹤`
  - 顯示目前使用者的追蹤清單，並查詢最新名額狀態
- `$刪追蹤 <課號>`
  - 從追蹤清單移除指定課程

## 注意事項

- 請確認你的 Supabase 資料表 `tracking_list` 已包含以下欄位：
  - `user_id`
  - `course_no`
  - `course_name`
- 如果 API 回傳失敗，Bot 會回報查無課程或請求失敗訊息。
