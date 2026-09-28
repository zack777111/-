"""USB UART multiplexing: checked PCM frames and correlated LED replies."""
import binascii
import queue
import struct
import threading
import time


class Board:
    def __init__(self, port=None, transport=None):
        if transport is None:
            import serial
            transport = serial.Serial(port, 921600, timeout=0.05, write_timeout=2)
        self.port = transport
        self.lock = threading.Lock()
        self.sequence = 0
        self.frames = queue.Queue(maxsize=32)
        self.replies = queue.Queue(maxsize=100)
        self.closed = threading.Event()
        self.failure = None
        self.audio_errors = 0
        self.last_sequence = None
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _line(self, line):
        if line.startswith(b"PCM:"):
            try:
                _, seq, encoded, checksum = line.split(b":")
                seq = int(seq)
                data = bytes.fromhex(encoded.decode("ascii"))
                if len(data) != 512 or not 0 <= seq <= 0xffffffff:
                    raise ValueError("invalid frame")
                crc = binascii.crc_hqx(struct.pack("<I", seq) + data, 0xffff)
                if crc != int(checksum, 16):
                    raise ValueError("bad CRC")
                if self.last_sequence is not None and seq != ((self.last_sequence + 1) & 0xffffffff):
                    self.audio_errors += 1
                self.last_sequence = seq
                try:
                    self.frames.put_nowait(data)
                except queue.Full:
                    self.audio_errors += 1
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                    self.frames.put_nowait(data)
            except (ValueError, UnicodeError, queue.Full):
                self.audio_errors += 1
        elif line.startswith((b"INFO:", b"OK:", b"STATE:", b"MIC:", b"ERR:")):
            try:
                self.replies.put_nowait(line.decode("ascii"))
            except (UnicodeError, queue.Full):
                pass

    def _read_loop(self):
        buffer = bytearray()
        try:
            while not self.closed.is_set():
                data = self.port.read(4096)
                if not data:
                    continue
                buffer.extend(data)
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if len(line) <= 1200:
                        self._line(bytes(line).rstrip(b"\r"))
                    else:
                        self.audio_errors += 1
                if len(buffer) > 4096:
                    buffer.clear()
                    self.audio_errors += 1
        except Exception as error:
            self.failure = error

    def exchange(self, command, prefix, timeout=3):
        # Caller serializes commands. The reader alone owns reads; never flush
        # the UART input because audio and command replies share it.
        while True:
            try:
                self.replies.get_nowait()
            except queue.Empty:
                break
        if self.failure:
            raise RuntimeError("USB 連線中斷：" + str(self.failure))
        self.port.write((command + "\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.failure:
                raise RuntimeError("USB 連線中斷：" + str(self.failure))
            try:
                reply = self.replies.get(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if reply.startswith(prefix):
                return reply[len(prefix):]
            if reply.startswith("ERR:"):
                raise RuntimeError("開發板拒絕指令：" + reply)
        raise RuntimeError("開發板未回覆：請確認 V3 USB 韌體、COM 埠與 921600 baud。")

    def info(self):
        with self.lock:
            return self.exchange("INFO", "INFO:VOICE_LED_V3:")

    def microphone(self, enabled):
        with self.lock:
            self.sequence += 1
            if enabled:
                self.last_sequence = None
            result = self.exchange("MIC {} {}".format(self.sequence, int(enabled)),
                                   "MIC:{}:".format(self.sequence))
            if result != str(int(enabled)):
                raise RuntimeError("麥克風控制回覆不符。")

    def set_light(self, color, count):
        if color not in ("BLUE", "GREEN", "OFF"):
            raise ValueError("無效的燈號。")
        if type(count) is not int or not 0 <= count <= 100:
            raise ValueError("閃爍次數必須是 0～100 的整數。")
        with self.lock:
            self.sequence += 1
            result = self.exchange("SET {} {} {}".format(self.sequence, color, count),
                                   "OK:{}:".format(self.sequence))
            if result != "{}:{}".format(color, count):
                raise RuntimeError("開發板回覆與指令不符。")

    def state(self):
        with self.lock:
            self.sequence += 1
            result = self.exchange("STATE {}".format(self.sequence), "STATE:{}:".format(self.sequence))
        color, remaining, lit = result.split(":")
        return dict(color=color, remaining=int(remaining), lit=lit == "1")

    def close(self):
        if not self.closed.is_set():
            try:
                self.microphone(False)
            except Exception:
                pass
            self.closed.set()
            self.reader.join(timeout=1)
            self.port.close()


class PCMStream:
    def __init__(self, board):
        self.board = board
        self.discard_old()

    def discard_old(self):
        while True:
            try:
                self.board.frames.get_nowait()
            except queue.Empty:
                break
        self.error_mark = self.board.audio_errors

    def verify(self):
        if self.board.failure:
            raise RuntimeError("USB 連線中斷：" + str(self.board.failure))
        if self.board.audio_errors != self.error_mark:
            raise RuntimeError("USB 音訊遺失或損毀，已停止辨識以免誤執行；請檢查線材並重新開始聆聽。")

    def read(self, size):
        self.verify()
        try:
            data = self.board.frames.get(timeout=3)
        except queue.Empty:
            self.verify()
            raise RuntimeError("收不到板載麥克風音訊，請確認 V3 韌體及 USB UART 連線。")
        self.verify()
        return data


def audio_source(board):
    import speech_recognition as sr

    class BoardAudio(sr.AudioSource):
        SAMPLE_RATE, SAMPLE_WIDTH, CHUNK = 16000, 2, 256

        def __init__(self):
            self.stream = None

        def __enter__(self):
            board.microphone(True)
            self.stream = PCMStream(board)
            return self

        def __exit__(self, exc_type, *args):
            self.stream = None
            try:
                board.microphone(False)
            except Exception:
                if exc_type is None:
                    raise

    return BoardAudio()
