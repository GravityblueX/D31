# D31 维护说明

## v0.1.0 - 2026-06-11

本仓库包含 Go、Python、Docker 与 Kubernetes 相关组件，当前更像一个基础设施/自愈系统原型。为了避免长期未维护导致项目烂尾，本次发布建立低风险维护基线。

### 当前结构

- `main.go` / `go.mod`：Go 入口与依赖定义。
- `core/healer/auto_healer.py`、`core/predictor/fault_predictor.py`：Python 自愈与故障预测逻辑。
- `docker/`、`docker-compose.yaml`：容器化运行配置。
- `k8s/`：Kubernetes 部署资源。
- `configs/healing_rules.yaml`：自愈规则配置。

### 本次维护

- 补充维护说明与发布基线，不直接修改运行时逻辑。
- 明确后续验证入口，降低继续接手成本。
- 创建 GitHub Release 作为 v0.1.0 维护基线。

### 建议验证

```bash
go mod download
go test ./...
python -m py_compile core/healer/auto_healer.py core/predictor/fault_predictor.py
docker compose config
```

### 后续建议

- 将 Go 与 Python 验证拆成 CI job。
- 为 Docker/Kubernetes 配置增加示例环境变量说明。
- 梳理 Python 依赖并补齐独立 requirements 文件。
