import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Go2 Local Control</title>
    <style>
        :root {
            --bg: #eef2ef;
            --surface: #ffffff;
            --surface-strong: #111716;
            --surface-soft: #f7faf8;
            --border: #d7ded9;
            --text: #17201d;
            --muted: #65716c;
            --green: #0f8f68;
            --green-dark: #0a6d51;
            --red: #d72e2e;
            --red-dark: #ad2020;
            --amber: #b86b00;
            --blue: #2368c8;
            --shadow: 0 18px 45px rgba(18, 30, 26, 0.12);
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(circle at 15% 10%, rgba(15, 143, 104, 0.12), transparent 26rem),
                linear-gradient(135deg, #eef2ef 0%, #f8faf8 48%, #e7ece8 100%);
            color: var(--text);
        }

        button {
            font: inherit;
        }

        .app {
            width: min(1180px, calc(100vw - 32px));
            margin: 0 auto;
            padding: 24px 0;
        }

        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 18px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .mark {
            width: 44px;
            height: 44px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: var(--surface-strong);
            color: #ffffff;
            font-weight: 800;
        }

        h1 {
            margin: 0;
            font-size: 28px;
            line-height: 1.15;
        }

        .subtitle {
            margin: 4px 0 0;
            color: var(--muted);
            font-size: 14px;
        }

        .status-strip {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            min-height: 34px;
            padding: 0 12px;
            border: 1px solid var(--border);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.76);
            color: var(--muted);
            font-size: 13px;
            font-weight: 700;
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 0 4px rgba(15, 143, 104, 0.14);
        }

        .workspace {
            display: grid;
            grid-template-columns: 280px minmax(360px, 1fr) 310px;
            gap: 18px;
            align-items: stretch;
        }

        .panel {
            background: rgba(255, 255, 255, 0.86);
            border: 1px solid rgba(215, 222, 217, 0.9);
            border-radius: 8px;
            box-shadow: var(--shadow);
            overflow: hidden;
        }

        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            min-height: 56px;
            padding: 0 18px;
            border-bottom: 1px solid var(--border);
            background: rgba(247, 250, 248, 0.94);
        }

        .panel-title {
            margin: 0;
            font-size: 15px;
            font-weight: 800;
        }

        .panel-body {
            padding: 18px;
        }

        .metric-list {
            display: grid;
            gap: 12px;
        }

        .metric {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 8px;
            align-items: center;
            padding: 14px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--surface-soft);
        }

        .metric-label {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .metric-value {
            grid-column: 1 / -1;
            min-height: 24px;
            overflow-wrap: anywhere;
            font-size: 18px;
            font-weight: 800;
        }

        .metric-badge {
            padding: 4px 8px;
            border-radius: 999px;
            background: rgba(15, 143, 104, 0.12);
            color: var(--green-dark);
            font-size: 12px;
            font-weight: 800;
        }

        .stage {
            display: grid;
            grid-template-rows: auto 1fr auto;
            min-height: 640px;
        }

        .visual {
            display: grid;
            place-items: center;
            min-height: 240px;
            padding: 24px;
            background:
                linear-gradient(rgba(17, 23, 22, 0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(17, 23, 22, 0.05) 1px, transparent 1px),
                #fbfcfb;
            background-size: 28px 28px;
            border-bottom: 1px solid var(--border);
        }

        .robot {
            position: relative;
            width: min(330px, 78vw);
            aspect-ratio: 1.65;
        }

        .robot-body {
            position: absolute;
            inset: 23% 18%;
            border-radius: 8px;
            background: linear-gradient(135deg, #202927, #35413d);
            box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.08), 0 18px 35px rgba(17, 23, 22, 0.2);
        }

        .robot-head {
            position: absolute;
            right: 7%;
            top: 28%;
            width: 22%;
            height: 32%;
            border-radius: 8px;
            background: #111716;
            box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.08);
        }

        .robot-eye {
            position: absolute;
            right: 10%;
            top: 41%;
            width: 26px;
            height: 8px;
            border-radius: 999px;
            background: #7bf0c6;
            box-shadow: 0 0 18px rgba(123, 240, 198, 0.82);
        }

        .leg {
            position: absolute;
            width: 14%;
            height: 54%;
            border-radius: 999px;
            border: 10px solid #26312e;
            border-top-color: transparent;
            transform-origin: top center;
        }

        .leg.one {
            left: 13%;
            top: 44%;
            transform: rotate(12deg);
        }

        .leg.two {
            left: 30%;
            top: 44%;
            transform: rotate(-10deg);
        }

        .leg.three {
            right: 29%;
            top: 44%;
            transform: rotate(10deg);
        }

        .leg.four {
            right: 12%;
            top: 44%;
            transform: rotate(-12deg);
        }

        .floor-line {
            position: absolute;
            left: 6%;
            right: 6%;
            bottom: 5%;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(15, 143, 104, 0.55), transparent);
        }

        .controls {
            padding: 18px;
        }

        .control-row {
            display: grid;
            gap: 12px;
            margin-bottom: 16px;
        }

        .control-row.two {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .section-label {
            margin: 0 0 10px;
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .action-button {
            min-height: 54px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            width: 100%;
            border: 1px solid transparent;
            border-radius: 8px;
            color: #ffffff;
            cursor: pointer;
            font-weight: 800;
            transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease, opacity 140ms ease;
        }

        .action-button:hover {
            transform: translateY(-1px);
            box-shadow: 0 12px 24px rgba(18, 30, 26, 0.16);
        }

        .action-button:active {
            transform: translateY(0);
            box-shadow: none;
        }

        .action-button:disabled {
            cursor: wait;
            opacity: 0.72;
            transform: none;
            box-shadow: none;
        }

        .danger {
            min-height: 64px;
            background: linear-gradient(180deg, var(--red), var(--red-dark));
            font-size: 18px;
        }

        .primary {
            background: linear-gradient(180deg, #217bdf, #1558ae);
        }

        .motion {
            background: linear-gradient(180deg, var(--green), var(--green-dark));
        }

        .secondary {
            background: linear-gradient(180deg, #5b655f, #343d39);
        }

        .button-icon {
            width: 28px;
            height: 28px;
            display: grid;
            place-items: center;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.18);
            font-size: 13px;
        }

        .motion-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }

        .motion-grid .wide {
            grid-column: span 3;
        }

        .log-list {
            display: grid;
            gap: 10px;
        }

        .log-item {
            display: grid;
            gap: 4px;
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--surface-soft);
        }

        .log-time {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }

        .log-text {
            overflow-wrap: anywhere;
            font-size: 14px;
            font-weight: 700;
        }

        .empty-log {
            color: var(--muted);
            padding: 18px 0;
            text-align: center;
            font-size: 14px;
        }

        .footer-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 14px 18px;
            border-top: 1px solid var(--border);
            background: rgba(247, 250, 248, 0.94);
            color: var(--muted);
            font-size: 13px;
            font-weight: 700;
        }

        .status-message {
            overflow-wrap: anywhere;
        }

        .busy .dot {
            background: var(--amber);
            box-shadow: 0 0 0 4px rgba(184, 107, 0, 0.14);
        }

        .error .dot {
            background: var(--red);
            box-shadow: 0 0 0 4px rgba(215, 46, 46, 0.14);
        }

        @media (max-width: 1040px) {
            .workspace {
                grid-template-columns: 1fr;
            }

            .stage {
                min-height: auto;
            }
        }

        @media (max-width: 640px) {
            .app {
                width: min(100vw - 20px, 1180px);
                padding: 14px 0;
            }

            .topbar,
            .footer-bar {
                align-items: flex-start;
                flex-direction: column;
            }

            .status-strip {
                justify-content: flex-start;
            }

            h1 {
                font-size: 23px;
            }

            .control-row.two,
            .motion-grid {
                grid-template-columns: 1fr;
            }

            .motion-grid .wide {
                grid-column: auto;
            }

            .visual {
                min-height: 200px;
                padding: 16px;
            }
        }
    </style>
