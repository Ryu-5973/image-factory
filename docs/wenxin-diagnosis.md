# Wenxin 图片接口诊断

如果文心图片生成始终返回限流或权限错误，可以先用本仓库的诊断脚本直接打接口。

脚本位置：

- [diagnose_wenxin_image.py](../scripts/diagnose_wenxin_image.py)

## 用法

PowerShell:

```powershell
$env:QIANFAN_API_KEY = "你的API Key"
python .\scripts\diagnose_wenxin_image.py
```

自定义参数：

```powershell
python .\scripts\diagnose_wenxin_image.py `
  --model qwen-image `
  --prompt "画一只小狗" `
  --size 512x512 `
  --n 1
```

## 输出内容

脚本会打印：

- 请求地址
- 请求模型
- 请求体
- HTTP 状态码
- 全部响应头
- 完整响应体

## 适用场景

适合排查：

- `401 invalid_model`
- `429 rpm_rate_limit_exceeded`
- 权限未开通
- 账号级额度或风控问题

## 建议

如果你要找百度支持或提工单，最好附上：

- 脚本输出的 HTTP 状态码
- 完整响应体
- 响应头里的请求 ID
- 你使用的 endpoint 和 model
