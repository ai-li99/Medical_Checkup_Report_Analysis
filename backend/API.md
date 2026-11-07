# 体检报告分析后端 · 接口说明（面向前端）

> 适用版本：v0.1.0　｜　最后更新：2026-11-06
> 本文档是前端接入的唯一契约来源，字段名、状态码、错误文案均与后端实现一致。

---

## 1. 基本信息

| 项 | 值 |
|---|---|
| Base URL（本地） | `http://127.0.0.1:8000` |
| 启动命令 | `cd backend` 后 `..\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000` |
| 自动文档 | `http://127.0.0.1:8000/docs`（Swagger UI，可直接试接口） |
| 鉴权 | **无**（演示版，未做登录/Token） |
| CORS | 已全开：`allow_origins=["*"]`，任意前端端口可直接调用 |
| 字符编码 | 全部 `UTF-8`；JSON 接口请带 `Content-Type: application/json; charset=utf-8` |
| 统一错误格式 | `{"detail": "中文错误说明"}`（422 校验错误除外，见 §7） |
| 状态轮询 | **无需**；`/api/submit` 为同步阻塞接口，返回即完整结果（应用2 慢时可能 10~30 秒） |

### 核心流程

```
① 上传文件            POST /api/upload_file        -> session_id
        │  needs_sheet_selection = true（多工作表时）
        ▼
② 选择工作表（可选）  POST /api/select_sheets      -> 最终行列信息
        │
        ▼
③ 提交问题（第一步）  POST /api/upload_message     -> message_id
        │
        ▼
④ 提交并取回答        POST /api/submit             -> answer + query_spec + result
        │
        ▼
⑤ 追问：重复 ③④（同一个 session_id，后端自动保持多轮记忆）
```

**状态机**：`待选工作表`（`needs_sheet_selection=true`）→ `就绪`（可提问）→ 每轮 `提问中` → `就绪`。
同一 `session_id` 重新调用 `/api/select_sheets` 会**重置对话记忆**；重新上传文件会**新建 session**。

---

## 2. `GET /api/healthy`

健康检查。

**响应 200**

```json
{
  "healthy": true,
  "dify_base_url": "http://47.114.83.33/v1",
  "app_ready": true
}
```

`app_ready=false` 表示 `.env` 里没配全两个 Dify 密钥，此时所有提问类接口会返回 502。

---

## 3. `POST /api/upload_file`

上传表格文件（`multipart/form-data`）。

**请求**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | File | 是 | 仅支持 `.xlsx` / `.csv`，≤ 50 MB，≤ 20 万行；`.xls` 老格式不支持 |

```bash
curl -X POST http://127.0.0.1:8000/api/upload_file -F "file=@checkup.xlsx"
```

**响应 200（多工作表，需要用户选择）**

```json
{
  "session_id": "s_7d17e2946d34",
  "file_id": "f_30255428b4bb",
  "filename": "checkup_sample.xlsx",
  "type": "xlsx",
  "needs_sheet_selection": true,
  "sheets": [
    { "name": "2023年", "rows": 6, "columns": 11 },
    { "name": "2024年", "rows": 6, "columns": 11 }
  ],
  "selected_sheets": [],
  "rows": 0,
  "columns": [],
  "message": "该文件含 2 个工作表，请选择要分析的工作表（合并全部或指定若干个）"
}
```

**响应 200（单工作表 / CSV，已就绪）**

```json
{
  "session_id": "s_a1b2c3d4e5f6",
  "file_id": "f_667f7a325566",
  "filename": "data.csv",
  "type": "csv",
  "needs_sheet_selection": false,
  "sheets": [{ "name": "CSV", "rows": 3, "columns": 4 }],
  "selected_sheets": ["CSV"],
  "rows": 3,
  "columns": [
    { "name": "姓名", "dtype": "文本", "non_null": 3, "missing": 0, "sample": ["张三", "李四", "王五"] }
  ],
  "message": "已载入 3 行 × 4 列，可以开始提问"
}
```

**字段说明**

| 字段 | 说明 |
|---|---|
| `session_id` | **后续所有接口的通行证**，前端必须保存 |
| `type` | `"xlsx"` 或 `"csv"` |
| `needs_sheet_selection` | `true` 时必须先调 ④ `/api/select_sheets`，否则 `rows=0`、`columns=[]`，且 `/api/submit` 会报 400 |
| `sheets[].rows / columns` | 每个工作表的行数、列数 |
| `columns[].dtype` | 中文类型标签：`文本 / 整数 / 小数 / 日期 / 布尔` |
| `columns[].non_null / missing` | 非空数 / 缺失数 |
| `columns[].sample` | 最多 3 个样例值（已截断到 20 字） |
| `message` | **可直接展示给用户**的中文提示 |

