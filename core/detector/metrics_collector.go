// OpsSentinel - 高性能监控检测引擎
// 实时采集系统指标并执行异常检测
package detector

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"
	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/disk"
	"github.com/shirou/gopsutil/v3/load"
	"github.com/shirou/gopsutil/v3/mem"
	"github.com/shirou/gopsutil/v3/net"
	"github.com/shirou/gopsutil/v3/process"
)

// MetricsData 监控指标数据结构
type MetricsData struct {
	Timestamp     time.Time `json:"timestamp"`
	NodeID        string    `json:"node_id"`
	CPUUsage      float64   `json:"cpu_usage"`
	MemoryUsage   float64   `json:"memory_usage"`
	DiskUsage     float64   `json:"disk_usage"`
	NetworkRxRate float64   `json:"network_rx_rate"`
	NetworkTxRate float64   `json:"network_tx_rate"`
	LoadAvg1      float64   `json:"load_avg_1"`
	LoadAvg5      float64   `json:"load_avg_5"`
	LoadAvg15     float64   `json:"load_avg_15"`
	ProcessCount  int       `json:"process_count"`
	ErrorRate     float64   `json:"error_rate"`
	ResponseTime  float64   `json:"response_time"`
}

// Alert 告警数据结构
type Alert struct {
	ID          string                 `json:"id"`
	Timestamp   time.Time             `json:"timestamp"`
	NodeID      string                `json:"node_id"`
	Level       AlertLevel            `json:"level"`
	Type        AlertType             `json:"type"`
	Message     string                `json:"message"`
	Metrics     MetricsData           `json:"metrics"`
	Metadata    map[string]interface{} `json:"metadata"`
}

// AlertLevel 告警级别
type AlertLevel int

const (
	INFO AlertLevel = iota
	WARNING
	ERROR
	CRITICAL
)

// AlertType 告警类型
type AlertType int

const (
	CPU_HIGH AlertType = iota
	MEMORY_HIGH
	DISK_HIGH
	NETWORK_HIGH
	LOAD_HIGH
	PROCESS_ANOMALY
	CUSTOM
)

// CollectorConfig 采集器配置
type CollectorConfig struct {
	NodeID           string        `json:"node_id"`
	CollectInterval  time.Duration `json:"collect_interval"`
	RedisAddr        string        `json:"redis_addr"`
	RedisPassword    string        `json:"redis_password"`
	RedisDB          int           `json:"redis_db"`
	AlertThresholds  AlertThresholds `json:"alert_thresholds"`
	EnableDetection  bool          `json:"enable_detection"`
	RetentionDays    int           `json:"retention_days"`
}

// AlertThresholds 告警阈值配置
type AlertThresholds struct {
	CPUWarning     float64 `json:"cpu_warning"`
	CPUCritical    float64 `json:"cpu_critical"`
	MemoryWarning  float64 `json:"memory_warning"`
	MemoryCritical float64 `json:"memory_critical"`
	DiskWarning    float64 `json:"disk_warning"`
	DiskCritical   float64 `json:"disk_critical"`
	LoadWarning    float64 `json:"load_warning"`
	LoadCritical   float64 `json:"load_critical"`
}

// MetricsCollector 监控指标采集器
type MetricsCollector struct {
	config        CollectorConfig
	redisClient   *redis.Client
	ctx          context.Context
	cancel       context.CancelFunc
	mutex        sync.RWMutex
	lastMetrics  MetricsData
	networkStats map[string]net.IOCountersStat
	running      bool
	alertChan    chan Alert
}

// NewMetricsCollector 创建新的监控采集器
func NewMetricsCollector(config CollectorConfig) *MetricsCollector {
	ctx, cancel := context.WithCancel(context.Background())
	
	rdb := redis.NewClient(&redis.Options{
		Addr:     config.RedisAddr,
		Password: config.RedisPassword,
		DB:       config.RedisDB,
	})

	return &MetricsCollector{
		config:       config,
		redisClient:  rdb,
		ctx:         ctx,
		cancel:      cancel,
		networkStats: make(map[string]net.IOCountersStat),
		alertChan:   make(chan Alert, 1000),
	}
}

