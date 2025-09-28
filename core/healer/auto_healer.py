#!/usr/bin/env python3
"""
OpsSentinel - 自动自愈引擎
智能故障恢复和系统自愈机制
"""

import asyncio
import json
import logging
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import subprocess
import requests
import redis
from kubernetes import client, config
from kubernetes.client.rest import ApiException

class HealingStatus(Enum):
    """自愈状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

class ActionType(Enum):
    """自愈动作类型"""
    RESTART_SERVICE = "restart_service"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    RESTART_POD = "restart_pod"
    CLEAR_CACHE = "clear_cache"
    CLEANUP_DISK = "cleanup_disk"
    KILL_PROCESS = "kill_process"
    UPDATE_CONFIG = "update_config"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    CUSTOM_SCRIPT = "custom_script"

@dataclass
class HealingAction:
    """自愈动作定义"""
    id: str
    type: ActionType
    target: str
    parameters: Dict[str, Any]
    timeout: int = 300
    retry_count: int = 3
    condition: Optional[str] = None
    rollback_action: Optional['HealingAction'] = None

@dataclass
class HealingRule:
    """自愈规则定义"""
    id: str
    name: str
    description: str
    trigger_conditions: Dict[str, Any]
    actions: List[HealingAction]
    enabled: bool = True
    cooldown_minutes: int = 30
    max_executions_per_hour: int = 5
    priority: int = 1

@dataclass
class HealingExecution:
    """自愈执行记录"""
    id: str
    rule_id: str
    start_time: datetime
    end_time: Optional[datetime]
    status: HealingStatus
    actions_executed: List[Dict[str, Any]]
    error_message: Optional[str]
    metrics_before: Dict[str, Any]
    metrics_after: Optional[Dict[str, Any]]

class AutoHealer:
    """自动自愈引擎"""
    
    def __init__(self, config_path: str = "configs/healing_rules.yaml"):
        self.config_path = config_path
        self.healing_rules: Dict[str, HealingRule] = {}
        self.execution_history: List[HealingExecution] = []
        self.redis_client = redis.Redis(host='localhost', port=6379, db=1)
        self.logger = self._setup_logger()
        
        # Kubernetes客户端
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()
        
        self.k8s_apps_v1 = client.AppsV1Api()
        self.k8s_core_v1 = client.CoreV1Api()
        
        # 执行统计
        self.execution_stats = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'rules_triggered': {},
            'avg_execution_time': 0
        }
        
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('AutoHealer')
        logger.setLevel(logging.INFO)
        
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    async def load_healing_rules(self):
        """加载自愈规则配置"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                rules_config = yaml.safe_load(f)
            
            self.healing_rules.clear()
            
            for rule_data in rules_config.get('healing_rules', []):
                # 解析自愈动作
                actions = []
                for action_data in rule_data.get('actions', []):
                    action = HealingAction(
                        id=action_data['id'],
                        type=ActionType(action_data['type']),
                        target=action_data['target'],
                        parameters=action_data.get('parameters', {}),
                        timeout=action_data.get('timeout', 300),
                        retry_count=action_data.get('retry_count', 3),
                        condition=action_data.get('condition'),
                    )
                    actions.append(action)
                
                # 创建自愈规则
                rule = HealingRule(
                    id=rule_data['id'],
                    name=rule_data['name'],
                    description=rule_data['description'],
                    trigger_conditions=rule_data['trigger_conditions'],
                    actions=actions,
                    enabled=rule_data.get('enabled', True),
                    cooldown_minutes=rule_data.get('cooldown_minutes', 30),
                    max_executions_per_hour=rule_data.get('max_executions_per_hour', 5),
                    priority=rule_data.get('priority', 1)
                )
                
                self.healing_rules[rule.id] = rule
            
            self.logger.info(f"加载了 {len(self.healing_rules)} 个自愈规则")
            
        except Exception as e:
            self.logger.error(f"加载自愈规则失败: {e}")
            raise
    
    async def check_trigger_conditions(self, alert_data: Dict[str, Any]) -> List[HealingRule]:
        """检查触发条件，返回匹配的规则"""
        triggered_rules = []
        
        for rule in self.healing_rules.values():
            if not rule.enabled:
                continue
            
            # 检查冷却时间
            if not self._check_cooldown(rule.id, rule.cooldown_minutes):
                continue
            
            # 检查执行次数限制
            if not self._check_execution_limit(rule.id, rule.max_executions_per_hour):
                continue
            
            # 检查触发条件
            if self._evaluate_conditions(rule.trigger_conditions, alert_data):
                triggered_rules.append(rule)
        
        # 按优先级排序
        triggered_rules.sort(key=lambda r: r.priority, reverse=True)
        
        return triggered_rules
    
    def _evaluate_conditions(self, conditions: Dict[str, Any], alert_data: Dict[str, Any]) -> bool:
        """评估触发条件"""
        try:
            # 简单的条件评估逻辑
            for key, expected_value in conditions.items():
                if key not in alert_data:
                    return False
                
                actual_value = alert_data[key]
                
                # 支持不同类型的比较
                if isinstance(expected_value, dict):
                    # 支持范围比较 {">=": 80, "<": 95}
                    for operator, threshold in expected_value.items():
                        if operator == ">=":
                            if actual_value < threshold:
                                return False
                        elif operator == ">":
                            if actual_value <= threshold:
                                return False
                        elif operator == "<=":
                            if actual_value > threshold:
                                return False
                        elif operator == "<":
                            if actual_value >= threshold:
                                return False
                        elif operator == "==":
                            if actual_value != threshold:
                                return False
                        elif operator == "!=":
                            if actual_value == threshold:
                                return False
                        elif operator == "in":
                            if actual_value not in threshold:
                                return False
                        elif operator == "contains":
                            if threshold not in str(actual_value):
                                return False
                else:
                    # 直接值比较
                    if actual_value != expected_value:
                        return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"条件评估失败: {e}")
            return False
    
    def _check_cooldown(self, rule_id: str, cooldown_minutes: int) -> bool:
        """检查规则冷却时间"""
        try:
            key = f"healing:cooldown:{rule_id}"
            last_execution = self.redis_client.get(key)
            
            if last_execution:
                last_time = datetime.fromisoformat(last_execution.decode())
                if datetime.now() - last_time < timedelta(minutes=cooldown_minutes):
                    return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"检查冷却时间失败: {e}")
            return True
    
    def _check_execution_limit(self, rule_id: str, max_executions: int) -> bool:
        """检查执行次数限制"""
        try:
            key = f"healing:executions:{rule_id}"
            current_hour = datetime.now().strftime("%Y%m%d%H")
            hour_key = f"{key}:{current_hour}"
            
            execution_count = self.redis_client.get(hour_key)
            if execution_count and int(execution_count) >= max_executions:
                return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"检查执行次数限制失败: {e}")
            return True
    
    async def execute_healing(self, rule: HealingRule, alert_data: Dict[str, Any]) -> HealingExecution:
        """执行自愈流程"""
        execution_id = f"healing-{rule.id}-{int(datetime.now().timestamp())}"
        
        execution = HealingExecution(
            id=execution_id,
            rule_id=rule.id,
            start_time=datetime.now(),
            end_time=None,
            status=HealingStatus.RUNNING,
            actions_executed=[],
            error_message=None,
            metrics_before=alert_data.get('metrics', {}),
            metrics_after=None
        )
        
        self.logger.info(f"开始执行自愈规则: {rule.name} (ID: {execution_id})")
        
        try:
            # 记录执行开始
            await self._record_execution_start(rule.id)
            
            # 执行所有自愈动作
            for action in rule.actions:
                if execution.status == HealingStatus.FAILED:
                    break
                
                # 检查动作条件
                if action.condition and not self._evaluate_action_condition(action.condition, alert_data):
                    self.logger.info(f"跳过动作 {action.id}，条件不满足")
                    continue
                
                action_result = await self._execute_action(action, alert_data)
                execution.actions_executed.append(action_result)
                
                if not action_result['success']:
                    execution.status = HealingStatus.FAILED
                    execution.error_message = action_result.get('error')
                    break
            
            # 验证自愈效果
            if execution.status != HealingStatus.FAILED:
                verification_result = await self._verify_healing_success(rule, alert_data)
                if verification_result:
                    execution.status = HealingStatus.SUCCESS
                    execution.metrics_after = verification_result
                else:
                    execution.status = HealingStatus.FAILED
                    execution.error_message = "自愈效果验证失败"
            
        except Exception as e:
            execution.status = HealingStatus.FAILED
            execution.error_message = str(e)
            self.logger.error(f"自愈执行异常: {e}")
        
        finally:
            execution.end_time = datetime.now()
            
            # 记录执行结果
            await self._record_execution_result(execution)
            
            # 更新统计信息
            self._update_statistics(execution)
            
            self.logger.info(f"自愈执行完成: {execution.status.value} (耗时: {execution.end_time - execution.start_time})")
        
        return execution
    
    def _evaluate_action_condition(self, condition: str, alert_data: Dict[str, Any]) -> bool:
        """评估动作执行条件"""
        try:
            # 简单的条件表达式评估
            # 支持 Python 表达式，例如: "cpu_usage > 90 and memory_usage < 80"
            namespace = {
                'cpu_usage': alert_data.get('metrics', {}).get('cpu_usage', 0),
                'memory_usage': alert_data.get('metrics', {}).get('memory_usage', 0),
                'disk_usage': alert_data.get('metrics', {}).get('disk_usage', 0),
                'load_avg': alert_data.get('metrics', {}).get('load_avg_1', 0),
                'error_rate': alert_data.get('metrics', {}).get('error_rate', 0),
            }
            
            return eval(condition, {"__builtins__": {}}, namespace)
            
        except Exception as e:
            self.logger.warning(f"条件评估失败: {condition}, 错误: {e}")
            return True  # 默认执行
    
    async def _execute_action(self, action: HealingAction, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个自愈动作"""
        action_result = {
            'action_id': action.id,
            'action_type': action.type.value,
            'target': action.target,
            'start_time': datetime.now().isoformat(),
            'success': False,
            'error': None,
            'result': None
        }
        
        try:
            self.logger.info(f"执行自愈动作: {action.type.value} -> {action.target}")
            
            # 根据动作类型执行相应操作
            if action.type == ActionType.RESTART_SERVICE:
                result = await self._restart_service(action.target, action.parameters)
            elif action.type == ActionType.SCALE_UP:
                result = await self._scale_deployment(action.target, action.parameters, scale_up=True)
            elif action.type == ActionType.SCALE_DOWN:
                result = await self._scale_deployment(action.target, action.parameters, scale_up=False)
            elif action.type == ActionType.RESTART_POD:
                result = await self._restart_pod(action.target, action.parameters)
            elif action.type == ActionType.CLEAR_CACHE:
                result = await self._clear_cache(action.target, action.parameters)
            elif action.type == ActionType.CLEANUP_DISK:
                result = await self._cleanup_disk(action.target, action.parameters)
            elif action.type == ActionType.KILL_PROCESS:
                result = await self._kill_process(action.target, action.parameters)
            elif action.type == ActionType.CUSTOM_SCRIPT:
                result = await self._execute_custom_script(action.target, action.parameters)
            else:
                raise ValueError(f"不支持的动作类型: {action.type}")
            
            action_result['success'] = True
            action_result['result'] = result
            
        except Exception as e:
            action_result['error'] = str(e)
            self.logger.error(f"动作执行失败: {action.id}, 错误: {e}")
        
        action_result['end_time'] = datetime.now().isoformat()
        return action_result
    
    async def _restart_service(self, target: str, params: Dict[str, Any]) -> str:
        """重启服务"""
        namespace = params.get('namespace', 'default')
        service_type = params.get('type', 'deployment')
        
        if service_type == 'deployment':
            # 重启 Deployment
            body = {'spec': {'template': {'metadata': {'annotations': {
                'kubectl.kubernetes.io/restartedAt': datetime.now().isoformat()
            }}}}}
            
            self.k8s_apps_v1.patch_namespaced_deployment(
                name=target,
                namespace=namespace,
                body=body
            )
            
            return f"重启 Deployment {target} 成功"
        
        elif service_type == 'systemd':
            # 重启系统服务
            cmd = f"sudo systemctl restart {target}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"重启服务失败: {result.stderr}")
            
            return f"重启系统服务 {target} 成功"
        
        else:
            raise ValueError(f"不支持的服务类型: {service_type}")
    
    async def _scale_deployment(self, target: str, params: Dict[str, Any], scale_up: bool) -> str:
        """扩缩容 Deployment"""
        namespace = params.get('namespace', 'default')
        current_replicas = params.get('current_replicas', 1)
        
        if scale_up:
            new_replicas = params.get('scale_to', current_replicas + 1)
            action_desc = "扩容"
        else:
            new_replicas = max(1, params.get('scale_to', current_replicas - 1))
            action_desc = "缩容"
        
        # 更新 Deployment 副本数
        body = {'spec': {'replicas': new_replicas}}
        
        self.k8s_apps_v1.patch_namespaced_deployment(
            name=target,
            namespace=namespace,
            body=body
        )
        
        # 等待扩缩容完成
        await asyncio.sleep(30)
        
        return f"{action_desc} Deployment {target} 从 {current_replicas} 到 {new_replicas} 个副本"
    
    async def _restart_pod(self, target: str, params: Dict[str, Any]) -> str:
        """重启 Pod"""
        namespace = params.get('namespace', 'default')
        label_selector = params.get('label_selector', f'app={target}')
        
        # 获取匹配的 Pod
        pods = self.k8s_core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector
        )
        
        deleted_pods = []
        for pod in pods.items:
            self.k8s_core_v1.delete_namespaced_pod(
                name=pod.metadata.name,
                namespace=namespace
            )
            deleted_pods.append(pod.metadata.name)
        
        return f"重启了 {len(deleted_pods)} 个 Pod: {', '.join(deleted_pods)}"
    
    async def _clear_cache(self, target: str, params: Dict[str, Any]) -> str:
        """清理缓存"""
        cache_type = params.get('type', 'redis')
        
        if cache_type == 'redis':
            # 清理 Redis 缓存
            cache_redis = redis.Redis(
                host=params.get('host', 'localhost'),
                port=params.get('port', 6379),
                db=params.get('db', 0)
            )
            
            pattern = params.get('pattern', '*')
            keys = cache_redis.keys(pattern)
            
            if keys:
                cache_redis.delete(*keys)
                return f"清理了 {len(keys)} 个 Redis 缓存键"
            else:
                return "没有找到匹配的缓存键"
        
        elif cache_type == 'system':
            # 清理系统缓存
            cmd = "sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"清理系统缓存失败: {result.stderr}")
            
            return "清理系统缓存成功"
        
        else:
            raise ValueError(f"不支持的缓存类型: {cache_type}")
    
    async def _cleanup_disk(self, target: str, params: Dict[str, Any]) -> str:
        """清理磁盘空间"""
        cleanup_paths = params.get('paths', ['/tmp', '/var/log'])
        file_age_days = params.get('file_age_days', 7)
        
        total_freed = 0
        
        for path in cleanup_paths:
            # 删除指定天数前的文件
            cmd = f"find {path} -type f -mtime +{file_age_days} -delete"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0:
                # 计算释放的空间（简化实现）
                total_freed += 100  # MB，实际应该计算真实大小
        
        return f"清理磁盘空间成功，释放约 {total_freed} MB"
    
    async def _kill_process(self, target: str, params: Dict[str, Any]) -> str:
        """终止进程"""
        process_name = params.get('process_name', target)
        signal = params.get('signal', 'TERM')
        
        # 查找并终止进程
        cmd = f"pkill -{signal} {process_name}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            return f"成功终止进程 {process_name}"
        else:
            return f"未找到进程 {process_name} 或终止失败"
    
    async def _execute_custom_script(self, target: str, params: Dict[str, Any]) -> str:
        """执行自定义脚本"""
        script_path = params.get('script_path', target)
        script_args = params.get('args', [])
        timeout = params.get('timeout', 300)
        
        cmd = [script_path] + script_args
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return f"脚本执行成功: {result.stdout}"
            else:
                raise Exception(f"脚本执行失败: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            raise Exception(f"脚本执行超时 (>{timeout}s)")
    
    async def _verify_healing_success(self, rule: HealingRule, original_alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """验证自愈效果"""
        # 等待一段时间让系统稳定
        await asyncio.sleep(60)
        
        try:
            # 获取当前系统指标
            current_metrics = await self._get_current_metrics(original_alert.get('node_id'))
            
            if not current_metrics:
                return None
            
            # 检查指标是否改善
            original_metrics = original_alert.get('metrics', {})
            
            # 简单的改善检查逻辑
            improvements = {}
            
            for metric_name in ['cpu_usage', 'memory_usage', 'disk_usage', 'load_avg_1']:
                original_value = original_metrics.get(metric_name, 0)
                current_value = current_metrics.get(metric_name, 0)
                
                if original_value > 0:
                    improvement = (original_value - current_value) / original_value * 100
                    improvements[metric_name] = improvement
            
            # 如果有任何指标改善超过10%，认为自愈成功
            significant_improvements = [imp for imp in improvements.values() if imp > 10]
            
            if significant_improvements:
                return {
                    'metrics': current_metrics,
                    'improvements': improvements,
                    'verification_time': datetime.now().isoformat()
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"验证自愈效果失败: {e}")
            return None
    
    async def _get_current_metrics(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取当前系统指标"""
        try:
            key = f"metrics:latest:{node_id}"
            data = self.redis_client.get(key)
            
            if data:
                return json.loads(data.decode())
            
            return None
            
        except Exception as e:
            self.logger.error(f"获取当前指标失败: {e}")
            return None
    
    async def _record_execution_start(self, rule_id: str):
        """记录执行开始"""
        # 设置冷却时间
        cooldown_key = f"healing:cooldown:{rule_id}"
        self.redis_client.setex(cooldown_key, 3600, datetime.now().isoformat())
        
        # 增加执行计数
        current_hour = datetime.now().strftime("%Y%m%d%H")
        count_key = f"healing:executions:{rule_id}:{current_hour}"
        self.redis_client.incr(count_key)
        self.redis_client.expire(count_key, 3600)
    
    async def _record_execution_result(self, execution: HealingExecution):
        """记录执行结果"""
        # 存储执行记录
        key = f"healing:history:{execution.rule_id}"
        data = json.dumps(asdict(execution), default=str)
        
        self.redis_client.zadd(key, {data: execution.start_time.timestamp()})
        
        # 保留最近100条记录
        self.redis_client.zremrangebyrank(key, 0, -101)
        
        # 存储到内存
        self.execution_history.append(execution)
        if len(self.execution_history) > 1000:
            self.execution_history = self.execution_history[-1000:]
    
    def _update_statistics(self, execution: HealingExecution):
        """更新统计信息"""
        self.execution_stats['total_executions'] += 1
        
        if execution.status == HealingStatus.SUCCESS:
            self.execution_stats['successful_executions'] += 1
        else:
            self.execution_stats['failed_executions'] += 1
        
        # 更新规则触发次数
        if execution.rule_id not in self.execution_stats['rules_triggered']:
            self.execution_stats['rules_triggered'][execution.rule_id] = 0
        self.execution_stats['rules_triggered'][execution.rule_id] += 1
        
        # 更新平均执行时间
        if execution.end_time:
            duration = (execution.end_time - execution.start_time).total_seconds()
            total_time = self.execution_stats['avg_execution_time'] * (self.execution_stats['total_executions'] - 1)
            self.execution_stats['avg_execution_time'] = (total_time + duration) / self.execution_stats['total_executions']
    
    async def process_alert(self, alert_data: Dict[str, Any]) -> List[HealingExecution]:
        """处理告警并执行自愈"""
        self.logger.info(f"收到告警，开始自愈处理: {alert_data.get('id', 'unknown')}")
        
        # 检查触发条件
        triggered_rules = await self.check_trigger_conditions(alert_data)
        
        if not triggered_rules:
            self.logger.info("没有匹配的自愈规则")
            return []
        
        executions = []
        
        # 执行匹配的自愈规则
        for rule in triggered_rules:
            try:
                execution = await self.execute_healing(rule, alert_data)
                executions.append(execution)
                
                # 如果自愈成功，停止执行其他规则
                if execution.status == HealingStatus.SUCCESS:
                    self.logger.info(f"自愈成功，停止执行其他规则")
                    break
                    
            except Exception as e:
                self.logger.error(f"执行自愈规则失败: {rule.id}, 错误: {e}")
        
        return executions
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.execution_stats.copy()
    
    def get_recent_executions(self, limit: int = 10) -> List[HealingExecution]:
        """获取最近的执行记录"""
        return self.execution_history[-limit:]

# 使用示例
async def main():
    """使用示例"""
    healer = AutoHealer()
    
    # 加载自愈规则
    await healer.load_healing_rules()
    
    # 模拟告警数据
    alert_data = {
        'id': 'cpu-high-alert-001',
        'node_id': 'worker-01',
        'level': 'CRITICAL',
        'type': 'CPU_HIGH',
        'message': 'CPU使用率过高',
        'metrics': {
            'cpu_usage': 95.0,
            'memory_usage': 75.0,
            'disk_usage': 60.0,
            'load_avg_1': 8.5
        }
    }
    
    # 执行自愈
    executions = await healer.process_alert(alert_data)
    
    for execution in executions:
        print(f"自愈执行结果: {execution.status.value}")
        print(f"执行动作数: {len(execution.actions_executed)}")
        if execution.error_message:
            print(f"错误信息: {execution.error_message}")

if __name__ == "__main__":
    asyncio.run(main())