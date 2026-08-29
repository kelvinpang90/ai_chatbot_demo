# 实施计划：引擎盖计划（WhatsApp 炫技升级）

方案文档：https://claude.ai/code/artifact/638f064c-a775-4633-b211-41bf08dbc973
v1 MVP 的实施记录已归档到 [tasks/todo-v1-mvp.md](todo-v1-mvp.md)（任务 1-16.1 全部完成）。

一句话目标：客户在自己手机的 WhatsApp 里跟 bot 聊天，你的笔记本上是另一块屏，实时滚着工具调用、真实 API 参数和 ERP 后台的每一次数据变化。左边是他看到的，右边是他要买的。

## 怎么用这份清单

沿用 v1 的约定，不变：

1. **一个 session 只做一个编号任务**，做完立刻验收 + commit，再开新 session 做下一个。
2. **每个任务开始时只需读这份 `todo.md` + 任务里点名的几个文件**，不依赖对话记忆。
3. 任务粒度控制在「1-3 个文件、单一目的、可独立验收」。做到一半觉得 session 快不够用，就先把当前这一小步收尾到「能跑通、能 commit」。
4. 做完把 `[ ]` 改成 `[x]`，任何新 session 打开就知道进度。

新增一条：

5. **每个批次的最后一个任务是「真机验收」，必须由用户拿手机完成，Claude 做不了。** 这类任务不要试图用模拟 webhook 糊弄过去——模拟能验证代码路径，验证不了「拍照识别准不准」「PDF 在手机上打不打得开」「语音听不听得懂马来语」。

## 已定下的前提（不再重新讨论）

- 主战场是 WhatsApp 真机；网页降级为「导演台」大屏 + 一条备份聊天线
- 真接 `crm_os` / `erp_os`，读写皆可，不做数据隔离（本来就是 demo 数据）
- 行业三档：旗舰 `retail`；深度 `food` + `realestate`（自建轻量后端）；轻量 `hotel` + `saas`；`banking` 下架
- 七件武器全要：图片识别 / 语音消息 / 发文件 / 交互按钮 / Flows / 主动推送 / 转人工
- ERP 一侧**走 `erp_os` 自己的 REST 路由，不裸连 MySQL**——写入要经过业务逻辑，否则后台刷出来是脏单，演示当场翻车

## 开工前的三个阻塞项（需要用户处理）

- [ ] **A. `erp_os` / `crm_os` 的 demo API 账号**——或者授权 Claude 上 VPS 自建。阻塞任务 8 及之后所有 ERP 相关任务。
- [ ] **B. Meta 后台三个入口确认能点**——媒体权限、模板提审、Flows。用户已确认后台可用，但任务 18 的模板提审要在批次 03 第一天就提交（审核要几小时到 1-2 天）。
- [ ] **C. 语音转录选型拍板**——外部 API（准、快、多一个供应商）vs 自托管 faster-whisper（无外部依赖、CPU 上每条慢 3-5 秒、吃 VPS 内存）。阻塞任务 15。建议先接外部 API 把戏跑通，转录做成抽象层，之后换实现只是换一个类。

---

## 批次 00：地基（不对客户展示）

> 没有客户看得见的东西，但后面五批全部压在这一批上。
> **这一批是整个工程唯一有回归风险的地方**——`whatsapp_gateway` 是 `ai_chatbot_demo`、`crm_os`、`acuven_aichat` 三家共用的。所以它单独成批、单独验收，在动它之后、堆功能之前先确认那两条线没坏。

- [ ] **任务 1：网关内网 API —— 媒体下载代理**
  项目：`whatsapp_gateway`
  文件：`app/routers/internal_media.py`（新增）、`app/services/whatsapp.py`（加 `fetch_media`）、`tests/test_internal_media.py`（新增）
  目标：`POST /internal/media/fetch`，body `{"media_id": "..."}`，校验 `X-Internal-Secret`。内部两步：`GET /{media_id}` 拿临时 URL，再带 token 下载二进制，返回二进制流 + `Content-Type`
  验收：pytest 覆盖密钥校验（缺失/错误 401）、Graph 两步调用的 mock；再用真实 `media_id` curl 拉一张图下来能打开