// Start 启动监控采集器
func (mc *MetricsCollector) Start() error {
	log.Printf("启动监控采集器: NodeID=%s, 采集间隔=%v", 
		mc.config.NodeID, mc.config.CollectInterval)

	mc.running = true

	// 启动指标采集协程
	go mc.collectMetricsLoop()

	// 启动异常检测协程
	if mc.config.EnableDetection {
		go mc.anomalyDetectionLoop()
	}

	// 启动告警处理协程
	go mc.alertProcessingLoop()

	// 启动数据清理协程
	go mc.dataCleanupLoop()

	return nil
}

// Stop 停止监控采集器
func (mc *MetricsCollector) Stop() error {
	log.Printf("停止监控采集器: NodeID=%s", mc.config.NodeID)
	
	mc.running = false
	mc.cancel()
	
	if mc.redisClient != nil {
		return mc.redisClient.Close()
	}
	
	return nil
}

// collectMetricsLoop 指标采集循环
func (mc *MetricsCollector) collectMetricsLoop() {
	ticker := time.NewTicker(mc.config.CollectInterval)
	defer ticker.Stop()

	for {
		select {
		case <-mc.ctx.Done():
			return
		case <-ticker.C:
			if err := mc.collectAndStoreMetrics(); err != nil {
				log.Printf("采集指标失败: %v", err)
			}
		}
	}
}

// collectAndStoreMetrics 采集并存储指标
func (mc *MetricsCollector) collectAndStoreMetrics() error {
	metrics, err := mc.collectSystemMetrics()
	if err != nil {
		return fmt.Errorf("采集系统指标失败: %w", err)
	}

	// 存储指标到Redis
	if err := mc.storeMetrics(metrics); err != nil {
		return fmt.Errorf("存储指标失败: %w", err)
	}

	// 更新最新指标
	mc.mutex.Lock()
	mc.lastMetrics = metrics
	mc.mutex.Unlock()

	// 检测异常
	if mc.config.EnableDetection {
		mc.detectAnomalies(metrics)
	}

	return nil
}

// collectSystemMetrics 采集系统指标
func (mc *MetricsCollector) collectSystemMetrics() (MetricsData, error) {
	now := time.Now()
	
	// CPU使用率
	cpuPercent, err := cpu.Percent(time.Second, false)
	if err != nil {
		return MetricsData{}, err
	}
	
	// 内存使用率
	memInfo, err := mem.VirtualMemory()
	if err != nil {
		return MetricsData{}, err
	}
	
	// 磁盘使用率 (根分区)
	diskInfo, err := disk.Usage("/")
	if err != nil {
		return MetricsData{}, err
	}
	
	// 系统负载
	loadInfo, err := load.Avg()
	if err != nil {
		return MetricsData{}, err
	}
	
	// 网络I/O速率
	networkRx, networkTx, err := mc.calculateNetworkRate()
	if err != nil {
		log.Printf("计算网络速率失败: %v", err)
		networkRx, networkTx = 0, 0
	}
	
	// 进程数量
	processes, err := process.Pids()
	if err != nil {
		return MetricsData{}, err
	}

	return MetricsData{
		Timestamp:     now,
		NodeID:        mc.config.NodeID,
		CPUUsage:      cpuPercent[0],
		MemoryUsage:   memInfo.UsedPercent,
		DiskUsage:     diskInfo.UsedPercent,
		NetworkRxRate: networkRx,
		NetworkTxRate: networkTx,
		LoadAvg1:      loadInfo.Load1,
		LoadAvg5:      loadInfo.Load5,
		LoadAvg15:     loadInfo.Load15,
		ProcessCount:  len(processes),
		ErrorRate:     mc.calculateErrorRate(), // 需要从应用日志计算
		ResponseTime:  mc.calculateResponseTime(), // 需要从应用监控计算
	}, nil
}

