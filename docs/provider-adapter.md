# Provider 接入说明

这份文档说明如何把真实生图 API 接到 `image-factory`。

## 目标

系统内部只关心三件事：

1. 提交任务
2. 查询远端任务状态
3. 拉取最终图片

任何外部生图平台，只要能被适配成这三个动作，就可以挂到当前调度器上。

## 当前接口

所有 provider 都需要实现 [base.py](../src/image_factory/providers/base.py) 中的接口：

- `submit(task) -> SubmissionResult`
- `poll(task) -> PollResult`
- `fetch_result(task) -> FetchResult`

当前调度器调用顺序：

1. worker 从 `ready` 队列取任务
2. 调用 `submit`
3. 保存 `remote_task_id` 和 `remote_metadata`
4. 到时调用 `poll`
5. 远端完成后进入 `downloading`
6. 调用 `fetch_result`
7. 图片写盘，任务标记为 `succeeded`

## 返回对象说明

### `SubmissionResult`

- `remote_task_id`
  远端任务唯一标识
- `remote_metadata`
  后续轮询和下载所需的补充信息
- `poll_after_seconds`
  建议下次轮询时间

### `PollResult`

- `state`
  `running / succeeded / failed`
- `remote_metadata`
  远端状态更新后的元数据
- `poll_after_seconds`
  如果仍在运行，下一次轮询间隔
- `error_code`
- `error_message`

### `FetchResult`

- `content`
  图片二进制内容
- `file_extension`
  保存扩展名
- `metadata`
  图片补充元数据

## 错误分类

建议所有真实 provider 都按两类错误抛出：

- `ProviderRetryableError`
- `ProviderFatalError`

### 应判定为可重试

- `429`
- `5xx`
- 网关错误
- 网络超时
- 结果下载超时
- 短时风控或瞬时额度波动

### 应判定为不可重试

- prompt 参数非法
- 鉴权失败
- 模型不存在
- 配额彻底耗尽且短时间无法恢复
- 内容审核拒绝

## 建议目录

如果你要接真实平台，建议按这种方式落文件：

```text
src/image_factory/providers/
|-- base.py
|-- mock.py
`-- your_provider.py
```

然后在 [__init__.py](../src/image_factory/providers/__init__.py) 里注册：

```python
from image_factory.providers.your_provider import YourProvider

def build_provider(name: str) -> ImageProvider:
    if name == "mock":
        return MockImageProvider()
    if name == "your-provider":
        return YourProvider()
    raise ValueError(f"Unknown provider: {name}")
```

## 真实 API 适配建议

### 同步接口

如果接口一次调用直接返回图片：

- `submit` 可以直接把任务标成可下载，或者把结果元数据写入 `remote_metadata`
- `poll` 可以实现为立即成功，或者在 `submit` 阶段直接切到 `downloading`

更推荐仍然保留三段式抽象，不要把 provider 特例写进调度器。

### 异步接口

如果接口返回远端任务 ID：

- `submit` 返回 `remote_task_id`
- `poll` 负责查状态
- `fetch_result` 负责下载图像

这是当前骨架的默认形态。

## 限流建议

当前代码已经拆开了三类节流：

- submit RPM
- poll RPM
- download RPM

接真实平台时，建议进一步扩展成：

- provider 级限流
- API key 级限流
- 不同接口独立配额

例如：

```text
provider=openai-images
submit_rpm=60
poll_rpm=180
download_rpm=120
key_1_submit_rpm=20
key_2_submit_rpm=20
key_3_submit_rpm=20
```

## 幂等与去重

真实平台接入时，建议增加：

- 本地 `task_hash`
- 远端请求幂等键
- `remote_task_id` 唯一索引

避免因为进程重启、网络抖动或重试导致重复出图。

## 建议补充的字段

真实 provider 接入时，通常还要在任务表里补：

- `provider_key_id`
- `model`
- `request_payload_json`
- `response_payload_json`
- `cost`
- `finished_at_remote`

第一版骨架没有强加这些字段，是为了先把主链路跑通。

## 验收标准

真实 provider 接入完成后，至少要验证：

1. 单任务成功生成
2. 批量任务能稳定推进
3. `429` 会进入退避重试
4. 不可恢复错误不会无限重试
5. worker 重启后能继续轮询和下载
6. 最终图片文件和数据库状态一致
