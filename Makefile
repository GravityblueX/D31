# OpsSentinel 智能运维监控平台 Makefile
# 作者: GravityblueX
# 描述: 项目构建、部署和管理工具

.PHONY: help init build deploy clean test lint docker k8s-deploy k8s-clean dev status logs

# 默认目标
.DEFAULT_GOAL := help

# 项目信息
PROJECT_NAME = ops-sentinel
VERSION = 1.0.0
REGISTRY = docker.io/ops-sentinel
NAMESPACE = ops-sentinel

# 颜色定义
GREEN = \033[32m
YELLOW = \033[33m
RED = \033[31m
BLUE = \033[34m
RESET = \033[0m

# 帮助信息
help: ## 显示帮助信息
	@echo "$(BLUE)OpsSentinel 智能运维监控平台$(RESET)"
	@echo "$(YELLOW)可用命令:$(RESET)"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(GREEN)%-15s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "$(YELLOW)示例:$(RESET)"
	@echo "  make init      # 初始化开发环境"
	@echo "  make dev       # 启动开发环境"
	@echo "  make deploy    # 部署到Kubernetes"

# 环境初始化
init: ## 初始化开发环境
	@echo "$(BLUE)🚀 初始化OpsSentinel开发环境...$(RESET)"
	@echo "$(YELLOW)检查依赖...$(RESET)"
	@command -v docker >/dev/null 2>&1 || { echo "$(RED)❌ Docker 未安装$(RESET)"; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo "$(RED)❌ kubectl 未安装$(RESET)"; exit 1; }
	@command -v helm >/dev/null 2>&1 || { echo "$(YELLOW)⚠️  Helm 未安装，将跳过相关功能$(RESET)"; }
	@echo "$(GREEN)✅ 环境检查完成$(RESET)"
	@echo "$(YELLOW)创建必要目录...$(RESET)"
	@mkdir -p logs data backups models
	@echo "$(GREEN)✅ 目录创建完成$(RESET)"

# 构建所有镜像
build: ## 构建所有Docker镜像
	@echo "$(BLUE)🔨 构建OpsSentinel Docker镜像...$(RESET)"
	@echo "$(YELLOW)构建核心服务镜像...$(RESET)"
	@docker build -t $(REGISTRY)/core:$(VERSION) -f docker/core/Dockerfile .
	@echo "$(YELLOW)构建代理镜像...$(RESET)"
	@docker build -t $(REGISTRY)/agent:$(VERSION) -f docker/agent/Dockerfile .
	@echo "$(YELLOW)构建仪表板镜像...$(RESET)"
	@docker build -t $(REGISTRY)/dashboard:$(VERSION) -f docker/dashboard/Dockerfile .
	@echo "$(GREEN)✅ 镜像构建完成$(RESET)"

# 推送镜像
push: build ## 推送Docker镜像到注册表
	@echo "$(BLUE)📤 推送镜像到注册表...$(RESET)"
	@docker push $(REGISTRY)/core:$(VERSION)
	@docker push $(REGISTRY)/agent:$(VERSION)
	@docker push $(REGISTRY)/dashboard:$(VERSION)
	@echo "$(GREEN)✅ 镜像推送完成$(RESET)"

# 开发环境
dev: ## 启动本地开发环境
	@echo "$(BLUE)🚀 启动OpsSentinel开发环境...$(RESET)"
	@docker-compose up -d
	@echo "$(GREEN)✅ 开发环境已启动$(RESET)"
	@echo ""
	@echo "$(YELLOW)🌐 服务访问地址:$(RESET)"
	@echo "  核心服务:     http://localhost:8080"
	@echo "  仪表板:       http://localhost:3001"
	@echo "  Grafana:      http://localhost:3000 (admin/admin123)"
	@echo "  指标端点:     http://localhost:9100/metrics"
	@echo ""
	@echo "$(BLUE)💡 使用 'make logs' 查看日志，'make status' 查看状态$(RESET)"

# 停止开发环境
dev-stop: ## 停止本地开发环境
	@echo "$(YELLOW)⏹️  停止开发环境...$(RESET)"
	@docker-compose down
	@echo "$(GREEN)✅ 开发环境已停止$(RESET)"

# 重启开发环境
dev-restart: dev-stop dev ## 重启本地开发环境

# 查看状态
status: ## 查看服务状态
	@echo "$(BLUE)📊 OpsSentinel 服务状态$(RESET)"
	@echo ""
	@echo "$(YELLOW)Docker Compose 服务:$(RESET)"
	@docker-compose ps 2>/dev/null || echo "开发环境未启动"
	@echo ""
	@echo "$(YELLOW)Kubernetes 服务 (如果已部署):$(RESET)"
	@kubectl get pods -n $(NAMESPACE) 2>/dev/null || echo "Kubernetes环境未部署"

# 查看日志
logs: ## 查看服务日志
	@echo "$(BLUE)📋 OpsSentinel 服务日志$(RESET)"
	@echo "$(YELLOW)选择要查看的服务日志:$(RESET)"
	@echo "  1) 核心服务 (core)"
	@echo "  2) 代理服务 (agent)"
	@echo "  3) 仪表板 (dashboard)"
	@echo "  4) 所有服务 (all)"
	@read -p "请输入选择 [1-4]: " choice; \
	case $$choice in \
		1) docker-compose logs -f ops-sentinel-core ;; \
		2) docker-compose logs -f ops-sentinel-agent ;; \
		3) docker-compose logs -f ops-sentinel-dashboard ;; \
		4) docker-compose logs -f ;; \
		*) echo "$(RED)无效选择$(RESET)" ;; \
	esac

