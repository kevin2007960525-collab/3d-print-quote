# 將網站變成私人分享網址（不須密碼）

這是 **不主動公開宣傳、禁止搜尋引擎索引** 的網站，不是強制存取控制。取得網址的人都能進入，也可能轉傳。

## 上線預覽網站
1. 使用 GitHub 建立 Private repo，把本資料夾內的檔案上傳至儲存庫根目錄（不是再多包一層 bambu_quote_site）。
2. 使用 [Render](https://dashboard.render.com) 登入，新增 Web Service，連結剛才的私人 GitHub 儲存庫。
3. 選擇 Python，Build command：`pip install -r requirements.txt`；Start command：`gunicorn --bind 0.0.0.0:$PORT app:app`。
4. 待部署成功，Render 會提供 `https://<你建立的服務名稱>.onrender.com` 網址。這只是網站預覽；切片未設置時會明確告知尚不能估價。

## 真正能讓客戶上傳後自動估價的必要條件
- 部署到能執行 Bambu Studio CLI 的隔離運算機或 Linux 容器（不是 GitHub Pages）。官方 CLI 指令文件：https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- 把 A1 mini / A2L 的完整 `machine`、`process`、`filament` profile JSON 放入 `profiles/`；**必須實機切片測試後才能開放客戶**。
- 設 `BAMBU_STUDIO_CLI` 為切片可執行檔絕對路徑；必要時用 xvfb-run 或容器供應 GUI 執行環境。
- 強烈建議另設一台隔離切片 worker：限制 CPU / RAM / 上傳速率、逾時、使用者資料刪除規則，避免處理不信任的模型造成資安風險。
- 若提供客戶使用，需對 STL/3MF 不信任資料做防護，並加入頻率限制及存取日誌的匿名化；避免在網頁或郵件公開模型內容。

## 收費
單件價格 = 切片耗材 g × NT$1 + 切片分鐘 × NT$0.5。多件目前線性乘數量，不作多件重新排盤切片。總耗材超過 350g 顯示 20% 預收款（人工處理及退回）。正式報價、交期、拆模加工由店家確認。
