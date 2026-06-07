# 招聘自动化 MVP

一个一下午内可落地的招聘自动化 Demo：

- 多平台采集：支持本地目录、平台导出文件、邮箱未读附件
- AI 解析：自动提取姓名、电话、邮箱、学历、年限、技能
- JD 打分：按岗位 JD 输出匹配分和推荐结论
- 岗位权重：支持 HR 按不同岗位配置能力维度权重，总分 100
- 真实对接：支持企业微信群 Webhook、腾讯文档行追加接口
- 看板展示：本地 Streamlit 页面查看候选人和统计结果

## 目录结构

```text
.
├─ app.py
├─ .env.example
├─ requirements.txt
└─ app
   ├─ config.py
   ├─ incoming
   ├─ data
   ├─ models.py
   ├─ storage
   └─ services
```

## 快速启动

1. 激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

2. 安装依赖

```powershell
pip install -r requirements.txt
```

3. 复制环境变量模板

```powershell
Copy-Item .env.example .env
```

4. 启动页面

```powershell
streamlit run app.py
```

## 环境变量

### LLM

- `LLM_API_KEY`: 大模型 API Key
- `LLM_BASE_URL`: OpenAI 兼容接口地址，默认是 DeepSeek
- `LLM_MODEL`: 使用的模型名

如果不配置 LLM，系统会自动退回到规则解析和规则打分，Demo 也能运行。

### 企业微信群推送

- `WECOM_WEBHOOK_URL`: 群里的消息推送 Webhook

说明：

- 现在支持多岗位多群自动路由，路由表保存在 `app/data/wecom_routes.csv`
- 推荐优先在页面里维护 `position_id -> group_name -> webhook_url`
- `WECOM_WEBHOOK_URL` 仍保留为兜底值，当某个岗位没有单独配置路由时会使用它

### 腾讯文档

- `TENCENT_DOCS_ACCESS_TOKEN`: 腾讯文档开放平台 Access Token
- `TENCENT_DOCS_CLIENT_ID`: 腾讯文档开放平台应用 ID
- `TENCENT_DOCS_OPEN_ID`: 当前授权用户的 Open ID
- `TENCENT_DOCS_FILE_ID`: 腾讯文档文件 ID
- `TENCENT_DOCS_APPEND_ROWS_URL`: 可选，自定义覆盖完整写入接口 URL
- `TENCENT_DOCS_FILE_URL`: 文档打开链接，用于群消息跳转

说明：

- 当前已适配腾讯文档官方 `batchUpdate` 接口，默认会拼接 `https://docs.qq.com/openapi/spreadsheet/v3/files/{fileId}/batchUpdate`
- 工作表 `sheetId` 会自动从 `TENCENT_DOCS_FILE_URL` 的 `tab` 参数中提取
- 若你的租户存在自定义地址，也可以直接填写 `TENCENT_DOCS_APPEND_ROWS_URL` 覆盖默认地址
- 如果你的租户请求体字段不同，只需要调整 [tencent_docs.py](file:///f:/就业/项目/云测/app/services/tencent_docs.py) 里的 `_build_payload`

### 邮箱采集

- `IMAP_ENABLED`: 是否开启邮箱采集，true/false
- `IMAP_HOST`: IMAP 服务器地址
- `IMAP_PORT`: 端口，默认 993
- `IMAP_USER`: 邮箱账号
- `IMAP_PASSWORD`: 邮箱密码或授权码
- `IMAP_FOLDER`: 邮箱文件夹，默认 `INBOX`

### 状态邮件分发

- `SMTP_HOST`: SMTP 服务器地址
- `SMTP_PORT`: SMTP 端口，默认 `587`
- `SMTP_USER`: 发件邮箱账号
- `SMTP_PASSWORD`: 发件邮箱密码或授权码
- `SMTP_FROM`: 发件人邮箱
- `SMTP_USE_TLS`: 是否启用 TLS，true/false
- `SMTP_USE_SSL`: 是否启用 SSL，true/false

常见邮箱示例：

- QQ 邮箱
  - `SMTP_HOST=smtp.qq.com`
  - `SMTP_PORT=587`
  - `SMTP_USE_TLS=true`
  - `SMTP_USE_SSL=false`
- 163 邮箱
  - `SMTP_HOST=smtp.163.com`
  - `SMTP_PORT=465`
  - `SMTP_USE_TLS=false`
  - `SMTP_USE_SSL=true`

## 演示流程

1. 上传几份 PDF/DOCX/TXT 简历，或从邮箱拉取附件
2. 在左侧维护岗位库，填写 `岗位ID / 岗位名称 / JD`
3. 在左侧维护企业微信群路由，填写 `岗位ID / 群名称 / Webhook`
4. 点击“批量处理并同步”
5. 系统自动完成：
   - 文本提取
   - 姓名/电话识别
   - 简历重命名
   - JD 打分
   - 写入本地 CSV
   - 按岗位 ID 自动路由推送到对应企业微信群
   - 调用腾讯文档接口追加行

## 代码入口

- 主页面：[app.py](file:///f:/就业/项目/云测/app.py)
- 简历解析：[resume_parser.py](file:///f:/就业/项目/云测/app/services/resume_parser.py)
- JD 打分：[scoring.py](file:///f:/就业/项目/云测/app/services/scoring.py)
- 企业微信通知：[notifier.py](file:///f:/就业/项目/云测/app/services/notifier.py)
- 腾讯文档接口：[tencent_docs.py](file:///f:/就业/项目/云测/app/services/tencent_docs.py)
