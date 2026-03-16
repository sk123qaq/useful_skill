# 火山引擎录音文件识别 API 参考

## 概述

大模型录音文件识别服务的处理流程分为提交任务和查询结果两个阶段。

## API 端点

| 操作 | URL |
|------|-----|
| 提交任务 | `https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit` |
| 查询结果 | `https://openspeech.bytedance.com/api/v3/auc/bigmodel/query` |

## 认证 Header

所有请求需要以下 Header：

| Header | 说明 | 示例 |
|--------|------|------|
| X-Api-App-Key | APP ID (火山引擎控制台获取) | 123456789 |
| X-Api-Access-Key | Access Token | your-access-key |
| X-Api-Resource-Id | 资源ID | volc.bigasr.auc / volc.seedasr.auc |
| X-Api-Request-Id | 任务ID (UUID) | 67ee89ba-7050-4c04-a3d7-ac61a63499b3 |
| X-Api-Sequence | 发包序号，固定值 | -1 |

## 支持的语言

### 默认支持
- 中文（普通话）
- 英语
- 上海话
- 闽南语
- 四川话
- 陕西话
- 粤语

### 可指定语言

| 语言 | 参数值 |
|------|--------|
| 英语 | en-US |
| 日语 | ja-JP |
| 印尼语 | id-ID |
| 西班牙语 | es-MX |
| 葡萄牙语 | pt-BR |
| 德语 | de-DE |
| 法语 | fr-FR |
| 韩语 | ko-KR |
| 菲律宾语 | fil-PH |
| 马来语 | ms-MY |
| 泰语 | th-TH |
| 阿拉伯语 | ar-SA |

## 音频格式

| 格式 | format 值 | 说明 |
|------|-----------|------|
| WAV | wav | |
| MP3 | mp3 | |
| OGG | ogg | |
| PCM | raw | |

## 请求参数

### audio 对象

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| url | string | 是 | 音频链接 |
| format | string | 是 | 音频格式 |
| language | string | 否 | 指定语言 |
| codec | string | 否 | 编码格式 (raw/opus) |
| rate | int | 否 | 采样率 (默认16000) |
| bits | int | 否 | 采样位数 (默认16) |
| channel | int | 否 | 声道数 (1=mono, 2=stereo) |

### request 对象

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| model_name | string | bigmodel | 模型名称 |
| model_version | string | 310 | 模型版本 (传400使用400模型) |
| enable_itn | bool | true | 启用文本规范化 |
| enable_punc | bool | false | 启用标点 |
| enable_ddc | bool | false | 启用语义顺滑 |
| enable_speaker_info | bool | false | 启用说话人分离 |
| enable_channel_split | bool | false | 启用双声道识别 |
| show_utterances | bool | false | 输出分句信息 |
| show_speech_rate | bool | false | 输出语速信息 |
| show_volume | bool | false | 输出音量信息 |
| enable_lid | bool | false | 启用语种识别 |
| enable_emotion_detection | bool | false | 启用情绪检测 |
| enable_gender_detection | bool | false | 启用性别检测 |
| vad_segment | bool | false | 使用VAD分句 |
| end_window_size | int | - | 强制判停时间 (300-5000ms) |

## 错误码

| 错误码 | 含义 |
|--------|------|
| 20000000 | 成功 |
| 20000001 | 正在处理中 |
| 20000002 | 任务在队列中 |
| 20000003 | 静音音频 |
| 45000001 | 请求参数无效 |
| 45000002 | 空音频 |
| 45000151 | 音频格式不正确 |
| 55000031 | 服务器繁忙 |

## 使用示例

```python
from volc_transcriber import VolcAudioTranscriber

# 初始化客户端
client = VolcAudioTranscriber(
    app_key="your-app-key",
    access_key="your-access-key"
)

# 提交转写任务
result = client.submit_task(
    audio_url="https://example.com/audio.mp3",
    format="mp3",
    language="zh-CN",
    enable_punc=True
)

request_id = result["request_id"]

# 等待结果
final_result = client.wait_for_result(request_id)

# 获取文本
if final_result.get("result"):
    text = final_result["result"]["text"]
    print(text)
```

## 敏感词过滤

```python
sensitive_words_filter = json.dumps({
    "system_reserved_filter": True,  # 使用系统敏感词
    "filter_with_empty": ["敏感词1"],  # 过滤为空
    "filter_with_signed": ["敏感词2"]  # 替换为 *
})
```
