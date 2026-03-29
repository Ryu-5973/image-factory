# Wenxin API 接入

这份文档说明如何把 `image-factory` 切到百度智能云千帆的文心图片生成 API。

## 当前实现

当前 provider 文件：

- [wenxin.py](../src/image_factory/providers/wenxin.py)

使用方式：

1. 创建 `provider=wenxin` 的批次
2. 设置 `QIANFAN_API_KEY`
3. 启动 `run-worker --provider wenxin`

## 环境变量

至少需要：

```powershell
$env:QIANFAN_API_KEY = "your_api_key"
```

可选项：

```powershell
$env:QIANFAN_IMAGE_MODEL = "v3-base"
$env:QIANFAN_IMAGE_TYPE = "generations"
$env:QIANFAN_IMAGE_ENDPOINT = "https://qianfan.baidubce.com/beta/image/qianfan-image-v1"
$env:QIANFAN_IMAGE_POLL_AFTER_SECONDS = "3"
$env:QIANFAN_IMAGE_RESOLUTION = "1k"
$env:QIANFAN_IMAGE_N = "1"
```

## 批次输入

每个任务至少要有：

- `prompt`

推荐参数：

- `negative_prompt`
- `width`
- `height`

示例：

```json
{"prompt":"Q版水墨国风手游角色立绘，林冲，完整全身站姿，不要文字","negative_prompt":"低清晰度, 模糊, 水印, logo污染","width":512,"height":512}
{"prompt":"国风手游主界面概念图，竖屏布局，水墨淡彩，不要文字","negative_prompt":"低清晰度, 模糊, 乱码","width":750,"height":1334}
```

## 运行

```powershell
python -m image_factory create-batch --db data/image_factory.db --input jobs.jsonl --provider wenxin
python -m image_factory run-worker --db data/image_factory.db --provider wenxin --submit-rpm 30 --poll-rpm 120 --download-rpm 60
```

## 参数映射

当前 provider 会把内部任务映射到文心接口：

- `prompt` -> `model_parameters.prompt`
- `negative_prompt` -> `model_parameters.negative_prompt`
- `width/height` -> 自动推断最接近的 `aspect_ratio`
- `resolution` -> `model_parameters.resolution`
- `n` -> `model_parameters.n`
- `image` / `reference_image` -> `model_parameters.image`

如果你直接传了 `aspect_ratio`，会优先使用，不再从尺寸推断。

## 当前边界

- 当前任务表只支持单条 `result_path`，所以 `n > 1` 时虽然会保留全部 URL 到元数据，但默认只下载第一张图
- 轮询响应的图片 URL 提取做了兼容式解析，优先适配官方常见字段
- 如果后面你要稳定支持多图结果，应该把一条业务需求拆成多条任务

## 官方文档

当前实现基于百度智能云官方文档：

- 图片生成接口：
  https://cloud.baidu.com/doc/qianfan-api/s/jmmot21am
- 认证鉴权：
  https://cloud.baidu.com/doc/qianfan-api/s/ym9chdsy5

我这里采用的是官方文档里的 `Authorization: Bearer <API Key>` 方式。
