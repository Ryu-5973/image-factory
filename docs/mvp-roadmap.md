# MVP 路线图

## Phase 1 已完成

当前仓库已经完成第一阶段骨架：

- Python 包结构
- CLI 入口
- SQLite 持久化
- 批次与任务状态机
- submit / poll / download 三段式调度
- token bucket 限流
- retry / dead letter
- 本地文件落盘
- mock provider 联调
- 基础测试

## Phase 2 真实 API 接入

这一阶段的目标是把 mock provider 替换成真实生图平台。

建议内容：

- 接入一个真实 provider
- 增加 API key 配置
- 支持 provider 特定请求参数
- 正确分类 `429 / 5xx / timeout / invalid request / moderation reject`
- 增加运行日志
- 增加成功和失败任务导出

验收标准：

- 批量任务可稳定跑通
- 有限流时不会打爆 provider
- worker 重启后能继续推进
- 成功图像和数据库状态一致

## Phase 3 调度增强

这一阶段开始从“能跑”升级到“更稳”：

- 多 provider 支持
- 多 key 轮询调度
- provider 级和 key 级限流
- 熔断与恢复
- 更准确 ETA
- 更完整指标统计

## Phase 4 规模化

当任务量和运行时长继续扩大，再做这些：

- PostgreSQL
- Redis 或其他外部队列
- 分布式 worker
- task leasing / heartbeat
- webhook 回调
- 对象存储
- 成本报表

## Phase 5 可操作性增强

如果后面要让运营或业务同学直接用，再考虑：

- HTTP API
- Web 管理台
- 批次筛选和检索
- 图片预览
- 导出和打包下载
- 人工复跑和失败回放
