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
| 鉴权 | 除 `GET /api/healthy`、`/api/register`、`/api/login`、`/api/refresh` 外，其余接口均需 `Authorization: Bearer <access token>`；access 30 分钟、refresh 30 天，详见 §13 |
| CORS | 已全开：`allow_origins=["*"]`，任意前端端口可直接调用 |
| 字符编码 | 全部 `UTF-8`；JSON 接口请带 `Content-Type: application/json; charset=utf-8` |
| 统一错误格式 | `{"detail": "中文错误说明"}`（422 校验错误除外，见 §7） |
| 状态轮询 | **无需**；`/api/submit` 为同步阻塞接口，返回即完整结果（应用2 慢时可能 10~30 秒） |

### 核心流程

```
⓿ 注册 / 登录        POST /api/register | /api/login     -> token（此后每个请求都带 Authorization）
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

> 🔒 **需要登录**：请求头带 `Authorization: Bearer <token>`，否则 `401`。

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

> 🔒 **需要登录**；且 `session_id` 必须属于当前用户，否则 `404`。

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

> 🔒 **需要登录**；且 `session_id` 必须属于当前用户，否则 `404`。

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

> 🔒 **需要登录**；且 `session_id` 必须属于当前用户，否则 `404`。

执行完整链路并返回回答（`application/json`）。**最慢的接口**，后端 Dify 超时为 180 秒，前端超时建议设为 ≥ 180 秒。

> 想要逐字展示，请用 §15 的 `POST /api/submit/stream`（SSE）；本接口保留给非流式场景。

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
后端会自动把最近若干轮的「问题 + 查询规格」附给应用1：按 **1500 字符预算**从最近往前装（通常 5–6 轮，历史问题截断到 300 字，查询规格完整保留），因此「那他们的平均年龄是多少？」这类指代能被正确解析并继承筛选条件。
**当前问题始终完整发送，不参与该预算**（`/api/upload_message` 的硬限制仍是 1–2000 字）。
**超出预算的更早轮次不会带入**；若用户引用很早以前的条件，建议在问题里重述。

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
| 400 | 注册：用户名/密码格式不符 | `用户名需为 3-32 位字母、数字或下划线`、`密码至少 8 位` |
| 400 | 生成报告：未选工作表 / 日期格式错 | `请先选择要分析的工作表（调用 /api/select_sheets）`、`report_date 格式应为 YYYY-MM-DD` |
| 404 | 生成报告：file_id 不存在或不属于当前用户 | `文件不存在或无权访问` |
| 401 | access 过期 | `{"detail": "登录已过期", "code": "token_expired"}` |
| 401 | 未登录 / 令牌伪造 / 已被吊销 | `{"detail": "未登录或登录已过期", "code": "token_invalid"}` |
| 401 | 登录失败（用户不存在或密码错） | `{"detail": "用户名或密码错误", "code": "bad_credentials"}` |
| 401 | refresh 无效 / 已轮换 / 已吊销 / 已过期 | `{"detail": "登录已过期，请重新登录", "code": "refresh_invalid"}` |
| 404 | session 过期/不存在，或不属于当前用户 | `会话不存在或已过期，请重新上传文件` |
| 404 | 历史记录/历史会话不属于当前用户 | `记录不存在` / `会话不存在` |
| 409 | 注册时用户名已存在（含大小写变体） | `用户名已存在` |
| 422 | 请求体校验失败（字段缺失、message 为空/超 2000 字） | `detail` 是**数组**，结构同 FastAPI 标准校验错误 |
| 429 | 登录失败次数过多（含锁定期内密码正确） | `{"detail": "登录失败次数过多，请 15 分钟后再试", "code": "login_locked"}` + `Retry-After` |
| 501 | 未登录调用重置密码 | `{"detail": "未登录重置密码需邮箱验证，注册升级后开放", "code": "reset_requires_login"}` |
| 502 | Dify 调用失败（含未配密钥） | `应用1 调用失败：…` / `应用2 调用失败：…` |

> 400/404/502 的 `detail` 都是**一句中文**，可直接 toast 展示。
> 401 会额外带 `code`：`token_expired` 走刷新，其余跳登录页；`429` 时提示稍后再试。

---

## 8. 限制与注意

| 项 | 值 |
|---|---|
| 文件格式 | `.xlsx`、`.csv`（UTF-8 / UTF-8-BOM / GB18030 自动识别，逗号/制表符/分号自动嗅探） |
| 文件大小 / 行数 | ≤ 50 MB / ≤ 200,000 行 |
| 会话存储 | 数据库 + 内存缓存；重启后历史会话可从原始文件恢复；内存最多缓存 100 个 |
| access / refresh 有效期 | 30 分钟 / 30 天（`AUTH_ACCESS_TTL_SECONDS` / `AUTH_REFRESH_TTL_SECONDS`） |
| 登录失败锁定 | 用户名+IP 15 分钟内 5 次；单 IP 15 分钟内 20 次 → 锁 15 分钟 |
| 历史记录 | **永久保留**（含原始上传文件），不自动清理 |
| 返回行数（同时喂给应用2） | 最多 200 行；`truncated=true` 表示还有数据未返回，单元格超 50 字截断 |
| 查询 `limit` | 默认 50，最大 500 |
| 追问上下文 | 1500 字符预算（`APP1_CONTEXT_MAX_CHARS`），历史问题截断 300 字（`APP1_CONTEXT_QUESTION_CHARS`）；当前问题不受此限 |
| 文本型数字 | 载入时自动转成数值（`"50岁"` → `50`、`"45"` → `45`），因此 `columns[].dtype` 可能显示为「整数/小数」；带前导零的编号（`"007"`）与超长数字不转 |
| 单个问题长度 | 1–2000 字（超出返回 422） |
| 每次上传 | 生成新 `session_id`；旧会话永久可从历史恢复 |
| 重新选 sheet | 清空该 session 的对话记忆 |

---

## 9. 前端接入清单（建议实现顺序）

0. 登录/注册：`POST /api/register` 或 `POST /api/login` → 保存 `token` + `refresh_token`。
1. 封装请求拦截器：所有请求带 `Authorization: Bearer <token>`；`401` + `code=token_expired` → 调 `/api/refresh` 换新并重试一次；`401` 其他 code → 清令牌跳登录页；`429` + `login_locked` → 提示稍后再试。
2. 上传页：选文件 → `POST /api/upload_file` → 保存 `session_id`，展示 `columns` 表头预览。
3. 若 `needs_sheet_selection`：弹出选择（合并全部 / 勾选若干）→ `POST /api/select_sheets`。
   - 捕获 400 的 `选择的sheet的列名不一致，请重新上传`，引导重新上传。
4. 提问框：`POST /api/upload_message` → **`POST /api/submit/stream`（SSE，逐字渲染）**；需要非流式时回退 `POST /api/submit`。
5. 先渲染 `result` 事件的结果表，再逐段追加 `delta`；`done` 后收尾并记住 `turn_id`。
6. 追问：保持同一 `session_id`，重复第 4 步。
7. 历史页：`GET /api/history`（会话列表）→ `GET /api/sessions/{id}/turns`（该文件问答）→ `GET /api/history/{turn_id}`（单条结果）。点「继续问」先 `POST /api/sessions/{id}/resume`，再走第 4 步；点「删除」用 `DELETE /api/sessions/{id}`（**会连原始文件一起删**，务必二次确认）。
8. 设置页：`POST /api/password/reset`（新密码 + 可选旧密码）→ 成功后清令牌跳登录页。
9. 报告页：填受检单位/编制/审核 → `POST /api/get_pdf`（`fetch` 取 blob 下载，见 §16）；首次 10–40 秒要 loading。
10. 错误处理：`400` toast `detail`；`404` 回到上传页/历史页；`502` 提示重试。

---

## 10. TypeScript 类型定义（可直接复制）

```ts
export interface AuthResponse {
  user_id: number
  username: string
  created_at: string
  /** access token：放进 Authorization: Bearer <token>，默认 30 分钟 */
  token: string
  /** refresh token：access 过期时用它换新，默认 30 天 */
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface TokenPairResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface TurnSummary {
  turn_id: number
  question: string
  answer_preview: string
  degraded: boolean
  created_at: string
}

export interface HistorySessionItem {
  session_id: string
  filename: string
  rows: number
  columns: number
  turn_count: number
  last_question: string
  last_asked_at: string
  created_at: string
  updated_at: string
}

export interface HistorySessionsResponse {
  total: number
  items: HistorySessionItem[]
}

export interface SessionTurnsResponse {
  session_id: string
  filename: string
  rows: number
  columns: number
  turns: TurnSummary[]
}

export interface TurnDetailResponse {
  turn_id: number
  session_id: string
  question: string
  answer: string
  query_spec: Record<string, unknown> | null
  result: QueryResult | null
  degraded: boolean
  error: string
  elapsed_ms: number
  created_at: string
}

export interface ResumeResponse {
  session_id: string
  filename: string
  row_count: number
  column_count: number
  columns: ColumnInfo[]
  conversation_id: string
  turns: TurnSummary[]
  message: string
}

export type StreamEventName = 'stage' | 'result' | 'delta' | 'done' | 'error'

export interface StreamStageEvent {
  stage: 'generating_query' | 'querying' | 'answering'
}

export interface StreamResultEvent {
  query_spec: Record<string, unknown> | null
  result: QueryResult | null
  degraded: boolean
  error: string
}

export interface StreamDeltaEvent {
  text: string
}

export interface StreamErrorEvent {
  detail: string
  code?: string
}

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
  /** 本轮记录 id，可用于 GET /api/history/{turn_id} */
  turn_id: number
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
| `main.py` | 路由、CORS、追问上下文注入、异常 → HTTP 状态码映射、注册/登录/刷新/重置 |
| `auth.py` | 密码哈希（PBKDF2）、双令牌签发/轮换/吊销、登录限流、`get_current_user` 依赖 |
| `auth_store.py` | 用户、刷新令牌、登录失败计数（SQLite，`backend/data/app.db`） |
| `chat_store.py` | 会话与问答记录持久化（历史记录、会话恢复、报告缓存索引） |
| `report_rules.py` | 体检异常判定规则库（阈值 + 规则文本 + 参考来源） |
| `report_stats.py` | 由 DataFrame 计算报告统计数据（全部确定性计算） |
| `report_service.py` | 调用应用3 生成叙述 + 结构与数字校验（不通过则回退模板文字） |
| `report_pdf.py` | reportlab 渲染 A4 PDF（封面 + 八章 + 附录 A/B） |
| `tools/reset_password.py` | 运维兜底：命令行重置密码 |
| `query_spec.py` | Query Spec 校验 + pandas 执行（零 eval）+ 给应用2 的数据格式化 |
| `dify_client.py` | 调用应用1/2，剥离 `<think>`，提取 JSON |
| `file_store.py` | 文件落盘、xlsx/csv 解析、sheet 合并与列名一致性校验、内存会话 |
| `schema_card.py` | 由 DataFrame 生成给应用1 的表结构卡片 |
| `config.py` / `.env` | 配置与密钥 |
| `models.py` | 请求/响应模型（与本文档 §10 对应） |

---

## 13. 认证：注册 / 登录

除 `GET /api/healthy`、`POST /api/register`、`POST /api/login` 外，**其余接口都需要登录**。

### `POST /api/register`

```json
{"username": "alice", "password": "secret123"}
```

| 字段 | 规则 |
|---|---|
| `username` | 3–32 位字母、数字、下划线；**大小写不敏感唯一**（`Alice` 与 `alice` 视为同一人） |
| `password` | 8–64 位 |

成功 `201`（**注册即登录**，直接返回一对令牌）：

```json
{
  "user_id": 1,
  "username": "alice",
  "created_at": "2026-11-09T13:59:13+08:00",
  "token": "<access token，30 分钟有效>",
  "refresh_token": "<refresh token，30 天有效>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

错误：`400` 用户名/密码格式不符；`409` `用户名已存在`

### `POST /api/login`

请求同注册。成功 `200`，返回结构与注册完全一致（access + refresh）。

错误：

- `401` `{"code": "bad_credentials", "detail": "用户名或密码错误"}`（**用户不存在与密码错误返回同一文案**，避免被枚举账号）
- `429` `{"code": "login_locked"}` + `Retry-After`（触发了失败次数限制）

### 双令牌（access + refresh）

| 令牌 | 有效期 | 存放 | 用途 |
|---|---|---|---|
| **access token**（响应里的 `token` 字段） | **30 分钟**（`AUTH_ACCESS_TTL_SECONDS`） | 前端内存 / localStorage | 调所有业务接口 |
| **refresh token**（`refresh_token` 字段） | **30 天**（`AUTH_REFRESH_TTL_SECONDS`） | localStorage | 只用来换新的 access |

- 请求头统一：`Authorization: Bearer <access token>`
- access 过期 → `401` + `{"code": "token_expired"}` → 前端调 `/api/refresh` 换新后重试一次
- 其他 401（伪造 / 已吊销 / 改密作废）→ `{"code": "token_invalid"}` → 直接跳登录页
- access 是 HMAC 签名串，只含 `uid`、令牌版本号、签发/过期时间，不含密码

### `POST /api/refresh`

```json
{"refresh_token": "<refresh>"}
```

成功 `200`：

```json
{"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 1800}
```

- **一次性轮换**：每次刷新都返回新的 refresh，旧的立即作废
- **盗用检测**：拿已用过的 refresh 来换，后端会吊销这一整族令牌（连同正在用的），必须重新登录
- 失败：`401` `{"code": "refresh_invalid"}`

### `POST /api/logout`

需登录。body：`{"refresh_token": "..."}`；不传则吊销该用户**全部** refresh。

```json
{"detail": "已退出登录", "revoked": true}
```

> access 无法单独作废，靠 30 分钟有效期自然过期；改密码会立即让所有 access 失效。

### `POST /api/password/reset`

**一个接口两种模式**：

| 情况 | 请求 | 结果 |
|---|---|---|
| 已登录（带有效 access） | `{"new_password": "...", "old_password": "..."（可选）}` | `200` 重置成功 |
| 未登录 | 同上 | `501` `{"code": "reset_requires_login"}` |

- 登录态下只要求新密码；`old_password` 传了就校验，错误返回 `400` `{"code": "old_password_mismatch"}`
- 新密码不能与原密码相同
- **成功后：旧 access 立即失效、所有 refresh 吊销**，前端应清空令牌跳登录页
- 未登录重置需要邮箱验证，等注册升级成邮箱后开放（接口契约不变）

### 登录失败限制

| 维度 | 阈值 | 结果 |
|---|---|---|
| 用户名 + IP | 15 分钟内失败 5 次 | 锁定 15 分钟 |
| 单个 IP | 15 分钟内失败 20 次 | 锁定 15 分钟 |

- 锁定期间登录（**即使密码正确**）→ `429` + `Retry-After: 900` + `{"code": "login_locked"}`
- 登录成功会清零计数
- 阈值都可在 `.env` 调整

### 会话归属

上传的文件 / `session_id` 绑定到当前用户。用别人的 `session_id` 调用任何接口都返回 `404`，文案与"会话不存在"相同（不泄露存在性）。

### 前端要点

1. 登录/注册后保存 `token` 和 `refresh_token`；本项目不用 Cookie，不需要 `credentials`。
2. 所有业务请求加 `Authorization` 头；`multipart/form-data` 上传也一样。
3. **统一拦截 401**：
   - `code=token_expired` → 调 `/api/refresh`，成功后重试原请求一次
   - `code=token_invalid` → 清空令牌跳登录页
4. `429` + `code=login_locked` → 提示"登录失败次数过多，请稍后再试"。
5. 重置密码成功后清空本地令牌、跳登录页。
6. `401` 与 `404` 分开处理：`401` 是登录态问题，`404` 是会话过期或不属于当前用户。

### 安全说明（演示项目范围）

- 密码 PBKDF2-HMAC-SHA256（20 万次迭代 + 每人随机盐），不存明文
- access 经 HMAC-SHA256 签名；refresh 只存 SHA-256 哈希，一次性使用
- 改密 / 重置会让 `token_version` 递增，旧 access 立即失效
- 未做：邮箱验证码、异常登录告警、HTTPS（**生产环境必须上 HTTPS**）

---

## 14. 历史记录

所有历史接口都按 `user_id` 过滤，越权一律 `404`。记录里存的是**当时的快照**，点开不需要重新查数据、不消耗 Dify 额度。

### `GET /api/history?limit=20&offset=0`

会话列表（按文件分组，最近更新的在前）。`limit` 默认 20、最大 100。

```json
{
  "total": 3,
  "items": [
    {
      "session_id": "s_6c29c63da0ed",
      "filename": "checkup_sample.xlsx",
      "rows": 12,
      "columns": 12,
      "turn_count": 5,
      "last_question": "那他们里女性有多少人？",
      "last_asked_at": "2026-11-09T14:45:16+08:00",
      "created_at": "2026-11-09T14:40:00+08:00",
      "updated_at": "2026-11-09T14:45:16+08:00"
    }
  ]
}
```

### `GET /api/sessions/{session_id}/turns`

该会话下的全部轮次（摘要，按时间正序）。

```json
{
  "session_id": "s_6c29c63da0ed",
  "filename": "checkup_sample.xlsx",
  "rows": 12,
  "columns": 12,
  "turns": [
    {
      "turn_id": 1,
      "question": "年龄大于40岁的人有多少？",
      "answer_preview": "年龄大于40岁的共有 **8 人**…",
      "degraded": false,
      "created_at": "2026-11-09T14:45:16+08:00"
    }
  ]
}
```

### `GET /api/history/{turn_id}`

单轮完整结果（`answer` / `query_spec` / `result` 与 `/api/submit` 的对应字段完全一致）。

```json
{
  "turn_id": 1,
  "session_id": "s_6c29c63da0ed",
  "question": "年龄大于40岁的人有多少？",
  "answer": "年龄大于40岁的共有 **8 人**。…",
  "query_spec": {"op": "count", "filters": [{"column": "年龄", "operator": ">", "value": 40}]},
  "result": {"kind": "count", "row_count": 1, "matched_rows": 8, "value": 8, "columns": ["计数"], "rows": [[8]]},
  "degraded": false,
  "error": "",
  "elapsed_ms": 3120,
  "created_at": "2026-11-09T14:45:16+08:00"
}
```

### `POST /api/sessions/{session_id}/resume`

把历史会话恢复到内存，之后用原有的 `/api/upload_message` + `/api/submit` 继续提问。

```json
{
  "session_id": "s_6c29c63da0ed",
  "file_id": "f_30255428b4bb",
  "filename": "checkup_sample.xlsx",
  "row_count": 12,
  "column_count": 12,
  "columns": [{"name": "年龄", "dtype": "整数", "non_null": 12, "missing": 0, "sample": ["30", "45"]}],
  "conversation_id": "9e508b7f-…",
  "turns": [{"turn_id": 1, "question": "…", "answer_preview": "…", "degraded": false, "created_at": "…"}],
  "message": "会话已恢复，可以继续提问"
}
```

- 恢复时会重建应用1 的追问上下文（问题 + 查询规格）和应用2 的 `conversation_id`，所以「那他们…」这类指代能继续用
- **`file_id` 也在这里返回**：从历史记录进入会话时，用这个 `file_id` 调 `POST /api/get_pdf` 生成报告
- 即使前端不调 resume，直接 `submit` 时后端也会**透明恢复**（第一次多约 1 秒）
- 原始文件已不存在时返回 `404`，文案会说明只能查看历史

### `DELETE /api/sessions/{session_id}`

删除该文件的**全部对话记录**：会话本身、所有轮次，以及上传的原始文件。

```json
{"detail": "已删除该文件的对话记录", "session_id": "s_6c29c63da0ed", "deleted_turns": 5, "file_removed": true}
```

- 需登录；会话不属于当前用户 → `404`（与其他接口一致，不泄露存在性）
- 删除后该会话从历史列表消失，`turns` / `history/{turn_id}` / `resume` 全部返回 `404`
- **原始文件会一并删除**（避免磁盘残留），删完如需继续分析要重新上传
- 重复删除 → `404`

### 历史页推荐交互

```
历史列表（按文件） → 点某个文件 → 轮次列表 → 点某条 → 单轮详情（回答 + 结果表）
                                          → 点「继续问」→ resume → 正常提问
                                          → 点「删除」→ DELETE /api/sessions/{id}（二次确认）
```

---

## 15. 流式输出（SSE）

回答支持逐字流式返回，**推荐前端使用这个接口**；`POST /api/submit` 保留兼容。

### `POST /api/submit/stream`

请求与 `/api/submit` 完全一致（`{"session_id": "..."}`），需要登录，响应 `text/event-stream`。

> ⚠️ **不能用 `EventSource`**：它不支持自定义请求头，带不了 `Authorization`。请用 `fetch` + `ReadableStream` 读取（示例见下）。

### 事件序列

| 事件 | data | 说明 |
|---|---|---|
| `stage` | `{"stage": "generating_query"}` | 正在让应用1 生成查询规格 |
| `stage` | `{"stage": "querying"}` | 正在执行 pandas 查询 |
| `result` | `{"query_spec": {…}, "result": {…}, "degraded": false, "error": ""}` | 查询结果，可立即渲染表格 |
| `stage` | `{"stage": "answering"}` | 应用2 开始生成回答 |
| `delta` | `{"text": "年龄大于"}` | 回答片段，按顺序追加 |
| `done` | 同 `/api/submit` 的响应体（含 `answer`、`turn_id`、`elapsed_ms`） | 结束 |
| `error` | `{"detail": "…", "code": "app1_failed"}` | 出错；收到后终止 |

- `delta` 按顺序拼接后应等于 `done.answer`
- 推理标签 `<think>…</think>` 已由后端剥离（含标签被拆到多个分片的情况），前端直接展示即可
- `degraded=true` 时流程仍然正常：`result` 里 `result: null`，回答是应用2 对失败原因的解释
- 出错时 HTTP 状态已经是 200（流已开始），错误通过 `error` 事件传递

### 前端示例（fetch + 手动解析 SSE）

```js
async function streamAsk(sessionId, { onStage, onResult, onDelta, onDone }) {
  const res = await fetch(`${BASE}/api/submit/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error((await res.json()).detail)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let index
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)

      let event = ''
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!event || !data) continue

      const payload = JSON.parse(data)
      if (event === 'stage') onStage(payload.stage)
      else if (event === 'result') onResult(payload)
      else if (event === 'delta') onDelta(payload.text)
      else if (event === 'done') onDone(payload)
      else if (event === 'error') throw new Error(payload.detail)
    }
  }
}
```

### 注意

- 流程与 `/api/submit` 相同：先 `upload_message`，再调本接口；**成功后问题才清空**，失败可直接重试
- 回答结束后照常写入历史，`done.turn_id` 可直接用于 `GET /api/history/{turn_id}`
- 用户中途关闭页面 → 后端停止生成，**该轮不写入历史**
- 反向代理需要关闭缓冲：后端已返回 `X-Accel-Buffering: no`，Nginx 建议同时加 `proxy_buffering off;`
- 流式和非流式共用同一套落库逻辑，历史记录不会重复

---

## 16. 体检报告 PDF（`POST /api/get_pdf`）

按 `file_id` 生成（或复用）团体体检分析报告 PDF。结构与 `体检报告模板.docx` 一致：封面、报告摘要、一~八章、附录 A（异常统计明细）、附录 B（判定规则与来源）。

### 请求

```json
{
  "file_id": "f_30255428b4bb",
  "unit_name": "某单位",
  "prepared_by": "张三",
  "reviewed_by": "李四",
  "report_date": "2026-11-16"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `file_id` | 是 | 上传接口返回的 `file_id` |
| `unit_name` | 是 | 受检单位（写进封面） |
| `prepared_by` | 是 | 编制人 |
| `reviewed_by` | 是 | 医学审核 |
| `report_date` | 否 | 默认当天，格式 `YYYY-MM-DD` |

### 响应

`200`，`application/pdf`，下载文件名 `{unit_name}体检分析报告.pdf`。

| 响应头 | 值 | 说明 |
|---|---|---|
| `X-Report-Cached` | `true` / `false` | 是否直接复用了之前生成的 PDF |
| `X-Report-Narrative` | `llm` / `fallback` / `cached` | 叙述来源：LLM 生成 / 校验未通过回退模板 / 命中缓存 |

### 缓存规则

- PDF 存到 `backend/reports/{file_id}.pdf`，索引在数据库 `chat_reports` 表
- 同一 `file_id` + 相同封面参数 → 直接返回缓存（秒回）
- 封面参数变化（单位/编制/审核/日期/版本）→ **重新生成并覆盖**
- 重新调用 `/api/select_sheets` → 报告作废（数据变了）
- 删除会话（`DELETE /api/sessions/{id}`）→ 报告与 PDF 一并删除

### 错误

| HTTP | 场景 | detail |
|---|---|---|
| 400 | 未选工作表 | `请先选择要分析的工作表（调用 /api/select_sheets）` |
| 400 | 日期格式不对 | `report_date 格式应为 YYYY-MM-DD` |
| 404 | file_id 不存在或不属于当前用户 | `文件不存在或无权访问` |
| 502 | 应用3 调用失败 | `应用3 执行未成功：…` |

### 前端要点

返回二进制且需要 `Authorization` 头，**不能 `window.open`**，必须 `fetch` 取 blob 再触发下载：

```js
const res = await fetch(`${BASE}/api/get_pdf`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({ file_id, unit_name, prepared_by, reviewed_by }),
})
if (!res.ok) throw new Error((await res.json()).detail)

const blob = await res.blob()
const url = URL.createObjectURL(blob)
const link = document.createElement('a')
link.href = url
link.download = `${unit_name}体检分析报告.pdf`
link.click()
URL.revokeObjectURL(url)
```

- 首次生成约 **10–40 秒**（统计 + 应用3 写叙述 + 排版），需要 loading；二次调用基本瞬时
- 报告**不含姓名、身份证号、联系方式**等个人信息，只呈现汇总数量
- `X-Report-Narrative=fallback` 表示这次 LLM 输出没通过校验（数字对不上或结构不对），已用模板文字兜底，报告本身仍然可用

### 数据口径

- 异常判定规则与参考来源见报告附录 B（如《中国高血压防治指南（2018年修订版）》《中国成人血脂异常防治指南（2016年修订版）》）
- 检出率分母是**该项目有效检查人数**，不同项目分母可能不同；各类异常人数不可相加
- 有效数据少于 10 人的项目不纳入统计（`REPORT_MIN_VALID`）
- 正文分析类别数 5–8（`REPORT_FOCUS_MIN` / `REPORT_FOCUS_MAX`）