---

## 4. `POST /api/select_sheets`

多工作表时选择要分析的工作表（`application/json`）。

**请求**

```json
{ "session_id": "s_7d17e2946d34", "mode": "merge_all", "sheets": [] }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | string | 是 | 上传接口返回的 |
| `mode` | `"merge_all"` \| `"select"` | 否，默认 `"select"` | `merge_all`=合并全部工作表；`select`=合并指定的若干个 |
| `sheets` | string[] | `mode=select` 时必填 | 工作表名，取 `upload_file.sheets[].name` 的原值；选 1 个即单表，多个即纵向合并 |

**三种 UI 选项与请求的对应**

| 界面选项 | 请求 |
|---|---|
| 合并全部 sheet | `{"mode":"merge_all","sheets":[]}` |
| 只取某一个 sheet | `{"mode":"select","sheets":["2023年"]}` |
| 取其中几个并合并 | `{"mode":"select","sheets":["2023年","2024年"]}` |

**响应 200**

```json
{
  "session_id": "s_7d17e2946d34",
  "mode": "merge_all",
  "selected_sheets": ["2023年", "2024年"],
  "merged": true,
  "rows": 12,
  "columns": [
    { "name": "姓名", "dtype": "文本", "non_null": 12, "missing": 0, "sample": ["张三", "李四", "钱七"] },
    { "name": "_sheet", "dtype": "文本", "non_null": 12, "missing": 0, "sample": ["2023年", "2024年"] }
  ],
  "message": "已载入 12 行 × 12 列，可以开始提问"
}
```

**规则与错误**

- 合并多个工作表时，若**列名不一致**：`400`，`detail` 固定为
  **`选择的sheet的列名不一致，请重新上传`**
  → 前端此时应提示用户重新上传文件（无法通过改选 sheet 解决）。
- 列名集合相同、顺序不同：自动按第一个 sheet 的列序对齐，不算错误。
- 多表合并会**自动追加一列 `_sheet`**，标记每行来自哪个工作表（列名 `_sheet` 为系统保留）。
- CSV 文件调用本接口：`400`，`detail` = `CSV 文件只有一个数据表，不需要选择工作表`。
- 工作表名不存在：`400`，`detail` 里会列出可用工作表名。
- 重复调用会重新载入并**清空对话记忆**。

---

## 5. `POST /api/upload_message`

提交本轮问题（`application/json`）。这是"点提交"的第一步，答案在 `/api/submit` 返回。

**请求**

```json
{ "session_id": "s_7d17e2946d34", "message": "年龄大于40岁的人有多少？" }
```

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `session_id` | string | 是 | — |
| `message` | string | 是 | 1~2000 字，首尾空白会被 trim |

**响应 200**

```json
{
  "session_id": "s_7d17e2946d34",
  "message_id": "m_9f2c1a7b3d",
  "message": "年龄大于40岁的人有多少？"
}
```

> 问题会暂存在会话里，直到 `/api/submit` 成功执行才清空。
> 若 `/api/submit` 失败（4xx/5xx），**问题仍保留**，前端可直接重试 submit，无需重新 upload_message。

---

## 6. `POST /api/submit`

执行完整链路并返回回答（`application/json`）。**最慢的接口**，后端 Dify 超时为 180 秒，前端超时建议设为 ≥ 180 秒。

**请求**

```json
{ "session_id": "s_7d17e2946d34" }
```

**响应 200**

```json
{
  "session_id": "s_7d17e2946d34",
  "message": "年龄大于40岁的人有多少？",
  "answer": "年龄大于 40 岁的人数为 **8 人**。\n\n本次统计共命中 12 条体检记录……",
  "query_spec": {
    "op": "count",
    "filters": [{ "column": "年龄", "operator": ">", "value": 40 }],
    "note": "按年龄大于40岁（不含40）统计行数"
  },
  "raw_output": "<think>…</think>{\"op\":\"count\",…}",
  "result": {
    "kind": "count",
    "row_count": 1,
    "matched_rows": 8,
    "columns": ["计数"],
    "rows": [[8]],
    "truncated": false,
    "value": 8,
    "group_by": [],
    "note": "按年龄大于40岁（不含40）统计行数",
    "reason": ""
  },
  "conversation_id": "9e508b7f-a829-4b4c-85a8-a2e095fbfc29",
  "degraded": false,
  "error": "",
  "elapsed_ms": 3800
}
```

### 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `answer` | string | **直接展示的回答**。已剥离 `<think>` 推理内容，是 Markdown（含表格、列表、加粗） |
| `query_spec` | object \| null | 后端从应用1 解析出的查询规格；`null` 表示应用1 返回不可解析 |
| `raw_output` | string | 应用1 原始输出（**可能含 `<think>`**，一般只用于调试，不建议展示） |
| `result` | object \| null | pandas 执行结果（见下表）；执行失败/无法回答时为 `null` |
| `conversation_id` | string | 应用2 的会话 id，前端**无需传给后端**（后端自己保存），可用于展示或排查 |
| `degraded` | bool | `true` = 查询没能执行成功，`answer` 是应用2 对失败原因的解释 |
| `error` | string | `degraded=true` 时的错误原因（可直接展示或仅记录） |
| `elapsed_ms` | int | 本次端到端耗时（毫秒） |

### `result` 字段

| 字段 | 说明 |
|---|---|
| `kind` | `count`（计数）/ `list`（明细行）/ `aggregate`（分组统计）/ `distinct`（去重取值） |
| `matched_rows` | **过滤后命中的总行数**（不受返回行数限制） |
| `row_count` | **本次返回的结果行数**（受 `limit` 与内部上限约束） |
| `columns` | 结果列名（与 `rows` 的列一一对应） |
| `rows` | 二维数组 `[[...], [...]]`，与 `columns` 对齐；空结果为 `[]` |
| `truncated` | 结果是否被截断（命中/分组数 > 返回行数） |
| `value` | 仅 `kind=count` 且无分组时存在的标量值 |
| `group_by` | 分组列名数组（`count/aggregate/distinct` 可能有值） |
| `note` | 应用1 给出的取数假设说明 |
| `reason` | 仅 `kind=unsupported` 时存在，说明为什么无法查询 |

> `result.kind` 可能为 `unsupported`：表示问题所需字段不在表里。此时 `result` 非空但 `rows=[]`，`degraded=false`，`answer` 是应用2 的解释与替代问法建议。

### 前端展示建议

1. 主体渲染 `answer`（Markdown）。
2. 折叠面板展示 `result`：`count` 显示 `value`；其余用 `columns` + `rows` 渲染表格；`matched_rows > row_count` 时提示"仅展示前 N 行"。
3. `degraded=true` 时用警示色标注，并以 `error` 作为补充说明。
4. `query_spec` 可作为"查询详情"给高级用户看（调试友好）。

### 追问

同一个 `session_id` 再调一次 `upload_message` → `submit` 即可。
后端会自动把**最近 2 轮**的「问题 + 查询规格」附给应用1，因此「那他们的平均年龄是多少？」这类指代能被正确解析并继承上一轮筛选条件。
**超过 2 轮的指代可能失效**，前端可在 UI 上提示用户"涉及更早的数据请重新描述条件"。

---

## 7. 错误码一览

| HTTP | 触发场景 | `detail` 示例（可直接展示） |
|---|---|---|
| 400 | 文件类型不支持 | `不支持的文件类型「.xls」，仅支持 .xlsx 和 .csv` |
| 400 | 文件为空 | `上传的文件内容为空` |
| 400 | 文件过大 | `文件大小超过 50 MB 上限` |
| 400 | 表格解析失败 / 无可用列 / 超行数上限 | `Excel 解析失败：…`、`文件里没有可用的列`、`数据行数 300000 超过上限 200000 行` |
| 400 | 多 sheet 列名不一致 | **`选择的sheet的列名不一致，请重新上传`** |
| 400 | 工作表名不存在 | `工作表「xx」不存在；可用工作表：2023年、2024年` |
| 400 | CSV 调 select_sheets | `CSV 文件只有一个数据表，不需要选择工作表` |
| 400 | 未选工作表就提交 | `请先选择要分析的工作表（调用 /api/select_sheets）` |
| 400 | 未调 upload_message 就 submit | `请先通过 /api/upload_message 提交问题` |
| 404 | session 过期/不存在 | `会话不存在或已过期，请重新上传文件` |
| 422 | 请求体校验失败（字段缺失、message 为空/超 2000 字） | `detail` 是**数组**，结构同 FastAPI 标准校验错误 |
| 502 | Dify 调用失败（含未配密钥） | `应用1 调用失败：…` / `应用2 调用失败：…` |

> 400/404/502 的 `detail` 都是**一句中文**，可直接 toast 展示。
> 前端只需针对 `404`（回到上传页）与 `502`（提示稍后重试）做流程跳转。

---

## 8. 限制与注意

| 项 | 值 |
|---|---|
| 文件格式 | `.xlsx`、`.csv`（UTF-8 / UTF-8-BOM / GB18030 自动识别，逗号/制表符/分号自动嗅探） |
| 文件大小 / 行数 | ≤ 50 MB / ≤ 200,000 行 |
| 会话存储 | **进程内存**，重启丢失；最多 100 个 session（超出淘汰最旧） |
| 返回行数（同时喂给应用2） | 最多 200 行；`truncated=true` 表示还有数据未返回，单元格超 50 字截断 |
| 查询 `limit` | 默认 50，最大 500 |
| 每次上传 | 生成新 `session_id`，旧会话仍可继续用直到被淘汰 |
| 重新选 sheet | 清空该 session 的对话记忆 |

---

## 9. 前端接入清单（建议实现顺序）

1. 上传页：选文件 → `POST /api/upload_file` → 保存 `session_id`，展示 `columns` 表头预览。
2. 若 `needs_sheet_selection`：弹出选择（合并全部 / 勾选若干）→ `POST /api/select_sheets`。
   - 捕获 400 的 `选择的sheet的列名不一致，请重新上传`，引导重新上传。
3. 提问框：`POST /api/upload_message` → 按钮 loading → `POST /api/submit`（超时 ≥120s）。
4. 渲染 `answer`（Markdown）+ 可折叠 `result` 表格。
5. 追问：保持同一 `session_id`，重复第 3 步；把历史问答追加到对话列表（后端不返回历史，前端自行维护）。
6. 错误处理：`400` 直接 toast `detail`；`404` 回到上传页；`502` 提示重试。

---

## 10. TypeScript 类型定义（可直接复制）

```ts
export type ColumnDtype = '文本' | '整数' | '小数' | '日期' | '布尔'