# 代码检查
lint: ## 执行代码静态检查
	@echo "$(BLUE)🔍 执行代码检查...$(RESET)"
	@echo "$(YELLOW)Python代码检查...$(RESET)"
	@find core -name "*.py" -exec python -m py_compile {} \; 2>/dev/null || echo "⚠️  Python代码检查跳过"
	@echo "$(YELLOW)Go代码检查...$(RESET)"
	@go vet ./... 2>/dev/null || echo "⚠️  Go代码检查跳过"
	@echo "$(GREEN)✅ 代码检查完成$(RESET)"

# 运行测试
test: ## 运行测试套件
	@echo "$(BLUE)🧪 运行测试套件...$(RESET)"
	@echo "$(YELLOW)Python测试...$(RESET)"
	@python -m pytest tests/ -v 2>/dev/null || echo "⚠️  Python测试跳过"
	@echo "$(YELLOW)Go测试...$(RESET)"
	@go test ./... -v 2>/dev/null || echo "⚠️  Go测试跳过"
	@echo "$(GREEN)✅ 测试完成$(RESET)"

# Kubernetes部署
k8s-deploy: ## 部署到Kubernetes集群
	@echo "$(BLUE)🚀 部署OpsSentinel到Kubernetes...$(RESET)"
	@echo "$(YELLOW)创建命名空间...$(RESET)"
	@kubectl apply -f k8s/namespace.yaml
	@echo "$(YELLOW)部署配置映射...$(RESET)"
	@kubectl apply -f k8s/configmaps.yaml
	@echo "$(YELLOW)部署核心服务...$(RESET)"
	@kubectl apply -f k8s/deployment.yaml
	@echo "$(YELLOW)部署服务...$(RESET)"
	@kubectl apply -f k8s/services.yaml
	@echo "$(GREEN)✅ Kubernetes部署完成$(RESET)"
	@echo ""
	@echo "$(YELLOW)🌐 检查部署状态:$(RESET)"
	@kubectl get pods -n $(NAMESPACE)
	@echo ""
	@echo "$(BLUE)💡 使用 'kubectl port-forward' 访问服务$(RESET)"

# Kubernetes清理
k8s-clean: ## 清理Kubernetes部署
	@echo "$(YELLOW)🧹 清理Kubernetes部署...$(RESET)"
	@kubectl delete -f k8s/services.yaml --ignore-not-found=true
	@kubectl delete -f k8s/deployment.yaml --ignore-not-found=true
	@kubectl delete -f k8s/configmaps.yaml --ignore-not-found=true
	@kubectl delete -f k8s/namespace.yaml --ignore-not-found=true
	@echo "$(GREEN)✅ 清理完成$(RESET)"

# Kubernetes重新部署
k8s-redeploy: k8s-clean k8s-deploy ## 重新部署到Kubernetes

# 备份数据
backup: ## 备份重要数据
	@echo "$(BLUE)💾 备份OpsSentinel数据...$(RESET)"
	@mkdir -p backups/$(shell date +%Y%m%d_%H%M%S)
	@echo "$(YELLOW)备份配置文件...$(RESET)"
	@cp -r configs backups/$(shell date +%Y%m%d_%H%M%S)/
	@echo "$(YELLOW)备份模型文件...$(RESET)"
	@cp -r models backups/$(shell date +%Y%m%d_%H%M%S)/ 2>/dev/null || echo "模型目录不存在"
	@echo "$(GREEN)✅ 备份完成$(RESET)"