// calculateNetworkRate 计算网络传输速率
func (mc *MetricsCollector) calculateNetworkRate() (float64, float64, error) {
	netStats, err := net.IOCounters(false)
	if err != nil {
		return 0, 0, err
	}
	
	if len(netStats) == 0 {
		return 0, 0, fmt.Errorf("未找到网络接口")
	}
	
	currentStats := netStats[0]
	
	// 获取上次的统计数据
	lastStats, exists := mc.networkStats["total"]
	if !exists {
		mc.networkStats["total"] = currentStats
		return 0, 0, nil
	}
	
	// 计算时间差
	timeDiff := time.Since(lastStats.LastUpdate).Seconds()
	if timeDiff <= 0 {
		return 0, 0, nil
	}
	
	// 计算速率 (字节/秒)
	rxRate := float64(currentStats.BytesRecv-lastStats.BytesRecv) / timeDiff
	txRate := float64(currentStats.BytesSent-lastStats.BytesSent) / timeDiff
	
	// 更新统计数据
	currentStats.LastUpdate = time.Now()
	mc.networkStats["total"] = currentStats
	
	return rxRate, txRate, nil
}

// calculateErrorRate 计算错误率 (模拟实现)
func (mc *MetricsCollector) calculateErrorRate() float64 {
	// 实际实现中应该从应用日志或APM系统获取
	// 这里返回模拟数据
	return 0.01 // 1%错误率
}

// calculateResponseTime 计算平均响应时间 (模拟实现)
func (mc *MetricsCollector) calculateResponseTime() float64 {
	// 实际实现中应该从应用监控系统获取
	// 这里返回模拟数据
	return 150.0 // 150ms
}

// storeMetrics 存储指标到Redis
func (mc *MetricsCollector) storeMetrics(metrics MetricsData) error {
	// 序列化指标数据
	data, err := json.Marshal(metrics)
	if err != nil {
		return err
	}
	
	// 存储到时序数据集合
	key := fmt.Sprintf("metrics:%s", mc.config.NodeID)
	score := float64(metrics.Timestamp.Unix())
	
	// 使用有序集合存储时序数据
	if err := mc.redisClient.ZAdd(mc.ctx, key, &redis.Z{
		Score:  score,
		Member: string(data),
	}).Err(); err != nil {
		return err
	}
	
	// 存储最新指标
	latestKey := fmt.Sprintf("metrics:latest:%s", mc.config.NodeID)
	if err := mc.redisClient.Set(mc.ctx, latestKey, string(data), time.Hour).Err(); err != nil {
		return err
	}
	
	return nil
}

// detectAnomalies 检测异常
func (mc *MetricsCollector) detectAnomalies(metrics MetricsData) {
	thresholds := mc.config.AlertThresholds
	
	// CPU异常检测
	if metrics.CPUUsage >= thresholds.CPUCritical {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("cpu-critical-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     CRITICAL,
			Type:      CPU_HIGH,
			Message:   fmt.Sprintf("CPU使用率严重过高: %.2f%%", metrics.CPUUsage),
			Metrics:   metrics,
		})
	} else if metrics.CPUUsage >= thresholds.CPUWarning {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("cpu-warning-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     WARNING,
			Type:      CPU_HIGH,
			Message:   fmt.Sprintf("CPU使用率过高: %.2f%%", metrics.CPUUsage),
			Metrics:   metrics,
		})
	}
	
	// 内存异常检测
	if metrics.MemoryUsage >= thresholds.MemoryCritical {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("memory-critical-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     CRITICAL,
			Type:      MEMORY_HIGH,
			Message:   fmt.Sprintf("内存使用率严重过高: %.2f%%", metrics.MemoryUsage),
			Metrics:   metrics,
		})
	} else if metrics.MemoryUsage >= thresholds.MemoryWarning {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("memory-warning-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     WARNING,
			Type:      MEMORY_HIGH,
			Message:   fmt.Sprintf("内存使用率过高: %.2f%%", metrics.MemoryUsage),
			Metrics:   metrics,
		})
	}
	
	// 磁盘异常检测
	if metrics.DiskUsage >= thresholds.DiskCritical {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("disk-critical-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     CRITICAL,
			Type:      DISK_HIGH,
			Message:   fmt.Sprintf("磁盘使用率严重过高: %.2f%%", metrics.DiskUsage),
			Metrics:   metrics,
		})
	} else if metrics.DiskUsage >= thresholds.DiskWarning {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("disk-warning-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     WARNING,
			Type:      DISK_HIGH,
			Message:   fmt.Sprintf("磁盘使用率过高: %.2f%%", metrics.DiskUsage),
			Metrics:   metrics,
		})
	}
	
	// 系统负载异常检测
	if metrics.LoadAvg1 >= thresholds.LoadCritical {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("load-critical-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     CRITICAL,
			Type:      LOAD_HIGH,
			Message:   fmt.Sprintf("系统负载严重过高: %.2f", metrics.LoadAvg1),
			Metrics:   metrics,
		})
	} else if metrics.LoadAvg1 >= thresholds.LoadWarning {
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("load-warning-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    metrics.NodeID,
			Level:     WARNING,
			Type:      LOAD_HIGH,
			Message:   fmt.Sprintf("系统负载过高: %.2f", metrics.LoadAvg1),
			Metrics:   metrics,
		})
	}
	
	// 高级异常检测
	mc.advancedAnomalyDetection(metrics)
}