export interface SheetInfo { name: string; rows: number; columns: number }

export interface ColumnInfo {
  name: string
  dtype: ColumnDtype
  non_null: number
  missing: number
  sample: string[]
}

export interface UploadFileResponse {
  session_id: string
  file_id: string
  filename: string
  type: 'xlsx' | 'csv'
  needs_sheet_selection: boolean
  sheets: SheetInfo[]
  selected_sheets: string[]
  rows: number
  columns: ColumnInfo[]
  message: string
}

export type SheetMode = 'merge_all' | 'select'

export interface SelectSheetsRequest {
  session_id: string
  mode?: SheetMode
  sheets?: string[]
}

export interface SelectSheetsResponse {
  session_id: string
  mode: SheetMode
  selected_sheets: string[]
  merged: boolean
  rows: number
  columns: ColumnInfo[]
  message: string
}

export interface UploadMessageResponse {
  session_id: string
  message_id: string
  message: string
}

export type QueryKind = 'count' | 'list' | 'aggregate' | 'distinct' | 'unsupported'

export interface QueryResult {
  kind: QueryKind
  row_count: number
  matched_rows: number
  columns: string[]
  rows: (string | number | boolean | null)[][]
  truncated: boolean
  value: unknown
  group_by: string[]
  note: string
  reason: string
}