- [ ] **任务 2：网关内网 API —— 媒体上传 + 主动外发**
  项目：`whatsapp_gateway`
  文件：`app/routers/internal_media.py`（扩展）、`app/routers/internal_send.py`（新增）、`app/services/whatsapp.py`、对应测试
  目标：`POST /internal/media/upload`（multipart）→ 返回 `media_id`；`POST /internal/send`（body 为 Meta 发送 payload）→ 直接调 Graph 外发，返回结果。两个都校验 `X-Internal-Secret`
  验收：pytest；curl 上传一个 PDF 拿到 `media_id`；用 `/internal/send` 给自己手机发一条文本消息，手机收到

- [ ] **任务 3：网关回归验证**
  项目：`whatsapp_gateway`（不改代码，只验证）
  目标：确认新增三条 API 之后，现有三个下游链路完全不受影响
  验收：用户拿手机走一遍——顶层菜单 → 进 `ai_chatbot` demo 问一句拿到回复 → 回菜单 → 进 `crm_os` demo 问一句拿到回复。再确认 `acuven_aichat` 那条线（公司客服号）正常
  说明：这是用户任务，Claude 只负责在验收前把三个容器日志的观察点写清楚

- [ ] **任务 4：ai_chatbot 侧的网关客户端封装**
  文件：`backend/app/services/gateway.py`（新增）、`backend/app/config.py`、`backend/tests/test_gateway.py`（新增）
  目标：封装 `fetch_media(media_id)` / `upload_media(bytes, mime, filename)` / `send_message(payload)` 三个函数，统一带 `X-Internal-Secret`；config 新增 `gateway_internal_base_url`
  验收：pytest 用 mock HTTP 验证三个函数的请求 URL、header、body 格式正确

- [ ] **任务 5：LLM 工具调用循环**
  文件：`backend/app/services/llm.py`、`backend/app/tools/registry.py`（新增）、`backend/tests/test_llm.py`
  目标：从单轮 `messages.create` 改成 SDK 的 tool runner（`@beta_tool` + `client.beta.messages.tool_runner()`）。工具列表按 bot 从 registry 取，**工具为空时行为与现在完全一致**——这是回归的安全绳
  验收：pytest 覆盖「无工具时输出不变」和「有工具时会调用并把结果喂回去」；`docker compose up` 后网页端问一句，确认回复正常（旧行为回归）

- [ ] **任务 6：事件总线 + 导演台 SSE 骨架**
  文件：`backend/app/console/events.py`（新增）、`backend/app/routers/console.py`（新增）、`backend/app/services/llm.py`（在 tool runner 的 per-turn 钩子里 emit）
  目标：内存 ring buffer 存事件（工具名、入参、返回、耗时、状态）；`GET /console/stream` 走 SSE 推给前端；每次工具调用前后各 emit 一条
  验收：`curl -N localhost:8000/console/stream` 订阅，另开一个终端发一条会触发工具的消息，看到事件实时滚出来

- [ ] **任务 7：模型选型与 prompt 缓存**
  文件：`backend/app/config.py`、`backend/app/services/llm.py`、`backend/app/bots/registry.py`
  目标：bot 元数据加 `model` 字段——旗舰/深度档用 `claude-opus-5`，轻量档留 `claude-sonnet-5`；给 `tools` + `system` 打 `cache_control` 断点，易变内容排到断点之后
  验收：连发两轮消息，日志打印 `usage.cache_read_input_tokens`，确认第二轮 > 0（缓存真的命中了）

---

## 批次 01：旗舰戏 —— 零售 × 真 ERP

> 给 B 类客户的主菜。演的时候左边浏览器开着 `erp.kelvinpeng.com` 的订单列表。
> 剧本：客户说「我要买两个蓝牙耳机」→ bot 查真实 SKU 和库存 → 回按钮 → 客户点确认 → bot 真的建单 → **刷新 ERP 后台那张单在那里** → bot 把 PDF 发票发进 WhatsApp。全程大屏滚着工具调用。

