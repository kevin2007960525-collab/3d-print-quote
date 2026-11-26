# Windows Bambu Studio 切片橋接

1. 在 Windows 對 ZIP 按右鍵，選「解壓縮全部」。保留解出的所有檔案在同一個資料夾。
2. 停掉先前的橋接程式，然後雙擊 `Start_Quote_Bridge.cmd`。電腦需安裝 Python 3.11 以上與包含 A1 mini 或 A2L 機型設定的 Bambu Studio。
3. 出現輸入框時，請先複製原本設在 Render 的 `QUOTE_BRIDGE_TOKEN`，點「貼上金鑰」。輸入框會顯示星號，再點「啟動切片橋接」。金鑰只用於這次啟動，程式不會寫到檔案。
4. 出現「啟用 STEP 匯入」時，選「是」並等待一次性下載。如果選「否」，仍可先使用 STL 和 3MF。
5. 保持啟動視窗開著。在私人估價站看到「Bambu Studio 切片已連線」後，上傳 STL、3MF 或 STEP（.step／.stp）即可開始切片估價。

如果要用原先已經設定過金鑰和 Bambu Studio 路徑的 PowerShell，請在該視窗切到解壓後的資料夾，執行 `py .\start_quote_bridge.py`。

## 啟動遇到問題

- **Python 3.11 or later was not found**：需要安裝 Python 3.11 或更新版本。
- **找不到 Bambu Studio 或機型資源**：啟動程式會先從預設安裝路徑找 Bambu Studio。如果你的安裝位置不同，在原來的 PowerShell 設定 `BAMBU_STUDIO_CLI` 為完整的執行檔路徑，再執行啟動程式。若機型資源另放於其他位置，`BAMBU_STUDIO_RESOURCES` 應指向含有 `profiles\BBL` 的資料夾。
- **HTTP 401**：確認使用 Render 上原有的橋接金鑰。若用舊的 PowerShell，請確認該視窗的環境變數仍是正確的值。
- **沒有列出你的機型**：確認 Bambu Studio 已安裝對應機型資源。
- 如果還是啟動失敗，視窗會停在錯誤畫面。保留畫面上的錯誤文字即可。

自動切片使用單一 PETG、0.4 mm 噴嘴、0.20 mm 層高、15% 填充和紋理 PEI 板。Bambu Studio 會先自動調整模型朝向，然後以自動支撐切片。模型和切片輸出使用本機暫存資料夾，工作結束會清除。橋接僅回傳切片資料，用於報價。
