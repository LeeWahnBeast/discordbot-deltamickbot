from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Discord Bot VPS</title>
    <style>
        body{
            margin:0;
            background:#0d1117;
            color:#f0f6fc;
            font-family:Arial,sans-serif;
            display:flex;
            justify-content:center;
            align-items:center;
            height:100vh;
        }
        .card{
            background:#161b22;
            padding:40px;
            border-radius:20px;
            text-align:center;
            max-width:500px;
            box-shadow:0 0 20px rgba(0,0,0,.4);
        }
        h1{
            margin-bottom:10px;
        }
        p{
            color:#8b949e;
            line-height:1.6;
        }
        .status{
            color:#3fb950;
            font-weight:bold;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>🤖 Discord Bot VPS</h1>
        <p class="status">● Online</p>
        <p>
            Đây <b>không phải là một website</b>.<br>
            Máy chủ này chỉ được sử dụng để giữ bot Discord hoạt động 24/7.
        </p>
        <hr style="border-color:#30363d;">
        <small>Powered by Flask • Python</small>
    </div>
</body>
</html>
"""

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    Thread(target=run, daemon=True).start()
