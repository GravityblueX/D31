# OpsSentinel Core Service Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY core/ ./core/
COPY configs/ ./configs/
COPY models/ ./models/

# 创建必要的目录
RUN mkdir -p /var/logs /var/dumps /tmp

# 设置环境变量
ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# 暴露端口
EXPOSE 8080 8090

# 启动命令
CMD ["python", "-m", "core.main"]