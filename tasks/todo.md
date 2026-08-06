# 实施计划：AI Chatbot Demo（网页 + WhatsApp）

对应设计文档：[docs/superpowers/specs/2026-08-05-ai-chatbot-demo-design.md](../docs/superpowers/specs/2026-08-05-ai-chatbot-demo-design.md)

## 怎么用这份清单（防止 session hit limit）

Claude Code 的用量限制是按时间窗口算的，一个 session 里塞的任务越多、读写文件越多、来回调试越多，越容易在做到一半时被打断，浪费掉的上下文和工作量也越多。用下面的拆分方式来规避：

1. **一个 session 只做一个编号任务**（如"任务 3"），做完立刻验收 + commit，再开新的 `claude` session 做下一个任务。不要在一个 session 里连续做多个任务。
2. **每个任务开始时，只需要让 Claude 读这份 `todo.md` + 设计文档 + 任务里点名的几个文件**，不需要回顾整个开发过程——因为上一个任务已经 commit 完毕、状态是干净的，新 session 靠读代码本身就能接上，不需要依赖对话记忆。
3. **任务粒度已经控制在"1-3 个文件、单一目的、可独立验收"**，正常情况下一个任务在一个 session 内能跑完并留有余量。如果某个任务做到一半感觉 session 快不够用了，优先让当前这一小步收尾到"能跑通、能 commit"的状态，而不是硬做完整个任务再收尾。
4. 每个任务做完在下面把 `[ ]` 改成 `[x]`，这样任何一个新 session 打开这个文件就知道进度到哪，不需要提问"之前做到哪了"。

## 本地验证方式说明

本地机器上已有 Docker 环境（跑着别的项目用的 Redis、MySQL，与本项目无关，本项目不使用它们）。为了让本地验证的运行环境尽量贴近 VPS 部署环境，约定：

- **后端**：从任务 2 起，"服务真正跑起来"的验收（curl 测接口、模拟 webhook 请求）一律通过 `docker compose up` 完成，不再用裸 `uvicorn`。`docker-compose.yml` 里给源码目录挂 volume + `uvicorn --reload`，改代码不需要重新 build 镜像。纯逻辑的 `pytest` 单元测试可以继续在本地 venv 里跑，更快，不强制进容器。
- **前端**：开发阶段（任务 10-13）继续用 `npm run dev`，体验和热更新更好，前端产物是静态文件，运行时环境差异对它影响不大。到任务 14 才补前端 Dockerfile，和后端一起进同一个 `docker-compose.yml` 做整体联调。
- **部署到 VPS**（任务 15）用的就是本地已经验证过的同一份 `docker-compose.yml`，理论上环境差异降到最低。

## 后端

- [x] **任务 1：项目骨架 + 配置**
  文件：`backend/app/main.py`、`backend/app/config.py`、`backend/requirements.txt`、`backend/.env.example`
  目标：FastAPI 应用能起来，有一个 `/health` 接口返回 200
  验收：`uvicorn app.main:app --reload` 启动成功，`curl localhost:8000/health` 返回正常
  （本任务是裸 venv 验证的，之后的任务改用 docker compose，见下）

- [x] **任务 2：后端容器化**
  文件：`backend/Dockerfile`、`docker-compose.yml`
  目标：把任务 1 的 FastAPI 服务用 Docker 跑起来，源码挂载支持热重载，端口不与本机已有的 Redis(6379)/MySQL(3306) 冲突
  验收：`docker compose up` 启动后 `curl localhost:8000/health` 返回正常；改动 `main.py` 后无需重新 build 就能看到效果

- [x] **任务 3：Bot registry + mock 数据（retail / hotel / banking）**
  文件：`backend/app/bots/registry.py`、`backend/app/bots/data/retail.json`、`hotel.json`、`banking.json`
  目标：registry 能加载这 3 个类型的元数据、2-3 个演示身份、3-4 条快捷问题、mock 业务数据（RM 计价，马来西亚风格）
  验收：本地 venv 跑 pytest，打印/断言这 3 个 bot 都能被正确加载

- [x] **任务 4：Bot registry + mock 数据（food / realestate / saas）**
  文件：`backend/app/bots/data/food.json`、`realestate.json`、`saas.json`
  目标：补完剩余 3 个类型，结构与任务 3 一致
  验收：同任务 3，本地 venv 跑 pytest，6 个类型全部能加载

- [x] **任务 5：会话存储**
  文件：`backend/app/session_store.py`
  目标：内存字典存会话（bot 类型 + 身份 + 历史），历史截断到最近 ~20 轮，WhatsApp 每日消息计数限流，message id 去重
  验收：本地 venv 跑 pytest，覆盖：写入/读取会话、历史截断生效、超过限流阈值后拒绝、重复 message id 被识别

