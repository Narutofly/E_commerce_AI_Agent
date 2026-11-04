# 单商家数码售后平台第一版

## 启动
从项目根目录运行（两个终端）：

```powershell
python -m pip install -r requirements-after-sales.txt
python -m uvicorn backend.after_sales.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

默认访问 http://127.0.0.1:3000/sales ，根路径及原教育页面路径均重定向至 /sales。
API 文档：http://127.0.0.1:8000/docs 。也提供 scripts/start-after-sales.ps1（支持 -Python 与 -Port）及 scripts/start-after-sales-frontend.ps1。

本机可用 Python：`C:\Users\Naruto\.conda\envs\edu_agent\python.exe`。系统的 python 别名不可执行，Anaconda base 不包含 FastAPI，需选用已装好依赖的环境或新建 venv。

本次验收未停止已占用8000的其他服务，实际使用：

```powershell
& 'C:\Users\Naruto\.conda\envs\edu_agent\python.exe' -m uvicorn backend.after_sales.main:app --host 127.0.0.1 --port 8011
# 另一终端
cd frontend
$env:SALES_API_TARGET='http://127.0.0.1:8011'
npm run dev -- --host 127.0.0.1 --port 3011
```

## 演示账号与步骤
- user / 123456：内部角色 customer。
- admin / 123456：内部角色 merchant。
- user 登录，订单页查看三笔模拟数码订单；选订单咨询“退货政策和运费由谁承担？”，核对回答中的政策标题、版本与实际回答模式。
- 返回订单页申请售后，选择退货/换货、填写原因并勾选确认。重复点击被页面锁定；网络重试使用同一请求标识。
- admin 登录，工单审核页查看原因、规则预检及政策快照，填写意见后受理或拒绝。已受理可继续填写意见并记录处理完成。
- user 再登录，在我的申请点击刷新，查看状态、意见；在原会话查询申请进度。
- admin 在政策管理保存新版本，查看版本历史；新咨询会检索当前政策，原工单快照保持不变。操作记录包含登录、申请、审核与政策更新。

## 数据与权限
默认数据库 `backend/after_sales/data/after_sales.sqlite3`；可设置 AFTER_SALES_DB 为另一个文件路径。请保留数据库文件，重启不会重置订单签收时间、工单、政策或聊天。首次启动种子只插入缺失记录。WAL 模式，单次写事务 BEGIN IMMEDIATE；不建议放到网络共享盘或使用大量并发写入。

密码采用带随机盐的 PBKDF2-SHA256；登录令牌随机生成，数据库仅保存其 SHA256，12小时过期，注销立即失效。只有两个指定名称能登录，角色由数据库校验，不信任请求参数。存在一个无法登录的隔离测试数据所有者，便于验证越权分支。

原教育 PostgreSQL 用户及业务数据保持原样，新入口不挂载教育 API，不接受原 JWT；原账号无法登录新产品。这里不是把教育数据自动转换成电商订单。新售后库账号规范化时按原 ID 修改 user1/student01 等已知别名，其他账号停用，发生身份变化时撤销所有会话，保留业务外键。该迁移针对本版 schema，非任意第三方数据库导入器。

申请的 request_id 按用户唯一，相同内容重试返回同一工单，内容不同返回409。部分唯一索引保证每订单最多一个 pending/approved；已拒绝/已完成后允许新申请。状态机只允许 pending→approved/rejected、approved→completed，审核串行事务校验状态。政策版本冲突返回409；版本历史和申请快照独立保存。

固定规则：从签收时刻起退货7×24小时、换货30×24小时；超期标记例外审核，仍创建 pending。政策管理只编辑正文，页面明确提示不会自动修改代码规则。金额存储为整数分。

## Agent 与模型边界
LangGraph：intent→query→answer。意图采用本地关键词；工具查询始终限定当前认证用户，保存会话历史、关联订单和每条回答的证据。默认本地政策检索与规则回答；未知问题返回证据不足，聊天没有创建/审核能力。

政策通过 SQLite FTS5 trigram 和关键词匹配检索；环境不支持 trigram 时自动使用关键词。未接入原 BGE-M3、Milvus、Reranker。数据保存在 SQLite，没有 LangGraph 持久化 checkpointer。

可选大模型通过原 `LLMFactory.get_llm('after_sales')`，复用原 `.env.local` 的供应商配置；执行 `python -m pip install -r requirements-after-sales-llm.txt` 安装模型工厂所需依赖（已有全量环境无需重复安装）。8秒超时或失败显式降级，回答标签显示实际模式。模型只接收已校验用户证据与最近8条会话，不能直接执行工具或更改状态。真实供应商调用没有纳入本次验收，成功/失败用替身验证。仅装最小依赖时模型工厂契约测试会跳过，其余本地与降级测试仍可运行。

## 构建与部署范围
后端 `python -m pytest tests/test_after_sales.py -q`；前端 `cd frontend; npm run build`，包含 vue-tsc。
开发服务器 /api 代理默认指向8000，可通过 SALES_API_TARGET 改端口。生产构建在 frontend/dist，需要静态托管支持 history 路由回退，并将 /api 反代到售后后端；本次没有部署公网服务。

未实现：真实订单/物流/退款、多商家租户、附件/OCR、生产认证（验证码、限流、密码管理、HTTPS部署等）。模拟受理和完成均不证明真实退款或寄回。
