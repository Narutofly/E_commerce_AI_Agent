# 新目录启动运行检查

日期：2026-10-31（Asia/Shanghai）。项目：`W:\HeiMa class\Projects\E_commerce_AI_Agent`。

## 结论

可以启动运行。已实际启动新目录前后端并验证接口和浏览器页面，无需修改业务代码。当前检查使用已有的 `edu_agent` Python 环境及已安装的前端依赖，未验证从零安装。

## 本次结果

- 后端：Uvicorn 启动完成，监听 `127.0.0.1:8011`。
- 健康检查：后端 `/api/sales/health` 返回 `status=ok`；前端3011代理同一接口也返回正常结果。
- 前端：Vite 启动完成，监听 `127.0.0.1:3011`。
- `npm run build`：vue-tsc 和 Vite 生产构建通过。
- 后端测试：**19 passed，12.32秒**。存在原 Pydantic 配置弃用警告及 pytest-asyncio scope 提示，不影响通过。
- 浏览器：user 登录、三笔订单显示、关联订单咨询正常；回答引用退换政策v1和运费政策v2，显示实际本地回答模式。
- 浏览器：admin 登录、商家概览和已迁移的历史工单读取正常。
- 本次页面检查捕获的 warn/error 控制台日志为空。
- 本次没有在演示库新增售后工单或修改审核状态；申请、审核、并发和持久化由新目录自动测试验证。真实模型供应商调用仍未验证。

## 启动时发现的环境问题

1. 默认8000/3000端口被其他服务占用，直接使用默认端口会启动失败。本次使用8011/3011，未停止其他项目。
2. pytest 默认临时目录 `C:\Users\Naruto\AppData\Local\Temp\pytest-of-Naruto` 拒绝访问，首轮18个用例在创建临时目录时出错。改用项目内新的独立临时目录后，全部19项通过，属于环境权限问题。

## 本机可用启动命令

终端一：

```powershell
Set-Location 'W:\HeiMa class\Projects\E_commerce_AI_Agent'
& 'C:\Users\Naruto\.conda\envs\edu_agent\python.exe' -m uvicorn backend.after_sales.main:app --host 127.0.0.1 --port 8011
```

终端二：

```powershell
Set-Location 'W:\HeiMa class\Projects\E_commerce_AI_Agent\frontend'
$env:SALES_API_TARGET = 'http://127.0.0.1:8011'
npm run dev -- --host 127.0.0.1 --port 3011 --strictPort
```

页面：http://127.0.0.1:3011/sales 。API文档：http://127.0.0.1:8011/docs 。

消费者 `user / 123456`；商家 `admin / 123456`。

## 避开系统临时目录权限的测试命令

在项目根目录执行，每次生成新的测试目录，避免重用目录触发清理：

```powershell
$salesTestDir = Join-Path (Get-Location) ('.pytest-run-' + [guid]::NewGuid().ToString('N'))
& 'C:\Users\Naruto\.conda\envs\edu_agent\python.exe' -m pytest tests/test_after_sales.py -q --tb=short --basetemp $salesTestDir
```

测试库与演示业务数据库分离，不覆盖演示订单和工单。
