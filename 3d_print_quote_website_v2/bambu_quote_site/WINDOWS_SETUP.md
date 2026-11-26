# Windows Bambu Studio 切片橋接

需有 Python 3.11 以上，以及包含你使用的 A1 mini 或 A2L 機型的 Bambu Studio。這個版本會讀取安裝中機型、製程與 Generic PETG 設定，不需要另外匯出六份 JSON。

1. 解壓縮，將這份 `windows_worker.py` 放入先前執行橋接的資料夾。
2. 停掉原本的橋接程式。在 Windows PowerShell 開啟該資料夾。
3. 用以下指令啟動。若已在該 PowerShell 設定過原本的 `QUOTE_BRIDGE_TOKEN`，可直接執行最後一行。輸入的應是 Render 上原有的橋接金鑰。

```powershell
if (-not $env:QUOTE_BRIDGE_TOKEN) {
    $env:QUOTE_BRIDGE_TOKEN = Read-Host "輸入原有的 Windows 橋接金鑰" -MaskInput
}
py .\windows_worker.py
```

舊版 PowerShell 5.1 若無法使用 `-MaskInput`，可沿用原先已有金鑰的 PowerShell 啟動方式。橋接預設連到原有 Render 服務。若 Bambu Studio 安裝位置與預設不同，先設定 `BAMBU_STUDIO_CLI` 為完整的 `bambu-studio.exe` 路徑。若機型資源位於其他位置，可設定 `BAMBU_STUDIO_RESOURCES` 為含有 `profiles\BBL` 的 `resources` 資料夾。

在 PowerShell 看到「Bambu Studio 切片橋接已啟動」後，保留視窗並避免電腦休眠。在私人估價頁看到「Bambu Studio 切片已連線」即可上傳模型。Render 冷啟動時可能要多等一會。

自動切片使用單一 PETG、0.4 mm 噴嘴、0.20 mm 層高、15% 填充及紋理 PEI 板。支撐可在估價頁切換。切片檔與模型會暫存在 Windows 暫存資料夾，工作結束時清除。橋接只產生報價資料，不會發送列印指令。

遇到 HTTP 401 時，請確認這個 PowerShell 和 Render 使用同一把原有橋接金鑰。遇到 HTTP 404 時，請確認 Render 已部署新版。遇到 HTTP 409 時，請確認執行的是這份新版檔案。沒有列出的機型請更新 Bambu Studio 的機型資源。清除重複啟動的舊橋接視窗後再試。