- [ ] **任务 8：ERP 只读工具**（依赖阻塞项 A）
  文件：`backend/app/tools/erp.py`（新增）、`backend/app/services/erp_client.py`（新增）、`backend/tests/test_erp_tools.py`（新增）
  目标：`erp_client` 封装 `erp_os` REST 调用（base url + demo 账号鉴权）；三个只读工具：`erp_search_sku(keyword)`、`erp_get_inventory(sku)`、`crm_lookup_customer(name_or_phone)`
  验收：pytest（mock HTTP）；再对着真实 `erp.kelvinpeng.com` 各调一次，返回的是真数据

- [ ] **任务 9：ERP 写入工具 —— 创建销售订单**
  文件：`backend/app/tools/erp.py`（扩展）、测试
  目标：`erp_create_sales_order(customer_id, items)`，走 `erp_os` 的 `sales_order` 路由，返回订单号
  验收：调一次，然后**在浏览器里打开 `erp.kelvinpeng.com` 的订单列表，那张单在那里，状态正确**

- [ ] **任务 10：e-Invoice PDF 生成 + 发进 WhatsApp**
  文件：`backend/app/tools/erp.py`（扩展）、`backend/app/services/gateway.py`（用上传接口）
  目标：`erp_generate_einvoice(order_id)` 拿到 PDF → 走网关 `media.upload` → 构造 document 消息 payload
  验收：手机上收到 PDF 发票并能打开，内容对得上刚才那张单

- [ ] **任务 11：retail bot 改造成工具驱动**
  文件：`backend/app/bots/data/retail.json`、`backend/app/bots/registry.py`
  目标：`retail` 的 `persona_prompt` 改成「用工具查，不要编」；`context_data` 里的静态商品/订单表删掉（改由工具实时查），只留 FAQ 和政策类文本；bot 元数据加 `tools` 字段声明它能用哪些工具
  验收：问「我的订单到哪了」，日志显示走的是工具调用而不是背 JSON

- [ ] **任务 12：导演台 v1 页面**
  文件：`frontend/src/pages/Console.tsx`（新增）、`frontend/src/api.ts`
  目标：订阅 SSE，把工具调用逐条渲染成一条流——工具名、入参、返回摘要、耗时、HTTP 状态。深色控制台风格，先能看清楚，不追求美观（v2 再打磨）
  验收：手机发消息，笔记本上的页面实时滚出对应的工具调用

- [ ] **任务 13：批次 01 真机验收**（用户任务）
  目标：用户拿手机走完整段旗舰剧本的七步，笔记本开着导演台
  验收：七步全通；ERP 后台刷出真单；PDF 发票能打开；大屏上每一步都有对应事件

---

## 批次 02：眼睛和耳朵

> 给 A 类小老板看的。他不关心 API，他关心「我的客人只会发照片和语音，你这东西认不认得」。
> 剧本：客户拍一张裂壳耳机的照片 → bot 认出 SKU → 找到订单 → 真的开退款单 → 客户用马来语语音追问，bot 用马来语答。全程零打字。

- [ ] **任务 14：图片消息接入**
  文件：`backend/app/routers/whatsapp_webhook.py`（`dispatch_message` 支持 `type == "image"`）、`backend/app/services/llm.py`（多模态 content block）、测试
  目标：收到图片 → 走网关 `media.fetch` 下载 → 转成 Claude 的 image content block 塞进对话；去掉现在的「只支持文本」提示
  验收：pytest 覆盖 image 分支；真机发一张商品照片，bot 能描述它

- [ ] **任务 15：语音转录抽象层 + 一个实现**（依赖阻塞项 C）
  文件：`backend/app/services/transcribe.py`（新增）、`backend/app/config.py`、测试
  目标：定义 `transcribe(audio_bytes, mime) -> str` 的抽象，按配置选实现（外部 API / 自托管）。webhook 支持 `type == "audio"`：下载 → 转录 → 当成文本走原有链路
  验收：pytest；真机按住说一句中文和一句马来语，日志里转录文本正确

