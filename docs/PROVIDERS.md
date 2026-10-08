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
| 原视频 / 词复刻音频转写 | 阿里云百炼（音频转写） | `https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/api/v1` | `POST /services/audio/asr/transcription`、`GET /tasks/{id}` |
| Seedance 视频 | 火山引擎原生 | 火山 `/api/v3` 或兼容代理地址 | `POST /contents/generations/tasks`、`GET /contents/generations/tasks/{id}` |
| 万相 3.0 视频 | 阿里云百炼 | `https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/api/v1` | `POST /services/aigc/video-generation/video-synthesis`、`GET /tasks/{id}` |

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

## 万相 3.0（新增于 2026-10-07）

在设置中心新增或编辑配置：用途选择 **视频生成**，协议选择 **阿里云百炼（万相视频）**，模型 ID 填写 `wan3.0-video` 或 `wan3.0-video-prime`。Base URL 填写控制台对应业务空间、地域的 `/api/v1` 基础地址，不包含视频操作路径或 `/compatible-mode/v1`。API Key 必须匹配该地域和业务空间，并已获得模型调用权限。阿里云百炼（万相视频）协议仅适配万相视频，音频转写使用独立协议，图片优化或视觉分析选择其对应协议。

适配器使用 `Authorization: Bearer ...` 与 `X-DashScope-Async: enable` 提交原生异步任务，将 `output.task_id` 持久化，之后每约 15 秒查询该任务。产品图片映射为 `input.media[].type=reference_image`；直接生成策略还输入 `reference_video`，关键画面/改编策略仅输入参考图片，不混用首尾帧类型。分辨率转换为 `480P/720P/1080P`，`audio` 对应音乐/口播任意一项开启，`watermark=false`；关闭 `prompt_extend` 以避免供应商再次改写已确认的产品约束和镜头脚本。

虽然模型支持最多 30 秒输出，本项目继续使用每段 **4–15 秒** 的通用时间线，长视频由 FFmpeg 拼接。参考片段最长使用 14.9 秒，给编码与音轨时长留出缓冲；完整源区间通过轻微变速映射，不删掉最后镜头。万相参考视频总时长加输出时长不得超过 30 秒。提交前检查参考片段的时长、边长、比例与 100 MB 大小限制；超过 20000 字符的提示词停止并提示精简，不截掉产品约束，也不消耗视频提交次数。

继续使用已配置的 TOS 公网 HTTPS 临时链接作为输入，阿里云接口支持此类 URL，无须另外配置 OSS。万相任务状态 `PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED` 转换为项目已有状态，成功后立即下载并存入数据库，复用产品质检和 FFmpeg 合成。任务与下载链接仅保留约 24 小时；`UNKNOWN`、损坏查询或缺少下载地址时保留原任务 ID，不把状态未知当成确定失败重新提交。网络异常或提交成功但 ID 缺失时，沿用管理员核查并关联任务的流程。

本次验证使用模拟 HTTP 服务与真实本地 FFmpeg，未调用真实计费生成。实际商品替换、巴西葡语口播和跨片段连续性需用你的样片验收。[万相 3.0 官方 API](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference)、[阿里云错误码](https://help.aliyun.com/zh/model-studio/error-code)。

## 阿里云音频转写

核对日期：2026-10-07。设置中心新增模型时填写：

| 配置项 | 填写内容 |
| --- | --- |
| 模型用途 | **音频转写** |
| 接口协议 | **阿里云百炼（音频转写）**，内部标识 `dashscope_asr` |
| 模型 ID | `qwen3-asr-flash-filetrans`，或控制台已开通的日期版本，例如 `qwen3-asr-flash-filetrans-2025-11-17` |
| API Base URL | 控制台对应地域的 `/api/v1` 地址，例如 `https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/api/v1` |
| API Key | 与模型、基础地址同地域的百炼密钥 |

北京也可使用 `https://dashscope.aliyuncs.com/api/v1`；新加坡使用控制台对应的业务空间地址或 `https://dashscope-intl.aliyuncs.com/api/v1`。不要填 `compatible-mode/v1`，也不要填完整的 `.../services/audio/asr/transcription` 操作路径。该模型使用专用异步接口，和万相视频协议分别配置。`qwen3-asr-flash` 的聊天兼容调用不能代替这里的文件转写与词时间戳。[阿里云 Qwen-ASR API](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)、[支持模型与地域](https://help.aliyun.com/zh/model-studio/non-realtime-speech-recognition-user-guide)。

管理员须先启用现有 TOS，使用阿里云转写期间保持配置有效并启用。当前创建、分析、生成入口会检查 TOS；已有任务重试继续查询，但任务入口仍要求有效的 TOS 配置。服务端提取音频，保存到项目数据库，再向私有桶上传用于模型读取的临时副本并生成签名 HTTPS 链接，无须另建 OSS。接口使用 `X-DashScope-Async: enable` 提交、保存任务 ID 后查询；转写原始结果和词时间信息入库。转写会产生模型费用，已确认的任务在重试时继续查询，不自动重复提交。原片转写自动识别语言，词复刻生成后的巴西站点口播按葡萄牙语识别。

提交状态不确定且没有任务 ID 时，先在百炼控制台核查同一音频与提交时间，再由管理员在项目的 **模型任务 → 关联转写任务 ID** 保存核对结果；该操作不调用收费模型。随后点击项目 **重试任务** 继续查询。已知 ID 即使查询失败也保留，不因无法查询再次提交。

该配置可供原有视频复刻分析口播，也可供词复刻识别生成视频中的实际巴西葡语口播。词复刻请求词级时间戳，再用于字幕高亮和对齐；识别错误与时间偏差仍需人工试听确认。接口适配测试不调用真实计费模型。

百炼返回 `SUCCESS_WITH_NO_VALID_FRAGMENT` 时，表示本次转写没有识别到有效语音片段，不能据此断言原片一定没有声音。项目会在 **模型任务** 显示 **未识别到口播**、安全的原因提示及已有任务 ID。参考视频遇到该结果仍可继续按产品事实和画面分析并编写新口播，但无法还原原口播；词复刻成片遇到该结果则停止字幕合成，保留已生成片段，不能编造口播或词时间戳。

该结果会缓存。已有失败任务点击 **重试任务** 时只查询保存的任务 ID 以取得明确结果，不重新提交音频；已缓存的无有效口播结果直接复用。参考视频继续分析可能按正常流程产生视觉分析费用，不会因为上述错误自动重交转写或重做视频。

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
