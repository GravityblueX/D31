package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gravityblue/ops-sentinel/core/collector"
	"github.com/gravityblue/ops-sentinel/core/detector"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/sirupsen/logrus"
)

var (
	configFile = flag.String("config", "/app/configs/agent.yaml", "配置文件路径")
	logLevel   = flag.String("log-level", "info", "日志级别")
	version    = flag.Bool("version", false, "显示版本信息")
)

const (
	Version = "1.0.0"
	Build   = "20231201"
)

func main() {
	flag.Parse()

	if *version {
		fmt.Printf("OpsSentinel Agent\nVersion: %s\nBuild: %s\n", Version, Build)
		os.Exit(0)
	}

	// 设置日志
	setupLogging(*logLevel)

	logrus.WithFields(logrus.Fields{
		"version": Version,
		"build":   Build,
	}).Info("启动 OpsSentinel Agent")

	// 加载配置
	config, err := loadConfig(*configFile)
	if err != nil {
		logrus.WithError(err).Fatal("加载配置失败")
	}

	// 创建上下文
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// 创建指标收集器
	metricsCollector, err := detector.NewMetricsCollector(config)
	if err != nil {
		logrus.WithError(err).Fatal("创建指标收集器失败")
	}

	// 创建数据收集器
	dataCollector, err := collector.NewDataCollector(config)
	if err != nil {
		logrus.WithError(err).Fatal("创建数据收集器失败")
	}

	// 启动指标收集
	go func() {
		if err := metricsCollector.Start(ctx); err != nil {
			logrus.WithError(err).Error("指标收集器启动失败")
		}
	}()

	// 启动数据收集
	go func() {
		if err := dataCollector.Start(ctx); err != nil {
			logrus.WithError(err).Error("数据收集器启动失败")
		}
	}()

	// 启动Prometheus指标服务器
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", healthCheck)
	mux.HandleFunc("/ready", readinessCheck)

	server := &http.Server{
		Addr:    ":9100",
		Handler: mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// 启动HTTP服务器
	go func() {
		logrus.Info("启动HTTP服务器在端口 :9100")
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logrus.WithError(err).Fatal("HTTP服务器启动失败")
		}
	}()

	// 等待中断信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	logrus.Info("收到关闭信号，开始优雅关闭...")

	// 优雅关闭
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	// 关闭HTTP服务器
	if err := server.Shutdown(shutdownCtx); err != nil {
		logrus.WithError(err).Error("HTTP服务器关闭失败")
	}

	// 取消上下文，停止所有收集器
	cancel()

	// 等待收集器停止
	time.Sleep(2 * time.Second)

	logrus.Info("OpsSentinel Agent 已关闭")
}

func setupLogging(level string) {
	logrus.SetFormatter(&logrus.JSONFormatter{
		TimestampFormat: time.RFC3339,
	})

	switch level {
	case "debug":
		logrus.SetLevel(logrus.DebugLevel)
	case "info":
		logrus.SetLevel(logrus.InfoLevel)
	case "warn":
		logrus.SetLevel(logrus.WarnLevel)
	case "error":
		logrus.SetLevel(logrus.ErrorLevel)
	default:
		logrus.SetLevel(logrus.InfoLevel)
	}

	// 输出到标准输出
	logrus.SetOutput(os.Stdout)
}

func loadConfig(configFile string) (*detector.Config, error) {
	// 默认配置
	config := &detector.Config{
		Redis: detector.RedisConfig{
			Host:     getEnv("REDIS_HOST", "localhost"),
			Port:     getEnv("REDIS_PORT", "6379"),
			DB:       0,
			Password: getEnv("REDIS_PASSWORD", ""),
			Timeout:  30 * time.Second,
		},
		InfluxDB: detector.InfluxDBConfig{
			Host:     getEnv("INFLUXDB_HOST", "localhost"),
			Port:     getEnv("INFLUXDB_PORT", "8086"),
			Database: getEnv("INFLUXDB_DATABASE", "ops_sentinel"),
			Username: getEnv("INFLUXDB_USERNAME", "admin"),
			Password: getEnv("INFLUXDB_PASSWORD", "password"),
			Timeout:  30 * time.Second,
		},
		Collector: detector.CollectorConfig{
			Interval:    parseDuration(getEnv("COLLECT_INTERVAL", "30s")),
			EnableCPU:   true,
			EnableMem:   true,
			EnableDisk:  true,
			EnableNet:   true,
			EnableProc:  true,
		},
		NodeName: getEnv("NODE_NAME", "unknown"),
	}

	// 如果配置文件存在，尝试加载
	if _, err := os.Stat(configFile); err == nil {
		logrus.WithField("config_file", configFile).Info("加载配置文件")
		// 这里可以添加YAML配置文件加载逻辑
	}

	return config, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func parseDuration(s string) time.Duration {
	d, err := time.ParseDuration(s)
	if err != nil {
		logrus.WithError(err).WithField("duration", s).Warn("解析持续时间失败，使用默认值30s")
		return 30 * time.Second
	}
	return d
}

func healthCheck(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"healthy","timestamp":"` + time.Now().Format(time.RFC3339) + `"}`))
}

func readinessCheck(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ready","timestamp":"` + time.Now().Format(time.RFC3339) + `"}`))
}