- [ ] **任务 16：退货剧情的工具**
  文件：`backend/app/tools/erp.py`（扩展）、测试
  目标：`erp_find_order_by_sku(customer_id, sku)`、`erp_create_credit_note(order_id, reason)`
  验收：调一次 credit note，`erp.kelvinpeng.com` 后台能看到那张退款单

- [ ] **任务 17：批次 02 真机验收**（用户任务）
  目标：用户拍一张破损商品照片发过去，走完「识别 → 找单 → 开退款单」，再用语音追问一句
  验收：全程不打字，五步全通，ERP 后台有退款单

---

## 批次 03：临门一脚

> 前面所有功能都是「客户问，它答」，只有主动推送是**它自己动了**——这一下对老板的杀伤力被严重低估。转人工则是成交前最后一个问题的答案：「那 AI 搞不定怎么办？」

- [ ] **任务 18：模板消息文案 + 提审**（用户任务，批次第一天就做）
  文件：`docs/whatsapp-templates.md`（新增，Claude 写）
  目标：Claude 写好两个模板的 JSON 和中/英/马三语文案（订单已确认、已出库+追踪号）；用户在 Meta 后台粘贴提交
  验收：Meta 后台显示模板状态 Approved
  说明：审核要几小时到 1-2 天，先提交再做任务 19，不要串行等

- [ ] **任务 19：主动推送**
  文件：`backend/app/services/notify.py`（新增）、`backend/app/tools/erp.py`（下单成功后触发）
  目标：下单成功 N 秒后，走网关 `/internal/send` 主动推一条消息。24 小时窗口内用普通文本，窗口外用已审核模板
  验收：真机下单后手机自动「叮」一声收到确认消息

- [ ] **任务 20：人工接管状态机**
  文件：`backend/app/session_store.py`（加接管标志）、`backend/app/routers/whatsapp_webhook.py`、测试
  目标：客户说「找真人」→ 会话标记为人工模式，bot 静默；用户在自己手机上直接回消息；用户发暗号 → bot 接管回来
  验收：pytest 覆盖状态迁移；真机走一轮，客户侧全程无感
  参考：`acuven_aichat` 的 `smb_message_echoes` 做法，直接搬

- [ ] **任务 21：批次 03 真机验收**（用户任务）
  验收：主动推送收到；人工接管一轮进出正常

---

## 批次 04：广度 —— 原生表单和两个新行业

> 让 A 类客户在列表里看见自己的行业，是他掏钱的关键。餐饮和房产最贴近马来西亚中小企业，后台也最简单好做。
> **不新开项目**：作为 `backend/app/verticals/{food,realestate}/`，共用 vps_infra 里开一个 MySQL db，后台页面挂在导演台同一个域名下——保持一个部署单元，不增加运维负担。

- [ ] **任务 22：verticals 骨架 + 数据库**
  文件：`backend/app/verticals/__init__.py`（新增）、`backend/app/verticals/db.py`（新增）、`docker-compose.yml` / `docker-compose.prod.yml`（接 `data_net`）
  目标：在 vps_infra 的 MySQL 上开一个独立 db + 用户；建表；本地 compose 能连上
  验收：`docker compose up` 后能建表、写一行、读回来

- [ ] **任务 23：realestate 后端 + 后台页面**
  文件：`backend/app/verticals/realestate/`（models / routes）、`frontend/src/pages/VerticalAdmin.tsx`（新增）
  目标：房源表 + 看房预约表 + REST 接口；一个极简后台页面能看到预约列表
  验收：curl 建一条预约，后台页面刷新能看到

- [ ] **任务 24：WhatsApp Flow —— 预约看房**
  文件：`backend/app/tools/realestate.py`（新增）、`docs/whatsapp-flows.md`（新增，Flow JSON）
  目标：bot 弹出原生表单（姓名 / 日期 / 房源）→ 提交回调写进 vertical 后端
  验收：真机在 WhatsApp 里填完表单不跳出 App，后台页面出现那条预约
  **降级方案**：Flow JSON 配置是七件武器里最容易卡住的。卡住就降级为多轮交互按钮引导，戏照演，只是没那么惊艳——**不要在这里死磕超过一个 session**

