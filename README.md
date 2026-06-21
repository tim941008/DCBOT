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
pip install -r requirements.txt
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
- `$查課號 <課號>`
  - 查詢指定課號並顯示可前往選課系統的連結
- `$加追蹤 <課號>`
  - 將指定課號加入目前使用者的追蹤清單
- `$我的追蹤`
  - 顯示目前使用者的追蹤清單，並可用按鈕刪除追蹤
- `$刪追蹤 <課號>`
  - 從追蹤清單移除指定課程

## 注意事項

  - `user_id`
  - `course_no`
  - `course_name`

## 更新與補充說明

以下為 README 補充內容，確保與程式碼一致並方便部署與排錯：

### 資料表 schema 範例
請確認你的 Supabase 資料表 `tracking_list` 含有下列欄位：

```text
user_id    TEXT        -- 使用者 Discord ID（字串）
course_no  TEXT        -- 課號（標準化格式）
course_name TEXT       -- 課程名稱
threshold  INTEGER     -- 通知門檻（當剩餘 >= threshold 時通知，預設 1）
```

若你使用 Supabase SQL 建表，請為 `threshold` 設定預設值 1，並建議為 `(user_id, course_no)` 加上唯一限制，避免同一使用者重複追蹤同一門課。

### 新增/變更的指令
- `$加追蹤 <課號> [門檻]`：將課程加入追蹤，第二參數為可選整數門檻（預設 1），例如 `$加追蹤 12345 2`。
- `$設定門檻 <課號> <數字>`：更新已追蹤項目的通知門檻，例如 `$設定門檻 12345 3`。

已存在的指令仍然可用：`$我的追蹤`、`$刪追蹤` 等，`$我的追蹤` 會顯示每筆追蹤的門檻值。

### Bot 權限與 Intents
- 請在 Discord Developer Portal 啟用 `Message Content Intent`（若你的 Bot 使用到訊息內容解析）。
- 邀請 Bot 時至少包含 `bot` scope 和 `Send Messages` 權限；若要在頻道發通知，請同時給予 `Send Messages` 與 `Embed Links` 權限。

### 常見問題與排錯建議
- 如果看不到追蹤資料，請確認 `.env` 中的 `SUPABASE_KEY` 權限允許讀寫 `tracking_list` 表。
- 若按鈕無反應，先查看 Bot 日誌是否有錯誤，以及確認 Bot 已正確登入並擁有必要權限。
- 當查課 API 失敗或回傳格式異常時，Bot 會回報查無課程或錯誤訊息，建議檢查 API 網路連線與 `COURSE_API_URL` 是否正確。

### 執行環境版本
- Python 3.10+；若你使用不同版本，請先在虛擬環境中測試相依套件相容性。

---

如需我幫你把 `tracking_list` 的 SQL 建表範例也加進 README，我可以一併產生並 commit。
