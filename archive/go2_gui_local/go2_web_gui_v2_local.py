from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
import os
import time


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8001"))


class MockRobot:
    """
    This is a fake robot.
    It does not control the real Go2.
    It only prints actions to the terminal.
    """

    def __init__(self):
        self.status = "Ready"

    def stop(self):
        self.status = "Stopped"
        print("[MockRobot] STOP")

    def stand_up(self):
        self.status = "Standing"
        print("[MockRobot] Stand Up")

    def stand_down(self):
        self.status = "Lying down"
        print("[MockRobot] Stand Down")

    def damp(self):
        self.status = "Damp mode"
        print("[MockRobot] Damp / Soft Stop")

    def move(self, vx, vy, wz, duration):
        self.status = "Moving"
        print("[MockRobot] Move command:")
        print(f"  vx = {vx}")
        print(f"  vy = {vy}")
        print(f"  wz = {wz}")
        print(f"  duration = {duration}")

        time.sleep(duration)

        self.stop()


robot = MockRobot()


def parse_float(data, name):
    value_list = data.get(name, [""])[0:1]
    value_str = value_list[0]

    try:
        return float(value_str)
    except ValueError:
        raise ValueError(f"{name} must be a number")


def validate_motion(vx, vy, wz, duration):
    if not -0.30 <= vx <= 0.30:
        raise ValueError("vx must be between -0.30 and 0.30")

    if not -0.20 <= vy <= 0.20:
        raise ValueError("vy must be between -0.20 and 0.20")

    if not -0.40 <= wz <= 0.40:
        raise ValueError("wz must be between -0.40 and 0.40")

    if not 0.1 <= duration <= 2.0:
        raise ValueError("duration must be between 0.1 and 2.0 seconds")


HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Go2 GUI V2 Local Mock</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #111827;
            color: white;
            text-align: center;
            padding: 30px;
        }

        h1 {
            margin-bottom: 5px;
        }

        .subtitle {
            color: #d1d5db;
            margin-bottom: 25px;
        }

        .panel {
            max-width: 800px;
            margin: 0 auto;
            background: #1f2937;
            padding: 25px;
            border-radius: 16px;
        }

        button {
            font-size: 18px;
            padding: 14px 22px;
            margin: 8px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            min-width: 150px;
        }

        .stop {
            background: #dc2626;
            color: white;
            font-weight: bold;
            font-size: 22px;
            min-width: 330px;
        }

        .normal {
            background: #2563eb;
            color: white;
        }

        .motion {
            background: #059669;
            color: white;
        }

        .danger {
            background: #f97316;
            color: white;
        }

        .section {
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid #374151;
        }

        label {
            display: inline-block;
            margin: 8px;
            font-size: 16px;
        }

        input {
            font-size: 16px;
            padding: 8px;
            border-radius: 8px;
            border: none;
            width: 90px;
            text-align: center;
        }

        .lock {
            font-size: 18px;
            color: #fbbf24;
            margin: 15px;
        }

        #status {
            margin-top: 25px;
            font-size: 18px;
            color: #93c5fd;
            white-space: pre-line;
        }
    </style>
</head>