- [ ] **任务 25：food 后端 + 点餐流程**
  文件：`backend/app/verticals/food/`、`backend/app/tools/food.py`（新增）、`backend/app/bots/data/food.json`
  目标：菜单 → 加购物车 → 下单 → 查配送状态，工具驱动
  验收：真机走完一遍点餐，后台能看到订单和状态流转

- [ ] **任务 26：批次 04 真机验收**（用户任务）
  验收：房产表单预约通；餐饮点餐通；两个后台页面都能看到数据

---

## 批次 05：成品

> 前面五批做的是「能演」，这一批做的是「好看」和「不用你在场也能演」。

- [ ] **任务 27：导演台 v2**
  文件：`frontend/src/pages/Console.tsx`、样式
  目标：深色控制台美学；工具调用瀑布流、ERP 数据变化 diff、耗时柱、本次会话 token 消耗
  验收：投屏到大屏上看着专业，手机端发消息时信息密度和可读性都在

- [ ] **任务 28：网页聊天线视觉重做**
  文件：`frontend/src/App.css`、`frontend/src/pages/*.tsx`
  目标：明亮、亲和、类 WhatsApp 的气质，留给不方便加号的客户。三语 i18n 保留
  验收：手机和桌面尺寸都正常；三语切换正常

- [ ] **任务 29：自动演示模式**
  文件：`frontend/src/pages/Console.tsx` 或独立页、`backend/app/routers/console.py`
  目标：点播放键，bot 自己走完一整段最精彩的对话。**工具调用是真的**，只有用户那几句是脚本喂的
  验收：点一下，一段完整的戏自动演完，中途不需要人操作

- [ ] **任务 30：banking 下架 + 全量回归 + 部署**
  文件：删除 `backend/app/bots/data/banking.json`、`.github/workflows/deploy.yml`（如需）
  目标：下架 banking；五个 bot 全部回归一遍；部署到线上
  验收：`chatbot.acuventech.com` 线上完整走通；WhatsApp 真机五个 bot 各问一句；网关三条下游链路正常

---

## 可选项（做完再看）

- [ ] WhatsApp 端显示「正在输入」状态（v1 就列过，工具调用变慢之后价值更高了）
- [ ] 每晚定时重置 `erp_os` demo 数据——用户说过无所谓写脏，但**演示效果需要干净的起点**
- [ ] `session_store` 落 Redis（vps_infra 有现成的）。只在需要「隔天推送」时才是必须的
- [ ] 每个 bot 类型加不同主色调，视觉上更像「独立产品」

## 评审记录

（每个任务完成后，如有偏离原方案的地方或踩坑教训，记录在这里）

- 2026-08-27（立项）：v1 的 `tasks/todo.md` 归档为 `tasks/todo-v1-mvp.md`。
- 2026-08-27（架构侦察）：确认 `ai_chatbot_demo` **自己不持有 Meta 凭据**——它挂在 `whatsapp_gateway` 后面，通过 `POST /internal/whatsapp/inbound` 收消息、**同步返回** payload 列表由网关代发。七件武器里有四件（收图、收语音、发文件、主动推送）突破了这个同步请求-响应契约。解法不是把凭据复制一份给 demo（那会让两个项目抢同一个号的状态），而是给网关加三条反向内网 API 借出能力。`dispatch_message` 的返回值语义保持不变，`crm_os` 和 `acuven_aichat` 零改动——这是批次 00 单独验收的全部理由。
- 2026-08-27（选型）：ERP 一侧决定走 `erp_os` 自己的 REST 路由（`sales_order` / `sku` / `inventory` / `invoice` / `customer` 都是现成的），不裸连 MySQL。理由：写入要经过业务逻辑，否则演示时刷新后台看到的可能是一张状态不对的脏单，当场翻车。
