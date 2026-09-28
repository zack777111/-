# 作業一 V3：USB 板載麥克風＋中英文語音＋網頁燈光控制

**開發板不使用 Wi-Fi。** 板載麥克風收音後，經 USB UART 傳到電腦辨識，再由同一條 USB 線控制燈號。電腦及瀏覽器麥克風均不使用。

音訊方向：板子麥克風 → USB UART → 電腦 → Google 語音辨識。
控制方向：電腦 → USB UART → 板子 LED。

Google 辨識仍需要電腦能上網（有線網路也可以），不是完全離線辨識。開發板不用設定 SSID、密碼或 IP，也不需要另一條 USB OTG 線。舊的 wifi_config.h 已不被程式引用，裡面的設定沒有作用；保留它只是避免丟失舊設定。

## 功能

| 指令 | 燈號 |
| --- | --- |
| 左邊開燈 / Turn on the left light / Left light on | 藍燈亮起、綠燈熄滅 |
| 右邊開燈 / Turn on the right light / Right light on | 綠燈亮起、藍燈熄滅 |

- 網頁設定 0～100 次：0 是持續亮燈；1～100 是閃爍指定次數後熄滅。
- 每次亮約 0.3 秒，相鄰閃爍之間熄滅約 0.3 秒。USB 傳輸會使時間有少量誤差。
- 新指令立即取代舊序列，兩燈互斥。設定只影響下一次開燈。
- 支援手動控制、全部熄滅、開始／停止聆聽、中文／英文／自動比對。
- 開發板回覆確認後，終端機才印出「藍燈亮起」或「綠燈亮起」。
- 自動模式會分別嘗試中文與英文，結果衝突時不執行；單選一種語言較快。
- 重啟電腦程式後，恢復 0 次和自動語言。

## 1. 重新燒入 V3 韌體

1. 用可傳輸資料的 USB 線，將板子的 **USB UART 接口**接到電腦。
2. Arduino IDE 開啟 **assessment_1/assessment_1.ino**。同資料夾的 UsbMic.cpp 和 UsbMic.h 會一起編譯。
3. 選擇 **AMB82-MINI** 及正確 COM 埠，燒入。需要手動下載模式時：按住 BOOT、按一下 RESET、放開 BOOT。
4. 上傳完成後按 RESET。
5. 關閉 Arduino 序列埠監控視窗，USB 保持連接。

不用編輯任何 Wi-Fi 設定。舊版 V2 韌體與 V3 電腦端程式不相容，必須重新上傳。

## 2. 執行電腦程式

在「作業一」資料夾開啟 PowerShell：

```powershell
.\.venv\Scripts\python.exe voice_control.py --list-ports
.\.venv\Scripts\python.exe voice_control.py --port COM3
```

把 COM3 換成實際的埠。如果只有一個 COM 埠，直接執行也會自動選用：

```powershell
.\.venv\Scripts\python.exe voice_control.py
```

本資料夾已有 .venv。換電腦或沒有 .venv 時，先執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

V3 不需要 FFmpeg、imageio-ffmpeg 或 PyAudio。原環境已裝的舊套件可以保留，不會使用。

## 3. 使用網頁

1. 開啟 **http://127.0.0.1:8000**，不要直接雙擊 index.html。
2. 選擇閃爍次數及語言，按「儲存設定」。
3. 先按手動開燈按鈕，確認 USB 燈號控制。
4. 按「開始聆聽」。校正時安靜約 1 秒，看到「聆聽中」後對著**板子麥克風**說話。
5. 辨識期間等待下一次聆聽提示，再說下一句。
6. 用完先按「停止聆聽」，需要關燈則再按「全部熄滅」。Ctrl+C 結束電腦程式。

例如次數設為 3，說 Turn on the left light，藍燈會閃 3 次後熄滅，綠燈保持熄滅。

開始聆聽後，語音片段會由電腦送到 Google 辨識服務；不會儲存錄音檔。關閉網頁不會自動停止背景聆聽。停止聆聽會阻止未完成辨識結果開燈，但等候音訊／網路時可能需幾秒才退出。已開始的閃爍仍由板子自行完成；結束 Python 不會自動熄滅持續亮著的燈。

## 排除問題

- **V3 韌體未回覆**：確認重新上傳、按 RESET、COM 正確，並關閉 Arduino 監控及其他占用 COM 的程式。
- **COM 無法開啟**：檢查 USB UART 接口、資料線、驅動程式；重新插拔後 COM 編號可能改變。
- **收不到板載音訊／MIC_ERROR**：重置板子後重試。確認本機 SDK 與下方已驗證版本一致；韌體初始化或實體麥克風需進一步檢查。
- **音訊遺失／損毀**：本版使用 921600 baud，請用穩定的資料線，避免不穩定的 USB 集線器。先停止再開始；持續出錯時須檢查實機吞吐量與 UART 驅動。
- **序列埠监控亂碼**：應用程式啟動後使用 921600 baud；開機 ROM 日誌仍可能是 115200。一般操作請用 Python，不要同時開監控視窗。
- **Google 服務錯誤**：檢查電腦的網際網路。網站及手動控制不依賴 Google。
- **聽不清楚**：靠近板子、降低背景噪音，完整說出指令。不要／don't 等否定句不在指令白名單。
- **8000 已占用**：加上 --web-port 8080，改開 http://127.0.0.1:8080。
- 網頁每秒查詢板子狀態，不會精準顯示每一次快速閃爍。

## 實作與驗證

- assessment_1.ino：LED、文字控制協定、USB 傳輸排程。
- UsbMic.cpp / UsbMic.h：AudioStream 16 kHz、16-bit 單聲道 PCM，透過自訂 MMF sink 排入 FreeRTOS queue。
- usb_audio.py：USB 接收、音訊／回覆分流、序號及 CRC-16 檢查。控制指令不會清空音訊接收緩衝區。
- voice_control.py：辨識、控制及本機網站。
- index.html：網站介面。

PCM 每包 512 bytes，十六進位編碼傳送；資料量約 66 KB/s，小於 921600 baud、8N1 的理論上限約 92 KB/s。實際穩定性仍需測試線材與板子。資料遺失或損毀時停止該次語音辨識，避免不完整錄音導致誤控制。

SDK 4.0.9 的 Serial.begin() 預設鎖定 115200，因此韌體直接呼叫該 SDK 的 serial_baud 設定 LOG UART，不修改 SDK 檔案。這部分與 SDK 版本有關。

已使用本機 **AmebaPro2 4.0.9-build20250805** 編譯成功。編譯環境使用 LC_ALL=C、LANG=C 及英文暫存路徑避開 locale 錯誤。主機測試涵蓋中英文指令、HTTP 操作、序列埠回覆配對、USB 分段資料、CRC 與遺失封包。

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_voice_control.py
```

**尚未燒入實體板子驗證 USB 收音、辨識率與 LED 次數。** 編譯與模擬通訊通過不等於實機端到端測試成功；ACK 是韌體執行 GPIO 的確認，不是光學檢測。

參考：[Realtek 官方 MMF 自訂模組文件](https://github.com/Ameba-AIoT/ameba-rtos-pro2-doc/blob/master/source/application_note/06_MMF.rst)。
