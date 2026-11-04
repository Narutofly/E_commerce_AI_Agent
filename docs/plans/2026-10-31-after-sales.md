# Single merchant after-sales Implementation Plan

**Goal:** 将默认产品迁移为单商家数码售后演示，完成消费者咨询、申请、商家审核及进度闭环。

**Architecture:** 独立 FastAPI 入口 + SQLite 事务持久化 + LangGraph 只读查询图。原教育模块保留供对照，新服务不挂载教育 API，不接受原 JWT。Vue 默认进入 /sales。

**Tech Stack:** 现有 Vue 3 / TypeScript / Vite、FastAPI、LangGraph；Python sqlite3。可选模型通过现有 LLMFactory。

## 现状与方案
- 原项目：PostgreSQL / SQLAlchemy、JWT，教育 QA / Exam / Resume / Interview，多模型启动预热及 Milvus。没有现有售后表，也无本地售后账号可迁移。
- 选择独立 SQLite 业务库，避免教育数据库结构及账号被破坏。另一方案是扩展 PostgreSQL，增加启动依赖；原教育 Agent 就地替换则耦合过高。
- 新库中以稳定用户 ID 维护归属，启动账号规范化仅修改用户名/角色并禁用其他用户，认证版本变更时清理会话；不会重写业务外键。
- 仅 user/customer 与 admin/merchant 可登录，密码 PBKDF2；随机会话令牌哈希持久化、到期及注销失效。
- 工单状态 pending → approved/rejected；approved → completed。提交请求标识按用户唯一，复用不同内容返回冲突。事务 + 部分唯一索引阻止活动工单重复。
- 政策版本乐观锁、不可变版本记录；申请保存全部当前政策快照与代码规则预检。正文不改变固定规则。

## 实施顺序
1. 新建 backend/after_sales/store.py：schema、账号初始化、模拟订单、政策/版本/FTS、事务封装。
2. service.py：所有权检查、申请幂等、状态机、规则与审计。
3. agent.py：意图识别→受限查询→依据回答，持久化对话与关联订单，可选模型超时降级。
4. main.py：请求校验、数据库会话认证、角色依赖、消费者与商家 API。
5. frontend/src/views/AfterSalesView.vue 与 API 类型：两套导航、响应式列表、确认表单、审核、政策与审计。
6. 更新 router 默认路径、启动脚本、独立依赖与 README。
7. tests/test_after_sales.py：认证/隔离/幂等/并发/规则/版本/快照/持久化/模型替身；执行 pytest、vue-tsc 与 build。
8. 浏览器走通完整流程，检查窄屏和运行错误，记录实际验证结果及未验证边界。

## API 契约
前缀 /api/sales；auth/login, auth/me, auth/logout；orders；tickets GET/POST；tickets/{id}/review POST；policies GET、policies/{id} PUT、policies/{id}/versions GET；audit GET；conversations GET/POST、conversations/{id} GET、conversations/{id}/messages POST。
创建申请：order_id, kind(return/exchange), reason, request_id；审核：status, opinion；政策编辑：version, body；聊天：message, order_id?, mode(local/llm)。

## 验证
运行 python -m pytest tests/test_after_sales.py -q；前端 npm run build。浏览器分别登录 user/admin 完成申请、受理、查看意见、完成；手机宽度检查 document scrollWidth。所有实际结论写入 docs/after-sales-acceptance.md。
