# Windows 免費切片橋接設定（測試版）

此版由 Windows 主動透過 HTTPS 向 Render 網站取工作，不需要路由器轉發或將 Windows 連接埠開放到外網。

1. 先在 Render → Environment 設定 `QUOTE_BRIDGE_TOKEN`，值為**自行隨機產生、至少 32 字元**的密碼；不要存入 GitHub，也不要傳給他人。
2. Windows 安裝 Python 3.11+ 與 Bambu Studio。
3. 在 Bambu Studio 匯出兩台機型對應的**完整** machine/process/filament JSON 並依命名放進 `profiles/`，即 `mini_machine.json`、`mini_process.json`、`mini_filament.json`、`a2l_machine.json`、`a2l_process.json`、`a2l_filament.json`。僅預設資源檔不是完整設定；需以你正在使用的切片版本實測。
4. Windows PowerShell 設定：
```powershell
$env:QUOTE_SITE_URL="https://你的服務.onrender.com"
$env:QUOTE_BRIDGE_TOKEN="請填入Render相同密鑰"
$env:BAMBU_STUDIO_CLI="C:\Program Files\Bambu Studio\bambu-studio.exe"
python windows_worker.py
```
5. 打開網站 `/api/status` 查看 `slicing_ready`。保持電腦不休眠。

注意：Render Free 會休眠且暫存工作可能消失，免費額度和政策會變動。上線供客戶使用前需用真實 STL/3MF 測試切片、尺寸限制、模型安全、資料保護。大檔案可能超出 Render 免費額度或請求時間限制。多個 gunicorn worker 不共用這個記憶體佇列，務必只用單一 worker。

程式保留原始網站的計價：1 元/g + 30 元/hr；350g 以上預收款規則只是顯示，不會收款。
