# image-factory

`image-factory` 是一个面向外部生图 API 的无界面批量调度工具。

当前版本的目标不是做 UI，而是先把下面这条链路做稳：

- 大批量任务导入
- 多阶段队列流转
- API 侧限流与节流
- 异步轮询和结果回收
- 自动重试与死信处理
- 批次进度追踪
- 本地结果落盘

## 当前能力

当前仓库已经包含第一版可运行骨架：

- `CLI` 入口
- `SQLite` 持久化
- 批次与任务模型
- `submit / poll / download` 三段式调度
- token bucket 限流器
- retry / dead letter 状态流转
- `mock provider` 端到端联调能力
- `sd-local` 本地 Stable Diffusion 批次执行器接入

## 适用场景

适合这类任务：

- 一次导入几千到几十万条 prompt
- 调用外部图片生成 API，而不是本地推理
- API 有 RPM、并发、额度或轮询限制
- 需要随时查看批次进度
- 需要失败重试和断点续跑

## 目录结构

```text
.
|-- assets/examples/         # 示例输入
|-- docs/                    # 架构和接入文档
|-- src/image_factory/
|   |-- cli.py               # CLI 入口
|   |-- config.py            # 运行时配置
|   |-- input_loader.py      # JSONL / CSV / TXT 输入解析
|   |-- models.py            # 批次、任务、provider 数据模型
|   |-- progress.py          # 批次进度统计
|   |-- rate_limiter.py      # token bucket 限流器
|   |-- scheduler.py         # 调度器
|   |-- storage.py           # SQLite 持久化
|   `-- providers/
|       |-- base.py          # provider 接口约束
|       `-- mock.py          # 本地 mock provider
`-- tests/                   # 存储与调度基础测试
```

## 快速开始

1. 初始化环境：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

2. 创建批次：

```powershell
python -m image_factory create-batch --input assets/examples/prompts.jsonl --provider mock
```

3. 启动 worker：

```powershell
python -m image_factory run-worker --provider mock
```

4. 查看批次：

```powershell
python -m image_factory list-batches
python -m image_factory status --batch-id <batch-id>
python -m image_factory list-tasks --batch-id <batch-id> --limit 20
```

生成产物会落到 `outputs/<batch-id>/`。

## 输入格式

当前支持：

- `jsonl`
- `csv`
- `txt`

### JSONL

```json
{"prompt":"A cinematic portrait of a red panda barista","seed":101}
{"prompt":"A minimal product render of wireless headphones on marble","seed":102,"ready_after_seconds":0.1}
```

### CSV

至少包含 `prompt` 列，其他列会作为参数透传给 provider。

```csv
prompt,seed,style
"A futuristic sneaker ad",201,"studio"
"A tea package mockup",202,"minimal"
```

### TXT

每行一个 prompt。

## 当前 CLI

### `create-batch`

从本地输入文件创建批次并写入数据库。

```powershell
python -m image_factory create-batch --input assets/examples/prompts.jsonl --provider mock --db data/image_factory.db
```

### `run-worker`

启动本地 worker，负责：

- 提升 `pending` 和到期 `retry_waiting` 任务
- 提交到外部 API
- 轮询异步状态
- 下载图片
- 标记成功、失败、重试或死信

```powershell
python -m image_factory run-worker --provider mock --submit-rpm 60 --poll-rpm 240 --download-rpm 120
```

### `run-sd-local`

把一个 `provider=sd-local` 的批次交给本地 `StableDiffusion` 项目执行。

这条命令不会改 `StableDiffusion` 项目本身，而是会：

1. 从数据库里取出一批 `ready` 任务
2. 导出成 `sd_batch` 可读取的 `CSV`
3. 调用 `StableDiffusion` 项目的 Python 入口
4. 解析 `manifest.jsonl` 和 `failures.jsonl`
5. 回写任务状态和结果路径

示例：

```powershell
python -m image_factory run-sd-local `
  --db data/image_factory.db `
  --batch-id <batch-id> `
  --stable-diffusion-root E:\workspace\StableDiffusion `
  --sd-config E:\workspace\StableDiffusion\configs\default.json `
  --output-dir outputs `
  --max-tasks-per-run 100
```

如果不传 `--python-exe`，默认会优先使用：

```text
E:\workspace\StableDiffusion\.venv\Scripts\python.exe
```

当前这条接入路径适合本地 GPU 批量出图，不走 HTTP，也不走当前通用 provider 的 `submit/poll/fetch` 三段式接口。

### `list-batches`

查看批次列表和整体完成进度。

### `status`

查看单个批次的聚合状态。

示例输出：

```text
batch_id=batch_xxx
provider=mock
total=50000
done=18320
active=31680
progress=36.64%
eta_seconds=8040
polling=4200
retry_waiting=91
succeeded=18020
failed=9
```

### `list-tasks`

查看批次内的任务明细。

## 任务状态

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

含义说明：

- `pending`：刚入库，尚未进入待发送队列
- `ready`：可以提交给外部 API
- `submitting`：正在调用提交接口
- `polling`：已拿到远端任务 ID，等待轮询
- `downloading`：远端已完成，等待拉取图片
- `retry_waiting`：临时失败，等待退避后重试
- `failed`：不可恢复失败
- `dead_letter`：达到重试上限后进入死信

对于 `sd-local`：

- 执行时任务会先进入 `submitting`
- 子进程跑完后会被回写为 `succeeded / failed / retry_waiting / dead_letter`
- 这个接入方式是“整批交接”，不是逐任务远端轮询

## 当前限制

这是第一版骨架，当前仍然是：

- 单进程 worker
- 单 provider 实例
- 本地 SQLite
- 本地文件存储
- 无 webhook
- 无分布式租约
- 无多 key 负载均衡
- `sd-local` 当前按“一次运行一个本地批次”接入
- `sd-local` 最适合 `num_images=1`；多图变体目前只会保留单条结果路径

## 文档

- [架构设计](docs/architecture.md)
- [Provider 接入说明](docs/provider-adapter.md)
- [Stable Diffusion 本地接入](docs/stable-diffusion-integration.md)
- [MVP 路线图](docs/mvp-roadmap.md)
