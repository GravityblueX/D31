#!/usr/bin/env python3
"""
OpsSentinel - AI故障预测引擎
基于机器学习的智能故障预测系统
"""

import numpy as np
import pandas as pd
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import tensorflow as tf
from tensorflow import keras
import redis
import logging

@dataclass
class PredictionResult:
    """预测结果数据类"""
    timestamp: datetime
    risk_score: float
    confidence: float
    predicted_failure_time: Optional[datetime]
    risk_factors: List[str]
    recommended_actions: List[str]

@dataclass
class MetricData:
    """监控指标数据类"""
    timestamp: datetime
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_io: float
    error_rate: float
    response_time: float

class FaultPredictor:
    """AI故障预测引擎"""
    
    def __init__(self, model_path: str = "models/fault_predictor.h5"):
        self.model_path = model_path
        self.model = None
        self.scaler = StandardScaler()
        self.isolation_forest = IsolationForest(contamination=0.1, random_state=42)
        self.redis_client = redis.Redis(host='localhost', port=6379, db=0)
        self.logger = self._setup_logger()
        
        # 预测阈值配置
        self.risk_thresholds = {
            'low': 0.3,
            'medium': 0.6,
            'high': 0.8,
            'critical': 0.9
        }
        
        # 故障模式库
        self.failure_patterns = {
            'memory_leak': {
                'indicators': ['memory_usage_trend_up', 'gc_frequency_up'],
                'threshold': 0.85,
                'prediction_horizon': 3600  # 1小时
            },
            'cpu_saturation': {
                'indicators': ['cpu_usage_high', 'load_average_high'],
                'threshold': 0.9,
                'prediction_horizon': 1800  # 30分钟
            },
            'disk_full': {
                'indicators': ['disk_usage_trend_up', 'disk_write_high'],
                'threshold': 0.95,
                'prediction_horizon': 7200  # 2小时
            },
            'network_congestion': {
                'indicators': ['network_latency_high', 'packet_loss_up'],
                'threshold': 0.8,
                'prediction_horizon': 900   # 15分钟
            }
        }
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('FaultPredictor')
        logger.setLevel(logging.INFO)
        
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    async def load_model(self):
        """加载预训练的AI模型"""
        try:
            if self.model is None:
                self.model = keras.models.load_model(self.model_path)
                self.logger.info(f"AI模型加载成功: {self.model_path}")
            return True
        except Exception as e:
            self.logger.error(f"模型加载失败: {e}")
            # 如果模型不存在，创建一个新的LSTM模型
            await self._create_lstm_model()
            return False
    
    async def _create_lstm_model(self):
        """创建LSTM神经网络模型"""
        self.logger.info("创建新的LSTM故障预测模型...")
        
        model = keras.Sequential([
            keras.layers.LSTM(64, return_sequences=True, input_shape=(60, 6)),
            keras.layers.Dropout(0.2),
            keras.layers.LSTM(32, return_sequences=False),
            keras.layers.Dropout(0.2),
            keras.layers.Dense(16, activation='relu'),
            keras.layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(
            optimizer='adam',
            loss='binary_crossentropy',
            metrics=['accuracy', 'precision', 'recall']
        )
        
        self.model = model
        self.logger.info("LSTM模型创建完成")
    
    async def predict_fault_risk(
        self, 
        metrics: List[MetricData], 
        time_window: str = '1h',
        confidence_threshold: float = 0.85
    ) -> PredictionResult:
        """预测故障风险"""
        try:
            # 确保模型已加载
            await self.load_model()
            
            # 预处理时序数据
            features = self._preprocess_metrics(metrics)
            
            # AI模型预测
            risk_score = await self._predict_with_lstm(features)
            
            # 异常检测
            anomaly_score = self._detect_anomalies(features)
            
            # 融合预测结果
            final_risk_score = self._combine_scores(risk_score, anomaly_score)
            
            # 分析风险因素
            risk_factors = self._analyze_risk_factors(metrics)
            
            # 预测故障时间
            failure_time = self._predict_failure_time(final_risk_score, risk_factors)
            
            # 生成推荐操作
            actions = self._generate_recommendations(final_risk_score, risk_factors)
            
            # 缓存预测结果
            await self._cache_prediction_result(final_risk_score, risk_factors)
            
            result = PredictionResult(
                timestamp=datetime.now(),
                risk_score=final_risk_score,
                confidence=self._calculate_confidence(features),
                predicted_failure_time=failure_time,
                risk_factors=risk_factors,
                recommended_actions=actions
            )
            
            self.logger.info(f"故障风险预测完成: 风险评分={final_risk_score:.3f}")
            return result
            
        except Exception as e:
            self.logger.error(f"故障预测失败: {e}")
            raise
    
    def _preprocess_metrics(self, metrics: List[MetricData]) -> np.ndarray:
        """预处理监控指标数据"""
        if len(metrics) < 60:  # 需要至少60个时间点
            raise ValueError("需要至少60个时间点的数据进行预测")
        
        # 提取特征
        features = []
        for metric in metrics[-60:]:  # 取最近60个时间点
            features.append([
                metric.cpu_usage,
                metric.memory_usage,
                metric.disk_usage,
                metric.network_io,
                metric.error_rate,
                metric.response_time
            ])
        
        features_array = np.array(features)
        
        # 标准化
        features_scaled = self.scaler.fit_transform(features_array)
        
        # 重塑为LSTM输入格式 (samples, timesteps, features)
        return features_scaled.reshape(1, 60, 6)
    
    async def _predict_with_lstm(self, features: np.ndarray) -> float:
        """使用LSTM模型进行预测"""
        prediction = self.model.predict(features, verbose=0)
        return float(prediction[0][0])
    
    def _detect_anomalies(self, features: np.ndarray) -> float:
        """使用孤立森林检测异常"""
        # 将3D数组转换为2D用于异常检测
        features_2d = features.reshape(features.shape[1], features.shape[2])
        
        # 训练孤立森林（在实际应用中应该使用历史数据预训练）
        self.isolation_forest.fit(features_2d)
        
        # 计算异常分数
        anomaly_scores = self.isolation_forest.decision_function(features_2d)
        
        # 转换为0-1范围的风险分数
        normalized_score = (anomaly_scores.min() - anomaly_scores.mean()) / \
                          (anomaly_scores.min() - anomaly_scores.max() + 1e-8)
        
        return max(0, min(1, normalized_score))
    
    def _combine_scores(self, lstm_score: float, anomaly_score: float) -> float:
        """融合LSTM预测和异常检测结果"""
        # 加权平均，LSTM权重更高
        combined_score = 0.7 * lstm_score + 0.3 * anomaly_score
        return min(1.0, max(0.0, combined_score))
    
    def _analyze_risk_factors(self, metrics: List[MetricData]) -> List[str]:
        """分析风险因素"""
        risk_factors = []
        
        if not metrics:
            return risk_factors
        
        latest_metric = metrics[-1]
        
        # CPU风险分析
        if latest_metric.cpu_usage > 80:
            risk_factors.append("CPU使用率过高")
        
        # 内存风险分析
        if latest_metric.memory_usage > 85:
            risk_factors.append("内存使用率过高")
        
        # 磁盘风险分析
        if latest_metric.disk_usage > 90:
            risk_factors.append("磁盘空间不足")
        
        # 网络风险分析
        if latest_metric.network_io > 100000000:  # 100MB/s
            risk_factors.append("网络I/O过高")
        
        # 错误率风险分析
        if latest_metric.error_rate > 0.05:  # 5%
            risk_factors.append("错误率过高")
        
        # 响应时间风险分析
        if latest_metric.response_time > 2000:  # 2秒
            risk_factors.append("响应时间过长")
        
        # 趋势分析
        if len(metrics) >= 10:
            cpu_trend = self._calculate_trend([m.cpu_usage for m in metrics[-10:]])
            memory_trend = self._calculate_trend([m.memory_usage for m in metrics[-10:]])
            
            if cpu_trend > 5:  # CPU使用率持续上升
                risk_factors.append("CPU使用率呈上升趋势")
            
            if memory_trend > 5:  # 内存使用率持续上升
                risk_factors.append("内存使用率呈上升趋势")
        
        return risk_factors
    
    def _calculate_trend(self, values: List[float]) -> float:
        """计算数值趋势（斜率）"""
        if len(values) < 2:
            return 0
        
        x = np.arange(len(values))
        z = np.polyfit(x, values, 1)
        return z[0]  # 返回斜率
    
    def _predict_failure_time(
        self, 
        risk_score: float, 
        risk_factors: List[str]
    ) -> Optional[datetime]:
        """预测故障发生时间"""
        if risk_score < self.risk_thresholds['medium']:
            return None
        
        # 基于风险评分和因素估算故障时间
        base_minutes = 180  # 基础3小时
        
        # 风险评分越高，预测时间越短
        risk_factor = (1 - risk_score) * base_minutes
        
        # 根据具体风险因素调整
        for factor in risk_factors:
            if "磁盘空间不足" in factor:
                risk_factor *= 0.5  # 磁盘满了很快就会故障
            elif "内存使用率过高" in factor:
                risk_factor *= 0.7
            elif "CPU使用率过高" in factor:
                risk_factor *= 0.8
        
        predicted_minutes = max(5, int(risk_factor))  # 最少5分钟
        return datetime.now() + timedelta(minutes=predicted_minutes)
    
    def _generate_recommendations(
        self, 
        risk_score: float, 
        risk_factors: List[str]
    ) -> List[str]:
        """生成推荐操作"""
        recommendations = []
        
        if risk_score >= self.risk_thresholds['critical']:
            recommendations.append("立即执行故障预防措施")
            recommendations.append("启动应急响应流程")
        elif risk_score >= self.risk_thresholds['high']:
            recommendations.append("密切监控系统状态")
            recommendations.append("准备故障恢复预案")
        
        # 基于具体风险因素的建议
        for factor in risk_factors:
            if "CPU使用率" in factor:
                recommendations.append("考虑扩容CPU资源或优化应用性能")
            elif "内存使用率" in factor:
                recommendations.append("检查内存泄漏并考虑扩容内存")
            elif "磁盘空间" in factor:
                recommendations.append("清理磁盘空间或扩容存储")
            elif "网络I/O" in factor:
                recommendations.append("检查网络瓶颈并优化网络配置")
            elif "错误率" in factor:
                recommendations.append("检查应用日志定位错误原因")
            elif "响应时间" in factor:
                recommendations.append("分析性能瓶颈并优化查询")
        
        return list(set(recommendations))  # 去重
    
    def _calculate_confidence(self, features: np.ndarray) -> float:
        """计算预测置信度"""
        # 基于特征的方差计算置信度
        feature_variance = np.var(features)
        
        # 方差越小，置信度越高
        confidence = 1.0 / (1.0 + feature_variance)
        
        return min(1.0, max(0.5, confidence))
    
    async def _cache_prediction_result(
        self, 
        risk_score: float, 
        risk_factors: List[str]
    ):
        """缓存预测结果到Redis"""
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'risk_score': risk_score,
                'risk_factors': risk_factors
            }
            
            # 缓存最近的预测结果
            self.redis_client.setex(
                'fault_prediction:latest',
                3600,  # 1小时过期
                str(cache_data)
            )
            
        except Exception as e:
            self.logger.warning(f"缓存预测结果失败: {e}")
    
    async def get_historical_predictions(
        self, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[PredictionResult]:
        """获取历史预测结果"""
        # 实际实现中应该从数据库查询
        # 这里返回示例数据
        return []
    
    async def retrain_model(self, training_data: List[Tuple[List[MetricData], bool]]):
        """重新训练AI模型"""
        self.logger.info("开始重新训练AI模型...")
        
        # 准备训练数据
        X, y = self._prepare_training_data(training_data)
        
        # 训练模型
        history = self.model.fit(
            X, y,
            epochs=50,
            batch_size=32,
            validation_split=0.2,
            verbose=1
        )
        
        # 保存模型
        self.model.save(self.model_path)
        
        self.logger.info("AI模型重新训练完成")
        return history
    
    def _prepare_training_data(
        self, 
        training_data: List[Tuple[List[MetricData], bool]]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """准备训练数据"""
        X, y = [], []
        
        for metrics, failed in training_data:
            if len(metrics) >= 60:
                features = self._preprocess_metrics(metrics)
                X.append(features[0])  # 移除batch维度
                y.append(1 if failed else 0)
        
        return np.array(X), np.array(y)

# 使用示例
async def main():
    """使用示例"""
    predictor = FaultPredictor()
    
    # 模拟监控数据
    metrics = []
    for i in range(60):
        metric = MetricData(
            timestamp=datetime.now() - timedelta(minutes=60-i),
            cpu_usage=70 + i * 0.5,  # 模拟CPU使用率上升
            memory_usage=80 + i * 0.3,
            disk_usage=85,
            network_io=50000000,
            error_rate=0.01,
            response_time=1000
        )
        metrics.append(metric)
    
    # 执行预测
    result = await predictor.predict_fault_risk(metrics)
    
    print(f"故障风险评分: {result.risk_score:.3f}")
    print(f"置信度: {result.confidence:.3f}")
    print(f"风险因素: {result.risk_factors}")
    print(f"推荐操作: {result.recommended_actions}")
    
    if result.predicted_failure_time:
        print(f"预测故障时间: {result.predicted_failure_time}")

if __name__ == "__main__":
    asyncio.run(main())