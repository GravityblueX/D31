# OpsSentinel Dashboard Dockerfile
FROM node:18-alpine AS builder

WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache git python3 make g++

# 复制package文件
COPY package*.json ./
RUN npm ci --only=production

# 复制源代码
COPY src/ ./src/
COPY public/ ./public/
COPY *.config.js ./

# 构建应用
RUN npm run build

# 运行阶段
FROM nginx:1.25-alpine

# 安装额外工具
RUN apk add --no-cache curl jq

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制nginx配置
COPY docker/dashboard/nginx.conf /etc/nginx/nginx.conf
COPY docker/dashboard/default.conf /etc/nginx/conf.d/default.conf

# 创建非root用户
RUN addgroup -g 1000 nginx-user && \
    adduser -D -s /bin/sh -u 1000 -G nginx-user nginx-user

# 设置权限
RUN chown -R nginx-user:nginx-user /usr/share/nginx/html && \
    chown -R nginx-user:nginx-user /var/cache/nginx && \
    chown -R nginx-user:nginx-user /var/log/nginx && \
    chown -R nginx-user:nginx-user /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nginx-user:nginx-user /var/run/nginx.pid

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

# 暴露端口
EXPOSE 3000

# 使用非root用户运行
USER nginx-user

# 启动命令
CMD ["nginx", "-g", "daemon off;"]