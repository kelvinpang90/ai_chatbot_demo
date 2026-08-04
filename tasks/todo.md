# 实施计划：AI Chatbot Demo（网页 + WhatsApp）

对应设计文档：[docs/superpowers/specs/2026-08-05-ai-chatbot-demo-design.md](../docs/superpowers/specs/2026-08-05-ai-chatbot-demo-design.md)

## 怎么用这份清单（防止 session hit limit）

Claude Code 的用量限制是按时间窗口算的，一个 session 里塞的任务越多、读写文件越多、来回调试越多，越容易在做到一半时被打断，浪费掉的上下文和工作量也越多。用下面的拆分方式来规避：

1. **一个 session 只做一个编号任务**（如"任务 3"），做完立刻验收 + commit，再开新的 `claude` session 做下一个任务。不要在一个 session 里连续做多个任务。
2. **每个任务开始时，只需要让 Claude 读这份 `todo.md` + 设计文档 + 任务里点名的几个文件**，不需要回顾整个开发过程——因为上一个任务已经 commit 完毕、状态是干净的，新 session 靠读代码本身就能接上，不需要依赖对话记忆。
3. **任务粒度已经控制在"1-3 个文件、单一目的、可独立验收"**，正常情况下一个任务在一个 session 内能跑完并留有余量。如果某个任务做到一半感觉 session 快不够用了，优先让当前这一小步收尾到"能跑通、能 commit"的状态，而不是硬做完整个任务再收尾。
4. 每个任务做完在下面把 `[ ]` 改成 `[x]`，这样任何一个新 session 打开这个文件就知道进度到哪，不需要提问"之前做到哪了"。

## 后端

- [ ] **任务 1：项目骨架 + 配置**
  文件：`backend/app/main.py`、`backend/app/config.py`、`backend/requirements.txt`、`backend/.env.example`
  目标：FastAPI 应用能起来，有一个 `/health` 接口返回 200
  验收：`uvicorn app.main:app --reload` 启动成功，`curl localhost:8000/health` 返回正常

- [ ] **任务 2：Bot registry + mock 数据（retail / hotel / banking）**
  文件：`backend/app/bots/registry.py`、`backend/app/bots/data/retail.json`、`hotel.json`、`banking.json`
  目标：registry 能加载这 3 个类型的元数据、2-3 个演示身份、3-4 条快捷问题、mock 业务数据（RM 计价，马来西亚风格）
  验收：写一个简单脚本或 pytest，打印/断言这 3 个 bot 都能被正确加载

- [ ] **任务 3：Bot registry + mock 数据（food / realestate / saas）**
  文件：`backend/app/bots/data/food.json`、`realestate.json`、`saas.json`
  目标：补完剩余 3 个类型，结构与任务 2 一致
  验收：同任务 2，6 个类型全部能加载

- [ ] **任务 4：会话存储**
  文件：`backend/app/session_store.py`
  目标：内存字典存会话（bot 类型 + 身份 + 历史），历史截断到最近 ~20 轮，WhatsApp 每日消息计数限流，message id 去重
  验收：pytest 覆盖：写入/读取会话、历史截断生效、超过限流阈值后拒绝、重复 message id 被识别

- [ ] **任务 5：Claude API 封装**
  文件：`backend/app/services/llm.py`
  目标：组装 system prompt（bot 人设 + 身份数据 + 语言指令 + 长度约束 + 防注入），调用 Claude API，失败时返回兜底提示
  验收：用真实 `ANTHROPIC_API_KEY` 跑一次脚本，针对某个 bot+身份问一个问题，确认回复内容对得上 mock 数据；再模拟 API 报错场景确认兜底提示生效

- [ ] **任务 6：网页端 REST 接口**
  文件：`backend/app/routers/chat.py`、`backend/app/models.py`
  目标：访问口令校验、创建会话、选类型、选身份、发消息、重置会话
  验收：用 curl 走一遍完整链路（口令 → 建会话 → 选类型 → 选身份 → 发消息拿到回复 → 重置）

