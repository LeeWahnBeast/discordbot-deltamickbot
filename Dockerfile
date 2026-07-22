FROM python:3.11-slim

# cairosvg cần thư viện hệ thống libcairo2 để chạy — buildpack Python thường
# (không Docker) của Render KHÔNG cho cài lib hệ thống, nên bắt buộc phải build
# bằng Docker mới dùng được cairosvg. libcairo2-dev có sẵn header phòng khi cần
# build lại wheel; nếu muốn image nhẹ hơn có thể bỏ '-dev' sau khi xác nhận chạy ổn.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# web_server.py mở cổng 8080 cho UptimeRobot ping giữ bot thức
EXPOSE 8080

CMD ["python", "main.py"]