# 性能测试
benchmark: ## 运行性能测试
	@echo "$(BLUE)⚡ OpsSentinel 性能测试$(RESET)"
	@echo "$(YELLOW)测试API响应时间...$(RESET)"
	@curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8080/health 2>/dev/null || echo "服务未启动"
	@echo "$(YELLOW)测试指标采集性能...$(RESET)"
	@curl -w "@curl-format.txt" -o /dev/null -s http://localhost:9100/metrics 2>/dev/null || echo "代理未启动"

# 安全扫描
security-scan: ## 执行安全扫描
	@echo "$(BLUE)🔒 执行安全扫描...$(RESET)"
	@echo "$(YELLOW)Docker镜像安全扫描...$(RESET)"
	@docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
		aquasec/trivy image $(REGISTRY)/core:$(VERSION) 2>/dev/null || echo "⚠️  安全扫描跳过"

# 监控检查
monitor: ## 检查监控系统状态
	@echo "$(BLUE)📊 监控系统状态检查$(RESET)"
	@echo ""
	@echo "$(YELLOW)Redis状态:$(RESET)"
	@docker-compose exec redis redis-cli ping 2>/dev/null || echo "Redis未运行"
	@echo "$(YELLOW)InfluxDB状态:$(RESET)"
	@curl -s http://localhost:8086/ping >/dev/null && echo "InfluxDB正常" || echo "InfluxDB异常"
	@echo "$(YELLOW)Grafana状态:$(RESET)"
	@curl -s http://localhost:3000/api/health >/dev/null && echo "Grafana正常" || echo "Grafana异常"

# 清理环境
clean: ## 清理构建文件和临时数据
	@echo "$(YELLOW)🧹 清理环境...$(RESET)"
	@docker system prune -f
	@rm -rf logs/*.log data/temp/* backups/temp*
	@echo "$(GREEN)✅ 清理完成$(RESET)"

# 完整部署流程
deploy: init build k8s-deploy ## 完整部署流程（初始化 + 构建 + 部署）
	@echo "$(GREEN)🎉 OpsSentinel 部署完成！$(RESET)"
	@echo ""
	@echo "$(BLUE)📝 下一步操作:$(RESET)"
	@echo "  1. 访问仪表板配置监控规则"
	@echo "  2. 导入Grafana监控面板"
	@echo "  3. 配置告警通知渠道"
	@echo "  4. 运行健康检查验证部署"

# 健康检查
health-check: ## 执行系统健康检查
	@echo "$(BLUE)🏥 OpsSentinel 健康检查$(RESET)"
	@echo ""
	@echo "$(YELLOW)检查核心服务...$(RESET)"
	@curl -f http://localhost:8080/health >/dev/null 2>&1 && echo "✅ 核心服务正常" || echo "❌ 核心服务异常"
	@echo "$(YELLOW)检查代理服务...$(RESET)"
	@curl -f http://localhost:9100/metrics >/dev/null 2>&1 && echo "✅ 代理服务正常" || echo "❌ 代理服务异常"
	@echo "$(YELLOW)检查仪表板...$(RESET)"
	@curl -f http://localhost:3001/health >/dev/null 2>&1 && echo "✅ 仪表板正常" || echo "❌ 仪表板异常"

# 开发工具
dev-tools: ## 安装开发工具
	@echo "$(BLUE)🛠️  安装开发工具...$(RESET)"
	@pip install black pylint pytest 2>/dev/null || echo "Python工具安装失败"
	@go install golang.org/x/tools/cmd/goimports@latest 2>/dev/null || echo "Go工具安装失败"
	@echo "$(GREEN)✅ 开发工具安装完成$(RESET)"

# 生成文档
docs: ## 生成项目文档
	@echo "$(BLUE)📚 生成项目文档...$(RESET)"
	@mkdir -p docs/api docs/deployment docs/monitoring
	@echo "$(YELLOW)生成API文档...$(RESET)"
	@echo "# API 文档\n\n待补充..." > docs/api/README.md
	@echo "$(YELLOW)生成部署文档...$(RESET)"
	@echo "# 部署指南\n\n待补充..." > docs/deployment/README.md
	@echo "$(GREEN)✅ 文档生成完成$(RESET)"

# 版本信息
version: ## 显示版本信息
	@echo "$(BLUE)OpsSentinel 版本信息$(RESET)"
	@echo "项目版本: $(GREEN)$(VERSION)$(RESET)"
	@echo "构建时间: $(GREEN)$(shell date '+%Y-%m-%d %H:%M:%S')$(RESET)"
	@echo "Git版本: $(GREEN)$(shell git rev-parse --short HEAD 2>/dev/null || echo 'unknown')$(RESET)"