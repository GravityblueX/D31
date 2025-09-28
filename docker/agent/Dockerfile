# OpsSentinel Agent Dockerfile
FROM golang:1.21-alpine AS builder

WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache git ca-certificates tzdata

# 复制go模块文件
COPY go.mod go.sum ./
RUN go mod download

# 复制源代码
COPY core/detector/ ./core/detector/
COPY core/collector/ ./core/collector/
COPY main.go ./

# 构建应用
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o ops-sentinel-agent .

# 运行阶段
FROM alpine:3.18

# 安装运行时依赖
RUN apk add --no-cache \
    ca-certificates \
    curl \
    procps \
    util-linux \
    && rm -rf /var/cache/apk/*

WORKDIR /app

# 从构建阶段复制二进制文件
COPY --from=builder /app/ops-sentinel-agent .
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# 创建非root用户
RUN addgroup -g 1000 ops && \
    adduser -D -s /bin/sh -u 1000 -G ops ops

# 设置权限
RUN chown ops:ops /app/ops-sentinel-agent && \
    chmod +x /app/ops-sentinel-agent

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:9100/metrics || exit 1

# 暴露端口
EXPOSE 9100

# 使用非root用户运行
USER ops

# 启动命令
CMD ["./ops-sentinel-agent"]