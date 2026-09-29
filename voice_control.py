"""AMB82-MINI onboard microphone, bilingual voice and local web controller."""
import argparse
import json
import secrets
import sys
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from usb_audio import Board, audio_source


def parse_command(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(c for c in text if not c.isspace()
                   and not unicodedata.category(c).startswith("P"))
    text = text.translate(str.maketrans("边开灯蓝绿闪烁时", "邊開燈藍綠閃爍時"))
    text = text.replace("3", "三")
    special = {
        "藍燈閃爍三次": "BLUE_BLINK3", "左邊閃爍三次": "BLUE_BLINK3",
        "綠燈閃爍三次": "GREEN_BLINK3", "右邊閃爍三次": "GREEN_BLINK3",
        "藍綠燈閃爍三次": "BOTH_BLINK3", "兩顆燈閃爍三次": "BOTH_BLINK3",
        "同時亮燈": "BOTH", "藍綠同時亮燈": "BOTH", "兩顆燈同時亮": "BOTH",
        "turnonbothlights": "BOTH", "bothlightson": "BOTH",
    }
    for color, target in (("blue", "BLUE"), ("left", "BLUE"),
                          ("green", "GREEN"), ("right", "GREEN"), ("both", "BOTH")):
        noun = "lights" if color == "both" else "light"
        for article in ("", "the"):
            for times in ("three", "三"):
                special["blink" + article + color + noun + times + "times"] = target + "_BLINK3"
    if text in special:
        return special[text]
    return {"左邊開燈": "BLUE", "右邊開燈": "GREEN",
            "turnontheleftlight": "BLUE", "turnonleftlight": "BLUE",
            "leftlighton": "BLUE", "turnontherightlight": "GREEN",
            "turnonrightlight": "GREEN", "rightlighton": "GREEN"}.get(text)


def valid_count(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("閃爍次數必須是 0～100 的整數。")
    return value


class Controller:
    def __init__(self, board):
        self.board = board
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.count = 0
        self.language = "auto"
        self.phase = "尚未開始"
        self.logs = []

    def log(self, message):
        print(message, flush=True)
        with self.lock:
            self.logs.append({"time": time.strftime("%H:%M:%S"), "text": message})
            self.logs = self.logs[-40:]

    def configure(self, count, language):
        valid_count(count)
        if language not in ("auto", "zh-TW", "en-US"):
            raise ValueError("無效的辨識語言。")
        with self.lock:
            self.count, self.language = count, language

    def light(self, color):
        with self.lock:
            fixed = {"BLUE_BLINK3": "BLUE", "GREEN_BLINK3": "GREEN", "BOTH_BLINK3": "BOTH"}
            if color in fixed:
                color, count = fixed[color], 3
            else:
                count = 0 if color in ("OFF", "BOTH") else self.count
            self.board.set_light(color, count)
            self.log({"BLUE": "藍燈亮起", "GREEN": "綠燈亮起", "BOTH": "藍燈與綠燈同時亮起", "OFF": "兩燈已熄滅"}[color])
            if count:
                self.log("閃爍 {} 次後熄滅".format(count))

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("聆聽仍在執行或停止中，請稍候。")
            self.stop_event.clear()
            self.phase = "連線中"
            self.worker = threading.Thread(target=self.listen, daemon=True)
            self.worker.start()

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if self.worker and self.worker.is_alive():
                self.phase = "停止中"

    def set_phase(self, phase):
        with self.lock:
            self.phase = "停止中" if self.stop_event.is_set() else phase

    def listen(self):
        try:
            import speech_recognition as sr
            info = self.board.info()
            if info != "USB_PCM_16000":
                raise RuntimeError("板載麥克風初始化失敗，請重新燒入 V3 韌體並按 RESET。")
            recognizer = sr.Recognizer()
            recognizer.operation_timeout = 8
            recognizer.pause_threshold = 0.7
            with audio_source(self.board) as source:
                self.set_phase("校正噪音，請安靜")
                recognizer.adjust_for_ambient_noise(source, duration=1)
                self.log("板載麥克風已連線；可以說中文或英文指令。")
                while not self.stop_event.is_set():
                    source.stream.discard_old()
                    self.set_phase("聆聽中，請對板子說話")
                    try:
                        audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)
                        source.stream.verify()
                    except sr.WaitTimeoutError:
                        continue
                    if self.stop_event.is_set():
                        break
                    self.set_phase("辨識中")
                    with self.lock:
                        language = self.language
                    languages = ("zh-TW", "en-US") if language == "auto" else (language,)
                    matches, transcripts, errors = set(), [], []
                    for lang in languages:
                        if self.stop_event.is_set():
                            break
                        try:
                            text = recognizer.recognize_google(audio, language=lang)
                            transcripts.append(text)
                            color = parse_command(text)
                            if color:
                                matches.add(color)
                        except sr.UnknownValueError:
                            pass
                        except sr.RequestError as error:
                            errors.append(str(error))
                    with self.lock:
                        if self.stop_event.is_set():
                            break
                        if transcripts:
                            self.log("辨識：" + " / ".join(transcripts))
                        if len(matches) == 1:
                            self.light(matches.pop())
                        elif len(matches) > 1:
                            self.log("中英文辨識指令不一致，請再說一次。")
                        elif errors:
                            self.log("語音服務無法使用，請檢查網路：" + errors[0])
                        else:
                            self.log("未辨識到完整指令，請再說一次。")
        except Exception as error:
            self.log("語音控制停止：" + str(error))
        finally:
            with self.lock:
                self.phase = "已停止"

    def snapshot(self):
        try:
            board_state = self.board.state()
            connection_error = ""
        except Exception as error:
            board_state, connection_error = None, str(error)
        with self.lock:
            return dict(count=self.count, language=self.language, phase=self.phase,
                        listening=bool(self.worker and self.worker.is_alive()),
                        board=board_state, error=connection_error, logs=list(self.logs))


def make_handler(controller, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, content_type="application/json; charset=utf-8"):
            body = value.encode("utf-8") if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                page = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
                self.send(200, page.replace("__TOKEN__", token), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self.send(200, controller.snapshot())
            else:
                self.send(404, {"error": "找不到頁面"})

        def do_POST(self):
            if self.headers.get("X-Control-Token") != token:
                self.send(403, {"error": "請重新載入控制頁面。"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("無效的請求長度。")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("無效的請求。")
                if self.path == "/api/settings":
                    controller.configure(data.get("count"), data.get("language"))
                elif self.path == "/api/light":
                    controller.light(data.get("color"))
                elif self.path == "/api/start":
                    controller.start()
                elif self.path == "/api/stop":
                    controller.stop()
                else:
                    self.send(404, {"error": "找不到操作"})
                    return
                self.send(200, {"ok": True})
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, {"error": str(error)})
            except Exception as error:
                self.send(503, {"error": str(error)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="例如 COM3；只有一個序列埠時自動選用")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--web-port", type=int, default=8000)
    args = parser.parse_args()
    board = server = controller = None
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        if args.list_ports:
            for port in ports:
                print("{}: {}".format(port.device, port.description))
            if not ports:
                print("未找到 COM 埠，請連接 USB UART。")
            return 0
        selected = args.port or (ports[0].device if len(ports) == 1 else None)
        if selected is None:
            print("請指定 --port COM3。可用的 COM 埠：")
            for port in ports:
                print("{}: {}".format(port.device, port.description))
            return 1
        board = Board(selected)
        print("正在確認 V3 USB 韌體……")
        for attempt in range(8):
            try:
                info = board.info()
                break
            except RuntimeError:
                if attempt == 7:
                    raise
        print("板載音訊：" + info)
        controller = Controller(board)
        server = ThreadingHTTPServer(("127.0.0.1", args.web_port), make_handler(controller, secrets.token_hex(24)))
        server.daemon_threads = True
        print("請開啟 http://127.0.0.1:{} ，按「開始聆聽」。".format(args.web_port))
        print("板載錄音會傳送至 Google 語音辨識服務。Ctrl+C 結束。")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在結束……")
    except Exception as error:
        print("啟動失敗：{}\n請確認已安裝 requirements.txt，並關閉 Arduino 序列埠監控視窗。".format(error))
        return 1
    finally:
        if controller:
            controller.stop()
            if controller.worker:
                controller.worker.join(timeout=25)
        if server:
            server.server_close()
        if board:
            board.close()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())