export interface SubmitResponse {
  session_id: string
  message: string
  answer: string
  query_spec: Record<string, unknown> | null
  raw_output: string
  result: QueryResult | null
  conversation_id: string
  degraded: boolean
  error: string
  elapsed_ms: number
}
```

---

## 11. 可直接跑的调用示例（JavaScript）

```js
const BASE = 'http://127.0.0.1:8000'

async function uploadFile(file) {
  const form = new FormData()
  form.append('file', file)
  return (await fetch(`${BASE}/api/upload_file`, { method: 'POST', body: form })).json()
}

async function postJson(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail ?? '请求失败')
  }
  return res.json()
}

async function ask(sessionId, question) {
  await postJson('/api/upload_message', { session_id: sessionId, message: question })
  return postJson('/api/submit', { session_id: sessionId })
}

// 使用
const up = await uploadFile(input.files[0])
if (up.needs_sheet_selection) {
  await postJson('/api/select_sheets', { session_id: up.session_id, mode: 'merge_all', sheets: [] })
}
const res = await ask(up.session_id, '年龄大于40岁的人有多少？')
console.log(res.answer)
```

---

## 12. 后端文件职责（排障用）

| 文件 | 职责 |
|---|---|
| `main.py` | 路由、CORS、追问上下文注入、异常 → HTTP 状态码映射 |
| `query_spec.py` | Query Spec 校验 + pandas 执行（零 eval）+ 给应用2 的数据格式化 |
| `dify_client.py` | 调用应用1/2，剥离 `<think>`，提取 JSON |
| `file_store.py` | 文件落盘、xlsx/csv 解析、sheet 合并与列名一致性校验、内存会话 |
| `schema_card.py` | 由 DataFrame 生成给应用1 的表结构卡片 |
| `config.py` / `.env` | 配置与密钥 |
| `models.py` | 请求/响应模型（与本文档 §10 对应） |
