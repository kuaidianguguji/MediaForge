# 模型与存储接口配置

核对日期：2026-09-24。代码只实现调用协议，不内置 API Key，也没有执行任何真实计费生成。管理员必须在服务商开通对应模型，保存密钥后才能生成；第三方中转站的模型 ID、额度、文件限制和兼容程度需要按其实际服务核实。

## 能力与协议

| 用途 | 协议 | Base URL 示例 | 本项目调用路径 |
| --- | --- | --- | --- |
| 图片/抽帧视觉分析 | OpenAI 兼容 | `https://api.openai.com/v1` | `POST /chat/completions` |
| 图片/抽帧视觉分析 | Anthropic | `https://api.anthropic.com/v1` | `POST /messages` |
| 火山视觉分析 | 火山引擎 | `https://ark.cn-beijing.volces.com/api/v3` | `POST /chat/completions` |
| 商品图优化 | OpenAI 兼容图像编辑 | 服务商实际 `/v1` 地址 | `POST /images/edits`，multipart 图片文件 |
| 商品图优化 | 火山引擎 Seedream | 火山 `/api/v3` 地址 | `POST /images/generations`，`image` Data URI |
| 原视频语音转写 | OpenAI 兼容转写 | 服务商实际 `/v1` 地址 | `POST /audio/transcriptions`，multipart 音频文件 |
| Seedance 视频 | 火山引擎原生 | 火山 `/api/v3` 或兼容代理地址 | `POST /contents/generations/tasks`、`GET /contents/generations/tasks/{id}` |

Base URL 需要包含版本路径，不能直接填写某个完整接口路径。允许管理员配置内网 HTTP/HTTPS 代理；接口不跟随重定向，以免转发凭据。公网服务应使用 HTTPS。

“OpenAI 兼容”通常只代表部分接口格式兼容，不能推导出支持图像编辑、语音转写或 Seedance。Seedance 中转站必须选择“火山引擎”协议，且真实支持上述异步任务 API。Anthropic Messages 适合视觉分析，不提供本项目所需的图片编辑或音频转写接口。