<body>
    <h1>Go2 GUI V2 Local Mock</h1>
    <div class="subtitle">
        Local simulation only. This does not control the real robot.
    </div>

    <div class="panel">
        <button class="stop" onclick="sendSimpleAction('stop')">STOP</button>

        <div class="section">
            <button class="normal" onclick="sendSimpleAction('stand_up')">Stand Up</button>
            <button class="normal" onclick="sendSimpleAction('stand_down')">Stand Down</button>
            <button class="danger" onclick="sendSimpleAction('damp')">Damp</button>
        </div>

        <div class="section">
            <div class="lock">
                <input type="checkbox" id="enableMotion">
                <label for="enableMotion">Enable Motion</label>
            </div>

            <button class="motion" onclick="presetForward()">Preset Forward</button>
            <button class="motion" onclick="presetLeftTurn()">Preset Left Turn</button>
            <button class="motion" onclick="presetRightTurn()">Preset Right Turn</button>
            <button class="motion" onclick="presetArcLeft()">Preset Arc Left</button>
            <button class="motion" onclick="presetArcRight()">Preset Arc Right</button>
        </div>

        <div class="section">
            <h2>Custom Move</h2>

            <label>
                vx:
                <input id="vx" value="0.20">
            </label>

            <label>
                vy:
                <input id="vy" value="0.00">
            </label>

            <label>
                wz:
                <input id="wz" value="0.00">
            </label>

            <label>
                duration:
                <input id="duration" value="1.00">
            </label>

            <br>

            <button class="motion" onclick="sendCustomMove()">Run Custom Move</button>
        </div>

        <div id="status">Ready.</div>
    </div>

    <script>
        function motionEnabled() {
            return document.getElementById("enableMotion").checked;
        }

        function setParams(vx, vy, wz, duration) {
            document.getElementById("vx").value = vx;
            document.getElementById("vy").value = vy;
            document.getElementById("wz").value = wz;
            document.getElementById("duration").value = duration;
        }

        function presetForward() {
            setParams("0.20", "0.00", "0.00", "1.00");
        }

        function presetLeftTurn() {
            setParams("0.00", "0.00", "0.25", "0.80");
        }

        function presetRightTurn() {
            setParams("0.00", "0.00", "-0.25", "0.80");
        }

        function presetArcLeft() {
            setParams("0.20", "0.00", "0.20", "1.00");
        }

        function presetArcRight() {
            setParams("0.20", "0.00", "-0.20", "1.00");
        }

        async function sendSimpleAction(action) {
            const status = document.getElementById("status");
            status.innerText = "Sending: " + action;

            const response = await fetch("/action", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: "action=" + encodeURIComponent(action)
            });

            const text = await response.text();
            status.innerText = text;
        }

        async function sendCustomMove() {
            const status = document.getElementById("status");

            if (!motionEnabled()) {
                status.innerText = "Motion is locked. Check Enable Motion first.";
                return;
            }

            const vx = document.getElementById("vx").value;
            const vy = document.getElementById("vy").value;
            const wz = document.getElementById("wz").value;
            const duration = document.getElementById("duration").value;

            status.innerText = "Sending custom move...";

            const body =
                "action=custom_move" +
                "&enable_motion=true" +
                "&vx=" + encodeURIComponent(vx) +
                "&vy=" + encodeURIComponent(vy) +
                "&wz=" + encodeURIComponent(wz) +
                "&duration=" + encodeURIComponent(duration);

            const response = await fetch("/action", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: body
            });

            const text = await response.text();
            status.innerText = text;
        }
    </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def do_POST(self):
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        data = parse_qs(body)

        action = data.get("action", [""])[0]

        try:
            if action == "stop":
                robot.stop()
                message = "Completed: STOP"

            elif action == "stand_up":
                robot.stand_up()
                message = "Completed: Stand Up"

            elif action == "stand_down":
                robot.stand_down()
                message = "Completed: Stand Down"

            elif action == "damp":
                robot.damp()
                message = "Completed: Damp"

            elif action == "custom_move":
                enable_motion = data.get("enable_motion", ["false"])[0]

                if enable_motion != "true":
                    raise ValueError("Motion is locked")

                vx = parse_float(data, "vx")
                vy = parse_float(data, "vy")
                wz = parse_float(data, "wz")
                duration = parse_float(data, "duration")

                validate_motion(vx, vy, wz, duration)

                robot.move(vx, vy, wz, duration)

                message = (
                    "Completed custom move:\\n"
                    f"vx={vx}, vy={vy}, wz={wz}, duration={duration}"
                )

            else:
                message = f"Unknown action: {action}"

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode("utf-8"))

        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode("utf-8"))


if __name__ == "__main__":
    print(f"Starting Go2 GUI V2 local mock at http://localhost:{PORT}")
    print("This is local simulation only. It does not control the real robot.")
    print("Press Ctrl+C to stop.")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