// advancedAnomalyDetection 高级异常检测
func (mc *MetricsCollector) advancedAnomalyDetection(current MetricsData) {
	mc.mutex.RLock()
	last := mc.lastMetrics
	mc.mutex.RUnlock()
	
	if last.Timestamp.IsZero() {
		return
	}
	
	// 检测资源使用率突增
	cpuChange := math.Abs(current.CPUUsage - last.CPUUsage)
	memoryChange := math.Abs(current.MemoryUsage - last.MemoryUsage)
	
	if cpuChange > 30 { // CPU使用率突增30%
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("cpu-spike-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    current.NodeID,
			Level:     WARNING,
			Type:      CPU_HIGH,
			Message:   fmt.Sprintf("CPU使用率突增: %.2f%% -> %.2f%%", last.CPUUsage, current.CPUUsage),
			Metrics:   current,
			Metadata: map[string]interface{}{
				"change_rate": cpuChange,
				"trend": "spike",
			},
		})
	}
	
	if memoryChange > 20 { // 内存使用率突增20%
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("memory-spike-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    current.NodeID,
			Level:     WARNING,
			Type:      MEMORY_HIGH,
			Message:   fmt.Sprintf("内存使用率突增: %.2f%% -> %.2f%%", last.MemoryUsage, current.MemoryUsage),
			Metrics:   current,
			Metadata: map[string]interface{}{
				"change_rate": memoryChange,
				"trend": "spike",
			},
		})
	}
	
	// 检测进程数异常
	processChange := math.Abs(float64(current.ProcessCount - last.ProcessCount))
	if processChange > 100 { // 进程数变化超过100
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("process-anomaly-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    current.NodeID,
			Level:     INFO,
			Type:      PROCESS_ANOMALY,
			Message:   fmt.Sprintf("进程数异常变化: %d -> %d", last.ProcessCount, current.ProcessCount),
			Metrics:   current,
			Metadata: map[string]interface{}{
				"change_count": processChange,
			},
		})
	}
}

// sendAlert 发送告警
func (mc *MetricsCollector) sendAlert(alert Alert) {
	select {
	case mc.alertChan <- alert:
		// 告警已发送
	default:
		log.Printf("告警队列已满，丢弃告警: %s", alert.ID)
	}
}

// anomalyDetectionLoop 异常检测循环
func (mc *MetricsCollector) anomalyDetectionLoop() {
	// 实现基于历史数据的异常检测算法
	// 例如：基于统计的异常检测、时序预测等
	
	ticker := time.NewTicker(time.Minute * 5) // 每5分钟执行一次高级检测
	defer ticker.Stop()
	
	for {
		select {
		case <-mc.ctx.Done():
			return
		case <-ticker.C:
			mc.performAdvancedAnalysis()
		}
	}
}

// performAdvancedAnalysis 执行高级分析
func (mc *MetricsCollector) performAdvancedAnalysis() {
	// 获取最近1小时的历史数据
	key := fmt.Sprintf("metrics:%s", mc.config.NodeID)
	now := time.Now()
	start := now.Add(-time.Hour)
	
	results, err := mc.redisClient.ZRangeByScore(mc.ctx, key, &redis.ZRangeBy{
		Min: fmt.Sprintf("%d", start.Unix()),
		Max: fmt.Sprintf("%d", now.Unix()),
	}).Result()
	
	if err != nil {
		log.Printf("获取历史数据失败: %v", err)
		return
	}
	
	if len(results) < 10 { // 至少需要10个数据点
		return
	}
	
	// 解析历史数据
	var metrics []MetricsData
	for _, result := range results {
		var metric MetricsData
		if err := json.Unmarshal([]byte(result), &metric); err == nil {
			metrics = append(metrics, metric)
		}
	}
	
	// 执行趋势分析
	mc.analyzeTrends(metrics)
}