- [x] **任务 6：Claude API 封装**
  文件：`backend/app/services/llm.py`
  目标：组装 system prompt（bot 人设 + 身份数据 + 语言指令 + 长度约束 + 防注入），调用 Claude API，失败时返回兜底提示
  验收：`docker compose up` 起服务后（容器内能出网访问 Anthropic API），针对某个 bot+身份问一个问题，确认回复内容对得上 mock 数据；再模拟 API 报错场景确认兜底提示生效

- [x] **任务 7：网页端 REST 接口**
  文件：`backend/app/routers/chat.py`、`backend/app/models.py`
  目标：访问口令校验、创建会话、选类型、选身份、发消息、重置会话
  验收：`docker compose up` 起服务后，用 curl 走一遍完整链路（口令 → 建会话 → 选类型 → 选身份 → 发消息拿到回复 → 重置）

- [x] **任务 8：WhatsApp API 封装**
  文件：`backend/app/services/whatsapp.py`
  目标：发文本消息、发交互式列表消息、签名校验（`X-Hub-Signature-256`）、markdown → WhatsApp 格式转换
  验收：本地 venv 跑 pytest，覆盖签名校验函数和 markdown 转换函数；发送函数用 mock HTTP 验证请求体格式正确

- [x] **任务 9：WhatsApp webhook**
  文件：`backend/app/routers/whatsapp_webhook.py`
  目标：GET 验证握手、POST 立即返回 200 + `BackgroundTasks` 异步处理、类型/身份两级交互列表选择、非文本消息提示、限流拦截
  验收：`docker compose up` 起服务后，用 curl 模拟 Meta 的 webhook 请求格式（含签名）跑通：验证握手、首次消息触发类型列表、选类型后触发身份列表、选完进入正常问答、重复发送同一 message id 被去重

## 前端

- [x] **任务 10：前端脚手架 + i18n**
  文件：`frontend/`（Vite + React + TS 初始化）、`frontend/src/i18n/strings.ts`、`frontend/src/api.ts`
  目标：项目能跑起来，中/英/马来语三语字典就位，封装好调后端接口的函数
  验收：`npm run dev` 能看到空白页正常渲染，无报错

- [x] **任务 11：访问口令页 + 选择页**
  文件：`frontend/src/pages/PasswordGate.tsx`、`frontend/src/pages/BotSelect.tsx`
  目标：输口令校验通过后进入 bot 卡片网格选择页，响应式布局
  验收：浏览器里手动走一遍，手机尺寸和桌面尺寸都正常

- [x] **任务 12：身份选择页 + 聊天页骨架**
  文件：`frontend/src/pages/IdentitySelect.tsx`、`frontend/src/pages/Chat.tsx`
  目标：选完身份进入聊天页，能发消息、收到后端真实回复，基础气泡 UI
  验收：浏览器里选类型 → 选身份 → 发一条消息 → 收到 Claude 回复

- [x] **任务 13：聊天页体验完善**
  文件：`frontend/src/pages/Chat.tsx`、相关样式文件
  目标：快捷问题按钮、"重新开始"按钮、发送失败重试提示、语言切换、loading 态
  验收：完整走一遍：点快捷问题发送、切换三种语言收到对应语言回复、断网时看到失败重试提示、点重新开始清空会话

## 部署

- [x] **任务 14：前端容器化 + 整体联调**
  文件：`frontend/Dockerfile`、`docker-compose.yml`（扩展，加入 frontend 服务）
  目标：`docker compose up` 一次性跑起后端 + 前端，本地用容器化的完整拓扑走一遍全流程
  验收：容器跑起来后，浏览器访问前端能完整聊一轮（选类型 → 选身份 → 对话）

- [ ] **任务 15：部署到服务器**（代码和容器都已就绪，卡在 DNS，见评审记录）
  文件：`docker-compose.prod.yml`、`.github/workflows/deploy.yml`、`deploy/nginx/chatbot.acuventech.com.conf`
  目标：实际采用的方案和最初设计不同——服务器已有多个项目共用一个 Docker 化的 Nginx（`infra_nginx`，走共享的 `proxy_net` 网络，域名证书是 `*.acuventech.com` 通配符证书，不需要单独申请）。部署改成 GitHub Actions 自动化：push 到 master → 构建 backend/frontend 镜像推到 GHCR → SSH 进服务器 `git pull` + `docker compose -f docker-compose.prod.yml pull/up`，和这台服务器上其他项目（demo_os 等）的模式保持一致
  验收：用域名通过 HTTPS 访问到网页端（DNS 加好后待验证）

