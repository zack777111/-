"""Host-side tests; no physical board or microphone is used."""
import json
import binascii
import queue
import struct
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from types import SimpleNamespace
from usb_audio import PCMStream

import voice_control as app


class FakeBoard:
    def __init__(self):
        self.commands = []

    def info(self):
        return "USB_PCM_16000"

    def set_light(self, color, count):
        if color not in ("BLUE", "GREEN", "OFF"):
            raise ValueError("Invalid color")
        app.valid_count(count)
        self.commands.append((color, count))

    def state(self):
        color, count = self.commands[-1] if self.commands else ("OFF", 0)
        return dict(color=color, remaining=count, lit=color != "OFF")


class Tests(unittest.TestCase):
    def test_pcm_loss_cannot_reach_recognition(self):
        import speech_recognition as sr
        board = SimpleNamespace(frames=queue.Queue(), failure=None, audio_errors=0)
        stream = PCMStream(board)
        board.frames.put(b"\x00\x01" * 256)
        self.assertEqual(len(stream.read(256)), 512)
        board.frames.put(b"\x00\x01" * 256)
        board.audio_errors += 1
        with self.assertRaises(RuntimeError):
            stream.read(256)
        stream.discard_old()
        self.assertTrue(board.frames.empty())
        stream.verify()

        controller = app.Controller(FakeBoard())
        class BrokenSource:
            def __enter__(self): self.stream = self; return self
            def __exit__(self, *args): pass
            def discard_old(self): pass
            def verify(self): raise RuntimeError("USB audio lost")
        with patch.object(app, "audio_source", return_value=BrokenSource()), patch.object(sr, "Recognizer") as recognizer:
            controller.listen()
            recognizer.return_value.recognize_google.assert_not_called()
        self.assertEqual(controller.board.commands, [])

    def test_phrases_and_negation(self):
        for phrase, color in [("左邊開燈！", "BLUE"), ("右边开灯", "GREEN"),
                              ("Turn on the LEFT light.", "BLUE"),
                              ("Turn on the right light", "GREEN"),
                              ("Right light on", "GREEN")]:
            self.assertEqual(app.parse_command(phrase), color)
        for phrase in ["不要左邊開燈", "Don't turn on the left light", "left", "", "左邊開燈右邊開燈"]:
            self.assertIsNone(app.parse_command(phrase))

    def test_count_bounds(self):
        for count in [0, 1, 100]:
            self.assertEqual(app.valid_count(count), count)
        for count in [-1, 101, True, 2.5, "3", None]:
            with self.assertRaises(ValueError):
                app.valid_count(count)

    def test_failed_ack_never_reports_success(self):
        board = FakeBoard()
        controller = app.Controller(board)
        with patch.object(board, "set_light", side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                controller.light("BLUE")
        self.assertEqual(controller.logs, [])

    def test_serial_ack_correlation(self):
        class Port:
            def __init__(self):
                self.incoming = queue.Queue()
            def read(self, size):
                try: return self.incoming.get(timeout=0.05)
                except queue.Empty: return b""
            def write(self, data):
                self.sent = data
                if data.startswith(b"MIC"):
                    _, seq, value = data.split()
                    self.incoming.put(b"MIC:" + seq + b":" + value + b"\n")
                else:
                    self.incoming.put(self.response)
            def close(self): pass
        port = Port()
        board = app.Board(transport=port)
        try:
            port.response = b"OK:999:BLUE:3\nOK:1:BLUE:3\n"
            board.set_light("BLUE", 3)
            self.assertEqual(port.sent, b"SET 1 BLUE 3\n")
            port.response = b"OK:2:GREEN:3\n"
            with self.assertRaises(RuntimeError):
                board.set_light("BLUE", 3)
            data = b"\x01\x02" * 256
            crc = binascii.crc_hqx(struct.pack("<I", 0) + data, 0xffff)
            line = b"PCM:0:" + data.hex().encode() + (":%04x\n" % crc).encode()
            # Split a PCM line across USB reads; mix unrelated SDK log lines.
            port.incoming.put(b"SDK boot log\n" + line[:17])
            port.incoming.put(line[17:])
            self.assertEqual(board.frames.get(timeout=1), data)
            self.assertEqual(board.audio_errors, 0)
            board._line(line.strip()[:-4] + b"0000")
            self.assertEqual(board.audio_errors, 1)
            self.assertTrue(board.frames.empty())
            crc = binascii.crc_hqx(struct.pack("<I", 2) + data, 0xffff)
            board._line(b"PCM:2:" + data.hex().encode() + (":%04x" % crc).encode())
            self.assertEqual(board.audio_errors, 2) # Missing sequence 1.
        finally:
            board.close()

    def test_bilingual_audio_dispatch_and_stop(self):
        import speech_recognition as sr
        for transcripts, expected in [(["無關內容", "Turn on the right light"], "GREEN"),
                                       (["左邊開燈", "Turn on the right light"], None)]:
            controller = app.Controller(FakeBoard())
            controller.count = 4
            class Source:
                def __enter__(self):
                    self.stream = self
                    return self
                def __exit__(self, *args): pass
                def discard_old(self): pass
                def verify(self): pass
            class Recognizer:
                def __init__(self): self.listens = 0
                def adjust_for_ambient_noise(self, *args, **kwargs): pass
                def listen(self, *args, **kwargs):
                    self.listens += 1
                    if self.listens > 1:
                        controller.stop_event.set()
                    return object()
                def recognize_google(self, audio, language):
                    return transcripts[0 if language == "zh-TW" else 1]
            with patch.object(app, "audio_source", return_value=Source()), patch.object(sr, "Recognizer", Recognizer):
                controller.listen()
            self.assertEqual(controller.board.commands, [(expected, 4)] if expected else [])
            self.assertEqual(controller.phase, "已停止")

    def test_http_controls_and_invalid_requests(self):
        controller = app.Controller(FakeBoard())
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(controller, "test-token"))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = "http://127.0.0.1:{}".format(server.server_port)
        def post(path, payload, token="test-token"):
            req = urllib.request.Request(base + path, data=json.dumps(payload).encode(),
                                         headers={"X-Control-Token": token, "Content-Type": "application/json"})
            return urllib.request.urlopen(req, timeout=5)
        try:
            with urllib.request.urlopen(base, timeout=5) as response:
                self.assertIn("test-token", response.read().decode())
            with post("/api/settings", {"count": 3, "language": "auto"}) as response:
                self.assertEqual(response.status, 200)
            with post("/api/light", {"color": "BLUE"}): pass
            with post("/api/light", {"color": "GREEN"}): pass
            with post("/api/light", {"color": "OFF"}): pass
            self.assertEqual(controller.board.commands, [("BLUE", 3), ("GREEN", 3), ("OFF", 0)])
            for count in [-1, 101, 2.5]:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post("/api/settings", {"count": count, "language": "auto"})
                self.assertEqual(error.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as error:
                post("/api/light", {"color": "BLUE"}, "wrong-token")
            self.assertEqual(error.exception.code, 403)
            with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                state = json.load(response)
                self.assertEqual(state["board"]["color"], "OFF")
                self.assertEqual(state["count"], 3)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