// analyzeTrends 分析趋势
func (mc *MetricsCollector) analyzeTrends(metrics []MetricsData) {
	if len(metrics) < 10 {
		return
	}
	
	// 计算CPU使用率趋势
	cpuTrend := mc.calculateTrend(metrics, func(m MetricsData) float64 { return m.CPUUsage })
	memoryTrend := mc.calculateTrend(metrics, func(m MetricsData) float64 { return m.MemoryUsage })
	diskTrend := mc.calculateTrend(metrics, func(m MetricsData) float64 { return m.DiskUsage })
	
	// 趋势告警
	if cpuTrend > 5 { // CPU使用率持续上升超过5%/小时
		latest := metrics[len(metrics)-1]
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("cpu-trend-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    latest.NodeID,
			Level:     WARNING,
			Type:      CPU_HIGH,
			Message:   fmt.Sprintf("CPU使用率持续上升趋势，斜率: %.2f%%/小时", cpuTrend),
			Metrics:   latest,
			Metadata: map[string]interface{}{
				"trend_slope": cpuTrend,
				"analysis_type": "trend",
			},
		})
	}
	
	if memoryTrend > 3 { // 内存使用率持续上升超过3%/小时
		latest := metrics[len(metrics)-1]
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("memory-trend-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    latest.NodeID,
			Level:     WARNING,
			Type:      MEMORY_HIGH,
			Message:   fmt.Sprintf("内存使用率持续上升趋势，斜率: %.2f%%/小时", memoryTrend),
			Metrics:   latest,
			Metadata: map[string]interface{}{
				"trend_slope": memoryTrend,
				"analysis_type": "trend",
			},
		})
	}
	
	if diskTrend > 1 { // 磁盘使用率持续上升超过1%/小时
		latest := metrics[len(metrics)-1]
		mc.sendAlert(Alert{
			ID:        fmt.Sprintf("disk-trend-%d", time.Now().Unix()),
			Timestamp: time.Now(),
			NodeID:    latest.NodeID,
			Level:     INFO,
			Type:      DISK_HIGH,
			Message:   fmt.Sprintf("磁盘使用率持续上升趋势，斜率: %.2f%%/小时", diskTrend),
			Metrics:   latest,
			Metadata: map[string]interface{}{
				"trend_slope": diskTrend,
				"analysis_type": "trend",
			},
		})
	}
}

// calculateTrend 计算趋势（线性回归斜率）
func (mc *MetricsCollector) calculateTrend(metrics []MetricsData, getValue func(MetricsData) float64) float64 {
	n := len(metrics)
	if n < 2 {
		return 0
	}
	
	var sumX, sumY, sumXY, sumX2 float64
	
	for i, metric := range metrics {
		x := float64(i)
		y := getValue(metric)
		
		sumX += x
		sumY += y
		sumXY += x * y
		sumX2 += x * x
	}
	
	// 计算线性回归斜率
	denominator := float64(n)*sumX2 - sumX*sumX
	if math.Abs(denominator) < 1e-10 {
		return 0
	}
	
	slope := (float64(n)*sumXY - sumX*sumY) / denominator
	
	// 转换为每小时的变化率
	timeRange := metrics[n-1].Timestamp.Sub(metrics[0].Timestamp).Hours()
	if timeRange > 0 {
		slope = slope * float64(n-1) / timeRange
	}
	
	return slope
}

// alertProcessingLoop 告警处理循环
func (mc *MetricsCollector) alertProcessingLoop() {
	for {
		select {
		case <-mc.ctx.Done():
			return
		case alert := <-mc.alertChan:
			mc.processAlert(alert)
		}
	}
}