- [ ] **任务 16：Meta webhook 注册 + WhatsApp 真机联调**
  目标：Meta 开发者后台注册 webhook URL 并验证通过；需要用户用真实手机发消息测试完整流程
  验收：用户手机发消息给 WhatsApp 号码，走完选类型→选身份→问答的完整流程

## 可选项（非必须，MVP 之后再看要不要做）

- [ ] 每个 bot 类型加不同主色调，视觉上更像"独立产品"而非同一套壳子
- [ ] WhatsApp 端显示"正在输入"状态，网页端加打字动画，体验更真实
- [ ] 更完整的 markdown → WhatsApp 格式转换（列表、链接等，目前只处理加粗/代码）

## 评审记录

（每个任务完成后，如有偏离原方案的地方或踩坑教训，记录在这里）

- 2026-08-05：新增"后端容器化"任务（原任务 2 之后插入），后续任务编号整体 +1。原因：本地已有 Docker 环境，希望本地验证的运行环境从早期就贴近 VPS 部署环境，减少移植时的意外。Redis/MySQL 确认与本项目无关，不引入这两个依赖。
- 2026-08-05（任务 9）：webhook 里顺带实现了 WhatsApp 端的快捷问题按钮（quick reply buttons），虽然任务 9 的目标描述里没有单独列出，但设计文档明确要求 WhatsApp 端要有和网页端对等的快捷问题体验，属于该任务合理的实现范围。
- 2026-08-05（任务 9）：本地测试发现，`WHATSAPP_ACCESS_TOKEN` 为空时会导致 `Authorization: Bearer ` 请求头非法，httpx 直接抛 `LocalProtocolError`。这在生产环境不会发生（部署时必须配置真实 token），且已被 webhook 顶层的 try/except 兜住不会导致服务崩溃，所以未做额外处理，只是记录下来。
- 2026-08-05（任务 9）：给 `main.py` 加了 `logging.basicConfig(level=logging.INFO)`，否则应用日志默认级别是 WARNING，webhook 里的内部流转日志（选类型、去重、限流等）看不到，验证时不好排查。
- 2026-08-05（任务 12）：浏览器验证时发现，这个环境的 `computer` 工具模拟鼠标点击 `type="submit"` 按钮偶发不会真正触发表单提交（点击坐标/时序问题，不是代码 bug）。用 `element.click()` / `form.requestSubmit()` 通过 `javascript_tool` 直接触发是可靠的替代方式，后续 UI 验证优先用这种方式。顺带确认了 React StrictMode 下 `BotSelect` 的 `useEffect` 会按预期触发两次请求（开发模式的正常行为，两次都成功，不影响功能）。
- 2026-08-05（任务 13）：聊天页里切换语言不会重置对话（原方案没细化这点）。原因：如果每次切语言都清空对话会很突兀，而且 Claude 本来就是按用户实际打字的语言回复，跟 UI 语言开关是两回事——UI 文案（按钮、输入框占位符）照常跟着语言切换实时变化，只是不重新拉取开场白/清空历史。只有真正开一个新会话（换 bot/身份/session）才会重置。
- 2026-08-06（任务 15）：部署架构和原方案（host 级 Nginx + Certbot）不同——服务器上已经有一套多项目共用的 Docker 化 Nginx（`infra_nginx`，走 `proxy_net` 共享网络，域名走 `*.acuventech.com` 通配符证书），其他项目（demo_os/crm_os/erp_os）都用同样的 GHCR 镜像 + GitHub Actions 自动部署模式。为保持一致性照做，同时新增 `docker-compose.prod.yml` 让本地开发（build 本地镜像、暴露 host 端口）和生产（拉 GHCR 镜像、只接 `proxy_net`、不暴露 host 端口）分开，互不影响。
- 2026-08-06（任务 15）：`appleboy/ssh-action` 的多行 `script` 字段里用 `${{ secrets.VPS_DEPLOY_PATH }}` 时，实际执行时 `cd` 没有拿到真实路径（服务器上残留在默认登录目录，导致 `git pull` 报 "not a git repository"）。部署路径本身不是敏感信息，改成直接写死在 workflow 的 `env:` 里、不再用 secret，问题消失，顺手把这个 secret 删掉了。
- 2026-08-06（任务 15）：`docker login ghcr.io` 用的是当次 workflow run 的临时 `GITHUB_TOKEN`，run 结束后这个登录凭据就失效了——如果之后要手动在服务器上单独 `docker compose pull`（不经过 workflow），会因为登录过期报 `denied`，需要重新登录一次（用 `gh auth token` 或者一个 PAT）。自动化流程本身没问题，因为每次 workflow run 都会重新登录。
