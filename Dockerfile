FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# web_server.py mở cổng 8080 cho UptimeRobot ping giữ bot thức
EXPOSE 8080

CMD ["python", "main.py"]
