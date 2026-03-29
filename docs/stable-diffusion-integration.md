# Stable Diffusion 本地接入

这份文档说明如何把本机上的 `E:\workspace\StableDiffusion` 接到 `image-factory`。

## 接入方式

这里采用的是“批次交接”而不是“单任务 provider”。

原因：

- 你的 `StableDiffusion` 项目本质上是一个本地批处理器
- 它会自动按尺寸、步数等参数合批执行
- 如果按单任务逐个调用，会丢掉它现有的合批收益

所以当前方案是：

1. `image-factory` 负责维护批次和任务状态
2. `image-factory` 导出一批任务到 CSV
3. 调用 `StableDiffusion` 的 `sd_batch`
4. 解析它生成的 `manifest.jsonl / failures.jsonl`
5. 回写数据库和结果路径

## 适用前提

当前默认假设：

- `StableDiffusion` 根目录为 `E:\workspace\StableDiffusion`
- Python 环境为 `E:\workspace\StableDiffusion\.venv\Scripts\python.exe`
- 任务的 `provider` 为 `sd-local`

## 输入任务格式

`image-factory` 的任务会被导出成 `sd_batch` 可识别的 CSV 列：

- `job_id`
- `prompt`
- `negative_prompt`
- `width`
- `height`
- `steps`
- `guidance_scale`
- `num_images`
- `seed`
- `filename`

其中：

- `prompt` 直接来自任务主字段
- 其他字段来自任务 `params`

也就是说，你在 `create-batch` 的输入里可以这样写：

```json
{"prompt":"Commercial studio photo of a silver watch","width":1024,"height":1024,"steps":30,"guidance_scale":6.5,"seed":101}
{"prompt":"Commercial studio photo of a leather bag","width":1024,"height":1024,"steps":30,"guidance_scale":6.5,"seed":102}
```

创建批次时记得指定：

```powershell
python -m image_factory create-batch --input assets/examples/sd_jobs.jsonl --provider sd-local
```

## 执行命令

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

如果不传 `--python-exe`，会默认尝试：

```text
E:\workspace\StableDiffusion\.venv\Scripts\python.exe
```

## 可选覆盖参数

可以在 `run-sd-local` 时额外覆盖 `sd_batch` 的配置，例如：

- `--model`
- `--batch-size`
- `--sd-max-retries`
- `--device`
- `--dtype`
- `--variant`
- `--default-negative-prompt`
- `--default-width`
- `--default-height`
- `--default-steps`
- `--default-guidance-scale`
- `--default-num-images`
- `--prompt-template`
- `--attention-slicing`
- `--vae-tiling`
- `--cpu-offload`
- `--local-files-only`
- `--enable-xformers`

## 输出位置

每次运行会在 `image-factory` 的输出目录下创建一个独立 run 目录：

```text
outputs/<batch-id>/stable_diffusion/<run-id>/
```

里面会包含：

- `input.csv`
- `images/`
- `manifest.jsonl`
- `failures.jsonl`

任务成功后，`result_path` 会指向这个 run 目录下的图片文件。

## 状态回写规则

- manifest 中出现的任务：标记为 `succeeded`
- failures 中出现的任务：标记为 `failed`
- 本次被 claim 但没有结果记录的任务：
  - 未达到重试上限：标记为 `retry_waiting`
  - 达到重试上限：标记为 `dead_letter`

## 当前限制

这版接入有几个明确边界：

- 一次命令只跑一个 `batch_id`
- 这是同步批处理，不是异步轮询
- 最适合 `num_images = 1`
- `num_images > 1` 时，当前任务表只能保存单条 `result_path`

如果后面你要稳定支持多图变体，建议把一条业务记录预拆成多条任务，而不是让单个任务生成多张图。