视觉分析通过提示词要求 JSON，并验证返回结果；未使用所有中转站都未必支持的 `response_format` 扩展。图片是 JPEG Base64。商品图编辑会校验返回图像，再将内容作为文件资产保存。OpenAI 图片编辑同时兼容返回 `b64_json` 或公网 HTTPS `url`，不强行给 GPT Image 模型传入不适用的 `response_format` 参数。[OpenAI 视觉输入](https://developers.openai.com/api/docs/guides/images-vision)、[图片编辑](https://developers.openai.com/api/reference/resources/images/methods/edit)、[语音转写](https://developers.openai.com/api/docs/guides/speech-to-text)、[Anthropic 视觉输入](https://platform.claude.com/docs/en/build-with-claude/vision)。

本项目的关键画面策略要求图片模型支持**同时参考多张图片进行编辑**：输入关联产品图与原片关键画面，先替换可见产品，再由视觉模型核对。OpenAI 兼容适配器使用多图 multipart，火山适配器使用 `image` 数组。仅支持单图编辑的中转站不适合该策略；请选择直接生成或调整动作与构图。关键画面核对未通过、图片接口失败或提交状态不确定时，不自动重复修图。

产品档案分析、优化图核对、关键画面核对、每段视频生成后的产品一致性检查与用户主动复查，均调用项目选择的视觉模型。视频每秒估价不包含这些费用，也不包含图片编辑费用；应在实际服务商确认多图输入额度、上下文限制和价格。检查仅覆盖有限帧，未发现问题不等同于全片保证。

## Seedance 2.0

官方模型列表可确认以下 ID：

- `doubao-seedance-2-0-260128`：本项目的标准目标模型。
- `doubao-seedance-2-0-fast-260128`：快速版本。
- `doubao-seedance-2-0-mini-260615`：轻量版本。

这些型号单次生成 4–15 秒，24 fps；720p 可用。标准版还列出 1080p/4K，fast/mini 为 480p/720p。账号实际开通状态与限制以控制台为准，本项目不自动换模型。官方现有 2.5 型号，需求明确使用 2.0，因此本项目仍以 2.0 的 15 秒切段约束为准。[官方模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=zh)

下面是产品替换的请求形状示例。`PRODUCT_IMAGE_SIGNED_URL` 和 `REFERENCE_SEGMENT_SIGNED_URL` 必须替换为当次创建的可访问 HTTPS 签名链接，不能把占位符直接提交；`duration` 是该片段的整数秒数。

```http
POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
Authorization: Bearer YOUR_ARK_API_KEY
Content-Type: application/json
```

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {
      "type": "text",
      "text": "参考视频1的镜头顺序、构图和运镜。将视频中的核心商品替换为图片1的商品，保持图片1商品的轮廓、颜色、结构和标识一致。口播使用巴西葡萄牙语，文案按已确认脚本。不要生成画面字幕，字幕由后期合成。"
    },
    {
      "type": "image_url",
      "image_url": {"url": "PRODUCT_IMAGE_SIGNED_URL"},
      "role": "reference_image"
    },
    {
      "type": "video_url",
      "video_url": {"url": "REFERENCE_SEGMENT_SIGNED_URL"},
      "role": "reference_video"
    }
  ],
  "duration": 10,
  "ratio": "9:16",
  "resolution": "720p",
  "generate_audio": true,
  "watermark": false,
  "execution_expires_after": 86400
}
```

官方允许同次参考图片和视频。2.0 支持最多 9 张图片、3 个视频、3 个音频；参考视频累计不能超过 15 秒。`reference_image` / `reference_video` 属于全模态参考，不能与 `first_frame` / `last_frame` 混用。可在提示词中描述首尾构图，但这不等价于锁定首尾帧。2.0 支持葡萄牙语提示词；`generate_audio` 只控制是否生成混合音轨，不是独立的音乐/口播开关。[创建任务 API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)

输入校验应以服务商最新文档为准。2026-09-22 官方页面列出的单张图片上限为 30 MB、宽高 300–6000 px；参考视频为 MP4/MOV、24–60 fps，单个 2–15 秒。当前页面列出的单视频大小上限为 200 MB，部分旧教程仍写 50 MB，生产处理建议控制到较小体积。本项目的 720p 参考片段目标可避免依赖较新的高分辨率扩展。模型生成时长接口是整数秒，最终精确时长应以 FFprobe 读取并通过 FFmpeg 裁剪/拼接校准。[创建任务参数](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)

人物参考另有准入要求：官方不接受直接上传普通真人脸图/视频，支持通过已授权真人素材、预置虚拟人像及符合条件的模型原始产物使用。检测到人物素材时应明确提示要求，不能把提高复刻等级当成绕过审核的方法。[官方肖像素材说明](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh)

查询成功返回 `content.video_url`；链接有效期为 24 小时，任务只能查询近 7 天记录，必须及时下载并归档为数据库资产。保存任务 ID 后轮询，不能重新创建任务当作查询。`queued`、`running` 继续查询；`succeeded` 下载；`failed`、`cancelled`、`expired` 终止。局域网服务器无需提供公网回调地址。[查询任务 API](https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh)

产品替换能以该输入组合实现，但精确商品形状、包装文字、手部互动、口播发音和跨片段一致性仍需要质检。保留参考视频的镜头结构不保证逐帧等同。火山另有独立 LAS 视频编辑算子，官方列出 `object_replace` 用途；它有独立鉴权和计费接口，当前未混入 Ark 适配器。[LAS 视频编辑增强版](https://docs.volcengine.com/docs/Lake%20AI%20Service/2499936?lang=en)

## 私有 TOS 存储桶

管理员需要提供 `endpoint`、`region`、`bucket`、`access_key_id`、`secret_access_key`。例如北京地域 Endpoint 为 `tos-cn-beijing.volces.com`、Region 为 `cn-beijing`。不要把桶名重复写到 Endpoint 中。

`publish_media(settings, key, data, mime)` 使用 TOS Python SDK 的 `put_object` 上传，显式指定私有 ACL，再用 `pre_signed_url(Http_Method_Get, ...)` 生成临时地址。应用内部保留对象 key，按使用时机重新签名；签名 URL 不应被当作永久文件地址保存。工作台默认 URL TTL 为 24 小时，可设置 1 小时到 7 天；应长于排队加执行时间，上传后尽快提交。[TOS 普通上传](https://www.volcengine.com/docs/6349/92800?lang=zh)、[TOS Python 预签名](https://docs.volcengine.com/docs/TorchObjectStorage/GeneralpresignedPythonSDK?lang=zh)、[官方 Python SDK](https://github.com/volcengine/ve-tos-python-sdk)

SDK 也支持 PUT 预签名供浏览器直传。本项目先由服务端上传，避免额外的浏览器跨域和临时上传权限流程。密钥仅服务端解密后传给 SDK。私有 ACL 不能覆盖管理员已配置的公开桶策略，请在 TOS 控制台保持桶和策略私有，并给中转素材前缀配置合适的生命周期清理规则。

## 故障与边界

- 创建视频时遇到网络异常、HTTP 408/5xx、响应损坏或缺少 ID，会抛出 `SubmissionUncertain`。上游可能已经受理并计费，程序不自动重试；管理员应先按提交时间和账号核查远程任务再决定重建。
- 模型接口的错误只显示固定提示和 HTTP 状态，原始响应可能回显 API Key 或签名地址，因此不会直接暴露给用户。
- 媒体下载只接受公网 HTTPS/443，拒绝用户信息、内网地址、云元数据和混合公网/私网 DNS。每次重定向重新检查地址；连接固定到验证过的 IP，同时保留原域名的 Host 和 TLS SNI。下载客户端不携带模型密钥、不继承代理环境变量、不跨跳转转发 Cookie；文件按流量限制大小。
- URL 接口协议通过模拟服务验证，不代表某个账号已开通相应模型，也不代表第三方中转站实现完全兼容。真实端到端成片需要用户配置有效服务和素材后验证。

运行离线适配器测试：`python -m pytest tests/test_providers.py -q`。