</head>
<body>
    <div class="app">
        <header class="topbar">
            <div class="brand">
                <div class="mark">G2</div>
                <div>
                    <h1>Go2 Local Control</h1>
                    <p class="subtitle">Operator console for local command testing</p>
                </div>
            </div>
            <div id="modePill" class="status-strip">
                <span class="pill"><span class="dot"></span><span id="connectionText">Local ready</span></span>
                <span class="pill">Mock mode</span>
            </div>
        </header>

        <main class="workspace">
            <aside class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">System State</h2>
                    <span class="metric-badge">Online</span>
                </div>
                <div class="panel-body">
                    <div class="metric-list">
                        <div class="metric">
                            <span class="metric-label">Command</span>
                            <span class="metric-value" id="commandValue">Ready</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Last Response</span>
                            <span class="metric-value" id="responseValue">No action sent</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Round Trip</span>
                            <span class="metric-value" id="latencyValue">-- ms</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Clock</span>
                            <span class="metric-value" id="clockValue">--:--:--</span>
                        </div>
                    </div>
                </div>
            </aside>

            <section class="panel stage">
                <div class="visual" aria-label="Go2 robot status visualization">
                    <div class="robot">
                        <div class="robot-body"></div>
                        <div class="robot-head"></div>
                        <div class="robot-eye"></div>
                        <div class="leg one"></div>
                        <div class="leg two"></div>
                        <div class="leg three"></div>
                        <div class="leg four"></div>
                        <div class="floor-line"></div>
                    </div>
                </div>

                <div class="controls">
                    <p class="section-label">Safety</p>
                    <div class="control-row">
                        <button class="action-button danger" data-action="stop" data-label="Emergency Stop">
                            <span class="button-icon">!</span>
                            Emergency Stop
                        </button>
                    </div>

                    <p class="section-label">Posture</p>
                    <div class="control-row two">
                        <button class="action-button primary" data-action="stand_up" data-label="Stand Up">
                            <span class="button-icon">UP</span>
                            Stand Up
                        </button>
                        <button class="action-button secondary" data-action="stand_down" data-label="Stand Down">
                            <span class="button-icon">DN</span>
                            Stand Down
                        </button>
                    </div>

                    <p class="section-label">Motion</p>
                    <div class="motion-grid">
                        <button class="action-button motion wide" data-action="forward_small" data-label="Forward Small">
                            <span class="button-icon">FW</span>
                            Forward Small
                        </button>
                        <button class="action-button motion" data-action="turn_left" data-label="Turn Left">
                            <span class="button-icon">LT</span>
                            Turn Left
                        </button>
                        <button class="action-button motion" data-action="arc_left" data-label="Arc Left">
                            <span class="button-icon">AL</span>
                            Arc Left
                        </button>
                        <button class="action-button motion" data-action="arc_right" data-label="Arc Right">
                            <span class="button-icon">AR</span>
                            Arc Right
                        </button>
                        <button class="action-button motion wide" data-action="turn_right" data-label="Turn Right">
                            <span class="button-icon">RT</span>
                            Turn Right
                        </button>
                    </div>
                </div>

                <div class="footer-bar">
                    <span class="status-message" id="status">Ready.</span>
                    <span>http://localhost:8000</span>
                </div>
            </section>

            <aside class="panel">
                <div class="panel-header">
                    <h2 class="panel-title">Activity</h2>
                    <span class="metric-badge" id="countValue">0</span>
                </div>
                <div class="panel-body">
                    <div id="logList" class="log-list">
                        <div class="empty-log">No commands yet</div>
                    </div>
                </div>
            </aside>
        </main>
    </div>

    <script>
        const buttons = Array.from(document.querySelectorAll("[data-action]"));
        const status = document.getElementById("status");
        const commandValue = document.getElementById("commandValue");
        const responseValue = document.getElementById("responseValue");
        const latencyValue = document.getElementById("latencyValue");
        const clockValue = document.getElementById("clockValue");
        const connectionText = document.getElementById("connectionText");
        const logList = document.getElementById("logList");
        const countValue = document.getElementById("countValue");
        const entries = [];

        function setBusy(isBusy) {
            document.body.classList.toggle("busy", isBusy);
            buttons.forEach((button) => {
                button.disabled = isBusy && button.dataset.action !== "stop";
            });
        }

        function setError(hasError) {
            document.body.classList.toggle("error", hasError);
            connectionText.innerText = hasError ? "Request failed" : "Local ready";
        }

        function escapeHtml(value) {
            return value.replace(/[&<>"']/g, (character) => ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#039;"
            }[character]));
        }

        function addLog(label, result, elapsed) {
            entries.unshift({
                label,
                result,
                elapsed,
                time: new Date().toLocaleTimeString()
            });

            if (entries.length > 7) {
                entries.pop();
            }

            countValue.innerText = String(entries.length);
            logList.innerHTML = entries.map((entry) => `
                <div class="log-item">
                    <span class="log-time">${escapeHtml(entry.time)} | ${entry.elapsed} ms</span>
                    <span class="log-text">${escapeHtml(entry.label)}: ${escapeHtml(entry.result)}</span>
                </div>
            `).join("");
        }

        async function sendAction(action, label) {
            const startedAt = performance.now();
            setBusy(true);
            setError(false);
            commandValue.innerText = label;
            responseValue.innerText = "Sending...";
            latencyValue.innerText = "-- ms";
            status.innerText = "Sending: " + label;

            try {
                const response = await fetch("/action", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    body: "action=" + encodeURIComponent(action)
                });

                const text = await response.text();
                const elapsed = Math.round(performance.now() - startedAt);
                if (!response.ok) {
                    throw new Error(text || "Request failed");
                }

                responseValue.innerText = text;
                latencyValue.innerText = elapsed + " ms";
                status.innerText = text;
                addLog(label, text, elapsed);
            } catch (error) {
                const elapsed = Math.round(performance.now() - startedAt);
                const message = error.message || "Request failed";
                setError(true);
                responseValue.innerText = message;
                latencyValue.innerText = elapsed + " ms";
                status.innerText = message;
                addLog(label, message, elapsed);
            } finally {
                setBusy(false);
            }
        }

        buttons.forEach((button) => {
            button.addEventListener("click", () => {
                sendAction(button.dataset.action, button.dataset.label);
            });
        });

        function updateClock() {
            clockValue.innerText = new Date().toLocaleTimeString();
        }

        updateClock();
        setInterval(updateClock, 1000);
    </script>
</body>
</html>
"""

def load_html():
    source = Path(__file__).read_text(encoding="utf-8")
    start_marker = 'HTML = """'
    end_marker = '"""\n\ndef load_html'

    try:
        start = source.index(start_marker) + len(start_marker)
        end = source.index(end_marker, start)
    except ValueError:
        return HTML.replace("http://localhost:8000", f"http://localhost:{PORT}")

    return source[start:end].replace("http://localhost:8000", f"http://localhost:{PORT}")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(load_html().encode("utf-8"))
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

        print(f"Mock action received: {action}")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"Mock completed action: {action}".encode("utf-8"))

class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    print(f"Starting local mock GUI at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    server = ReusableThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