// processAlert 处理告警
func (mc *MetricsCollector) processAlert(alert Alert) {
	// 序列化告警数据
	data, err := json.Marshal(alert)
	if err != nil {
		log.Printf("序列化告警失败: %v", err)
		return
	}
	
	// 存储告警到Redis
	alertKey := fmt.Sprintf("alerts:%s", alert.NodeID)
	score := float64(alert.Timestamp.Unix())
	
	if err := mc.redisClient.ZAdd(mc.ctx, alertKey, &redis.Z{
		Score:  score,
		Member: string(data),
	}).Err(); err != nil {
		log.Printf("存储告警失败: %v", err)
		return
	}
	
	// 发布告警事件
	channel := fmt.Sprintf("alerts:%s:%s", alert.NodeID, alert.Type)
	if err := mc.redisClient.Publish(mc.ctx, channel, string(data)).Err(); err != nil {
		log.Printf("发布告警事件失败: %v", err)
	}
	
	log.Printf("处理告警: %s - %s", alert.ID, alert.Message)
}

// dataCleanupLoop 数据清理循环
func (mc *MetricsCollector) dataCleanupLoop() {
	ticker := time.NewTicker(time.Hour * 6) // 每6小时执行一次清理
	defer ticker.Stop()
	
	for {
		select {
		case <-mc.ctx.Done():
			return
		case <-ticker.C:
			mc.cleanupOldData()
		}
	}
}

// cleanupOldData 清理过期数据
func (mc *MetricsCollector) cleanupOldData() {
	cutoff := time.Now().AddDate(0, 0, -mc.config.RetentionDays)
	cutoffScore := float64(cutoff.Unix())
	
	// 清理过期指标数据
	metricsKey := fmt.Sprintf("metrics:%s", mc.config.NodeID)
	deleted, err := mc.redisClient.ZRemRangeByScore(mc.ctx, metricsKey, "-inf", fmt.Sprintf("%.0f", cutoffScore)).Result()
	if err != nil {
		log.Printf("清理指标数据失败: %v", err)
	} else if deleted > 0 {
		log.Printf("清理了 %d 条过期指标数据", deleted)
	}
	
	// 清理过期告警数据
	alertKey := fmt.Sprintf("alerts:%s", mc.config.NodeID)
	deleted, err = mc.redisClient.ZRemRangeByScore(mc.ctx, alertKey, "-inf", fmt.Sprintf("%.0f", cutoffScore)).Result()
	if err != nil {
		log.Printf("清理告警数据失败: %v", err)
	} else if deleted > 0 {
		log.Printf("清理了 %d 条过期告警数据", deleted)
	}
}

// GetLatestMetrics 获取最新指标
func (mc *MetricsCollector) GetLatestMetrics() (MetricsData, error) {
	mc.mutex.RLock()
	defer mc.mutex.RUnlock()
	
	return mc.lastMetrics, nil
}

// IsHealthy 检查采集器健康状态
func (mc *MetricsCollector) IsHealthy() bool {
	return mc.running && mc.redisClient.Ping(mc.ctx).Err() == nil
}

// GetNodeStatus 获取节点状态摘要
func (mc *MetricsCollector) GetNodeStatus() map[string]interface{} {
	mc.mutex.RLock()
	metrics := mc.lastMetrics
	mc.mutex.RUnlock()
	
	status := "healthy"
	if metrics.CPUUsage > mc.config.AlertThresholds.CPUWarning ||
		metrics.MemoryUsage > mc.config.AlertThresholds.MemoryWarning ||
		metrics.DiskUsage > mc.config.AlertThresholds.DiskWarning {
		status = "warning"
	}
	
	if metrics.CPUUsage > mc.config.AlertThresholds.CPUCritical ||
		metrics.MemoryUsage > mc.config.AlertThresholds.MemoryCritical ||
		metrics.DiskUsage > mc.config.AlertThresholds.DiskCritical {
		status = "critical"
	}
	
	return map[string]interface{}{
		"node_id":      mc.config.NodeID,
		"status":       status,
		"last_update": metrics.Timestamp,
		"cpu_usage":   metrics.CPUUsage,
		"memory_usage": metrics.MemoryUsage,
		"disk_usage":   metrics.DiskUsage,
		"load_avg":     metrics.LoadAvg1,
		"uptime":       time.Since(metrics.Timestamp).Seconds(),
	}
}