- [ ] **任务 7：WhatsApp API 封装**
  文件：`backend/app/services/whatsapp.py`
  目标：发文本消息、发交互式列表消息、签名校验（`X-Hub-Signature-256`）、markdown → WhatsApp 格式转换
  验收：pytest 覆盖签名校验函数和 markdown 转换函数；发送函数用 mock HTTP 验证请求体格式正确

- [ ] **任务 8：WhatsApp webhook**
  文件：`backend/app/routers/whatsapp_webhook.py`
  目标：GET 验证握手、POST 立即返回 200 + `BackgroundTasks` 异步处理、类型/身份两级交互列表选择、非文本消息提示、限流拦截
  验收：用 curl 模拟 Meta 的 webhook 请求格式（含签名）跑通：验证握手、首次消息触发类型列表、选类型后触发身份列表、选完进入正常问答、重复发送同一 message id 被去重

## 前端

- [ ] **任务 9：前端脚手架 + i18n**
  文件：`frontend/`（Vite + React + TS 初始化）、`frontend/src/i18n/strings.ts`、`frontend/src/api.ts`
  目标：项目能跑起来，中/英/马来语三语字典就位，封装好调后端接口的函数
  验收：`npm run dev` 能看到空白页正常渲染，无报错

- [ ] **任务 10：访问口令页 + 选择页**
  文件：`frontend/src/pages/PasswordGate.tsx`、`frontend/src/pages/BotSelect.tsx`
  目标：输口令校验通过后进入 bot 卡片网格选择页，响应式布局
  验收：浏览器里手动走一遍，手机尺寸和桌面尺寸都正常

- [ ] **任务 11：身份选择页 + 聊天页骨架**
  文件：`frontend/src/pages/IdentitySelect.tsx`、`frontend/src/pages/Chat.tsx`
  目标：选完身份进入聊天页，能发消息、收到后端真实回复，基础气泡 UI
  验收：浏览器里选类型 → 选身份 → 发一条消息 → 收到 Claude 回复

- [ ] **任务 12：聊天页体验完善**
  文件：`frontend/src/pages/Chat.tsx`、相关样式文件
  目标：快捷问题按钮、"重新开始"按钮、发送失败重试提示、语言切换、loading 态
  验收：完整走一遍：点快捷问题发送、切换三种语言收到对应语言回复、断网时看到失败重试提示、点重新开始清空会话

## 部署

- [ ] **任务 13：容器化**
  文件：`backend/Dockerfile`、`frontend/Dockerfile`、`docker-compose.yml`
  目标：本地 `docker-compose up` 能跑通完整应用（后端单进程启动）
  验收：本地容器跑起来后，浏览器能访问前端并完整聊一轮

- [ ] **任务 14：部署到服务器**
  文件：`deploy/README-deploy.md` + 实际 SSH 操作（不是纯代码任务，需要用户提供服务器访问方式和域名）
  目标：DNS 指向服务器、Nginx 反向代理、Let's Encrypt HTTPS 证书、服务跑起来
  验收：用域名通过 HTTPS 访问到网页端

- [ ] **任务 15：Meta webhook 注册 + WhatsApp 真机联调**
  目标：Meta 开发者后台注册 webhook URL 并验证通过；需要用户用真实手机发消息测试完整流程
  验收：用户手机发消息给 WhatsApp 号码，走完选类型→选身份→问答的完整流程

## 可选项（非必须，MVP 之后再看要不要做）

- [ ] 每个 bot 类型加不同主色调，视觉上更像"独立产品"而非同一套壳子
- [ ] WhatsApp 端显示"正在输入"状态，网页端加打字动画，体验更真实
- [ ] 更完整的 markdown → WhatsApp 格式转换（列表、链接等，目前只处理加粗/代码）

## 评审记录

（每个任务完成后，如有偏离原方案的地方或踩坑教训，记录在这里）
