# MinerU Cloud API 完整文档

## 目录

1. [单个文件解析](#单个文件解析)
2. [批量文件解析](#批量文件解析)
3. [常见错误码](#常见错误码)

---

## 单个文件解析

### 创建解析任务

适用于通过 API 创建解析任务的场景。

**注意事项**:
- 单个文件大小不能超过 200MB，文件页数不超出 600 页
- 每个账号每天享有 2000 页最高优先级解析额度，超过 2000 页的部分优先级降低
- 因网络限制，github、aws 等国外 URL 会请求超时
- 该接口不支持文件直接上传
- header 头中需要包含 Authorization 字段，格式为 `Bearer + 空格 + Token`

#### Python 请求示例（适用于 pdf、doc、ppt、图片文件）

```python
import requests

token = "官网申请的api token"
url = "https://mineru.net/api/v4/extract/task"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "model_version": "vlm"
}

res = requests.post(url, headers=header, json=data)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

#### Python 请求示例（适用于 html 文件）

```python
import requests

token = "官网申请的api token"
url = "https://mineru.net/api/v4/extract/task"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "url": "https://****",
    "model_version": "MinerU-HTML"
}

res = requests.post(url, headers=header, json=data)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

#### CURL 请求示例（适用于 pdf、doc、ppt、图片文件）

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
    "model_version": "vlm"
}'
```

#### CURL 请求示例（适用于 html 文件）

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "url": "https://****",
    "model_version": "MinerU-HTML"
}'
```

#### 请求体参数说明

| 参数 | 类型 | 是否必选 | 示例 | 描述 |
|------|------|----------|------|------|
| url | string | 是 | `https://static.openxlab.org.cn/opendatalab/pdf/demo.pdf` | 文件 URL，支持.pdf、.doc、.docx、.ppt、.pptx、.png、.jpg、.jpeg、.html多种格式 |
| is_ocr | bool | 否 | false | 是否启动 ocr 功能，默认 false，仅对 pipeline、vlm 模型有效 |
| enable_formula | bool | 否 | true | 是否开启公式识别，默认 true，仅对 pipeline、vlm 模型有效。特别注意的是：对于 vlm 模型，这个参数指只会影响行内公式的解析 |
| enable_table | bool | 否 | true | 是否开启表格识别，默认 true，仅对 pipeline、vlm 模型有效 |
| language | string | 否 | ch | 指定文档语言，默认 ch |
| data_id | string | 否 | abc** | 解析对象对应的数据 ID。由大小写英文字母、数字、下划线（_）、短划线（-）、英文句号（.）组成，不超过 128 个字符 |
| callback | string | 否 | `http://127.0.0.1/callback` | 解析结果回调通知 URL，支持 HTTP 和 HTTPS |
| seed | string | 否 | abc** | 随机字符串，用于回调签名验证，不超过 64 个字符 |
| extra_formats | [string] | 否 | ["docx","html"] | markdown、json 为默认导出格式，该参数仅支持 docx、html、latex 三种格式中的一个或多个。对源文件为 html 的文件无效 |
| page_ranges | string | 否 | 1-600 | 指定页码范围，格式为逗号分隔的字符串 |
| model_version | string | 否 | vlm | mineru 模型版本：pipeline、vlm、MinerU-HTML，默认 pipeline |
| no_cache | bool | 否 | false | 是否绕过缓存，默认 false |
| cache_tolerance | int | 否 | 900 | 缓存容忍时间（秒），默认 900（15分钟） |

#### 响应参数说明

| 参数 | 类型 | 示例 | 说明 |
|------|------|------|------|
| code | int | 0 | 接口状态码，成功：0 |
| msg | string | ok | 接口处理信息，成功："ok" |
| trace_id | string | c876cd60b202f2396de1f9e39a1b0172 | 请求 ID |
| data.task_id | string | a90e6ab6-44f3-4554-b459-b62fe4c6b436 | 提取任务 id |

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "task_id": "a90e6ab6-44f3-4554-b4***"
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

### 获取任务结果

通过 task_id 查询提取任务目前的进度，任务处理完成后，接口会响应对应的提取详情。

#### Python 请求示例

```python
import requests

token = "官网申请的api token"
url = f"https://mineru.net/api/v4/extract/task/{task_id}"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

res = requests.get(url, headers=header)
print(res.status_code)
print(res.json())
print(res.json()["data"])
```

#### CURL 请求示例

```bash
curl --location --request GET 'https://mineru.net/api/v4/extract/task/{task_id}' \
--header 'Authorization: Bearer *****' \
--header 'Accept: */*'
```

#### 响应参数说明

| 参数 | 类型 | 示例 | 说明 |
|------|------|------|------|
| code | int | 0 | 接口状态码，成功：0 |
| msg | string | ok | 接口处理信息，成功："ok" |
| trace_id | string | c876cd60b202f2396de1f9e39a1b0172 | 请求 ID |
| data.task_id | string | abc** | 任务 ID |
| data.data_id | string | abc** | 解析对象对应的数据 ID |
| data.state | string | done | 任务处理状态：done(完成), pending(排队中), running(正在解析), failed(解析失败), converting(格式转换中) |
| data.full_zip_url | string | `https://cdn-mineru.openxlab.org.cn/pdf/xxx.zip` | 文件解析结果压缩包 |
| data.err_msg | string | 文件格式不支持 | 解析失败原因，当 state=failed 时有效 |
| data.extract_progress.extracted_pages | int | 1 | 文档已解析页数，当 state=running 时有效 |
| data.extract_progress.start_time | string | 2025-01-20 11:43:20 | 文档解析开始时间 |
| data.extract_progress.total_pages | int | 2 | 文档总页数 |

#### 响应示例 - 进行中

```json
{
  "code": 0,
  "data": {
    "task_id": "47726b6e-46ca-4bb9-******",
    "state": "running",
    "err_msg": "",
    "extract_progress": {
      "extracted_pages": 1,
      "total_pages": 2,
      "start_time": "2025-01-20 11:43:20"
    }
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

#### 响应示例 - 完成

```json
{
  "code": 0,
  "data": {
    "task_id": "47726b6e-46ca-4bb9-******",
    "state": "done",
    "full_zip_url": "https://cdn-mineru.openxlab.org.cn/pdf/018e53ad-d4f1-475d-b380-36bf24db9914.zip",
    "err_msg": ""
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 批量文件解析

### 文件批量上传解析

适用于本地文件上传解析的场景，可通过此接口批量申请文件上传链接，上传文件后，系统会自动提交解析任务。

**注意事项**:
- 申请的文件上传链接有效期为 24 小时
- 上传文件时，无须设置 Content-Type 请求头
- 文件上传完成后，无须调用提交解析任务接口，系统会自动扫描已上传完成文件自动提交解析任务
- 单次申请链接不能超过 200 个

#### Python 请求示例（适用于 pdf、doc、ppt、图片文件）

```python
import requests

token = "官网申请的api token"
url = "https://mineru.net/api/v4/file-urls/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"name":"demo.pdf", "data_id": "abcd"}
    ],
    "model_version":"vlm"
}
file_path = ["demo.pdf"]
try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            urls = result["data"]["file_urls"]
            for i in range(0, len(urls)):
                with open(file_path[i], 'rb') as f:
                    res_upload = requests.put(urls[i], data=f)
                    if res_upload.status_code == 200:
                        print(f"{urls[i]} upload success")
        else:
            print(f"apply upload url failed, reason:{result['msg']}")
except Exception as err:
    print(err)
```

#### CURL 请求示例

```bash
curl --location --request POST 'https://mineru.net/api/v4/file-urls/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"name":"demo.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}'
```

#### CURL 文件上传示例

```bash
curl -X PUT -T /path/to/your/file.pdf 'https://****'
```

#### 请求体参数说明

| 参数 | 类型 | 是否必选 | 描述 |
|------|------|----------|------|
| files | array | 是 | 文件列表 |
| files[].name | string | 是 | 文件名 |
| files[].data_id | string | 否 | 数据 ID |
| files[].is_ocr | bool | 否 | 是否启用 OCR |
| files[].page_ranges | string | 否 | 指定页码范围 |
| model_version | string | 否 | 模型版本 |
| enable_formula | bool | 否 | 是否开启公式识别 |
| enable_table | bool | 否 | 是否开启表格识别 |
| language | string | 否 | 文档语言 |
| callback | string | 否 | 回调 URL |
| seed | string | 否 | 随机种子 |
| extra_formats | [string] | 否 | 额外输出格式 |

#### 响应参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| code | int | 接口状态码，成功：0 |
| data.batch_id | string | 批量提取任务 id |
| data.file_urls | [string] | 文件上传链接 |

---

### URL 批量上传解析

适用于通过 API 批量创建提取任务的场景。

**注意事项**:
- 单次申请链接不能超过 200 个
- 文件大小不能超过 200MB，文件页数不超出 600 页
- 因网络限制，github、aws 等国外 URL 会请求超时

#### Python 请求示例

```python
import requests

token = "官网申请的api token"
url = "https://mineru.net/api/v4/extract/task/batch"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}
data = {
    "files": [
        {"url":"https://cdn-mineru.openxlab.org.cn/demo/example.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}

try:
    response = requests.post(url, headers=header, json=data)
    if response.status_code == 200:
        result = response.json()
        if result["code"] == 0:
            batch_id = result["data"]["batch_id"]
            print(f'batch_id:{batch_id}')
except Exception as err:
    print(err)
```

#### CURL 请求示例

```bash
curl --location --request POST 'https://mineru.net/api/v4/extract/task/batch' \
--header 'Authorization: Bearer ***' \
--header 'Content-Type: application/json' \
--header 'Accept: */*' \
--data-raw '{
    "files": [
        {"url":"https://cdn-mineru.openxlab.org.cn/demo/example.pdf", "data_id": "abcd"}
    ],
    "model_version": "vlm"
}'
```

---

### 批量获取任务结果

通过 batch_id 批量查询提取任务的进度。

#### Python 请求示例

```python
import requests

token = "官网申请的api token"
url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

res = requests.get(url, headers=header)
print(res.json())
```

#### CURL 请求示例

```bash
curl --location --request GET 'https://mineru.net/api/v4/extract-results/batch/{batch_id}' \
--header 'Authorization: Bearer *****' \
--header 'Accept: */*'
```

#### 响应参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| code | int | 接口状态码 |
| data.batch_id | string | batch_id |
| data.extract_result | array | 提取结果列表 |
| extract_result[].file_name | string | 文件名 |
| extract_result[].state | string | 任务状态 |
| extract_result[].full_zip_url | string | 结果下载链接 |
| extract_result[].err_msg | string | 错误信息 |
| extract_result[].data_id | string | 数据 ID |

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "batch_id": "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87",
    "extract_result": [
      {
        "file_name": "example.pdf",
        "state": "done",
        "err_msg": "",
        "full_zip_url": "https://cdn-mineru.openxlab.org.cn/pdf/xxx.zip"
      },
      {
        "file_name":"demo.pdf",
        "state": "running",
        "err_msg": "",
        "extract_progress": {
          "extracted_pages": 1,
          "total_pages": 2,
          "start_time": "2025-01-20 11:43:20"
        }
      }
    ]
  },
  "msg": "ok",
  "trace_id": "c876cd60b202f2396de1f9e39a1b0172"
}
```

---

## 常见错误码

| 错误码 | 说明 | 解决建议 |
|--------|------|----------|
| A0202 | Token 错误 | 检查 Token 是否正确，请检查是否有 Bearer 前缀或者更换新 Token |
| A0211 | Token 过期 | 更换新 Token |
| -500 | 传参错误 | 请确保参数类型及 Content-Type 正确 |
| -10001 | 服务异常 | 请稍后再试 |
| -10002 | 请求参数错误 | 检查请求参数格式 |
| -60001 | 生成上传 URL 失败 | 请稍后再试 |
| -60002 | 获取匹配的文件格式失败 | 检测文件类型失败，请求的文件名及链接中带有正确的后缀名，且文件为 pdf,doc,docx,ppt,pptx,png,jp(e)g 中的一种 |
| -60003 | 文件读取失败 | 请检查文件是否损坏并重新上传 |
| -60004 | 空文件 | 请上传有效文件 |
| -60005 | 文件大小超出限制 | 检查文件大小，最大支持 200MB |
| -60006 | 文件页数超过限制 | 请拆分文件后重试 |
| -60007 | 模型服务暂时不可用 | 请稍后重试或联系技术支持 |
| -60008 | 文件读取超时 | 检查 URL 可访问 |
| -60009 | 任务提交队列已满 | 请稍后再试 |
| -60010 | 解析失败 | 请稍后再试 |
| -60011 | 获取有效文件失败 | 请确保文件已上传 |
| -60012 | 找不到任务 | 请确保 task_id 有效且未删除 |
| -60013 | 没有权限访问该任务 | 只能访问自己提交的任务 |
| -60014 | 删除运行中的任务 | 运行中的任务暂不支持删除 |
| -60015 | 文件转换失败 | 可以手动转为 pdf 再上传 |
| -60016 | 文件转换失败 | 文件转换为指定格式失败，可以尝试其他格式导出或重试 |
| -60017 | 重试次数达到上限 | 等后续模型升级后重试 |
| -60018 | 每日解析任务数量已达上限 | 明日再来 |
| -60019 | html 文件解析额度不足 | 明日再来 |
| -60020 | 文件拆分失败 | 请稍后重试 |
| -60021 | 读取文件页数失败 | 请稍后重试 |
| -60022 | 网页读取失败 | 可能因网络问题或者限频导致读取失败，请稍后重试 |
