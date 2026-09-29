# AMB82-MINI 語音燈光控制

使用板載麥克風經 USB 傳送音訊，由電腦辨識中文／英文指令並控制藍燈、綠燈及閃爍次數。開發板不需要 Wi-Fi，電腦需連網使用 Google 語音辨識。

## 執行環境

- Python 3.10.21

## 使用方式

1. Arduino IDE 開啟 `assessment_1/assessment_1.ino`，選擇 AMB82-MINI 後燒入；完成後按 RESET 並關閉序列埠監控。
2. 安裝環境：

```powershell
python -m pip install -r requirements.txt
```

3. 啟動程式，把 `COM6` 改成實際埠號：

```powershell
python voice_control.py --port COM6
```

4. 開啟：<http://127.0.0.1:8000>

## 語音指令

| 中文 | English |
|---|---|
| 左邊開燈 | Turn on the left light |
| 右邊開燈 | Turn on the right light |
| 藍燈閃爍三次 | Blink the blue light three times |
| 綠燈閃爍三次 | Blink the green light three times |
| 藍綠燈閃爍三次 | Blink both lights three times |
| 同時亮燈 | Turn on both lights |
