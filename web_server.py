from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Discord Bot Status</title>

<style>
*{
    margin:0;
    padding:0;
    box-sizing:border-box;
    font-family:Segoe UI,Arial,sans-serif;
}

body{
    height:100vh;
    display:flex;
    justify-content:center;
    align-items:center;
    background:linear-gradient(135deg,#0d1117,#161b22,#1f2937);
    color:#fff;
    overflow:hidden;
}

.card{
    width:90%;
    max-width:520px;
    padding:35px;
    border-radius:22px;
    background:rgba(255,255,255,.05);
    backdrop-filter:blur(12px);
    border:1px solid rgba(255,255,255,.08);
    text-align:center;
    box-shadow:0 20px 40px rgba(0,0,0,.45);
    transition:.3s;
}

.card:hover{
    transform:translateY(-5px);
}

.logo{
    font-size:70px;
    margin-bottom:15px;
}

h1{
    font-size:30px;
    margin-bottom:10px;
}

.status{
    display:inline-flex;
    align-items:center;
    gap:8px;
    padding:8px 18px;
    border-radius:50px;
    background:rgba(63,185,80,.12);
    color:#3fb950;
    font-weight:bold;
    margin-bottom:20px;
}

.dot{
    width:10px;
    height:10px;
    background:#3fb950;
    border-radius:50%;
    animation:pulse 1.5s infinite;
}

p{
    color:#c9d1d9;
    line-height:1.7;
}

hr{
    border:none;
    height:1px;
    background:#30363d;
    margin:25px 0;
}

.footer{
    color:#8b949e;
    font-size:14px;
}

@keyframes pulse{
    0%{box-shadow:0 0 0 0 rgba(63,185,80,.7);}
    70%{box-shadow:0 0 0 10px rgba(63,185,80,0);}
    100%{box-shadow:0 0 0 0 rgba(63,185,80,0);}
}
</style>
</head>

<body>

<div class="card">

<div class="logo">🤖</div>

<h1>Discord Bot VPS</h1>

<div class="status">
<div class="dot"></div>
ONLINE
</div>

<p>
This server is <b>not a public website</b>.<br><br>
It is only used to keep a Discord bot running
continuously.
</p>

<hr>

<div class="footer">
Powered by Flask • Python • Discord.py
</div>

</div>

</body>
</html>
"""

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    Thread(target=run, daemon=True).start()
