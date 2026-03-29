# 架构设计

## 1. 项目定位

`image-factory` 不是本地生图程序，而是一个面向外部生图 API 的批量任务调度器。

核心思路只有一句话：

`任务总量不设上限，执行流速严格受控`

也就是：

- 可以一次性导入大量任务
- 不直接限制批次数量
- 限制的是对外 API 的发送速率、轮询速率和下载速率

## 2. 核心目标

第一版优先解决这几个问题：

- 批量导入任务
- 将任务拆成独立状态机
- 对外 API 调用限流
- 支持异步轮询
- 支持失败重试
- 可以查看批次进度
- 进程重启后尽量可恢复

## 3. 处理模型

系统内部把每一张图都视为一个独立任务。

一个批次只是任务集合，不是执行单元。真正被调度和重试的是任务。

这样做的原因：

- 批次里不同任务可能耗时不同
- 不同任务失败原因不同
- 部分任务失败不该阻塞整个批次
- 进度统计天然按任务数汇总

## 4. 状态机

当前状态机如下：

1. `pending`
2. `ready`
3. `submitting`
4. `polling`
5. `downloading`
6. `retry_waiting`
7. `succeeded`
8. `failed`
9. `dead_letter`
10. `cancelled`

状态流转说明：

- `pending -> ready`
  新任务入库后，由调度器提升为可发送状态

- `ready -> submitting -> polling`
  调用外部 API 成功，拿到远端任务 ID

- `polling -> downloading`
  远端已完成，可以下载结果

- `downloading -> succeeded`
  图片落盘成功，任务完成

- `submitting / polling / downloading -> retry_waiting`
  遇到临时错误，例如 `429`、`5xx`、超时

- `retry_waiting -> ready`
  到达重试时间后重新进入待发送

- 任意阶段 -> `failed`
  遇到不可恢复错误

- 任意阶段 -> `dead_letter`
  达到最大重试次数后进入死信

## 5. 多队列设计

虽然当前实现使用的是一张 `tasks` 表，但逻辑上已经拆成多个队列：

- submit queue
  `status = ready`

- poll queue
  `status = polling and next_poll_at <= now`

- download queue
  `status = downloading`

- retry queue
  `status = retry_waiting and next_retry_at <= now`

- dead-letter queue
  `status = dead_letter`

这样拆的原因是不同阶段瓶颈完全不同：

- 提交通常受 provider 请求额度限制
- 轮询通常调用更频繁，最容易打爆限额
- 下载受带宽和对象大小影响

如果只用一个总队列，后面很难精细调度。

## 6. 当前模块划分

### `storage`

负责：

- 初始化 SQLite schema
- 创建 batch 和 tasks
- 读取和更新任务状态
- 统计批次聚合信息
- 提供到期任务查询

对应实现见 [storage.py](../src/image_factory/storage.py)。

### `scheduler`

负责：

- 提升 `pending` 和到期重试任务
- 从不同逻辑队列取任务
- 按限流规则处理 submit / poll / download
- 把 provider 的返回写回存储层

对应实现见 [scheduler.py](../src/image_factory/scheduler.py)。

### `rate_limiter`

当前使用进程内 token bucket 控制三类操作速率：

- submit RPM
- poll RPM
- download RPM

对应实现见 [rate_limiter.py](../src/image_factory/rate_limiter.py)。

### `providers`

对外 API 适配层。

当前已有：

- 抽象接口 [base.py](../src/image_factory/providers/base.py)
- 测试用 provider [mock.py](../src/image_factory/providers/mock.py)

### `progress`

负责批次级统计：

- total
- done
- active
- progress percent
- ETA

对应实现见 [progress.py](../src/image_factory/progress.py)。

### `cli`

负责命令行入口，当前支持：

- 创建批次
- 运行 worker
- 列出批次
- 查看批次状态
- 查看任务详情

对应实现见 [cli.py](../src/image_factory/cli.py)。

## 7. 持久化设计

当前使用 SQLite，两张主表：

### `batches`

字段重点：

- `id`
- `name`
- `provider`
- `source_path`
- `total_tasks`
- `created_at`
- `updated_at`

### `tasks`

字段重点：

- `batch_id`
- `input_index`
- `prompt`
- `params_json`
- `provider`
- `status`
- `attempt`
- `remote_task_id`
- `remote_metadata_json`
- `result_path`
- `error_code`
- `error_message`
- `next_poll_at`
- `next_retry_at`
- `completed_at`

这已经足够支持：

- 批量导入
- 状态流转
- 到期轮询
- 到期重试
- 基础断点恢复

## 8. 限流策略

你一开始提出的关键要求是：

`不要直接限制任务数量`

当前方案就是按这个要求设计的。

系统允许无限提交任务，但执行时控制：

- `submit_rpm`
- `poll_rpm`
- `download_rpm`

这比“最多只允许 1000 条任务”更合理，因为真正风险来自：

- provider 限额
- 轮询风暴
- 下载拥塞

后续建议扩展成三层限流：

1. 全局级
2. provider 级
3. API key 级

## 9. 重试策略

当前实现已经支持：

- 最大重试次数
- 固定延迟序列
- 超出次数后进入 `dead_letter`

当前默认重试延迟可配置，例如：

```text
15,30,60,180
```

后续建议把错误再细分成：

- `retryable`
  `429`、超时、`5xx`

- `fatal`
  参数错误、鉴权失败、审核拒绝

## 10. 进度模型

当前批次进度由任务聚合计算得出。

输出包括：

- `total`
- `done`
- `active`
- `progress_percent`
- `eta_seconds`
- 各状态计数

这满足“知道进度就行”的要求，不依赖 UI。

## 11. 当前边界

第一版故意没有做下面这些能力：

- 分布式 worker
- Redis 队列或租约
- webhook 回调
- 多 key 调度
- 配额成本核算
- 取消任务
- 结果导出

这不是缺漏，而是阶段性取舍。当前优先级是先把：

`导入 -> 提交 -> 轮询 -> 下载 -> 重试 -> 进度`

整条链路打稳。

## 12. 下一步建议

最优先的后续工作：

1. 接入真实 provider
2. 增加 provider/key 配置层
3. 按错误类型做更细的重试决策
4. 增加运行日志和指标
5. 增加导出成功/失败清单
