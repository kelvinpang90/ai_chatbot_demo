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

6. **标了 🔍 的任务走双 agent 审查**：开发方 commit 后**先不推**，换另一个 agent 冷审。**2026-09-01 起交接自动化了**——commit message 里加一行 trailer：

   ```
   Review: required (task 9)
   ```

   Stop hook 会在后台起一个冷审 session（独立 worktree，改不到你的工作区），然后把你拽回来跑 `bash tasks/review/wait.sh` 等结果。规则、证据要求、输出格式全在 [tasks/REVIEW.md](REVIEW.md) 里，不用重写提示词。

   findings 只有 `queue=true` 的你必须负责——那些带着一个能跑红的 repro 测试，修到它转绿为止。降级的可以看可以不理。驳回的理由写回本文件。轮次上限 2 轮，超了自动升给用户。复验通过再推。

   **不要全上**——只标写真实数据和状态机那几个。

## 已定下的前提（不再重新讨论）

- 主战场是 WhatsApp 真机；网页降级为「导演台」大屏 + 一条备份聊天线
- 真接 `crm_os` / `erp_os`，读写皆可，不做数据隔离（本来就是 demo 数据）
- 行业三档：旗舰 `retail`；深度 `food` + `realestate`（自建轻量后端）；轻量 `hotel` + `saas`；`banking` 下架
- 七件武器全要：图片识别 / 语音消息 / 发文件 / 交互按钮 / Flows / 主动推送 / 转人工
- ERP 一侧**走 `erp_os` 自己的 REST 路由，不裸连 MySQL**——写入要经过业务逻辑，否则后台刷出来是脏单，演示当场翻车

## 阻塞项（需要用户处理）

- [x] ~~**A. `erp_os` / `crm_os` 的 demo API 账号**~~——**2026-08-30 实测已解决，两边都不用新建账号**：
  - `erp_os`：账号见环境变量 `ERP_EMAIL` / `ERP_PASSWORD`，对 `erp.kelvinpeng.com/api/auth/login` 实测 200
  - `crm_os`：账号见环境变量 `CRM_EMAIL` / `CRM_PASSWORD`，对 `crm.kelvinpeng.com/api/auth/login` 实测 200，role=admin
  - ⚠️ **密码曾以明文写在本文件和 `config.py` 里，而这三个仓库（`ai_chatbot_demo` / `erp_os` / `crm_os`）都是 PUBLIC。** 2026-09-01 的 Codex 审查发现，已从源码移除、改为必填环境变量（`ERP_EMAIL` / `ERP_PASSWORD` / `CRM_EMAIL` / `CRM_PASSWORD`，VPS 的 `.env` 已配好）。但**移除不等于消除**——凭据仍在 git 历史里，`git log -p` 就能翻出来。
  - ✅ **2026-09-01 用户拍板：不轮换，风险已知情接受。** 理由：demo 系统、数据不重要，被人改坏了重跑 seed 即可。**这是已决定的事，不要再提**；审查方若再报这一条，回「owner accepted, see tasks/todo.md」。源码侧的清理与轮换与否无关，继续保持——新密码永远不要写回仓库。
  - ⚠️ **两边都没有 API key 机制**，只有邮箱+密码换 JWT。access token 15 分钟过期、refresh 一次性、登录限流 10 次/分（连错 5 次锁 5 分钟）。所以客户端**必须缓存 token + 到期前刷新**，绝不能每次调用都登录——一场演示连调五六个工具就会撞限流
- [ ] **B. Meta 后台三个入口确认能点**——媒体权限、模板提审、Flows。用户已确认后台可用，但任务 18 的模板提审要在批次 03 第一天就提交（审核要几小时到 1-2 天）。
- [ ] **C. 语音转录选型拍板**——外部 API（准、快、多一个供应商）vs 自托管 faster-whisper（无外部依赖、CPU 上每条慢 3-5 秒、吃 VPS 内存）。阻塞任务 15。建议先接外部 API 把戏跑通，转录做成抽象层，之后换实现只是换一个类。
- [ ] **D. 演示环境的脏数据——会直接出现在演示要指的那块屏上**（2026-09-02 在 Chrome 上实地看到的）：
  - **Lead 那一列现在有一张标题是 `16315551181`、金额 RM 0 的卡**，负责人 Marcus Johnson。这正是 `crm_os/backend/app/utils/demo_scope.py` 注释里写「a dashboard full of leads named after phone numbers and worth RM 0 undercuts the product being demonstrated」的那种卡——但它**没有被过滤掉**，说明这条联系人的 `is_gateway` 是 false（`demo_scope` 只挡 true 的）。任务 9.1 建出来的线索卡就会挨着它出现
  - **联系人列表最上面 5 条是 `KK Hardware` / `demo company 1-4`**，全是 RM 0、0 个商机的空壳（列表按创建时间倒序，所以它们排最前）。客户点开 Contacts 第一眼看到的就是这些
  - 全库 26 条联系人。**要不要删由你定**——删是写操作，而且是你的数据，我没动
- [x] ~~**E. 本地 `backend/.env` 的 `CRM_PASSWORD` 已失效**~~——**2026-09-03 任务 11 实测已恢复，这一条可以划掉**。同一份 `backend/.env`（文件时间戳 09-03 11:32，看起来是被改过）在容器里跑 `crm_lookup_customer("David Park")` 和 `crm_lookup_customer("+1-858-555-1515")` 都返回真实联系人（MedTech Innovations），说明**登录这一跳是通的**——查不到人会返回 `NOT_FOUND`，登录失败才返回 `UNAVAILABLE`，两者分得开。ERP 侧同样实测 `login 200`。**VPS 上那份 `/opt/ai_chatbot/backend/.env` 仍未验**。以下是原文，留作来龙去脉：
  ~~（2026-09-02）~~：对 `crm.kelvinpeng.com/api/auth/login` 返回 **401**。`CRM_EMAIL` 是对的（`admin@crm.com`，和线上登录页显示的 demo 管理员一致），**密码不对**——`.env` 里是 14 位，而线上登录页预填的密码是 8 位。
  ⚠️ 同一份凭据在今天早些时候审查方跑 live 脚本时还是好的，所以是中途失效或那份 `.env` 从来就和线上不同步。
  按 CLAUDE.md 的高风险操作规则（认证失败一次即停、不连续换凭据重试，登录连错 5 次锁 5 分钟），**没有再试第二次**。这一条不解决，任务 9.1 及之后所有写 CRM 的真机验收都做不了。VPS 上那份 `/opt/ai_chatbot/backend/.env` 是否同样失效，也需要一并确认


---

## 批次 00：地基（不对客户展示）

> 没有客户看得见的东西，但后面五批全部压在这一批上。
>
> **2026-08-30：这一批原有 7 个任务，现在 4 个。** demo 线已脱离 `whatsapp_gateway`——
> Meta 的 Callback URL 直接指向 `chatbot.acuventech.com/webhook/whatsapp`，`ai_chatbot`
> 用自己的凭据收发。原任务 1、2、4 全是「向网关借凭据」的管道，任务 3 是动网关后的回归验证；
> 既然不再经过网关，四个一起塌缩成下面的任务 1。
>
> 连带消失的还有这一批原本「**整个工程唯一有回归风险**」的属性——那个风险来自
> `whatsapp_gateway` 同时扛着公司真实客服号（`acuven_aichat`），而现在我们根本不碰它。

- [x] **任务 1：Meta 媒体客户端（收图 / 收文件 / 发文件 / 主动外发）**——**2026-08-31 完成并真机验收**。5 个新 pytest 全过（全套 41 passed）；VPS 上打真实 Graph API 也走通了：上传 PDF 拿到 `media_id`，再用这个 id 回头走一遍 `fetch_media` 的两跳，下载回来 `file` 认成 `PDF document, version 1.4`，与原文件 `cmp` 字节一致。两点偏离 + 两条踩坑记录：
  - `send_message(payload)` 做成 `whatsapp.send_raw()` 的薄委托，没重复实现 URL/header——`send_raw` 本来就是同一个 `POST /{phone_number_id}/messages`
  - `fetch_media` 在下载前用元数据的 `file_size` 卡新配置 `whatsapp_media_max_bytes`（默认 5MB），免得 90MB 视频拉进内存后才发现喂不给模型
  - **验证媒体链路不需要有人拿手机发图**：自己上传拿到的 `media_id` 可以直接回查，`GET /{media_id}` 照样返回 `url` / `mime_type` / `file_size`。以后调媒体功能都用这个自环，比等一条入站消息快得多
  - **VPS 上的 `.env` 在 `/opt/ai_chatbot/backend/.env`**，不是 `/opt/ai_chatbot/.env`——compose 里写的是 `env_file: ./backend/.env`。另：Claude Code 权限分类器会拦「读 .env 凭据打外部 API」，这类真机验证只能由用户手工跑

  文件：`backend/app/services/whatsapp_media.py`（新增）、`backend/app/config.py`、`backend/tests/test_whatsapp_media.py`（新增）
  目标：三个函数，全部直连 Graph API，用 `ai_chatbot` 自己的 `WHATSAPP_ACCESS_TOKEN`：
  - `fetch_media(media_id)` —— 两步：`GET /{media_id}` 拿临时 URL，再带 token 下载二进制，返回 bytes + `Content-Type`
  - `upload_media(bytes, mime, filename)` —— multipart 传给 `POST /{phone_number_id}/media`，返回 `media_id`
  - `send_message(payload)` —— `POST /{phone_number_id}/messages`，供主动推送用（收到消息时的回复走现有 webhook 同步路径，不用这个）
  验收：pytest 用 mock HTTP 覆盖三个函数的 URL / header / body；再用真实 `media_id` 拉一张图下来能打开，上传一个 PDF 拿到 `media_id`

- [x] **任务 2：LLM 工具调用循环**——**2026-08-31 代码完成**，5 个 `test_llm.py` 测试全过（全套 44 passed）。三个判断：
  - **安全绳做成了真的分叉，不是「传空数组」**：`get_tools(bot.id)` 为空时走原来的 `messages.create`，一个字节都没动；有工具才走 `beta.messages.tool_runner`。理由是「行为完全一致」这句话，传 `tools=[]` 去 beta 端点即使能跑也已经不是同一个请求了，而线上四个 bot 正在接客。本地起 uvicorn 实测：retail 发一句，traceback 显示走的是 `/v1/messages` 的 `messages.create`，**没碰 beta 端点**
  - **`max_iterations=8`**：runner 默认无上限（`_beta_runner.py:126`，`max_iterations=None` 就永远不停）。演示时一个刹不住的工具循环比答得不完美糟糕得多。有测试钉住这个上限
  - **没动模型选型**——`settings.anthropic_model` 还是 `claude-sonnet-5`，那是任务 4 的事，这里不抢
  - **旧行为回归已验收**：2026-08-31 部署后往 demo 号发 WhatsApp，真实 key 下正常回复。WhatsApp 和网页端共用 `llm.get_reply`，这一条同时覆盖两边（本地假 key 下拿到的是 `FALLBACK_REPLY`，顺带证明兜底路径也没坏）

  文件：`backend/app/services/llm.py`、`backend/app/tools/registry.py`（新增）、`backend/tests/test_llm.py`
  目标：从单轮 `messages.create` 改成 SDK 的 tool runner（`@beta_tool` + `client.beta.messages.tool_runner()`）。工具列表按 bot 从 registry 取，**工具为空时行为与现在完全一致**——这是回归的安全绳
  验收：pytest 覆盖「无工具时输出不变」和「有工具时会调用并把结果喂回去」；`docker compose up` 后网页端问一句，确认回复正常（旧行为回归）

- [x] **任务 3：事件总线 + 导演台 SSE 骨架**——**2026-08-31 完成并验收**（全套 52 passed）。验收就是 todo 要求的那条：`curl -N localhost:8392/console/stream` 挂着，另一个终端发一条会触发工具的消息，两条事件实时滚出来——`tool_start`（工具名 + 入参）和 `tool_end`（返回、`duration_ms: 201`、`status: ok`），耗时和探针里 sleep 的 200ms 对得上。设计要点：
  - **订阅者按 seq 轮询 ring buffer，不是被 push**：聊天请求跑在 FastAPI 的同步线程池里，SSE 跑在事件循环上，跨线程往 `asyncio.Queue` 里塞是错的。轮询间隔 250ms，人眼看不出来，换来的是没有 per-subscriber 队列会在浏览器标签页关掉时泄漏
  - **`?replay=true` 才回放缓冲区**，默认只推新事件——演示时先连屏再说话，不该一上来糊一屏历史
  - **一个 turn 里的并行工具共享同一个 `duration_ms`**，因为 runner 是一起执行它们的。想要 per-tool 精确耗时得包装工具对象，现在不值得
  - ⚠️ **`/console/stream` 没有鉴权，靠「打不到」保护**：前端容器的 nginx 只转 `/api/` 和 `/webhook/`，`/console/` 会落到 SPA。**任务 12 建导演台页面时必须同时解决**——那条流里有 ERP 订单数据和客户资料，加了 nginx 转发就等于公开

  文件：`backend/app/console/events.py`（新增）、`backend/app/routers/console.py`（新增）、`backend/app/services/llm.py`（在 tool runner 的 per-turn 钩子里 emit）
  目标：内存 ring buffer 存事件（工具名、入参、返回、耗时、状态）；`GET /console/stream` 走 SSE 推给前端；每次工具调用前后各 emit 一条
  验收：`curl -N localhost:8000/console/stream` 订阅，另开一个终端发一条会触发工具的消息，看到事件实时滚出来

- [x] **任务 4：模型选型与 prompt 缓存**——**2026-08-31 代码完成**，全套 57 passed。
  - **模型写进每个 bot 的 JSON**：`retail` / `food` / `realestate` = `claude-opus-5`；`hotel` / `saas` / `banking` = `claude-sonnet-5`。`BotConfig.model` 为空时回落到 `settings.anthropic_model`
  - **`config.py` 没动**——任务清单里列了它，但 `anthropic_model` 本来就是现成的回落项，没有需要新增的东西，硬加一个反而多一处真相来源
  - **system prompt 拆成两块**：稳定块（人设 + `context_data` + 语言/长度/安全指令 + 免责声明）打 `cache_control`，易变块（identity profile）排在断点之后。**原模板里 identity 在中间，被挪到了末尾**——这是缓存能跨身份复用的前提，有测试钉住「两个不同身份的稳定块必须字节相同」
  - **一个断点同时覆盖 tools**：请求渲染顺序是 tools → system → messages，断点标的是「缓存前缀到此为止」，所以打在 system 稳定块尾部就把工具定义一起包进去了，不需要第二个标记
  - **TTL 用默认 5 分钟**，没上 1 小时：同一段对话里两轮间隔远小于 5 分钟，读一次就免费续期；1h TTL 把每次写入从 1.25× 抬到 2×，只在长间隔才回本，而这里的绝对差额是几厘钱
  - **缓存前缀的真实大小：`retail` = 1097 token**（生产日志实测）。缓存有最小前缀门槛——**Opus 5 是 512，Sonnet 5 是 1024**。旗舰档远远够。轻量档**卡在门槛线上，两可**：按实测/估算比例 1.195 换算，`hotel` ≈ 1065（大概率能缓存）、`saas` ≈ 949、`banking` ≈ 998（大概率不能，静默失效，只表现为 `cache_read=0`，不报错）。要确认就挑一个轻量档 bot 连发两轮看日志。断点对所有 bot 都留着：不花钱，前缀长了会自动开始生效
  - 任务 11 把 retail 的静态商品表换成工具后，前缀会缩水但工具定义会加回来，净效果要重新量——**别假设它还在 1024 以上**
  - **日志**：每次回复打一行 `claude usage bot=... model=... input=... output=... cache_write=... cache_read=...`，`docker logs ai_chatbot_backend | grep "claude usage"` 就能看
  - **已验收**（2026-08-31，WhatsApp 真机 + VPS 日志）：选 retail / 身份 vip_tan 连发两轮，
    `round 1: model=claude-opus-5 input=327 cache_write=1097 cache_read=0`，
    `round 2: model=claude-opus-5 input=440 cache_write=0 cache_read=1097`。
    第二轮命中，且日志证实 per-bot 模型选型在线上生效
  文件：`backend/app/config.py`、`backend/app/services/llm.py`、`backend/app/bots/registry.py`
  目标：bot 元数据加 `model` 字段——旗舰/深度档用 `claude-opus-5`，轻量档留 `claude-sonnet-5`；给 `tools` + `system` 打 `cache_control` 断点，易变内容排到断点之后
  验收：连发两轮消息，日志打印 `usage.cache_read_input_tokens`，确认第二轮 > 0（缓存真的命中了）

---

## 批次 01：旗舰戏 —— 零售 × 真 ERP

> 给 B 类客户的主菜。演的时候左边浏览器开着**两块后台**：`erp.kelvinpeng.com` 的订单列表 + `crm.kelvinpeng.com` 的管道看板。
>
> **剧本 1 —— 旗舰戏（8 步）**：客户用 rojak 话开场——**"Boss 这个 earbuds 还有 stock 吗? 我要 2 个, 可以 COD 吗?"**（一句话里混英文、中文、马来式语法，这才是马来西亚客人真实的说话方式）→ bot 查真实 SKU 和库存 → 回按钮 → **客户中途改主意：「算了，改成 3 个」→ bot 重查库存、重算价钱** → 客户点确认 → bot 真的建单 → **刷新 ERP 后台那张单在那里，同时 CRM 看板上长出一张线索卡** → bot 把 PDF 发票发进 WhatsApp。全程大屏滚着工具调用。
>
> 「改主意」那一步是刻意加的。**所有演示在客户老实按剧本走时都很漂亮，一旦他中途反悔就露馅**——而真实生意里天天发生：算了改成三个、等等先别下单、刚才那单能取消吗。接得住，证明它是个**会听懂的助理**；接不住，证明它是个**流程图**。老板分得清这两者。工具循环天然支持（Claude 自己会决定重查、改参数），**但必须专门验**，否则第一次被打断就翻车。
>
> 两块后台同时长东西是刻意的：ERP 那张单打动已经有 ERP 需求的 B 类客户，**CRM 那张卡打动所有做生意的人**——他们每天都在 WhatsApp 里丢单子。
>
> ✅ **剧本里的 "earbuds" 已经在真实 ERP 里了**（2026-09-01 建好并冷启动复验通过）。当初任务 8 实测发现线上只有电风扇，用户决定补 SKU 而不是改剧本。
>
> **`SKU-ELE-0001` / `Sony WF-C710N Wireless Earbuds` / MYR 299.00 未税（SST 10%）**，分类 Peripherals、单位 PCS、品牌 Sony（id 70，线上原本没有任何音频/电子品牌）。库存 **KL 42 / 槟城 25 / 新山 18，合计 85**。
> 冷启动实测：`erp_search_sku("earbuds")` 和 `erp_search_sku("Sony")` 都命中，`erp_get_inventory("earbuds")` 返回 `total_available: 85.0` 且三仓明细正确。
> 库存数字是照剧本挑的：客人要 2 个、中途改成 3 个都远在库存内；三个仓库数字不同，导演台上才看得出真实的分仓明细。
>
> ⚠️ **这是 ERP 数据库里的数据，不在版本控制里——`erp_os` 一旦重新 seed，这个 SKU 就没了，剧本第一句会当场查不到东西。** 重建脚本留在 `E:\projects\erp_create_earbuds.py`（仓库外，一次性数据修复不是产品代码），**幂等**，重跑即可。走的全是 `erp_os` 自己的 REST 路由，不裸连 MySQL。
> 另注：**带凭据「写」外部系统会被 Claude Code 的权限分类器拦**（只读放行），所以这类脚本只能由用户手工跑——任务 9 起写 ERP 的验收步骤同理。

- [x] **任务 8：ERP / CRM 只读工具 + 鉴权基类**——**2026-08-31 完成并对真实服务验收**。28 个新测试全过（全套 85 passed）。三个工具都打了真实的 `erp.kelvinpeng.com` / `crm.kelvinpeng.com`，返回的是真数据：
  - `erp_search_sku("a")` → `SKU-APL-0001 Pensonic Stand Fan 16 Inch PF-1607 / MYR 79.90` 等 5 条
  - `erp_get_inventory("a")` → 同 5 个 SKU，按仓库拆开（Main Warehouse - Kuala Lumpur 45 / Branch - Penang 28 / Branch - Johor Bahru 33），`total_available: 106`
  - `crm_lookup_customer("David Park")` → `MedTech Innovations`，`total_deal_amount: 390000.0`；换成 `+1-858-555-1515`、`18585551515`、`8585551515` 三种写法查同一个人，都命中
  - **token 缓存真的生效**：一个进程里连打 9 次工具，日志只有 2 行 `logging in as`（ERP 一次、CRM 一次）。这正是防限流的那条命——登录 10 次/分钟

  ⚠️ **三个必须往下带的发现**：
  - **ERP 商品库里没有 earbuds，是电风扇**（Pensonic / Khind / Milux）。而本文件的「剧本 1 —— 旗舰戏」整场戏是围绕 *"Boss 这个 earbuds 还有 stock 吗?"* 写的，`erp_search_sku("earbuds")` 实测返回「查无此商品」。~~**任务 11 / 13 之前必须二选一**：把剧本改成风扇，或者往 ERP 里加一个 earbuds SKU~~——**2026-09-01 已解决，补了 SKU，见上面「剧本 1」那一节**。（这行是任务 8 当时发现问题的记录，留着是为了说明来龙去脉；2026-09-03 有人只读到这里就把它当成未决阻塞项汇报过一次）
  - **`crm_os` 的 `?search=` 只匹配 name 和 company，不匹配 phone**（`contact_service.list_contacts:49-55`）。而手机号恰恰是 WhatsApp 场景里唯一稳定的身份标识。所以 `crm_lookup_customer` 判断参数长得像电话时**不发 `search`，改成分页拉回来在本地按「digits 后 8 位」比对**——避开了 `+60 17-394 8123` / `0173948123` / `60173948123` 三种写法和国家码的差异。分页上限 5 页 × 100 条，够这个 demo 库（实测 26 个联系人）用得很宽裕
  - **两边只有认证「流程」一样，响应「形状」不一样**：`erp_os` 直接返回 JSON，`crm_os` 把所有响应（含 token）包在 `{"success", "data"}` 里，而且列表路由还要再套一层（`data.data` 才是行）。所以基类留了一个 `_unwrap` 钩子，`CrmClient` 覆盖它，登录和取数共用同一个钩子

  另外四条判断：
  - **工具没有挂到任何 bot 上**——`tools/registry.py` 一个字节没动，`_TOOLS_BY_BOT` 还是空的，线上四个 bot 行为完全不变。挂载是任务 11 的事（它要往 bot JSON 加 `tools` 字段），这里不抢
  - **偏离文件清单**：`crm_lookup_customer` 放在新建的 `app/tools/crm.py`，不是 `tools/erp.py`——一个 CRM 工具住在 erp.py 里，任务 9.1 还得把它搬出来。**所以任务 9.1 的 `tools/crm.py` 和 `tests/test_crm_tools.py` 是「扩展」不是「新增」**。测试同理按被测模块拆成三个文件（`test_api_client.py` / `test_erp_tools.py` / `test_crm_tools.py`），跟仓库现有习惯一致
  - **查库存走 `/api/inventory/branch-matrix` 而不是 `/api/inventory/stocks`**：后者强制要 `warehouse_id`，而客人问「还有货吗」问的是整间店。matrix 一次调用就能按仓库拆开，还顺带给出总数。注意它的角色门槛排除了 sales（`_RESTOCK_ROLES`），我们用 admin 登录所以没事
  - **凭据写成 `config.py` 的默认值**，不是必填 env：两套都是 demo 系统、没有 API key 机制，账号密码本来就已经明文记在这份 todo 里了。写成默认值省掉「上线前记得改 VPS 的 .env」这个一定会忘、且忘了就当场演示失败的步骤。要覆盖照样可以走环境变量
  - 写测试时揪出一个真 bug：`int(payload.get("expires_in") or DEFAULT)` 会把服务端真的返回的 `expires_in: 0` 当成「没给」，静默变成 15 分钟。改成显式判 `None`

  ---

  🔍 **2026-09-01 Codex 独立审查（本项目第一次跑双 agent 流程）——两条 P1 全部接受，已修**（全套 97 passed，+12 个新测试）：

  - **P1-1：`except (ApiClientError, OSError)` 捕不到任何真实故障。接受。** httpx 的异常**没有一个继承自 `OSError`**（`ConnectError` / `ReadTimeout` / `HTTPStatusError` 的 MRO 都止于 `Exception`），所以 ERP 挂掉、超时、**登录撞上 10 次/分钟限流**这三种情况全部穿透工具往上抛，而限流恰恰是这个基类存在的全部理由。实测复现（base url 指向死端口）：`RAISED, UNCAUGHT -> ConnectError`。
    **为什么原测试全绿还是漏了**：原测试写的是 `side_effect=ApiClientError("boom")`——测的是「我选择去捕获的异常类型」，不是真实会发生的类型。**同义反复测试的教科书样本**，正好命中 `REVIEW.md` 固定第一问。
    **修法不是在工具层多 catch 一个类型**，而是在 `JsonApiClient` 边界把 `httpx.HTTPError` 统一包成 `ApiClientError`：调用方只认一种异常，任务 9/9.1/10 以后新增的工具**不可能再忘记捕获 httpx**。新增 12 个测试，其中 6 个直接 patch `httpx` 抛真实异常类型（dead-host / timeout / rate-limited 三种 × 两个工具）。修完同一个复现返回优雅降级消息。

  - **P1-2：公开仓库里有有效的管理员凭据。接受，且比 finding 描述的更严重。** 实测 `gh repo view`：`ai_chatbot_demo`、`erp_os`、`crm_os` **三个都是 PUBLIC**。凭据不止在 `config.py`——`crm_os/backend/seed.py:82` 明文写着种子密码，`erp_os` 里 `Admin@123` 出现在 5 个文件（含 `README.md`、`CLAUDE.md`、种子脚本、一个 `.pptx`）。而且 `git log -S` 显示它早在 `c4f32e3` 就进了本仓库的 `todo.md`，**不是任务 8 引入的，任务 8 只是又抄进了 `config.py`**——但这不构成辩护，只说明暴露面更大。
    **已做**：`config.py` 的账号密码改成必填环境变量（空默认值），base url 不是秘密所以保留；`.env.example` 补上四个变量；凭据缺失时报 `no credentials configured -- set ERP_EMAIL and ERP_PASSWORD` 并优雅降级（有测试）；本文件里的明文密码已清除。
    ✅ **轮换：用户明确决定不做（2026-09-01），风险已知情接受**——demo 系统、数据不重要，改坏了重跑 seed。所以旧密码在 git 历史里长期有效这一点是**已接受的现状**，不是待办。（当时给出的轮换路径留档备查：ERP 走 `POST /api/users/{id}/reset-password`、CRM 走 `PUT /api/users/{id}`，并须同步改 `crm_os/backend/seed.py` 和 `erp_os/backend/scripts/seed_master_data.py`，否则 re-seed 会把已知密码装回去。）
  - **P2（复验轮新增）：`httpx.InvalidURL` 仍能逃出边界。接受，已修。** 这条正是我请审查方专门去找的「边界包装有没有漏网路径」——**我自己判断不了，因为包装是我写的**。实测 `ERP_BASE_URL=http://[::1` → `RAISED, UNCAUGHT -> InvalidURL: Invalid port: ':1'`。
    反驳的举证责任是「证明畸形 base URL 不可能进入运行环境」，我达不到——`docker-compose.prod.yml` 用 `env_file` 把 VPS 上**手工编辑**的 `.env` 原样透传，零校验，而这四个变量恰好是 2026-09-01 手工加进去的。手改 env 正是 typo 高发地。
    **修法**：枚举了 httpx 全部异常，把逃逸集合固化成 `TRANSPORT_ERRORS = (HTTPError, InvalidURL)`。剩下 6 个（`CookieConflict` + `StreamError` 家族 5 个）**刻意不catch**——前者要 cookie 我们从不设，后者要「响应没读完」而 `get`/`post` 都是一次读完；把它们也吞掉只会掩盖自己的 bug。
    **没有做启动时校验 URL**：想过，否决了。畸形 URL 会让整个应用起不来，而这四个变量只影响两个工具——一个可选工具的配置 typo 不该拖垮 demo 号赖以存活的 webhook。降级 + 日志点名（`erp api: GET /api/skus failed: Invalid port`）是更合适的严重性。
    新增 3 个测试，其中一个**钉住枚举本身**（断言不在 `TRANSPORT_ERRORS` 里的 httpx 异常恰好是那 6 个），这样 httpx 将来新增一个逃逸异常会直接把测试打红，而不是等下一次线上翻车。

  ✅ **2026-09-01 复验 PASS，任务 8 的「开发 → 冷审 → 修复 → 复验」闭环走完**（本项目第一次跑这套流程）。审查方实测确认：100 passed、`ERP_BASE_URL=http://[::1` 下两个 ERP 工具都返回 `UNAVAILABLE`、原始 `InvalidURL` 只留在日志异常链里不外泄、`TRANSPORT_ERRORS` 的排除论证成立、不做启动校验的取舍接受，**无新增 finding**。
  **校准结果：报了 3 条，真的 3 条，误报 0**（记账见 [tasks/REVIEW.md](REVIEW.md)）。三条教训也记在那里——最要紧的一条是：开发方漏掉公开仓库凭据那条，不是因为看不见，而是**为自己的决定准备好了辩护，却没验证辩护的前提**。

    ⚠️ **部署前必须先在 VPS 的 `/opt/ai_chatbot/backend/.env` 补上 `ERP_EMAIL` / `ERP_PASSWORD` / `CRM_EMAIL` / `CRM_PASSWORD`**，否则任务 9 起的工具会全部返回「查不到」。这正是当初把凭据写成默认值想避免的那个「会忘的步骤」——安全性优先，代价就是这一步不能省。

  文件：`backend/app/services/api_client.py`（新增，登录+token 缓存+刷新基类）、`backend/app/services/erp_client.py`、`backend/app/services/crm_client.py`（均新增）、`backend/app/tools/erp.py`、`backend/app/tools/crm.py`（均新增）、`backend/app/config.py`、`backend/tests/test_api_client.py`、`backend/tests/test_erp_tools.py`、`backend/tests/test_crm_tools.py`（均新增）
  目标：`erp_os` 和 `crm_os` 的认证方式**完全一样**（邮箱+密码 → JWT，15 分钟过期，refresh 一次性），所以先写一个共用基类管登录/缓存/刷新，两个 client 各自只填 base url 和账号。三个只读工具：`erp_search_sku(keyword)`、`erp_get_inventory(sku)`、`crm_lookup_customer(name_or_phone)`
  验收：pytest（mock HTTP）覆盖「token 未过期时不重新登录」「过期时自动 refresh」「refresh 失败回退重新登录」；再对着真实 `erp.kelvinpeng.com` / `crm.kelvinpeng.com` 各调一次，返回的是真数据

- [x] 🔍 **任务 9：ERP 写入工具 —— 创建销售订单**——**2026-09-01 代码完成**（17 个新测试，全套后来到 155 passed），**2026-09-02 真机验收 PASS**，中间走了三轮冷审。验收实测：

  ```
  KL available before: 42
  {"order_no": "SO-2026-00001", "status": "CONFIRMED", "customer": "Sunrise Hypermart Sdn Bhd",
   "warehouse": "Main Warehouse - Kuala Lumpur", "currency": "MYR", "total_incl_tax": "986.7000",
   "lines": [{"code": "SKU-ELE-0001", "name": "Sony WF-C710N Wireless Earbuds",
              "qty": "3.0000", "unit_price": "299.0000", "line_total_incl_tax": "986.7000"}]}
  KL available after: 39   (moved 3)
  ```

  **三条判据全中**：状态 CONFIRMED 不是 DRAFT；金额 986.70 = 299.00 × 3 + SST 10%；**KL 可用库存 42 → 39，正好少 3**。第三条才是重点——前两条一张 DRAFT 也做得到，只有库存真的动了才证明 confirm 那一步跑成功了，而那正是任务 10 生成发票的前提。
  单号 `SO-2026-00001`：线上原有的 250 张全是种子数据，**这是第一张真正走 API 建出来的单**。

  ⚠️ **验收顺带把第 3 轮那条降级 finding（P3-1）坐实了**：明细里 `unit_price` 是 **299.0000（未税）**，而这一单实收 **986.70（含税）**。当时它只是「read-only 推测」不进队列，现在有线上真实数据——**客人听到的报价和账单上的数字确实不是一回事**（每个 299 vs 328.90）。任务 11 改报价口径时必须一起处理。

  ⚠️ **Claude 跑不了这一步，两次都被权限分类器拦下**（跑写入命令、以及写那个一次性脚本）：带凭据「写」外部系统属于拦截范围，只读放行。所以这类验收**只能由用户手工跑**，`todo.md` 里从任务 9 起的所有写 ERP/CRM 的验收步骤同理。

  **签名**：`erp_create_sales_order(customer_id: int, items: list[OrderLine], warehouse_id: int = 1)`，`OrderLine = {sku_id, quantity}`。用 `TypedDict` 而不是 `list[dict]` 是实测决定的：前者在 schema 里生成 `$defs.OrderLine` 把字段名写清楚，后者只给模型一个 `array of object`，键名全靠猜。

  **三个判断**：
  - **价格、单位、税率一律从商品档案取，不接受调用方传**。`erp_os` 的行项目要 `uom_id` / `tax_rate_id` / `unit_price_excl_tax`，工具自己去 `GET /api/skus/{id}` 拿。理由不是省参数，是**模型在跟客户聊天，不是在管价目表**——如果价格能由它填，客人一句「boss 算便宜点」就能让一张真单以编出来的价钱落进 ERP，而导演台上看起来和真促销一模一样
  - **建单之后接着 confirm，偏离了规格里的「创建」二字**。三条理由：① DRAFT 不锁库存，旗舰戏里「下完单再问一次还有几个」会显示库存没变，当场戳破「这是真的」这个主张；② 任务 10 的 e-invoice 实测要求 SO 处于 `PARTIAL_SHIPPED` / `FULLY_SHIPPED`（`erp_os/backend/app/services/einvoice.py:245`），而 DRAFT 连发货都进不去；③ 验收标准里的「状态正确」，对一张客户已经点头的单来说就是 CONFIRMED
  - **confirm 是第二次写，它自己会失败**（那个仓库库存不够、中途断线），失败时 DRAFT 已经躺在 ERP 里了。这种半成功**不吞**：返回一句点名单号的话，明说「单建了但没确认、没锁库存、发不了货」。**没有自动去 cancel 那张 DRAFT**——cancel 同样可能失败，而且人工要不要救这张单该由人决定，留一张状态诚实的草稿比留一个静默的撤销好

  **顺手修的两个**：
  - `JsonApiClient` 原本只有 `get`，没有带鉴权的 `post`（任务 8 只读）。抽了一个 `_request` 让 `get` / `post` 共用那套「401 就重登一次再试」的逻辑，而不是把它复制一遍。**给写操作重试是要论证的**：401 由鉴权依赖在路由函数跑之前拒掉，所以重试不可能建出第二张单；超时之类的**一律不重试**（那种情况写入可能已经落地了），宁可报失败让人去查
  - 错误信息现在带上服务端自己的说法（截断 300 字）。「库存不够」和「查无此客户」对一个在 WhatsApp 那头等着的客人是两个不同的答案，光一个 400 分不出来
  - `tasks/review/pytest_docker.sh` **在这台机器上根本跑不起来**（`docker: the working directory 'D:/Git/app' is invalid`）——Git Bash 会把参数里的 `/app` 改写成 Windows 路径。加了一行 `export MSYS_NO_PATHCONV=1`。它是审查双方唯一的测试入口，跑不了这一轮就只能交 `blocked`，所以顺手修了；这一条不属于任务 9 的改动范围，单独说明

  **业务日期按 +08:00 算，不是 `date.today()`**：VPS 是 UTC，本地时间凌晨到早上 8 点之间，`date.today()` 会把单据日期写成昨天——而这个日期客户和销售在屏幕上都看得见。马来西亚没有夏令时，固定偏移是精确值不是近似。

  ⚠️ ~~**必须往下带的一条：没有任何工具能给模型提供 `customer_id`**，任务 11 再解决~~——**这条被审查方判成 P1 打回来了，已经在本任务里修掉**，见下面的第 1 轮审查记录。当初的原文保留在 commit `40d4a8a` 里。

  **验收怎么做（写 ERP/CRM 的验收都照这个来，用户手工跑）**——凭据在 `backend/.env`（**不是 `.env.example`**，那个进 git 而且仓库是公开的）。跑之前先开 Docker Desktop，然后在**仓库根目录**用 PowerShell：

  ```powershell
  # 只读的先查一遍，拿 sku_id / customer_id / 当前库存
  docker run --rm -v "${PWD}\backend:/app" -w /app -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 `
    python:3.13-slim sh -c "pip install -q -r requirements.txt && python -c ""from app.tools.erp import *; print(erp_search_sku('earbuds')); print(erp_get_inventory('earbuds')); print(erp_find_customer('Sunrise'))"""
  ```

  写入那一步用 here-string 落一个一次性脚本再跑（`'@` 必须顶格）：`backend\book_order.py` → `docker run ... python book_order.py` → `Remove-Item`。**别把命令直接写成 bash 语法**——这台机器默认终端是 PowerShell，`cygpath` / `MSYS_NO_PATHCONV` / 反斜杠续行在那边全不认。
  ⚠️ **不要在 Git Bash 的命令里省掉 `MSYS_NO_PATHCONV=1`**：`-w /app` 会被改写成 `D:/Git/app`，docker 直接拒绝启动。

  文件：`backend/app/services/api_client.py`（加带鉴权的 `post` + 共用 `_request`）、`backend/app/services/erp_client.py`（加 `sku` / `create_sales_order` / `confirm_sales_order`）、`backend/app/tools/erp.py`（加 `erp_create_sales_order`）、`backend/tests/test_erp_tools.py`、`backend/tests/test_api_client.py`（均扩展）、`tasks/review/pytest_docker.sh`（一行环境变量）

  ---

  🔍 **2026-09-01 第 1 轮冷审（自动化模式第一次真跑）——报 4 条，2 条进队列，1 条修掉、1 条修实质但驳回证据形式**（全套 147 passed）：

  - **P1-1：`customer_id` 无处可得。接受，已在本任务修掉，不再推给任务 11。**
    这条我在自辩里**主动写了**，然后把它划给任务 11。审查方不接受这个划分，给了 repro 判成 P1 进队列。**它是对的**：一个必须靠模型编参数才能调用的写工具，交付的不是「待办」，是「会把单记到陌生人头上的功能」。而且 ERP 客户是 1..50 的小整数，编一个几乎必然命中一个真实的错客户——静默、且正好出现在演示要老板盯着看的那块屏上。
    **修法**：新增只读工具 `erp_find_customer(name_or_phone)`，走 `/api/customers`，返回 int 型 ERP `customer_id`；`erp_create_sales_order` 的 docstring 明写「id 只能来自 erp_find_customer，CRM 的 contact id 是另一套系统的标识，用了就是记错账」；查无此人返回的话里直接写「不要编造 customer_id」。手机号那条老坑照 `crm_lookup_customer` 的办法处理：ERP 的 `?search=` 不匹配 phone，所以判定像电话时分页拉回来本地按后 8 位比对。
    **顺带把电话匹配规则抽成 `app/services/phone.py`**，`crm_client` 改成从那里 import。两套系统在回答「同一个人是谁」，「哪几位数字算数」这条规则不能各留一份慢慢跑偏。
    ❗ **但那条 repro 我修不绿，驳回的是证据形式不是问题本身。** 它的最终断言是 `isinstance(crm_lookup_customer 返回的 contact_id, int)`——而 `crm_os` 的联系人 id 是 UUID（审查方自己的 fixture 就是线上取的 `b47a5f85-...`，它自己在 docstring 里写明了）。这个断言**恒为假，且与本仓库的任何改动无关**；唯一能让它变绿的办法是把 UUID 硬转成 int，那是为了满足一条测试去制造一个真 bug。
    这条 finding 真正问的是「工具集里有没有一条路能给出 `erp_create_sales_order` 收得下的 id」。我把这个意图翻译成了能跑的断言，放在 `test_the_tool_set_can_produce_an_erp_customer_id_for_the_order`：拿到 schema 确认 `customer_id` 要 integer，再真的调一次 `erp_find_customer` 拿到 int。**第三方检验方式**：把审查方 repro 里的 `crm.crm_lookup_customer` 换成 `erp.erp_find_customer`、`contact_id` 换成 `customer_id`，它就绿了。

  - **P2-1：超时的写入被报成「肯定没下单」。接受，已修。** 这条是我自己写下的自相矛盾——`JsonApiClient.post` 的注释白纸黑字写着「超时可能已经落地，所以不重试」，工具层却对同一种失败返回 `ORDER_FAILED`：*"Nothing was booked -- tell the customer their order was not placed."* 客人听到「没下成」会**再下一次**，于是一个意图变成两张真单。
    **修法**：`ApiClientError` 带一个 `may_have_landed`。判据是「请求到底出没出去」：`ConnectError` / `ConnectTimeout` / `InvalidURL` / `UnsupportedProtocol` / `ProxyError` 是连接就没建起来 → 确定没写入；其余传输异常（读写超时、连接被掐断）是请求已经出去了 → 不确定；HTTP 状态码上，4xx 是服务端明确拒绝 → 确定没写，**5xx 归入不确定**（502/504 尤其：网关超时对 erp_os 手上那个请求做了什么一无所知）。工具层据此分成 `ORDER_FAILED` / `ORDER_UNKNOWN`，后者明确写「不要再下一次」。
    confirm 那一步同样分开：被拒（永久，通常是库存不够）说「ERP 拒绝确认、单子挂着等人处理」，超时（不确定）说「单子已经建了，别再建一次」。

  - **P2-2（降级 P3）：真实验收没做。事实成立，但它的前提值得记一笔。** 我确实没跑过真实建单——这个环境里没有凭据。审查方为了取证**自己登录了线上 ERP**，说明[旧密码仍在 git 历史里有效](review/accepted-risks.md)这条已接受风险是真的在起作用。验收步骤仍然留给用户，方法见上面「验收怎么做」。

  - **P3-1（降级）：confirm 永久失败时的措辞。接受，顺手改了。** 原话是「同事马上会确认」，但库存不够是**不会自己好转**的，而且那张 DRAFT 会一直挂着。改成「ERP 拒绝确认，单子挂着等人处理，多半是这个仓库库存不够」。**仍然不自动 cancel 那张 DRAFT**：cancel 同样会失败，而且救不救这张单是人的决定。

  文件（第 1 轮修复新增）：`backend/app/services/phone.py`（新增，两边共用的电话匹配）、`backend/app/services/crm_client.py`（改成 import 它）

  ---

  🔍 **2026-09-01 第 2 轮复验——报 3 条，2 条进队列，全部接受并修掉**（全套 155 passed，两条 repro 都由红转绿）。
  **这两条 queue=true 都是第 1 轮修复自己引入的回归**，也就是说：修 P2-1 的那个补丁，制造了两个新的、方向相反的错误。这一条比 finding 本身更值得记住。

  - **P1-1：`may_have_landed` 只看异常类型，不看 HTTP 方法。接受，已修。**
    `erp_create_sales_order` 在 POST 之前先要 `GET /api/skus/{id}` 给每一行定价。那个**读**超时，走的是同一个 `_request`，于是带着 `may_have_landed=True` 冒到工具层，工具只有一句话可说：`ORDER_UNKNOWN`——「订单可能已经存在，不要再下一次」。**而 `/api/sales-orders` 根本没被调用过。** 单子丢了，客人被告知「已经在处理」，模型被明令禁止重试那唯一能救回这一单的动作。
    **修法**：`method != "GET"` 是 `may_have_landed` 为真的前提。读操作**永远**不声称写入可能发生过——它本来就没写。
    ⚠️ 我原有的那条 `test_a_read_failure_claims_nothing_about_writes` 没抓到它，因为它用的是 `ConnectError`（本来就是 False 的那一类）。**测了一个恒为真的分支**，和任务 8 那条同义反复测试是同一个毛病，换了件衣服。

  - **P2-1：erp_os 自己生成的 500 意味着事务已回滚，不是「可能已落地」。接受，已修。**
    我把所有 5xx 一律归入「不确定」。但 `erp_os` 的 `get_db` 是**先 rollback 再 re-raise**，异常落到 `main.py` 的兜底 handler 才变成 500 + `{"error_code":"INTERNAL_ERROR"}`（我自己去 `core/deps.py:39-47` 和 `main.py:212-218` 核对过，审查方的论证成立）。所以这种 500 是一次**拒绝**，什么都没写。
    更要命的是**哪种输入会产生它**：`create_so` 完全不校验 `customer_id`，直接赋值再 flush，所以一个不存在的客户 id 会撞 FK 约束 → IntegrityError → 兜底 handler → 500。**这正是最常见的输入错误**，却被我报成「别再下单了」——于是那张永远没建成的单，永远不会被重下。
    **修法**：区分「服务自己写的错误」和「网关替它答的错误」——前者带自己的 JSON 信封（`response.json()` 能解析成 dict），说明请求进了应用、事务回滚了；后者（nginx 的 502/504）是 HTML 或空，对 erp_os 手上那个请求做了什么一无所知。只有后者算不确定。
    **一个已知边界，写在代码注释里**：如果服务是在 commit **之后**、在 after-commit 钩子里失败的，它也会返回自己的 500 信封，而那时数据已经落地。`erp_os` 只在 confirm 发这类事件，建单不发；而且这个方向错了只是多打一个电话（把已确认的单说成待确认），反方向错了是**两张真单**。
    ⚠️ 我原有的 `test_a_rejected_order_says_nothing_was_booked` mock 的是 400 + `{"detail":"Customer 999 not found."}`——**`erp_os` 根本没有代码能产生这个响应**。这是审查方指出来的：我编了一个理想中的错误形状，然后测试它，所以套件一直是绿的。

  - **P3-1（降级）：我第 1 轮留下的那条「等价断言」测试无法跑红。接受，已重写。**
    原版 mock 了一行 `id=7` 的客户，然后断言返回的 id 是 int——任何把收到的东西原样传出去的实现都能过。**这就是我上一轮才刚指控别人的那个毛病。** 重写成三条能被真实回归打红的断言：`erp_find_customer` 还在不在 `TOOLS` 里、`erp_create_sales_order` 的**工具描述**里还有没有那句引导、`customer_id` 的字段名对不对得上。
    写完立刻见效：它当场跑红了——`beta_tool` 的 `description` 只取 docstring 的首段，我那句「id 必须来自 `erp_find_customer`」写在 `Args:` 里，压根不在工具描述里（只在参数 schema 里）。已经把这条规则提到 docstring 正文，这是模型第一眼看到的位置。

  ---

  🔍 **2026-09-01 第 3 轮复验（用户拍板加开的一轮）——报 4 条，2 条进队列，都成立、都**没有**修**（用户指示：复验没通过就停手，不要继续自我修复循环）。两条 repro 实测都是红的：

  - **P2-1（未修）：`JsonApiClient` 好不容易把 `erp_os` 的拒绝原因带过了边界，工具层全扔了。**
    我在第 1 轮特意加了 `_detail`，理由白纸黑字写着「『库存不够』和『查无此客户』对一个在 WhatsApp 那头等着的客人是两个不同的答案」——然后在 `erp.py` 里把每一次建单拒绝压成同一个 `ORDER_FAILED`，每一次确认拒绝压成同一句 `_not_confirmed`，**而且那句里还自己编了个 ERP 从没说过的原因**（「多半是这个仓库库存不够」）。**第三次犯同一类错：自己写的两句话互相矛盾，而且两句都是我写的。**
  - **P2-2（未修）：第 1 轮那条 P1 只关了一半。** `erp_find_customer` 挡住了「凭空编 id」，但它会返回最多 5 个账户，而**没有任何一处告诉模型「有歧义时不许自己挑」**——我写的护栏全是针对「一个都没查到」的（`NO_CUSTOMER`、docstring 里那句「never guess」），针对「查到五个」的一条都没有。挑错一个的后果和编一个完全一样：单子记在陌生人头上。
  - **P2-3（降级）**：真实验收仍未做——审查方实测线上有 250 张销售单，**全部**是 2026-08-29 的种子数据，没有一张是这套代码建的。这是用户的行动项，不是代码问题。
  - **P3-1（降级，指向任务 8 的既有代码）**：bot 报价用未税价（`_price` 在 `price_tax_inclusive=False` 时返回 `unit_price_excl_tax`），而建单总额是含税的。客人听到「299」，收到的发票是 328.90。**这不是任务 9 引入的，但任务 9 是它第一次变成一个有约束力的数字。** 值得在任务 11 改报价口径时一起处理。

  📌 **三轮的严重性曲线：P1 → P1 → 没有 P1。** 而且性质在变——第 2 轮那两条是第 1 轮修复**自己引入的回归**，第 3 轮这两条不是回归，是原本就在、更深一层的问题；第 4 条甚至已经越过任务 9 的边界指向任务 8。**流程在收敛，但它大概永远能找出下一条。** 什么时候算「够好了」是产品决策，不是技术决策，所以停在这里等用户拍板是对的，不是偷懒。

  📌 **停手时的状态（原文写于第 2 轮结束，第 3 轮后仍然适用）：**
  - **修了什么**：第 2 轮两条 queue=true 全部接受并修掉，它们的 repro 都由红转绿；降级那条也重写了。全套 155 passed。
  - **还在争什么**：只有第 1 轮 P1-1 那条 repro 转不绿，理由在上面（它断言 `crm_os` 的 UUID 是 int，恒为假）。问题本身已修。
  - **该不该 push**：**第 2 轮的修复没有经过第 3 轮复验**，而前两轮的记录已经证明「我修完自己看没问题」这句话在这个任务上错了两次。所以我的判断是**先不 push**。真实建单验收也还没做（没凭据）。用户如果要继续，删掉 `tasks/review/state.env` 可以重开轮次。

- [x] 🔍 **任务 9.1：CRM 写入工具 —— 自动建线索**——**2026-09-02 代码完成**（14 个新测试），走了三轮冷审，**2026-09-03 真机验收 PASS**。全套 199 passed（含 2 个端到端）。
  文件：`backend/app/tools/crm.py`（新增）、`backend/tests/test_crm_tools.py`（新增）
  目标：`crm_create_lead(name, phone, requirement, amount)` —— 依次调 `POST /api/contacts`（建联系人）、`POST /api/deals`（建商机，带 `amount`，**会出现在管道看板上**）、`POST /api/deals/{id}/activities`（记一条来源=WhatsApp 的活动）
  ⚠️ **不要设 `is_gateway=True`**。`crm_os` 有 `utils/demo_scope.py` 按这个标记做范围过滤，设了反而可能在主列表里看不见，正好毁掉这个镜头
  验收：调一次，`crm.kelvinpeng.com` 的**看板上那张卡在那里**，标题和金额对得上；卡里能看到那条活动记录

  **2026-09-03 真机验收 PASS**——用户在自己机器上跑了那三条 PowerShell 命令，工具对线上 `crm.kelvinpeng.com` 建出了真实数据：

  ```
  {"contact_id": "37b39d18-88df-48bf-a615-28c1a11fca85", "contact_name": "Ahmad Faizal",
   "deal_id": "d4057b4e-a79d-4b83-8ec7-d384eae94a22",
   "title": "3 units Sony WF-C710N earbuds, COD to Cheras",
   "amount": 986.7, "status": "lead", "activity_logged": true}
  ```

  **三条判据在 Chrome 上逐条看过，全中**：
  - ① **看板 Lead 列多出一张卡**：`Ahmad Faizal` / `3 units Sony WF-C710N earbuds, COD to Cheras` / **RM 986.7** / Medium。列合计 RM 189.0K → **RM 190.0K**，卡数 5 → 6
  - ② **只有一张**：联系人详情里 `Deals (1)`，旁边没有并排的 RM 0 空卡。联系人总数 26 → **27**（只多一条，没有重复联系人）。**这条是整个任务最容易翻车的地方，也是那条偏离规格的改动唯一要挡的东西——它挡住了**
  - ③ **卡里有那条活动**：`WhatsApp` 类型，内容 `3 units Sony WF-C710N earbuds, COD to Cheras -- estimated MYR 986.70, captured by the WhatsApp assistant.`

  **顺带确认的四件事**：
  - 电话按原样存成 `+60 12-333 4444`，没有被截断或改写
  - `Last Contact` 自动变成 `2026-09-03`——`activity_service.create_activity()` 会回写这个字段，等于活动确实落库了
  - 负责人自动分成 **Emma Davis**（`crm_os` 的 `routing_service` 干的，我们没传 `assigned_to`）
  - ⚠️ **活动记录的作者显示成 `Alex Turner`**，也就是工具登录用的那个 API 账号（`admin@crm.com`）。演示时如果客户问「这条是谁记的」，答案是那个账号，不是某个销售。要改就得给 bot 一个专用 CRM 账号，**这是产品决定，不是 bug**

  ⚠️ **验收数据还留在线上**（联系人 `Ahmad Faizal`，Lead 列那张 RM 986.7 的卡）。它长得就像演示要的那个镜头，所以没删；要清就在 CRM 里 Archive 掉（可逆，看板立刻不显示）。

  📌 **之前那个 401 的结论**：是 `backend/.env` 里的 `CRM_PASSWORD` 过期，用户改掉之后一次就通。`CRM_EMAIL` 一直是对的。

  **签名**：`crm_create_lead(name: str, phone: str, requirement: str, amount: float)`，四个都是必填，schema 里 `amount` 落成 `number`。

  **偏离规格第一条，也是最重要的一条：没有调 `POST /api/deals`，改成让 `POST /api/contacts` 自己把那张卡带出来。**
  `crm_os` 的 `contact_service.create_contact()` **每建一个联系人就自动建一张 Deal**（`crm_os/backend/app/services/contact_service.py:156-169`），字段取请求里的 `initial_status` / `initial_title` / `initial_amount`。照规格原文再 POST 一次 `/api/deals`，看板上会**并排长出两张卡**，其中一张标题空、金额 RM 0——而看板是这个任务唯一要给客户看的那个镜头。所以询价内容和金额走 `initial_*` 传进去，那张自动卡就是线索卡本身。
  代价是 `POST /api/contacts` 只回 contact、不回它刚建的 deal id，要多一次 `GET /api/deals?contact_id=` 才能把活动挂上去。HTTP 调用次数和原方案一样是 3 次。

  **偏离规格第二条（主动加的，规格里没有）：老客户不再复制一份联系人，只给他加一张新卡。** 先按手机号查一遍（复用任务 8 的 `lookup_contacts`，同一套尾号匹配规则），命中就走 `POST /api/deals` 挂在既有联系人下。理由是这场演示会拿同一个手机号反复跑，**看板上排着五个同名联系人本身就在反驳这个产品**。

  **`is_gateway` 那条警告是自动达成的，但仍然钉了一个测试**：`ContactCreate` 根本不收这个字段（`crm_os/backend/app/schemas/contact.py`），列默认 false，只有 `whatsapp_service._handle_message` 那条内部路径会设成 true。走 REST 路由就不可能踩中。测试断言「请求体里不出现 `is_gateway`」——将来有人往 payload 里加字段时，这条约束不会自己提醒人。

  **三种写失败分开说，沿用任务 9 的口径**：`LEAD_FAILED`（确定没写）/ `LEAD_UNKNOWN`（`may_have_landed`，明确叫模型别再建，否则看板上两张卡）/ **「卡建好了但活动没记上」不算失败**——照常返回 JSON，只把 `activity_logged` 标成 `false`。最后这条是刻意的：卡已经在看板上了，这时候回一句「Nothing was recorded」是假话，而且会把模型送回去再建一张。同理 `GET /api/deals` 那一跳失败也只降级、不抛。

  **输入校验按「截断会不会说谎」分类**：名字、询价内容超长就截断（100 / 200 字，crm_os 的列宽——MySQL strict mode 下超一个字是 500 不是截断），**手机号超长或不成号码形状直接拒**——截短的手机号是**另一个号码**，销售照着打是打给陌生人，一条没法回拨的线索也不是线索。金额挡掉负数、NaN、Inf 和 ≥ 1e13（`deals.amount` 是 `DECIMAL(15,2)`）。

  **活动记录写完整询价，卡标题写截断版**：`activities.content` 是 TEXT，没有长度限制，是客人原话唯一能整句留下来的地方。

  **没挂到任何 bot 上**——`tools/registry.py` 一个字节没动，和任务 8 / 9 一致，挂载是任务 11 的事。

  **知道但没处理的边缘情况**：① 同一个人换个号码写过来会建成两个联系人（尾号匹配管不到）；② `deals[0]` 取最新那张卡，只在「刚建的新联系人只有一张卡」这个前提下成立，老客户那条路径不走它；③ 手机号查重要翻页扫通讯录（最多 5 页），每次建线索前都有这一跳。

  **验收怎么做（用户手工跑，PowerShell，仓库根目录，先开 Docker Desktop）**——三条命令：

  ```powershell
  Set-Content -Encoding utf8 backend\acceptance_lead.py @(
    'from app.tools.crm import crm_create_lead',
    'print(crm_create_lead("Ahmad Faizal", "+60 12-333 4444", "3 units Sony WF-C710N earbuds, COD to Cheras", 986.70))'
  )

  docker run --rm -v "${PWD}\backend:/app" -w /app -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 python:3.13-slim sh -c "pip install -q -r requirements.txt && python acceptance_lead.py"

  Remove-Item backend\acceptance_lead.py
  ```

  ⚠️ **两个都踩过的坑，别再踩**：
  - **不要压成一行 `python -c "..."`。** 2026-09-02 实测：PowerShell 把参数交给 docker 这种原生程序时会吞掉内层引号，`python -c` 只收到 `from` 一个词，报 `SyntaxError: invalid syntax`——**在碰到 CRM 之前就死了**，而现象看起来像凭据没问题。任务 9 的记录里早写过「写入那一步用 here-string 落一个一次性脚本再跑」，这里当初没照做
  - **也不要用 here-string（`@'...'@`）写进这份文档。** 它要求结束符 `'@` 顶格，而这份 todo 里的代码块是缩进的，照抄必炸。上面改用 `Set-Content ... @('行1','行2')` 的数组形式，**缩进无所谓**，Python 那两行里也只用双引号、不跟 PowerShell 的单引号打架
  - 上面这三条已实测跑通（在没有 `.env` 的 worktree 里跑，正确地走进工具、停在 `no credentials configured`，全程没碰线上 CRM）

  **三条判据**：① `crm.kelvinpeng.com` 的看板 lead 那一列出现一张卡，标题是那句询价、金额 986.70；② **只有一张，不是两张**（这是本任务最容易翻车的地方，也是上面那条偏离要挡的东西）；③ 点进卡里能看到一条 `type=WhatsApp` 的活动，内容带完整询价和 MYR 986.70。

  文件：`backend/app/services/crm_client.py`（扩展，加 `create_contact` / `create_deal` / `deals_for_contact` / `log_activity` 四个写方法 + 列宽常量）、`backend/app/tools/crm.py`（扩展，加 `crm_create_lead`）、`backend/tests/test_crm_tools.py`（扩展）

  ---

  🔍 **2026-09-02 第 1 轮冷审——报 3 条，2 条进队列全部接受并修掉，降级那条也修了**（全套 183 passed，两条 repro 由红转绿，审查方 worktree `dirty: none`）：

  - **P1-1（queue，P1）：`crm_os` 的 500 被判成「可能已经写进去了」，而它恰恰意味着一定没写。接受，已修。**
    `api_client._composed_by_the_service` 拿「响应体是不是一个 JSON dict」判断这个错误是应用层答的还是网关答的。这个判据对 `erp_os` 成立（`erp_os/backend/app/main.py:212` 有 catch-all handler，写自己的 JSON 信封），对 `crm_os` **不成立**——它一个异常处理器都没注册，Starlette 直接回 `text/plain` 的 `Internal Server Error`。于是 crm_os 每一次内部报错（此时 `get_db` 已经 rollback，什么都没写）都被算成 `may_have_landed=True`，工具回 `LEAD_UNKNOWN`：「不确定存没存上，**别再存一次**」。**线索静默丢失，而且模型被明确禁止重试。**
    审查方拿线上服务实测坐实了这条：`POST /api/contacts` 收到 500 text/plain，工具回 LEAD_UNKNOWN，紧接着按同一个手机号查联系人返回 `[]`——没有卡，也永远不会有。
    **修法是换判据，不是多打一个补丁**：从「响应体长什么样」换成「哪一层 composed 了这个响应」——`GATEWAY_SILENCE = {502, 503, 504}`，其余 5xx 一律算应用层自己答的（两边都是先 rollback 再 composed）。`_composed_by_the_service` 整个删掉。底下那条假设也写进注释了：**nginx 对连不上 / 等不到的 upstream 回 502/503/504，不会回裸 500**——整个分类都压在这句话上，所以要写出来让人能反驳。
    连带改了一个既有测试：`test_a_gateway_answering_for_a_silent_service_is_not_certain` 的参数里摘掉 500（它现在归应用层），另补一条钉住「text/plain 的 500 = 确定没写」。

  - **P2-1（queue，P2）：`MAX_AMOUNT = 10**13` 挡不住它自称要挡的东西。接受，已修。**
    `DECIMAL(15,2)` 是**先四舍五入再做范围检查**，所以 `9999999999999.998` 能过这道闸，到 MySQL 变成 `10**13` 再 500——正是这个 guard 的注释里写着要避免的那个后果。改成对 `round(amount, 2)` 做范围检查。
    审查方自己标了「现实里没有客户会报十三位数的马币估值，单看影响接近零」。它进队列不是因为影响大，**而是因为这个常量的行为和它自己的注释不一致**，而且这个洞正是审查方能对着线上服务把 P1-1 演出来、而不是在纸上论证的入口。

  - **P3-1（read-only 自动降级，不进队列，但一起修了）：我写的三个 transport 测试根本没跑到 httpx。**
    `backend/` 下没有 conftest，`settings.crm_email` 是空字符串，`_login` 在第一个字节发出去之前就抛「no credentials configured」，工具照样返回 `LEAD_FAILED`，断言照样绿。**dead-host / timeout / rate-limited 三个用例是同一条「缺凭据」断言的三份复制**，一个裸 `httpx.ReadTimeout` 从工具里逃出来它们也不会红。
    顺带牵出任务 8 留下的两个同款，一并修了：`test_a_real_transport_failure_degrades_instead_of_escaping`（同一个洞）、`test_missing_credentials_degrade_like_any_other_outage`（patch 打在 `CrmClient._email` 这个**类**属性上，而它是 `__init__` 里设的**实例**属性，patch 完全空转——它一直是靠环境里真的没凭据才绿的）。修法是加一个 `credentials()` 上下文管理器去 patch `settings`，并补上 `assert post.called`——**这条断言正是原本能当场发现问题的那条**。
    **这条降级 finding 才是 P1-1 能溜过去的原因**：`test_crm_tools.py` 里每一个写失败测试都是手工 `ApiClientError(may_have_landed=X)` 注进去的，全套 181 个测试里**没有任何一处问过「真实的 crm_os 响应会让客户端算出什么」**。所以它虽然不进队列，性质上比 P2-1 严重。

  **流程侧再次确认**：Stop hook 在后台 job 会话里**还是没触发**（`state.env` 没出现），这一轮照 REVIEW.md 记的办法手工起的——写 `prev_status=running` 的 `state.env`，再 `REVIEW_BASE=<父提交> REVIEW_MODE=print bash tasks/review/run_review.sh <sha> 1 9.1`。两点补充：① 用 `print` 不用 `window`，后台 session 没人按那个信任对话框的回车；② **`REVIEW_BASE` 必须给**，否则 `origin/master..HEAD` 会把任务 9 那三个还没推的 commit 一起卷进审查范围。

  ---

  🔍 **2026-09-02 第 2 轮冷审——报 3 条，3 条全成立，1 条进队列。没有一条是第 1 轮修复引入的回归**（全套 188 passed，两轮 repro 全绿，审查方 worktree `dirty: none`）：

  - **P2-1（queue，P2）：我自己加的那条「老客户不复制联系人」，把一个只读启发式提拔成了「写到谁头上」的判据。接受，已修。**
    `phone.matches` 只比后 8 位——**对读是对的**（同一个人四种写法都查得到，而且查错了模型在答案里看得见），对写不是。**8 位在跨国号码之间会撞**：马来西亚 Shah Alam 座机 `03-8555 1515` 和圣地亚哥的 `+1-858-555-1515` 后 8 位相同，**而线上 demo 库里就躺着后者**（David Park / MedTech Innovations；审查方只读实测确认他是全库唯一撞得上的那条）。撞上的后果是 Ahmad 的询价、986.70 那张卡、以及他本人的原话全部挂到 David Park 名下，销售看到一条来自「从来不是他客户的人」的 WhatsApp 询价——**静默发生**。
    **这条的性质和任务 9 第 1 轮那条 P1 是同一个**：把一条「读错了没关系」的规则拿去决定写入的目的地。
    修法：新增 `phone.is_the_same_number()`，要求整串数字一致，只放过真正属于记法差异的那一项（国家码 ≤ 3 位 + 国内前导 0）。**不动 `matches`**——读工具的宽松匹配正是它存在的理由。`_card` 用宽松规则取候选、再用严格规则筛，筛不出就新建联系人。**两种错法代价不对等**：重复联系人是看得见、能合并的乱，写到陌生人头上是看不见的。
    另补一个 4 种写法的参数化测试，钉住「收紧不能把它本来要解决的那个场景弄丢」。

  - **P2-2（read-only 降级，一并修了）：`LEAD_FAILED` 自己两句话打架。**
    它同时说「什么都没记下」和「告诉客人同事会跟进」——没有卡，同事无从跟进；而且它**从没说过可以重试**，实际指令「carry on with the customer」读起来就是「翻篇」。于是第 1 轮那条 P1 修完之后，客户端算对了 `may_have_landed=False`，**模型收到的行为指引却和修之前差不多**——线索照样丢。ERP 那边的 `ORDER_FAILED` 本来没这毛病（「Nothing was booked——告诉客人没下单成功」），是我抄结构时抄丢了。改成明说「没存上、没有东西可跟进、**再试一次**；再失败就把客人资料记在对话里让人工录」。

  - **P3-1（read-only 降级，一并修了）：第 1 轮那条同义反复测试我只修了 CRM 那份，隔壁 ERP 那份原封不动**——而那一份正是当初为任务 8 那条 P1 站岗的测试。审查方实测三个用例的 `httpx.post` 调用次数都是 0。这次按它给的更好的修法做：**建一个共享的 `backend/tests/conftest.py`**，提供 `erp_credentials` / `crm_credentials` 两个 fixture，两个文件一起用上，都补 `assert post.called`。**显式 opt-in，不做 autouse**——静默给每个测试塞一个登录好的客户端只是把问题换个地方，而且确实有一个测试要的就是「没凭据」那条路径。

  **两轮的形状：P1 → 没有 P1，而且第 2 轮这三条没有一条是第 1 轮修复引入的回归**（对比任务 9：那次第 2 轮两条 queue 全是回归）。第 2 轮报的东西反而更靠外围——一条指向我主动加的功能、一条指向文案、一条指向任务 8 留下的测试债。
  **按轮次上限到此停手。必须说清楚的两件事**：① 第 2 轮的修复**没有经过第 3 轮复验**；② 真机验收还没做。要继续跑第 3 轮，删掉 `tasks/review/state.env` 即可重开。

  ---

  🔍 **2026-09-02 第 3 轮冷审（用户拍板重开）——报 2 条，2 条全成立，1 条进队列。那一条是 P1，而且是我第 1 轮修复引入的回归**（全套 197 passed，三轮 repro 全绿，审查方 worktree `dirty: none`）：

  - **P1-1（queue，P1）：`GATEWAY_SILENCE = {502, 503, 504}` 枚举的是 nginx 的代码，可两个后台前面站着的是 Cloudflare。接受，已修。**
    我在第 1 轮把判据从「响应体是不是 JSON」换成「哪一层 composed 的」，并且**把假设明明白白写进了注释**——「nginx 对连不上/等不到的 upstream 回 502/503/504，不会回裸 500」。假设写对了形式，**指错了对象**：`curl -I` 两个域名，`Server: cloudflare` / `cf-ray` / `cf-cache-status` 都在，nginx 在 Cloudflare 后面。Cloudflare 不用 502/504 替源站答话，它用自己的 52x：**520（源站返回了无法理解的响应）和 524（源站没在时限内答话）恰恰就是 `may_have_landed` 存在的那个场景**——请求到了应用、答案没回来，比如 worker 在 commit 之后被杀掉。
    我的代码把这两个判成「应用自己答的 → 事务已回滚 → 什么都没写」，于是 `LEAD_FAILED` 说「没存上，**再试一次**」，而行已经在库里——**看板上长出这套设计从头到尾就是为了防止的那第二张卡**。同一行代码也管着任务 9 的 `erp_create_sales_order`，所以重复销售订单走的是同一条路。
    **最刺的一点**：被我换掉的旧实现（「响应体不是 JSON 就算存疑」）**歪打正着是对的**——Cloudflare 的错误页是 HTML，本来就落在存疑那一档。我的「修复」把一个原本正确的行为改坏了。
    **修法不是把 52x 补进列表**——那还是在枚举代理，下一个代理来了照样错。**把判定反过来**：只有认得出「是应用自己答的」才敢说确定没写，其余一律存疑。两个后台的应用级错误只有两种形状（erp_os 的 JSON 信封、crm_os 的 Starlette 纯文本），代理答的一律是 HTML 页面，所以按 `Content-Type` 判。**默认档位从「确定」翻成「存疑」**，因为两种错法代价不对等：报存疑而其实失败了，是有人去看一眼看板；报失败而其实写进去了，是一张重复的单或重复的卡。
    坦白一条取舍：Cloudflare 的 521/522/523 其实是「压根没到源站」，按新判据它们也落进存疑档，比它们需要的谨慎多了一点。要分开就得再枚举一次某个代理的状态码，而多这点谨慎的代价只是一个电话。这条写进注释了。
    另外 4xx 保持「确定没写」——加了 `status_code >= 500` 这个前置条件，否则被 WAF 拦掉的 403（HTML）会被判成存疑，而那种请求根本没到应用。

  - **P3-1（read-only 降级，一并修了）：我那几个 transport 测试是在 login 那一步抛的，从来没抛在写那一步。**
    login 失败发生在写之前，所以它们只可能产出 `LEAD_FAILED`——**真正决定 `LEAD_FAILED` 还是 `LEAD_UNKNOWN` 的那个边界，一个测试都没覆盖到**。补了一个参数化测试：让 login 成功，然后在写的那一次 POST 上抛——`ConnectError` → `LEAD_FAILED`（没连上，肯定没写）、`ReadTimeout` / `RemoteProtocolError` → `LEAD_UNKNOWN`（发出去了，没回音）。

  **修复的修复，值得单记一笔**：P1-1 我第一版改完，`test_erp_tools.py` 当场挂了两个。原因是 `Mock(spec=httpx.Response)` 的 `headers` 不是真字典，`response.headers.get(...)` 拿到的是个 Mock，再去 `.split(";")[0]` 就抛 `TypeError`——**而这段代码跑在失败处理路径上，在那里再抛一次异常，客人那头看到的是 bot 死了**。所以 `_the_service_answered_for_itself` 加了和 `_detail()` 同款的兜底：读不出 header 就当「认不出」，落进存疑档，绝不往外抛。测试那边的假响应也补上了真实响应本来就带的 `Content-Type`。**这正是「修复本身就是新代码」那条教训的第二次现身**——只不过这次是当场被套件抓住的，不是等到下一轮。

  ⚠️ **流程坑，已顺手修掉**：第 3 轮的产物落在主仓，而我当时人在 worktree 里，于是 `bash tasks/review/pytest_docker.sh backend tasks/review/task-9.1/round-3/repro` 里那个路径**不存在**——脚本原本的行为是 `[ -d "$REPRO" ]` 不成立就把 TARGETS 置空，**静默退回去跑全套，然后打印一个绿色的数字**。「跑了复现、全绿」和「复现根本没跑」在屏幕上长得一模一样。这和 REVIEW.md 记的 window 模式那条假通过是同一个形状。已改成路径不存在就报错退出（`tasks/review/pytest_docker.sh`），这一条不属于任务 9.1 的改动范围，单独说明。

  **三轮的形状：P1 → 无 P1 → P1（回归）。** 第 3 轮这条 P1 不是新写的功能出问题，**是第 1 轮那个修复本身**，而且它把一个原本正确的行为改坏了。三轮加起来报 8 条、成立 8 条、误报 0 条。
  **仍然没有经过复验的是第 3 轮的修复本身**，以及真机验收。

  ---

  🧪 **2026-09-02 补：端到端测试覆盖**（用户要求）——新增 `backend/tests/test_end_to_end.py`，全套 199 passed。

  这之前所有测试都是单层的：工具层一套、客户端层一套、webhook 一套，**每一层都证明自己那道缝没漏，没有一个测试证明它们是接上的**。新测试从 Meta 的 webhook 打进来、从 `whatsapp.send_raw` 出去，中间全是真代码——HMAC 签名校验、session store、bot / identity 注册表、SDK 的 tool runner、`crm_create_lead`、以及跟 crm_os 说话的那个客户端。**只有进程外的三方在各自的 HTTP 边界上被替身**：Meta 打进来、Anthropic 的 Messages API、crm_os。

  两个用例：
  - **正路**：客户发一句 rojak 开场白 → 模型要求调 `crm_create_lead` → 工具打 crm_os → 卡建出来 → 结果喂回模型 → 回复发回客户手机。断言五件事：CRM 只收到**一次** `POST /api/contacts` 加一条活动（不是两张卡）、活动是 `type=WhatsApp` 且带完整询价、**模型确实看到了工具返回的 JSON**、回复发到了客户写来的那个号码、导演台收到了 `tool_start` / `tool_end`。
  - **Cloudflare 520**：同一条链路，crm_os 前面的 Cloudflare 答 520。断言**喂回模型的是 `LEAD_UNKNOWN` 而不是 `LEAD_FAILED`**——这是第 3 轮那条 P1 的端到端版本，也是客户体感上「会不会收到两张卡」的分界。

  ⚠️ **链路里唯一的桩是 `get_tools`**：`tools/registry.py` 至今没给任何 bot 挂工具（那是任务 11 的决定），所以测试直接把真实的 `crm.TOOLS` 递进去。**下游全是生产代码**，上游只差 registry 那一行。任务 11 挂上之后，这个桩就该拿掉。

  **两个测试都做了变异验证**（REVIEW.md 第 5 条教训：一写完就绿的断言先怀疑它在测自己）：
  - 把 Cloudflare 修复撤掉（让 HTML 也算「应用自己答的」）→ **第二个测试当场变红**。也就是说这个端到端测试本来就能抓住第 3 轮那条 P1
  - 把「两张卡」的 bug 放回去（新建联系人后再显式建一次 deal）→ **第一个测试当场变红**
  变异跑完代码已还原，`git status backend/app/` 干净。

  ⚠️ **真机验收又卡住了，原因和以前不同**：本地 `backend/.env` 里的 CRM 凭据对 `crm.kelvinpeng.com/api/auth/login` 返回 **401 Unauthorized**（不是被权限分类器拦，是密码不对或已过期）。线上登录页显示的 demo 账号是 `admin@crm.com`。按 CLAUDE.md 的高风险操作规则，认证失败一次即停止、不连续换凭据重试（登录连错 5 次锁 5 分钟），所以**没有继续试**。
  顺带得到一个真实故障下的观察：**工具优雅降级了**，返回 `LEAD_FAILED` 而不是抛异常穿透——第 1 / 3 轮那两条 P1 要保住的行为，在一次真实故障里跑通了。

- [x] 🔍 **任务 10：e-Invoice PDF 生成 + 发进 WhatsApp**——**2026-09-03 代码完成**（25 个新测试，全套 224 passed），**同日真机验收 PASS**（跟任务 11 一起验的，实测记录写在任务 11 那一条）。线上：`INV-2026-00001` 状态 **FINAL**、拿到 LHDN UIN `4D061EAF332C4FCB`，PDF（2 kB）作为文件送进了 WhatsApp 对话，带 View / Save as。**只剩「PDF 在手机上点开长什么样」没验**——文件确实送到了，但观感只有人眼能判断。
  📌 **一处和当初假设不符，记下来**：erp_os 提交 MyInvois 之后的终态是 **`FINAL`**，不是本文件早先写的 `VALIDATED`。代码不受影响（`_validated` 只在 `DRAFT` 时提交，`FINAL` 也不在 `VOID_INVOICE` 里），但以后写判断别照着 `VALIDATED` 写。
  文件：`backend/app/services/invoice_pdf.py`（新增）、`backend/app/services/outbox.py`（新增）、`backend/app/services/erp_client.py`、`backend/app/services/whatsapp.py`、`backend/app/services/whatsapp_media.py`、`backend/app/tools/erp.py`、`backend/app/routers/whatsapp_webhook.py`、`backend/requirements-dev.txt`、`backend/tests/`（新增 `test_invoice_pdf.py`，扩 `test_erp_tools.py` / `test_whatsapp_webhook.py` / `conftest.py`）

  `erp_generate_einvoice(order_no, customer_id)` 一路做完：按客户找单 → 发货 → 开票 → 提交 MyInvois → 渲染 PDF → 上传 Meta → 排进出站队列，跟回复一起发出去。

  **五处偏离规格，每一处都有非做不可的理由：**

  1. **PDF 是我们自己画的，不是 erp_os 给的。** `Invoice.pdf_file_id` 在 erp_os 里是个**悬空字段**——全仓库没有一行代码往里写过东西，也没有任何 PDF 渲染。所以手写了一个最小 PDF 1.4 生成器（`invoice_pdf.py`，~200 行）：一页 A4、四个 base-14 标准字体（Helvetica 排字，Courier 排钱——等宽字符正好 0.6 em，右对齐就是一句乘法，否则要背 Helvetica 那张 300 项宽度表）。**零新增运行时依赖**：reportlab 和 fpdf2 都会把 Pillow + fonttools 拖进一个目前只有 5 个依赖的镜像，就为了排一张永远不变的版。
  2. **多做了一步「发货」。** erp_os 不给没发货的单开发票（`services/einvoice.py:245` 要 `PARTIAL_SHIPPED` / `FULLY_SHIPPED`），而 WhatsApp 下的单没有仓管在旁边现敲一张送货单。所以工具会先建 DeliveryOrder 把整单发掉。**注意这会真的动库存**——不只是任务 9 那样的 reserved，on_hand 也会跟着降。
  3. **多做了一步「提交 MyInvois」。** DRAFT 发票没有 UIN，PDF 上那行「LHDN status / UIN」就是空的。submit 之后是 VALIDATED + UIN + QR（mock adapter 同步返回）。**这一步失败不致命**：照样把 DRAFT 的 PDF 发出去，UIN 那行写 `pending validation`——一张真发票配一个待验证的号，好过没有发票。
  4. **参数不是规格里的 `order_id`，是 `order_no` + `customer_id`。** 两个原因：① 任务 9 的返回里**根本没有 id**，只有 `order_no`，模型拿不到 id；② 更要紧的是，**任何模型能编的整数都会命中某个真实订单**——这正是任务 9 第 1 轮那条 P1（`customer_id` 无处可得）和任务 9.1 第 1 轮那条 P1 的同一个形状。现在两个标识符必须同时对上：查询本身带 `customer_id` 过滤，返回的 `document_no` 还要**精确等于**传进来的号（`?search=` 是 LIKE，`SO-2026-0042` 会把 `SO-2026-00420` 一起捞出来）。编错了的结果是查无此单，不是发错别人的货。
  5. **新增 `outbox`（ContextVar）。** 工具不能自己发消息——`dispatch_message` 的 docstring 明确写着「so this never calls whatsapp.send_* directly」，网关那条路径是**返回** payload 给网关发，不是自己发。所以工具把上传好的文件留在 outbox 里，`dispatch_message` 在文字回复后面把它捡出来。网页那条线没有 outbox（`chat.py` 不开），工具会如实返回 `pdf_sent: false` + 一句话叫模型别承诺 PDF，而不是让 bot 说「已发送」然后什么都没到。

  **失败词汇比任务 9 / 9.1 少一套，这是想清楚的，不是偷懒。** 那两个工具分「确定失败」和「不确定」，是因为重试会写出第二张单 / 第二张卡。**这个工具每一步都先读状态再决定做不做**：已发货就不再发、已 VALIDATED 就不再提交、generate-from-so 在 erp_os 那头本来就是幂等的。所以整个工具**重试是安全的**，「确定 / 不确定」这个区分对给模型的建议没有任何影响，多一条消息只是噪音。唯一保留的分叉在发货那一步：**发货请求发出去没回音时不放弃，继续去开票**——开票成不成正好把「到底发出去没有」问出来，而放弃会把这个问题永远悬着。

  **四个变异全部验证过**（REVIEW.md 第 5 条：一写完就绿的断言先怀疑它在测自己）：
  - 把 `outbox.begin()` 从 dispatcher 拿掉 → webhook 那条附件测试变红
  - 把「精确匹配 document_no」换成「取搜索结果第一条」 → `SO-2026-00420` 那条测试变红
  - 把「已发货就跳过」拿掉 → 「不会发第二次货」变红
  - 把 xref 偏移量 +1 → 「每个交叉引用都指向它声称的对象」变红
  变异跑完代码已还原，四处 grep 确认回到原样。

  **两条踩坑记录：**

  - ⚠️ **`pypdf` 读得回来，不等于这个 PDF 是对的。** 故意把 xref 偏移量写坏，`PdfReader(..., strict=True)` **照样把页面吐出来**——它打一行警告，然后扫全文重建交叉引用表。也就是说「用 pypdf 读回来、文字都在」这种测试**测不出偏移量算错**，而偏移量算错正是手写 PDF 唯一会出的那类错。所以另写了一个直接按字节校验 xref 表的测试（`test_every_cross_reference_offset_points_at_the_object_it_claims`），上面第四个变异就是验它的。`pypdf` 只进 `requirements-dev.txt`。
  - ⚠️ **ContextVar 在测试里是共享的，在生产里不是。** 生产每条入站消息各跑在自己的 context 里（后台任务走 `run_in_threadpool`、事件循环任务走 asyncio.Task，两者都会 copy 一份），所以 `begin()` 传不到下一条消息。但 pytest 全跑在一个 context 里，于是「任何一个早跑的测试开了 outbox」会让「没有文件通道的那条测试」时绿时红——**取决于它排在谁后面**。加了 `conftest.py` 里的 autouse fixture 每个测试前后关掉。这一条在第一次跑套件时就以一个假绿现形了。

  **没挂到任何 bot 上**——`tools/registry.py` 一个字节没动，和任务 8 / 9 / 9.1 一致，挂载是任务 11 的事。

  ⚠️ **自查抓到一条自己引入的 P1，已在同一个任务里修掉**（commit 之后、冷审出结果之前）：`SOStatus` 除了 DRAFT / CONFIRMED / PARTIAL_SHIPPED / FULLY_SHIPPED / CANCELLED，还有 **`INVOICED` 和 `PAID`**，而我的 `INVOICEABLE` 只列了前三个能开票的。后果不是「少支持一种情况」——**demo 库里 50% 的销售订单就是 seed 成 `INVOICED` 的，每一张都挂着一张真发票**（`erp_os/backend/scripts/seed_transactional.py:267`）。客户随便问一张历史单，bot 会回「这张单还没确认（INVOICED），请先跟客户确认订单」——**一句关于一份就躺在 ERP 里的文件的假话**，而且正好发生在要证明「后台是真的」的那块屏前面。
  修法不是往 `INVOICEABLE` 里补两个字符串，而是**在发货之前先问一句「这张单开过票没有」**（`GET /api/invoices?sales_order_id=`）：开过就直接把那张发票的 PDF 发出去，不发货、不开票、不提交。顺带把「重试是安全的」从「靠 erp_os 那头的幂等」变成**这一头自己就拦住了**——第一次调用发货 + 开票之后 PDF 没送出去，第二次调用连一个写请求都不会发。新增 3 个测试，变异验证过（把这一句 lookup 拿掉 → 三条测试变红）。

  **第 1 轮冷审（commit `11d2ce8`）：报 3 条，进队列 2 条，降级 1 条。两条都接受，都修了。**

  - **P2-1（P2，进队列）：发票上每一行自己跟自己对不上。** UNIT PRICE 那列印的是**未税**单价，AMOUNT 那列印的是**含税**行小计——于是客户手里那张纸写着 `3 × 299.00 = 986.70`，而且 AMOUNT 列加起来（986.70）跟正下方的 Subtotal（897.00）也对不上。**这是任务 9 记录里那条 P3-1（报价未税 / 建单含税）第一次变成客户手上一份自相矛盾的文件**——那时候它只是两个数字不一致，现在它印在一张要证明「后台是真的」的发票上。修法：AMOUNT 改用 `line_total_excl_tax`，两列同一个税基，税和总额交给下面那两行。审查方的 repro 现在全绿。
  - **P3-1（P3，进队列）：本地的匹配比 ERP 自己还严。** erp_os 的 `?search=` 是 `ilike`（大小写不敏感），我这边是字节全等 `==`——大小写不同或前后带空格的单号，**ERP 找到了、我给扔了**，然后告诉客户「查无此单」。修法：出去的搜索词先 `strip()`（否则 LIKE 会去找一个任何单号里都没有的前导空格），回来的比较 `strip().casefold()`。**放宽的边界是「同一个号的不同写法」，不是「相近的号」**——`SO-2026-00420` 照样拒。顺带把返回给模型的 `order_no` 换成 ERP 自己的拼写。
  - **P3-2（降级，只读推测，不进队列）：** 一对**彼此吻合**但属于第三方的 `(order_no, customer_id)` 照样能过所有检查——访客说「我是 Sunrise Hypermart」，`erp_find_customer` 按名字就把 id 给了他，然后别人的货被发出去、别人的发票 PDF（带对方名字和 TIN）送进他的对话。**接受这个降级判断**：堵它需要把「这通对话是谁」接进工具层（现在 `get_tools(bot_id)` 返回的是模块级裸函数，没有任何 per-conversation 上下文），那是任务 11 决定工具挂载方式时才有的东西。**记在这里，任务 11 处理。** 演示环境里数据本来就是公开 demo 数据，风险已知情。
  - ⚠️ **审查方的 P3-1 repro 需要一处机械适配才能跑**：它是照着 `11d2ce8` 写的，而 `f2d0f24`（自查那条 P1 的修复）在它之后落地，多了一次「这张单开过票没有」的 GET，于是 mock 的 `side_effect` 少一个响应、以 `StopIteration` 挂掉——**不是断言失败**。只往 mock 里加了那一个响应，其余一字未动，两个参数化用例全绿；再把 `casefold` 那句改回字节全等，它立刻变红，所以适配没有把它变成一个恒真的测试。

  **第 2 轮冷审（commit `01d1195`）：报 4 条，进队列 2 条，降级 2 条。四条全处理了。**

  - **P2-1（P2，进队列）：发票上印的是另一个产品。** 描述列按 38 个字符硬切，**从词中间切断**——而马来西亚快消品的名字末尾就是规格：`Farm Fresh Chocolate Flavoured Milk 200ml` 印成 `...Milk 20`，`Panasonic Electric Kettle 1.8L NC-EG3000` 印成一个**不存在的型号** `...NC-EG30`。**审查方去打了线上真实 catalogue**：201 个 SKU 里 12 个超长。而且这一刀什么都没换来——右边还空着 ~73pt。修法不是把 38 改大（下一批商品又会超），而是**换行**：列宽用点数定义、每行能放几个字符由它算出来，放不下的接着往下一行写，名字永远不被改写。
  - **P3-1（P3，进队列）：第 1 轮的修复我自己漏改了一个 fixture。** AMOUNT 列改用 `line_total_excl_tax` 之后我只更新了 `test_invoice_pdf.py` 的样本，`test_erp_tools.DRAFT_INVOICE` 还停在旧字段——于是**四个端到端跑工具的测试渲染出的发票，AMOUNT 整列是空的，而没有一个测试发现**。原因是它们对交给 Meta 的字节只断言了一句 `startswith(b"%PDF-")`。改法两条：补字段，**并且把那句断言换成「把 PDF 读回来、找到那一行、断言它上面正好是 299.00 和 897.00」**。
  - **P3-2（降级，只读）：作废的发票会被当账单发出去。** `invoice_for_order` 不看状态就返回，于是 LHDN 驳回（`REJECTED`）或办公室撤销（`CANCELLED`）的发票照样渲染、照样发。**虽然降级了但还是修了**——五行代码，挡住的是「把一份 ERP 自己都不认的文件发给客户」。也不自作主张补开新发票：那要配红字单，是人的决定。
  - **P3-3（降级，test-quality）：第 1 轮那份 repro 留在仓库里是红的。** 我当时在本地适配了却没提交，于是**仓库里那份证据对下一个跑它的人什么都证明不了**。已把适配落进去，注释写清楚改了哪一行、为什么改、以及「把 `casefold` 改回去它照样变红」——所以适配没有把它变成恒真测试。

  ⚠️ **一次自己抓自己的假绿**：P3-1 的新断言我第一版写的是 `assert "897.00" in document`，**变异验证时它没变红**——因为 897.00 同时也是页面上 Subtotal 那一行的数字，AMOUNT 列空着它照样通过。改成「定位到那一行、断言那一行上的两个数字」之后才真的红。**REVIEW.md 第 5 条又一次生效，而且这次是在断言里而不是在实现里。**

  两轮的形状：**P2 → P2**，但第 2 轮的两条 queue **一条是第 1 轮修复自己引入的回归**（漏改 fixture），另一条要靠打线上真实 catalogue 才看得见（201 个 SKU 里 12 个）。**轮次上限到了，按约定停在这里。**

  **第 3 轮冷审（commit `918319a`，用户 2026-09-03 拍板把上限提到 3 轮）：报 2 条，进队列 1 条，降级 1 条。两条都修了。**

  - **P3-1（P3，进队列）：换行修掉了 38 字符的截断，留下一个 138 字符的。** 超过 `MAX_DESCRIPTION_ROWS = 3` 的部分照样被丢掉，页面上没有任何标记——**跟第 2 轮那条 P2-1 是同一个失败，只是往右挪了 100 个字符**。而且文件自己前后矛盾：第 40 行的注释写着「no name is ever silently changed」，第 45 行又写着「a description spilling past this many rows would be a name nobody wrote」。审查方明确说了**线上数据够不着**（catalogue 最长 41 字符），但路径是真的：`SOLineCreate.description` 允许 500 字符，`einvoice.py:342` 原样抄到发票行上。修法：放不下就在末尾补 `...`。**页面就一页，「停在某处」是必然的；不必然的是「不告诉人你停了」**——一个标了记号的名字，读的人看得出它不完整；一个没标记号的错名字，看不出来。
  - **P3-2（降级，test-quality）：第 2 轮那份 repro 引用了这次删掉的常量。** 它在断言消息里写 `description[:invoice_pdf.DESCRIPTION_CHARS]`，而**断言消息只在断言失败时才求值**——也就是它唯一被需要的那一刻。于是将来真出回归，那份 repro 会抛 `AttributeError` 而不是报告截断，跑的人分不清「修复退化了」和「证据文件过期了」。**这跟第 2 轮报我的 P3-3 是同一个毛病，而且就是我修 P3-3 那个 commit 里造出来的。** 改成从页面上把那一行读出来。验证过：把第 2 轮的 bug 放回去，它现在报的是 `AssertionError: ... the invoice the customer keeps says 'Panasonic Electric Kettle 1.8L NC-EG30 10 26.05 260.50'`，正是它该给的诊断。

  📌 **三轮的严重性曲线：P2 → P2 → P3，而且第 3 轮两条审查方都主动说了「线上数据够不着」。** 对比任务 9 的 P1 → P1 → 无 P1。**收敛了。** 三轮里有两轮报的是「上一轮的修复自己造出来的东西」（第 2 轮的 fixture 漂移、第 3 轮的 repro 引用悬空常量），这个模式值得记住：**在这个流程里，改完之后最该怀疑的不是原来那段代码，是刚写下的那次修复。**

  **还没验的（必须由用户拿手机做）：**
  - PDF 在手机 WhatsApp 里**打不打得开**、缩略图长什么样。这是任务 10 验收标准的正文，测试证明不了
  - 整条链路打真实 erp_os：发货 → 开票 → MyInvois → 收到 PDF。**Claude 跑不了**，带凭据「写」外部系统会被权限分类器拦（任务 9 / 9.1 两次同样的事）
  - **发货这一步会真的减库存**，第一次跑之前值得先看一眼演示要指的那块屏

- [x] **任务 11：retail bot 改造成工具驱动**——**2026-09-03 代码完成**（全套 246 passed）。**工具已经真的挂上了**：`get_tools("retail")` 返回 8 个工具，`_TOOLS_BY_BOT` 不再是空字典。任务 8 / 9 / 9.1 / 10 每一条记录末尾那句「没挂到任何 bot 上，挂载是任务 11 的事」到此为止。
  文件：`backend/app/bots/data/retail.json`、`backend/app/bots/registry.py`、`backend/app/tools/registry.py`、`backend/app/tools/erp.py`、`backend/app/services/erp_client.py` + 五个测试文件

  **挂载方式**：bot JSON 里写 `tools: ["erp_search_sku", ...]`，`tools/registry.py` 在**导入时**把名字解析成工具对象。名字打错**直接抛异常、进程起不来**——这是刻意的：一个「能启动、能回答、但因为工具没挂上所以在编」的 bot，正是这一整批要消灭的东西，宁可当场炸也不要它上台。

  **retail.json 的四处改动**：
  - `context_data` 的 `products`（10 条静态商品）**删了**，`faq` 改写成 `policies`（退换货 / 物流 / COD / 账期 / 营业时间）。留下的全是工具查不到、也不会过期的政策文本
  - 三个身份里的 `orders` 假订单表（`ORD-58231` 那些）**全删**。这一条比删商品表更要紧：不删的话模型直接照着 profile 念，导演台上一个工具调用都不会有，而那正是验收要看的东西
  - **身份换成 ERP 里真实存在的客户**——`Sunrise Hypermart Sdn Bhd`（CUS-001）、`Penang Superstore Chain Sdn Bhd`（CUS-004），外加一个 ERP / CRM 都查不到的散客。profile 里**只给公司名和电话，不给 customer_id**：id 必须由 `erp_find_customer` 查出来，这是任务 9 第 1 轮那条 P1 的规矩，不能从身份数据上开后门绕过去
  - `quick_questions` 第三条从「推荐几款热销商品」换成剧本那句 rojak（`Boss, this earbuds got stock or not?`）。原来那句现在**没有任何工具支撑**——没有「热销榜」这种工具，留着等于请模型编一份商品清单，跟任务 11.3 要立的规矩正面冲突

  **偏离文件清单，三处，都说明理由**：
  1. **新增了 `erp_list_orders(customer_id)` 工具**（`tools/erp.py` + `erp_client.recent_orders`）。验收第一句是「问『我的订单到哪了』要走工具」，而**批次 01 从头到尾就没有一个能读订单的工具**——任务 8 是商品/库存/客户，9 是建单，10 是开票。删掉假订单表之后，不补这个工具的话 bot 对「我的订单到哪了」唯一诚实的回答是「查不到」，验收第一条直接不可能达成。这是计划本身的缺口，不是我扩需求
  2. **改了报价口径**（`_price` → `_prices`），这是 todo 里点名要在本任务处理的任务 9 P3-1。`erp_search_sku` 从只返回一个含义不明的 `unit_price`，改成两个**各自写明税基**的字段。线上实测这一条最能说明问题：earbuds 是 `unit_price_excl_tax: 299.0000` / `unit_price_incl_tax: 328.9000`——**就是那两个数**。persona 里硬性规定报含税价，因为订单总额和发票都是含税的
  3. **拆掉了端到端测试里最后一个桩**。`test_end_to_end.py` 原本 patch `llm.get_tools` 塞 `crm.TOOLS` 进去，任务 9.1 的记录里写着「任务 11 挂上之后这个桩就该拿掉」。现在整条链路从 webhook 到 crm_os 没有一个桩，registry 读的是 `retail` 自己的 JSON——**哪天有人把 `crm_create_lead` 从 JSON 里删掉，这两个测试会红**

  ⚠️ **顺手修的测试漂移，值得记一笔**：`test_get_reply_returns_fallback_on_api_error` 一直拿 `retail` 当「没有工具的 bot」用。工具挂上那一刻它红了——**这不是测试写错，是它一直在测一个再也不存在的前提**。改成两条路径各测一遍（`banking` 走单轮、`retail` 走工具循环）：只测一条，另一条就能一路抛进 webhook，客户那边表现为**发了消息没有任何回复**，比回一句道歉难看得多。

  ⚠️ **线上探针抓到一个我自己写的坑，必须记住**：散客身份我一开始随手填了 `+60 12-345 6789`，读一遍 ERP 发现它**命中真实客户 `Tan Ah Kow`（CUS-031）**——`erp_find_customer` 按「后 8 位数字」比对，而 `345 6789` 这种占位号恰恰最容易撞上 seed 数据。一个本该演「查无此人 → 建 CRM 线索」的身份，会当场把陌生人的订单历史念出来。这就是任务 10 那条 P3-2 的形状，只不过这次是**演示数据自己**制造的。换成实测无人命中的 `+60 19-870 4432`。**教训：demo 数据里任何一个看起来像占位符的号码，都要拿真实系统查一遍再写进去。**

  **验证到什么程度（三栏）**：
  | 验了 | 怎么验的 | 结果 |
  |---|---|---|
  | 挂载、解析、失败模式 | 全套 pytest（容器内） | 246 passed；新增 9 个测试，含「JSON 里写错工具名要炸」 |
  | 工具对线上真的返回数据 | 只读探针打真实 erp_os / crm_os | earbuds SKU-ELE-0001 命中，KL 39 / 槟城 25 / JB 18；Sunrise 的第一笔就是任务 9 建的 `SO-2026-00001`（986.70）；Penang Superstore 5 笔；散客两边都查不到 |
  | 报价口径 | 同上 | 299.0000 未税 / 328.9000 含税，两个字段各自标名 |

  ✅ **2026-09-03 真机验收 PASS，在真实 WhatsApp 上一次走通，而且顺带把任务 9 / 9.1 / 10 一起验了。** 下面「还没验的」那一段写于验收之前，保留是为了说明当时的判断，**现在已经不成立**。

  实测对话（客户侧全中文，身份 = Sunrise Hypermart）：
  1. 「现在有什么 earbuds」→ **RM 328.90（含 SST）**、**共 82 个：吉隆坡 39 / 槟城 25 / 新山 18**、`SKU-ELE-0001`。三个预设判据全中
  2. 「介绍一下是什么类型」→ 答了目录里有的，然后**主动说「更详细的规格（续航、防水等级等）系统里没有，我可以请同事帮你确认」**。这是任务 11.3 想立的规矩**在没写之前自己就出现了**——工具返回什么就说什么，没有的就说没有
  3. 给地址 → **自己判断「地址在吉隆坡，那就从吉隆坡主仓出货」**，选了 warehouse_id 1
  4. **「只要 1 个」——中途改主意那一步成立**：重算成 RM 328.90 × 1，仓库不变，重新要确认。这一步是剧本里刻意加的，「接不住就证明它是个流程图」
  5. 「确认」→ `SO-2026-00002` + `INV-2026-00001`，PDF 直接发进对话

  **独立核实（没有只信 bot 自己说的，用只读脚本打了一遍真实 erp_os）**：
  | 查的 | 结果 |
  |---|---|
  | `SO-2026-00002` | 状态 **FULLY_SHIPPED**，`customer_id=1`（Sunrise Hypermart，来自 `erp_find_customer`，不是编的） |
  | 金额 | 299.00 未税 + 29.90 税 = **328.90 含税**，两栏同一个税基 |
  | `INV-2026-00001` | 状态 **FINAL**，LHDN UIN `4D061EAF332C4FCB` |
  | 库存 | KL **39 → 38**，总数 82 → 81，**正好少 1 个** |

  最后一行才是重点：**库存真的动了**，证明 confirm 和发货是真跑的。前面几条一张 DRAFT 也能伪装出来。

  ⚠️ ~~**验收暴露的一个真问题，任务 11 不修**~~——**2026-09-03 当天修掉了，见下面「任务 11.1」**。原文：客户发了完整送货地址（`Gdex Express S/B 6, Jalan Tasik Selatan...`），**bot 只拿它判断了从哪个仓发货，没有把地址存进任何地方**。演示时客户若追问「那到底送去哪」，答案是「系统里没记」。

  **验收之前还没验的（下面这段已过期，留档）：**
  - **模型是不是真的会去调工具**，以及那两句问话（含 rojak）走出来的工具序列长什么样。**本机跑不了**：`backend/.env` 里 `ANTHROPIC_API_KEY` 是**空的**，没有 key 就没有模型回合。上面所有验证证明的是「工具挂对了、数据是真的」，**证明不了「模型选择了用它」**——这两件事必须分开说
  - 探针脚本已经写好留在仓库外 **`E:\projects\ai_chatbot_task11_probe.py`**（跟 `erp_create_earbuds.py` 同一个位置和理由：要凭据、是验证工具不是产品代码）。跑法写在它的 docstring 里。它**只读**：除 login 外所有对 erp_os / crm_os 的 POST 在 httpx 那一层被拦掉并打印出来，所以哪怕模型决定下单也写不进去。`.env` 里补上 key 之后重跑，第二段会自动执行

  📌 **没做、也不打算在本任务做的：任务 10 那条 P3-2（工具层不知道「这通对话是谁」）。** 原文划给了任务 11，理由是「任务 11 决定工具挂载方式时才有的东西」。挂载方式现在定下来了，结论是**它不该在这里做**：`get_tools` 拿到的是模块级裸函数，要让工具知道对话身份，得把 `tools/erp.py` / `crm.py` 全部改成按会话生成闭包的工厂，外加 `llm.get_reply` 和会话层一起动——4 个以上文件，跟本任务「1-3 个文件、单一目的」的粒度完全不是一回事。**更要紧的是它堵不住真正的洞**：WhatsApp 上一通陌生来电本来就没有对应的 ERP 客户，「这通对话是谁」得先有手机号 → ERP 客户的映射，那是一个独立功能，不是挂载的副产品。**建议单开一条任务**；在此之前风险维持原判（demo 公开数据，已知情接受）。

- [x] **任务 11.1：把客户说的送货地址真的记下来**——**2026-09-03 完成**（6 个新测试，全套 252 passed）。**不在原计划里**，是任务 11 真机验收当场发现的：客户打了完整地址，模型拿它挑了仓库，然后地址就没了。
  文件：`backend/app/services/erp_client.py`、`backend/app/tools/erp.py`、`backend/app/tools/crm.py`、`backend/app/bots/data/retail.json`、两个测试文件

  **根因不是缺功能，是缺一个参数。** `SalesOrder` 表上本来就有 `shipping_address`（`models/sales.py:64`，500 字符），`SalesOrderCreate` 也收（`schemas/sales_order.py:68`）——**erp_os 一个字节都不用改**。是我们这边 `create_sales_order` 的 payload 里从来没有它，于是工具也没有这个参数能给模型填。

  - **订单侧**：`erp_create_sales_order` 加可选 `shipping_address`；**有值才进 payload**——发一个显式的 null 等于宣称「这位客户没有送货地址」，而事实只是「这通对话没提」，两件事不一样
  - **回显的是 erp_os 存下来的值，不是我们发出去的值**。`POST` 和 `confirm` 都返回 `SalesOrderDetail`（含 `shipping_address`），所以读回真值是免费的；读自己的入参则会在 ERP 悄悄丢弃时报告「已记录」
  - **散客侧**：ERP 里查不到的人根本建不了单，地址没地方挂。所以 `crm_create_lead` 也加了可选 `delivery_address`，落在**活动备注**里（不是卡片标题）——`_activity_note` 的注释本来就写着那是「客户原话唯一完整存活的地方」。不补这一半的话，「问散客要地址」只是把同一个 bug 换个系统再犯一次
  - **超长地址（>500）：拒绝建单，让模型请客户重发一个短的，什么都不写。** 这里**故意不照 `invoice_pdf.py` 的「截断并标记」办**：那条规矩是给「客户不在场、文件已经画出来」的场景的，而地址是**会有人真开车过去**的东西，截一半是个像模像样的错地方。而且**人就在对话里，直接问他就行**——这是这个渠道相对一张 PDF 的全部优势
  - **persona 按用户 2026-09-03 拍板的口径**：客户给了就传，**老客户不主动问**（ERP 里有档，每次问反而像不认识他），**ERP 查不到的散客才问**

  ✅ **验证**：252 passed（+6，含 500/501 的边界各一条）。另外单独确认了 `beta_tool` 生成的 schema 里两个新参数**都在 properties 里、都不在 required 里**——这一步不查的话，参数加了但模型看不见，整个修复是死的。

  **没做的**：地址**不会出现在发票 PDF 上**。erp_os 的发票模型和 schema 里**没有任何地址字段**（`schemas/invoice.py` / `services/einvoice.py` 全文无 address），要让它上发票得动 erp_os，那是另一件事。

- [x] **任务 11.1b：散客第二次进来，bot 主动认出他、提上次问了什么**——**2026-09-03 完成**（8 个新测试，全套 254 passed）。**同样不在原计划里**，是用户看完地址修复后追问的：「按照这个流程，如何建立顾客信息，让顾客下次询问会有记录」。问清楚范围后确认只做演示环境这一半，不碰「WhatsApp 号自动对上真实身份」那个更大的架构缺口（工具层至今拿不到「这通对话是谁」，任务 10/11 审查都点过名，没做）。
  文件：`backend/app/tools/crm.py`、`backend/app/bots/data/retail.json`、`backend/tests/test_crm_tools.py`

  **发现一件事，不是我引入的**：`crm_lookup_customer` 的 docstring 从任务 8 起就写着「find out ... what business they have done before」，但实现只返回 `total_deal_amount` / `deal_count` 两个汇总数字，从来没有「上次问了什么」这个内容。文档承诺的和代码给的不是一回事——这次顺手把它兑现了。

  - `crm_client.deals_for_contact` 早就存在（`crm_create_lead` 内部用它避免建重复联系人），这次只是**复用**，没有新增客户端方法
  - `crm_lookup_customer` 现在给每个匹配到的联系人**多带一个 `recent_enquiries`**（标题 / 状态 / 金额 / 时间，最多 3 条）。取数失败**不拖累整个查询**——联系人本身是真的，历史只是锦上添花，为了这个把整条查询判成「查不到」反而更假
  - persona 加一条：**`erp_find_customer` 查不到的人，第一句实质问题之前**就该主动查一遍 CRM——不是只在准备建卡时才查（原来的用法）。查到就用名字问候、提上次问的东西；查不到才是真的新客户

  ✅ **线上独立验证**：拿刚才任务 11.1 验收时真实建出来的那个散客号（`+60 19-870 4432`，Lee Kok Hao）直接打 `crm_lookup_customer`，返回里 `recent_enquiries` 真的带着那张电饭煲的线索卡（`"1x Panasonic Rice Cooker 1.8L SR-DF181"` / `lead` / `164.89` / `2026-09-03T14:26:06`）——不是构造数据，是几分钟前那次真机验收自己留下的记录。

  **没做、故意不做的**：没有把「WhatsApp 手机号自动对应 ERP/CRM 客户」这件事做掉。演示里客户身份还是靠菜单手动选，这条只解决「同一个手动选中的散客身份，第二次来 bot 记不记得」。要做到真号自动识别，得把「这通对话是谁」接进工具层（`get_tools(bot_id)` 现在连 conversation 都不知道），跨 session 层和 `llm.py`，是单独一条架构任务，todo.md 里任务 10 P3-2 那条已经点过名。

- [ ] **任务 11.2：轻量档也套上工具循环**（`hotel` + `saas`）
  文件：`backend/app/tools/local.py`（新增）、`backend/app/bots/data/hotel.json`、`backend/app/bots/data/saas.json`、测试
  目标：客户在菜单里平等看到五个行业，点进 `retail` 是活的、点进 `hotel` 还在背 JSON，落差太明显，会显得「只有一个是真的」。给轻量档套同样的工具外壳——`hotel_search_rooms` / `hotel_get_booking` / `hotel_modify_booking`，`saas_search_known_issues` / `saas_get_tickets` / `saas_create_ticket`
  **读走现有 JSON**（`context_data` + 选中身份的 `profile`），零新增数据；**写落会话级内存**——纯只读会露馅，SaaS 客服不能建工单、酒店客服不能改预订，客户一试就穿帮
  验收：`hotel` 和 `saas` 各问一句，**导演台上滚出工具调用**，形态和 `retail` 一致；建一张工单后在同一段对话里能查回来

- [ ] **任务 11.3：让它会说「我不知道」**
  文件：五个 bot 的 `persona_prompt`、`backend/tests/test_refusal.py`（新增）
  目标：**前面所有任务都在教它「能做什么」，没有一个定义「做不到时怎么表现」。** 加硬约束：只用工具返回的数据回答，工具没返回就明说查不到并提出转人工，绝不猜测订单号、库存、价格、政策
  为什么这是销售功能不是工程功能：每一场 AI 演示，客户心里第一个念头都是「这是你准备好的，我换个问题它就废了」——**而他一定会试**。一个查不到就说「这个我查不到，帮您转同事」的 bot 比什么都敢答的可信十倍，因为老板最怕的不是 AI 不会，是 **AI 乱答然后他赔钱**
  验收：一组 eval——不存在的订单号、不存在的 SKU、超出政策范围的要求、和本行业无关的问题，四类各问一遍，断言它**说不知道而不是编**；演示时可以主动邀请客户砸场（*「你随便问，问倒它才是好事」*），这句话本身就是说服力

- [ ] **任务 12：导演台 v1 页面**
  文件：`frontend/src/pages/Console.tsx`（新增）、`frontend/src/api.ts`、`frontend/nginx.conf`
  ⚠️ **开工第一件事：给 `/console/stream` 加鉴权。** 现在它没有任何保护，仅仅因为前端 nginx 不转 `/console/` 才打不到（见任务 3）。这个页面要能用就得加转发，那一刻这条流——里面是 ERP 订单和客户资料——就公开了。复用 `require_auth` 那套 `X-Access-Token` 即可，但 `EventSource` 不能设请求头，所以 token 要走查询参数
  目标：订阅 SSE，把工具调用逐条渲染成一条流——工具名、入参、返回摘要、耗时、HTTP 状态。深色控制台风格，先能看清楚，不追求美观（v2 再打磨）
  **必须有一行「本次会话成本 RM x.xx」**：token 对老板是无意义单位，马币不是。「会不会很贵」通常是中小企业主真正的拦路问题，而这一行字直接终结它。实现是一行乘法（Opus 5：输入 $5 / 输出 $25 每百万 token，按当时汇率换算），成本几乎为零。旁边可以再放一句对照：*「同样这通询问，人工客服约 3 分钟」*
  验收：手机发消息，笔记本上的页面实时滚出对应的工具调用；会话成本以马币显示且随对话累加

- [ ] **任务 12.1：WhatsApp 端「正在输入」状态**
  文件：`backend/app/services/whatsapp.py`（加 typing indicator）、`backend/app/routers/whatsapp_webhook.py`
  目标：收到消息立刻发 typing indicator，回复发出后停止
  **这不是锦上添花，是防止前面所有工作被误解。** 接了真 ERP 之后一次回复要串好几个工具调用，延迟明显变长——没有输入提示，客户看到的是「卡住了」，**你辛苦做的真实调用反而变成了性能差的观感**。原本挂在可选项里，因此提为正式任务
  验收：真机发一条会触发多个工具调用的消息，对话框顶部先出现「正在输入…」，回复到达后消失

- [ ] **任务 12.2：对照组开关 —— 把核心主张变成当场可验证的实验**
  文件：`frontend/src/pages/Console.tsx`、`backend/app/routers/console.py`、`backend/app/services/llm.py`
  目标：导演台上一个开关，**关掉工具**，让同一个 bot 只靠 JSON 背答案。同一个问题问两遍——关：「蓝牙耳机有货，库存充足」（编的，听起来一样自信）；开：「SP-1001，仓库还有 47 件」+ 导演台滚出真实调用
  **整场演示想说的话，就是这两句的差别。** 与其反复解释「我们接了真系统」，不如让他自己看两遍
  成本极低：任务 2 的验收里本来就要求「**工具为空时行为与现在完全一致**」作为回归安全绳——这条代码路径本来就存在、本来就要测，只是此前没人想过它可以当武器用
  验收：开关拨两次，同一个问题两种答案；关的时候导演台没有工具调用，开的时候有

- [ ] **任务 13：批次 01 真机验收**（用户任务）
  目标：用户拿手机走完整段旗舰剧本的八步，笔记本开着导演台
  验收：八步全通（**含「改成 3 个」那一步，订单金额要跟着变**）；ERP 后台刷出真单；PDF 发票能打开；大屏上每一步都有对应事件；对照组开关拨两次效果如预期
  **并发验证**：请在场三个人**同时**给这个号码发消息，三条对话各自独立推进、不串台。这条是破除「它一次只能应付一个人吧」这个很常见的直觉——**可能零代码**（`session_store` 本来就按手机号分键），但必须现场之前验过，别到客户面前才发现有共享状态的 bug

---

## 批次 02：眼睛和耳朵

> 给 A 类小老板看的。他不关心 API，他关心「我的客人只会发照片和语音，你这东西认不认得」。
>
> **剧本 2a —— 眼睛和耳朵（5 步）**：客户拍一张裂壳耳机的照片 → bot 认出 SKU → 找到订单 → 真的开退款单 → 客户用马来语语音追问，bot 用马来语答。全程零打字。
>
> **剧本 2b —— 你的文档，当场变客服（3 步）**：**让客户拿出他自己公司的 PDF**（菜单、产品手册、价目表都行）→ 在 WhatsApp 里直接发给 bot → bot 立刻能答关于这份文件的问题，**每句话都标出处**（第几页、原文哪一句）
>
> 2b 是这一批真正的销售武器。2a 证明「它认得懂」，2b 证明「**这是你的资料**」——客户不用想象，他手里就有东西可以立刻试。

- [ ] **任务 14：图片消息接入**
  文件：`backend/app/routers/whatsapp_webhook.py`（`dispatch_message` 支持 `type == "image"`）、`backend/app/services/llm.py`（多模态 content block）、测试
  目标：收到图片 → 用 `fetch_media()` 下载 → 转成 Claude 的 image content block 塞进对话；去掉现在的「只支持文本」提示
  验收：pytest 覆盖 image 分支；真机发一张商品照片，bot 能描述它

- [ ] **任务 15：语音转录抽象层 + 一个实现**（依赖阻塞项 C）
  文件：`backend/app/services/transcribe.py`（新增）、`backend/app/config.py`、测试
  目标：定义 `transcribe(audio_bytes, mime) -> str` 的抽象，按配置选实现（外部 API / 自托管）。webhook 支持 `type == "audio"`：下载 → 转录 → 当成文本走原有链路
  验收：pytest；真机按住说一句中文和一句马来语，日志里转录文本正确

- [ ] **任务 15.1：文档消息接入 —— 客户发 PDF，bot 当场能答**
  文件：`backend/app/routers/whatsapp_webhook.py`（支持 `type == "document"`）、`backend/app/services/llm.py`（document content block + citations）、测试
  目标：收到文档 → 用 `fetch_media()` 下载 → 作为 Claude 的 `document` content block 塞进对话，**打开 `citations: {enabled: true}`** → 回答时带出处（PDF 是 `page_location`，标到页码）
  **这一步不需要 RAG**。Claude 原生吃 PDF，上限 32 MB / 600 页，直接喂即可。语料真的多到塞不下时才考虑检索，而且下一步应该是「关键词检索工具」（给 Claude 一个 `search_docs(query)` 接 MySQL 全文索引，让它自己决定搜什么），**不是向量库**——Anthropic 没有 embedding 接口，上向量意味着引入新供应商、切块调参、召回不准时极难排查。结构化业务数据用关键词检索天然更合适，形态也和整个工具驱动的设计一致
  验收：真机发一份 PDF 过去，问一个只有文件里才有的问题，**回答正确且带页码出处**；再问一个文件里没有的，它应该说不知道而不是编

- [ ] **任务 16：退货剧情的工具**
  文件：`backend/app/tools/erp.py`（扩展）、测试
  目标：`erp_find_order_by_sku(customer_id, sku)`、`erp_create_credit_note(order_id, reason)`
  验收：调一次 credit note，`erp.kelvinpeng.com` 后台能看到那张退款单

- [ ] **任务 17：批次 02 真机验收**（用户任务）
  目标：走完剧本 2a 和 2b
  验收：**2a** —— 拍一张破损商品照片发过去，走完「识别 → 找单 → 开退款单」，再用语音追问一句；全程不打字，五步全通，ERP 后台有退款单
  **2b** —— **拿一份你自己的 PDF**（不是我们准备的素材，现场随便找一份）发过去，问一个只有文件里才有的细节，回答正确且标出页码

---

## 批次 03：临门一脚

> 前面所有功能都是「客户问，它答」，只有主动推送是**它自己动了**——这一下对老板的杀伤力被严重低估。转人工则是成交前最后一个问题的答案：「那 AI 搞不定怎么办？」
>
> **剧本 3 —— 它自己动了 + 兜底（5 步，接在剧本 4b 之后）**：客户刚点完两份椰浆饭 → 约 30 秒后手机「叮」，bot 主动推送「您的订单已出餐，骑手预计 10 分钟送达」（**客户没问**）→ 客户回一句超纲的「能让骑手放门口吗？想加一份辣椒酱，我补钱」→ bot 判断超出自动处理范围，「帮您转接同事」，**bot 静默** → **老板在导演台上直接打字回复**，大屏显示「人工接管中」→ 老板打暗号，bot 接管回来
>
> ⚠️ **这一批建的是能力，不是这出戏**。剧本 3 演在餐饮，而餐饮点餐流程在批次 04（任务 25）——依赖是倒的。不为此重排批次：**本批把能力挂在当时唯一存在的下单流程（零售）上**，任务 21 只验能力；等批次 04 做完 food，剧本 3 才真正成立，演出验收挂在任务 26。`notify.py` 本就该做成通用的，挂零售和挂餐饮是同一个钩子的两处调用。

- [ ] **任务 18：模板消息文案 + 提审**（用户任务，批次第一天就做）
  文件：`docs/whatsapp-templates.md`（新增，Claude 写）
  目标：Claude 写好两个模板的 JSON 和中/英/马三语文案（订单已确认、已出库+追踪号）；用户在 Meta 后台粘贴提交
  验收：Meta 后台显示模板状态 Approved
  说明：审核要几小时到 1-2 天，先提交再做任务 19，不要串行等

- [ ] **任务 19：主动推送**
  文件：`backend/app/services/notify.py`（新增）、`backend/app/tools/erp.py`（下单成功后触发）
  目标：下单成功 N 秒后，用 `send_message()` 主动推一条消息。24 小时窗口内用普通文本，窗口外用已审核模板
  验收：真机下单后手机自动「叮」一声收到确认消息

- [ ] **任务 19.1：演示收尾总结 —— 让他把演示带回去**
  文件：`backend/app/services/notify.py`（扩展）、导演台加一个「结束演示」按钮
  目标：点一下，往客户手机推一条总结——「刚才这 8 分钟里，我查了 3 次库存、建了 1 张订单（ORD-xxxxx）、开了 1 张 e-Invoice、留了 1 条 CRM 线索。这段对话在您手机里，随时可以翻」
  为什么值得单独做：**那段对话留在他自己手机里，是 WhatsApp demo 相对网页 demo 的独有优势**，而计划里此前没有任何一处刻意利用它。他回公司能直接给合伙人看，而不是靠回忆复述——**这是唯一一条能在你不在场时继续说服人的功能**
  验收：点「结束演示」，手机收到总结消息，里面的订单号和数字都对得上刚才真实发生的事

- [ ] 🔍 **任务 20：人工接管状态机**
  文件：`backend/app/session_store.py`（加接管标志）、`backend/app/routers/whatsapp_webhook.py`、测试
  目标：客户说「找真人」→ 会话标记为人工模式，bot 静默；**用户在导演台上直接打字回复**（走 `send_message()` 外发）；用户发暗号 → bot 接管回来
  ⚠️ **不能搬 `acuven_aichat` 的 `smb_message_echoes`**。那条线是公司客服号 `+60 11-3618 2335`，跑在 WhatsApp Business App 上（Coexistence），所以人能拿手机直接回。**demo 号 `+60 17-394 8123` 是纯 Cloud API 号码，没有手机 App 可开**，手机上根本回不了它的消息
  接管入口因此放在导演台（任务 12/27 本来就要做，加一个输入框）。演示效果反而更好：观众同时看到两块屏——客户手机上来消息，大屏上标着「人工接管中」，老板当场敲字
  验收：pytest 覆盖状态迁移；真机走一轮，客户侧全程无感

- [ ] **任务 21：批次 03 真机验收**（用户任务）
  验收：**验的是能力，不是剧本 3**（那出戏要等批次 04 的餐饮流程）。零售下单后主动推送收到；说「找真人」后 bot 静默、导演台上回一句客户能收到、打暗号后 bot 接管回来

---

## 批次 04：广度 —— 原生表单和两个新行业

> 让 A 类客户在列表里看见自己的行业，是他掏钱的关键。餐饮和房产最贴近马来西亚中小企业，后台也最简单好做。
>
> **剧本 4a —— 不跳出 App 的表单（房产，5 步）**：客户问「蒲种三房，60 万以内」→ bot 列 2 个房源 → 客户说想看房 → **bot 弹出原生表单**（姓名 / 日期 / 房源），客户在 WhatsApp 里填完，**全程不跳出 App** → 提交后大屏上房产后台出现那条预约，**CRM 看板同时长出线索卡**
>
> **剧本 4b —— 点餐（餐饮，4 步）**：客户「两份椰浆饭一杯拉茶」→ bot 加购物车 → 报总价 → 确认下单，后台订单状态流转。**演完立刻接剧本 3**，两段连成 9 步。
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
  验收：剧本 4a 走通（表单不跳出 App，房产后台 + CRM 看板都出现记录）；**剧本 4b + 剧本 3 连演 9 步走通**——点餐 → 主动推送「已出餐」→ 客户提超纲要求 → 转人工 → 导演台回复 → 暗号接管回来

---

## 批次 05：成品

> 前面五批做的是「能演」，这一批做的是「好看」和「不用你在场也能演」。

- [ ] **任务 27：导演台 v2**
  文件：`frontend/src/pages/Console.tsx`、样式
  目标：深色控制台美学；工具调用瀑布流、ERP 数据变化 diff、耗时柱、本次会话 token 消耗
  验收：投屏到大屏上看着专业，手机端发消息时信息密度和可读性都在

- [ ] **任务 27.1：故障演练开关**
  文件：`frontend/src/pages/Console.tsx`、`backend/app/tools/`（注入失败）
  目标：导演台上一个开关，故意让下一次 ERP 调用失败。展示 bot **不崩、不编**，说「系统暂时查不到，帮您转同事」，然后走人工接管
  **「坏了怎么办」是老板一定会想、但未必会问出口的问题。** 主动演一遍比等他问更有力。做成开关而不是真断网，风险可控——演示时你完全掌握它什么时候坏
  验收：拨开关后下一次调用失败，客户侧收到得体的说明而不是报错或胡编，接管流程正常走完

- [ ] **任务 28：网页聊天线视觉重做**
  文件：`frontend/src/App.css`、`frontend/src/pages/*.tsx`
  目标：明亮、亲和、类 WhatsApp 的气质，留给不方便加号的客户。三语 i18n 保留
  验收：手机和桌面尺寸都正常；三语切换正常

- [ ] **任务 29：自动演示模式**
  文件：`frontend/src/pages/Console.tsx` 或独立页、`backend/app/routers/console.py`
  目标：点播放键，bot 自己走完**剧本 1（旗舰戏七步）**。**工具调用是真的**，只有用户那几句是脚本喂的
  为什么是剧本 1：排除法——剧本 2a 要真人拍照和说话、2b 要客户掏出自己的文件，都脚本喂不了；剧本 3 依赖主动推送的时序和真人打字，自动化很别扭；剧本 4a 的原生表单必须真人点提交。只有剧本 1 能纯脚本驱动，而且道具最齐（ERP 订单 + CRM 看板同时长东西）
  验收：点一下，八步自动演完，中途不需要人操作，两块后台都能看到新数据

- [ ] **任务 29.1：PDPA 与数据流向说明（一页纸）**
  文件：`docs/data-flow-pdpa.md`（新增，Claude 写初稿，用户核对后定稿）
  目标：**这一条不写代码，但缺了它有些客户签不了字。** 马来西亚 PDPA，老板会问「我客人的资料存在哪、谁能看得到」。一页说明讲清楚：数据留在你们自己的 VPS、对话内容只在调用时经过 Anthropic、不用于训练、留存策略是什么
  验收：一页纸能直接发给客户，且里面每一句都和实际架构对得上——**不要写做不到的承诺**

- [ ] **任务 30：banking 下架 + 全量回归 + 部署**
  文件：删除 `backend/app/bots/data/banking.json`、`.github/workflows/deploy.yml`（如需）
  目标：下架 banking；五个 bot 全部回归一遍；部署到线上
  验收：`chatbot.acuventech.com` 线上完整走通；WhatsApp 真机五个 bot 各问一句

---

## 可选项（做完再看）

- [ ] **现场导入客户自己的商品表**。`crm_os` 已经有 `/api/contacts/import` 和模板下载接口，ERP 侧大概也有。真做成「他发一个 CSV，五分钟后 bot 用他的真实商品回答」，说服力比剧本 2b 还强一档——但工作量大得多，等前面几批跑顺了再看

- [ ] 每晚定时重置 `erp_os` demo 数据——用户说过无所谓写脏，但**演示效果需要干净的起点**
- [ ] `session_store` 落 Redis（vps_infra 有现成的）。只在需要「隔天推送」时才是必须的
- [ ] 每个 bot 类型加不同主色调，视觉上更像「独立产品」

---

## 批次 06：记住这个人（2026-09-04 新增）

> 任务 11 真机验收通过后，用户拍板改思路：**演示不该每次从零开始**。手机号成为唯一身份，客户信息物理落盘，商品用可点列表呈现，客户可以直接发语音。
>
> **六个已拍板的前提（不再重新讨论）**：
> 1. **手机号即身份，「选身份」菜单删掉。** 真实号第一次进来当新客户，问到名字/公司就存下来；第二次直接续上
> 2. **网页也走同一套**：开场让访客输一个手机号，之后与 WhatsApp 完全同一条代码路径。演示时在电脑上输客户的号，能当场调出他手机上那段对话的历史
> 3. **存储用共享的 `infra_redis`**（本项目至今零持久化，这是引入的第一个存储层）。7 天滚动 TTL，每次活动刷新——昨天聊过的客户不该明天被忘掉
> 4. **CRM 清理按标记删**：bot 写的每一行带 `[DEMO]` 前缀，没标记的一律不动
> 5. **ERP 清理走 erp_os 自己的 demo reset**（见下面「开工前必读」），不自己写删除逻辑
> 6. **语音转录用 OpenAI Whisper API**，封在可替换的抽象层后面
>
> ### 开工前必读：侦察结论（2026-09-04 查证，别再重查一遍）
>
> - **`erp_os` 的销售单删不掉也取消不了。** 路由里没有 DELETE，只有 `cancel`，而 `services/sales.py` 的状态机只允许 `DRAFT` / `CONFIRMED` 取消。演示单每次都走到 `FULLY_SHIPPED` + `INVOICED`（任务 10 的设计），**所以它们在 erp_os 里是永久的**。这就是为什么 ERP 侧必须走 reset 而不是逐行删
> - **`erp_os` 自带 demo reset，已经写好了**：`POST /api/admin/demo-reset`（需 ADMIN 角色 + `DEMO_MODE=true`），走 Celery。`app/tasks/celery_app.py` 里还有一条 `demo_reset_nightly`，**每天凌晨 3 点吉隆坡时间**。现在显然没在跑——earbuds SKU 是 09-01 建的、`SO-2026-00001` 是 09-02 建的，今天都还在
> - **reset 比想象中安全得多**：`services/demo_reset.py` 的 `RESET_TABLES` **不含 `skus`、不含 `customers`**，只清交易单据 + 库存 + 审计表 + `document_sequences`。**手工建的 earbuds SKU 和 Sunrise Hypermart 这些主数据全都活着，不需要重建**（早先「reseed 会干掉 earbuds」的判断是错的，已更正）
> - **库存会被重灌**：`seed_initial_stock` 读的是「全部 active SKU」不是硬编码清单，所以 earbuds 会拿到库存。数量按 SKU 编码前缀查 `CATEGORY_BASE_QTY`，而 `ELE` **不在表里**，落到默认值 100 → 重置后大约 KL 150 / 槟城 ~100 / 新山 ~100。剧本要 2-3 个，**够用，不会演坏**，只是数字比现在的 42/25/18 大
> - **单号会归零**：`document_sequences` 也被清，重置后第一张单又是 `SO-2026-00001`。对演示是好事
> - **`crm_os` 没有 demo reset**，但有 `DELETE /api/contacts/{id}` 和 `DELETE /api/deals/{id}`——所以 CRM 侧我们自己按标记删
> - **ERP 侧不需要 `[DEMO]` 标记**：erp_os 的 reset 是整表 TRUNCATE，全有或全无。标记只对 CRM 有意义
> - **WhatsApp List Message 的硬上限**：10 行，行标题 24 字符，描述 72 字符（`whatsapp_webhook.py` 现有的 `_truncate` 就是按这个写的）。WhatsApp **不渲染表格**，Markdown 表格发过去是一团折行的竖线——这是「用表格展现商品」只能落成 List Message 的原因
>
> ### 阻塞项（需要用户处理）
>
> - [ ] **F. `erp_os` 要开 `DEMO_MODE=true`，并且 Celery worker + beat 要真的在跑。** 不开的话 `/api/admin/demo-reset` 直接返回 `DEMO_MODE_REQUIRED`，任务 34 的 ERP 那一半无从谈起。这是 `erp_os` 的部署改动，不在本仓库
> - [ ] **G. `OPENAI_API_KEY`**，任务 36 用。VPS 的 `/opt/ai_chatbot/backend/.env` 和本地都要有

- [x] **任务 31：接 Redis + 客户档案存取**（纯后端，对外行为零变化）——**2026-09-04 完成**。22 个新 pytest（全套 254 → **276 passed**），另外拿**真的 redis:7-alpine + 真的 redis-py** 跑了一遍活体验证（不是打桩）：写入/读回全字段含中文、`ttl=600s`、把 TTL 手动压到 30s 后再 save 又回到 600s、delete 生效、指向不存在的主机时降级到内存仍能读回。两个 compose 都过了 `docker compose config`。**已推 master 并部署，线上也验了**：`/api/bots` 401、`/webhook/whatsapp` 带错 token 403（加了 `data_net` 之后容器正常起来了）；`ai_chatbot_backend` 确实挂在 `data_net` 上、容器内 `REDIS_URL=redis://infra_redis:6379/16`；最关键的一步——**拿刚部署的那个镜像本身**在 `data_net` 上跑了一次真实存取：写入含中文的档案、读回一致、`ttl=60s`、探针 key 已删除。所以 db 16 和 `databases 256` 这两条假设是在线上被证实的，不是推断的。
  落地与计划的差异 / 需要知道的几件事：
  - **key 用「只留数字」的手机号**（`chat:user:60173948123`）。`+60 17-394 8123` / `017-3948123` / `60173948123` 落到同一个 key——**任务 33「网页输号码调出手机上的历史」直接依赖这一条**，否则两条渠道各存各的
  - **空号码抛 `ValueError`，不是存进 `chat:user:`**。否则所有匿名访客共用一条记录 = 把甲的对话给乙看
  - **TTL 没做成配置项**，`DEFAULT_TTL_SECONDS = 7 天` 写在模块里，构造函数可传（测试用）。只新增了一个配置 `REDIS_URL`，**留空 = 纯内存**，所以测试和裸 `uvicorn` 不会去连任何东西
  - **降级带熔断**：连不上后 30 秒内不再重试。没有这一条，Redis 挂掉时每条消息都要等一次连接超时（已把 connect/socket 超时压到 1 秒）——演示时客户正盯着「正在输入」
  - **内存兜底也存序列化后的 JSON**，和 Redis 完全一样。这样「改了 profile 但忘了 `save`」在两种模式下都同样丢失，不会出现「本地测着好好的，上了 Redis 就丢数据」
  - **db 编号选 16**：crm_os 占 0-4、erp_os 占 5-11，`vps_infra/README.md` 的分配口径是每个项目 16 个。⚠️ **依赖 `infra_redis` 的 `databases 256`**（`vps_infra/redis/redis.conf` 里确实是 256，已核）——本地起的默认 redis 只有 16 个 db，db 16 会报 `DB index is out of range`，这个错在我们代码里会被吃掉、静默降级成内存，只留一条 warning 日志
  - **`get_or_create` 不写盘**，要显式 `save()`。一个打错号码的人说一句话就走，不会因此变成一条客户记录
  - **未做（留给后面）**：没有任何调用方接进来，`session_store` 原样不动、对外行为零变化，这正是本任务的定义。并发写是「后写覆盖先写」无加锁——本服务按设计是单进程（见 `session_store` 的 docstring），到多 worker 那天才需要重看
  文件：`backend/app/services/user_store.py`（新增）、`backend/app/config.py`、`docker-compose.prod.yml`、`docker-compose.yml`、测试
  目标：接上共享 `infra_redis`，一个客户一个 key（`chat:user:{phone}`），**7 天滚动 TTL，每次写入刷新**。这一步**不改任何对外行为**——只是把存取能力建起来，让 32 有东西可用
  **存什么**（通用字段，全场景共用）：`erp_customer_id` / `crm_contact_id`（**最值钱的两个**：存了就不用每次重查，也杜绝认错人——正是任务 10 那条 P3-2 一直没堵的洞）、`language`（**第二次进来直接用对的语言开口**，成本几乎为零，演示效果极好）、`display_name`、`bot_id`、`first_seen` / `last_seen`、`history`（沿用现有 20 轮上限）
  **外加一个 per-bot 的自由 `profile` 槽**。**不预先写五套分场景 schema**——除了 `retail`，其余四个场景连工具都还没有，现在定字段就是投机性代码。各场景要存什么记在这里，做到那批再落地：`retail` = 送货地址 / 上一张单号 / 常买 SKU；`food` = 送货地址 / 常点的菜 / 辣度 / 忌口；`realestate` = 预算 / 意向地区 / 房型；`hotel` = 房型偏好 / 入住人数；`saas` = 公司 / 方案 / 未结工单
  ⚠️ Redis 连不上时**必须降级成「像今天一样用内存」**，不能让一个缓存服务把整个 demo 拖死
  验收：单测覆盖存取 + TTL 刷新 + Redis 挂掉时降级；线上行为与现在完全一致

- [x] **任务 32：手机号即身份（WhatsApp 侧）**——**2026-09-04 完成，代码侧全绿；真机那一半没做（要用户拿手机）**。287 passed（276 → **287**，净增 11 个测试），前端 `tsc -b && vite build` 也过了。另外做了一轮**变异测试**——手工把 5 处行为逐个改坏，确认每处都有测试变红，不是「写完就绿」的假绿：不写盘 / menu 把人删了 / 陌生人也建档 / 塞错手机号给模型 / 一个 bot 读到另一个 bot 的备注。
  **身份这一层是真的没了**：`Identity` 模型、`get_identity`、六个 JSON 的 `identities`、WhatsApp 的 `_send_identity_list`、网页的 `IdentitySelect.tsx` 全部删除。`test_registry.py` 里补了一条守门测试，因为 **pydantic 默认吃掉多余的 key**——JSON 里如果有人再写回 `identities`，加载时一声不吭，只有这条测试会喊。
  超出计划文件清单的几处（都是删 `identities` 逼出来的，不是顺手改的）：
  - **对话历史和 `bot_id` 从 `session_store` 搬到了 31 建的 Redis 档案里。** 不搬这一步验收就是空话——原来的 history 在进程内存里，重启即失忆，「换一次对话再进来 bot 认得他」无从谈起。`session_store` 现在只剩两件事：**消息去重**和**每日限流**，那两件本来就该是按天/按消息 id 的进程内状态
  - **`menu` 的语义变了**：清 `bot_id` + 清 history，**但人还在**（`display_name` / `language` / 两个后台 id / per-bot 备注都留着）。「换一个行业演示」不该等于「忘了这个客户是谁」
  - **只看过菜单的号码不建档**。第一条消息是 `hi` 或 `menu` 的陌生号，Redis 里什么都不写——沿用 31 的 `get_or_create` 不写盘。打错号码的人说一句就走，不该变成一条客户记录（到任务 34 还会顺着进 CRM）
  - **网页侧被迫一起改了**（`chat.py` / `models.py` / `api.ts` / `App.tsx` / `Chat.tsx` / 两处死掉的 CSS 和 i18n）。`identities` 一删，网页那条路径直接编译不过。网页现在从选场景**直接进聊天**，`llm.get_reply(bot, None, ...)` 走匿名分支——原来 `IdentitySelect` 那个位置，正好留给任务 33 放输手机号那一页
  system prompt 那块（缓存断点仍在同一处，稳定块逐字节不变，有测试盯着）：
  - 可变块从「假身份 profile」换成 `{"phone": "60173948123", ...}`，并**明说这个号码是渠道已经验证过的、不要再问客户要**。零售的 persona 早就写了「先用手机号 `crm_lookup_customer` 查一遍」，但以前模型手上只有假身份里那个假号码——**这一条从今天起才真的成立**
  - **没有的字段不写成 `null`，直接不出现**。`"display_name": null` 读起来像「查过了，没有名字」，会让模型不再问；不出现才是「我们还没问过」
  - free-form `profile` **只放当前 bot 那一格**。跟房产 bot 说的预算，不是零售 bot 该提起的
  **还没做（不是漏了，是没有东西会去写）**：`display_name` / `language` / `erp_customer_id` / `crm_contact_id` 四个字段现在**全程无人写入**，档案里实际只有 `phone` + history。所以「bot 认得他」目前靠两条真路径：① history 在 Redis 里存 7 天，第二天写信直接续上；② 零售靠真手机号走 `crm_lookup_customer` 查回上次的线索卡。要把那四个字段填上，得等工具侧动手（`erp_find_customer` / `crm_lookup_customer` 命中后回写 id，是最自然的落点），**不在本任务范围**
  ⚠️ **代价：另外五个 bot 丢了它们唯一的「客户数据」**。`hotel` 的 bookings、`saas` 的 tickets、`food` 的 orders、`realestate` 的 appointments、`banking` 的账户，全都只活在 `identities[].profile` 里，删身份就一起没了。它们现在只剩 `context_data`（行业通用资料），谈不了「你那张订单」。这是「不演假身份」的必然代价，补回来的地方是**任务 11.2**（hotel/saas 套工具外壳）和**批次 04**（food/realestate 自建后端），届时写进 `profile[bot_id]` 这一格。`banking` 反正任务 30 要下架
  验收现状：**代码侧验完了**（见上，含变异测试）。**真机那一条没验，需要用户做**：用一个新号进去，确认全程没有选身份这一步；聊几句报上名字，隔一段时间再写，看 bot 是否接得上——这一条 Claude 用模拟 webhook 只能证明代码路径，证明不了手机上的观感

- [ ] **任务 33：网页侧改成输手机号**
  文件：`frontend/src/pages/`、`backend/app/routers/chat.py`、`backend/app/services/api.ts`、测试
  目标：网页开场输一个手机号，之后与 WhatsApp 走同一条路径、同一个 Redis 档案
  验收：网页输入手机上那个真实号码，**能看到手机上那段对话的历史**——这一条本身就是很强的演示素材

- [ ] **任务 34：7 天清理**
  文件：`backend/app/tasks/`（新增）、`backend/app/tools/crm.py`、`backend/app/tools/erp.py`、测试
  目标：三件事。① Redis 靠 TTL 自动过期，**不用写任务**；② CRM：bot 建的联系人 `notes` 写 `[DEMO]` 前缀，清理时只删带标记的；③ ERP：调 `POST /api/admin/demo-reset`，不自己写删除
  ⚠️ **CRM 有个坑**：bot 有时是往**种子联系人**（如 David Park）身上加一张新卡。这种情况**只能删那张卡，不能删人**——删人会把种子数据搞没
  依赖阻塞项 F
  验收：跑一次清理，CRM 上带标记的卡没了、种子联系人还在；ERP 单据清空且库存重灌

- [ ] **任务 35：商品列表用 List Message**（不依赖前面，可插队）
  文件：`backend/app/services/outbox.py`、`backend/app/tools/erp.py`、`backend/app/routers/whatsapp_webhook.py`、测试
  目标：搜到多个商品时，在文字回复后面跟一条**可点选**的原生 List Message：行标题 = 商品名（24 字符），描述 = 价格 + 库存（72 字符），点一下直接进下单流程
  **走 `outbox`，不是工具返回值**——工具照常返回 JSON 给模型，后端往 outbox 塞列表。这套机制任务 10 发 PDF 时已经建好，`outbox.available()` 也已经能自动区分「WhatsApp 有、网页没有」
  超过 10 行就说「还有更多，告诉我品牌或类别」
  验收：真机问「有什么 rice cooker」，出来一条可点列表，点一下能直接下单

- [ ] **任务 36：语音输入**（原任务 15，口径改为抽象层；不依赖前面，可插队）
  文件：`backend/app/services/transcribe.py`（新增）、`backend/app/routers/whatsapp_webhook.py`、`backend/app/config.py`、测试
  目标：收到 `type: "audio"` → 用**任务 1 已经做好的** `whatsapp_media.fetch_media` 下载 → 转录 → 拿到文字后走现有文字路径，**下游一行都不用改**
  抽象层：`transcribe(audio, mime) -> str` 一个接口 + 一个 OpenAI Whisper API 实现，换供应商只是换实现类
  **导演台要显示「语音 → 文字」这一步**：客户听不到，但老板看得到它听懂了什么。马来西亚客人大概率中英马夹杂，这一行字就是证据
  依赖阻塞项 G
  验收：真机发一条中英夹杂的语音，bot 听懂并正确走工具

## 评审记录

（每个任务完成后，如有偏离原方案的地方或踩坑教训，记录在这里）

- 2026-08-27（立项）：v1 的 `tasks/todo.md` 归档为 `tasks/todo-v1-mvp.md`。
- 2026-08-27（架构侦察）：确认 `ai_chatbot_demo` **自己不持有 Meta 凭据**——它挂在 `whatsapp_gateway` 后面，通过 `POST /internal/whatsapp/inbound` 收消息、**同步返回** payload 列表由网关代发。七件武器里有四件（收图、收语音、发文件、主动推送）突破了这个同步请求-响应契约。解法不是把凭据复制一份给 demo（那会让两个项目抢同一个号的状态），而是给网关加三条反向内网 API 借出能力。`dispatch_message` 的返回值语义保持不变，`crm_os` 和 `acuven_aichat` 零改动——这是批次 00 单独验收的全部理由。
- 2026-08-27（选型）：ERP 一侧决定走 `erp_os` 自己的 REST 路由（`sales_order` / `sku` / `inventory` / `invoice` / `customer` 都是现成的），不裸连 MySQL。理由：写入要经过业务逻辑，否则演示时刷新后台看到的可能是一张状态不对的脏单，当场翻车。
- 2026-08-30（决定）：**`crm_os` 从网关的 demo 路由里彻底移除**，WhatsApp 线专供 `ai_chatbot`。网关侧已落地（`demos_registry` 删掉 crm 条目，demo 号加 `default_route="ai_chatbot"` 直连、不再发选择菜单）。CRM demo 只在网页/现场演示。菜单代码保留，服务于未注册号码兜底。
- 2026-08-30（阻塞项 A 解除）：两套系统的 demo 账号本来就 seed 好了，实测线上可登录，**不需要新建**。同时确认两边都无 API key 机制，只有短命 JWT，因此新增鉴权基类（任务 8）。顺带发现 `crm_os` 的 `POST /api/auth/register` **完全开放**——无鉴权、无邀请码，任何人都能注册出一个 `sales` 角色账号。现在里面是 seed 假数据所以影响有限，真放客户资料前必须堵上。归属 crm_os 项目。
- 2026-08-30（补剧本）：原计划只有批次 01/02 写了剧本，03/04/05 只有工程验收条件——一段自己写着「杀伤力被严重低估」的功能却没有能讲给客户听的戏。补齐剧本 3、4，并指定任务 29 演剧本 1。**剧本会反过来定义验收标准**（剧本 1 那七步直接定义了任务 13），所以补在开工前而不是做到那批再说。
- 2026-08-30（剧本 3 挪到餐饮）：「你的餐出锅了」比「订单已确认」画面感强，加辣椒酱这种要求本来就该人来拍板。挪完后演出分布从「零售 3 出」变成零售 2 出、餐饮 1 出（最长的一出，9 步）、房产 1 出。
- 2026-09-04（线上事故 + 五处加固）：任务 32 上线当天真机演示，客户发「Update me after it ship out」**没有收到任何回复**。查下来是**一条静默失败链**，五个环节各让它过了一关：
  1. 模型这一轮撞上 `MAX_REPLY_TOKENS = 512`（日志里 `output=512`），被截断在一个没写完的 tool_use 上，**一个文本块都没产出**
  2. `"".join(text blocks)` = `""`，直接当成回复往下传
  3. `build_text_message` 照样构造出 `{"body": ""}`
  4. Meta 返回 **400**，而 `send_raw` 从不看状态码（`return httpx.post(...)`），调用方也从不看返回值——**日志里只有一行和成功时一模一样的 httpx INFO**
  5. 这条空回复还被 `add_message` 写进了 Redis 档案。Messages API 拒收空文本块，所以**那个号码之后每条消息都会失败**，7 天内只能收到三语道歉，除非手工删 key
  修的时候刻意**不针对「空文本」打补丁**，而是把三个不设防的边界各加一道只写一次的检查：
  - **出口**：`send_raw` 非 2xx 就抛，带上 Meta 的 error body。杀掉的是**整类**——24 小时窗口过期、模板没过审、`media_id` 失效、限流、payload 超限，这些以前全是静默的
  - **入口**：渠道契约由 builder 承担，不由调用方自觉。新增 `_body()`：空的拒绝（抛 `UnsendableMessage`），超长的截断（文本 4096 / 交互 1024）。理由是**将来的生产者**——任务 35 的 List Message、36 的语音转文字、19 的主动推送都是新的文本来源，检查写在 `get_reply` 里只保今天这一个
  - **模型侧**：`_reply_text()` 把 `stop_reason == "max_tokens"` 和空文本都当成**这一轮失败**，返回 `FALLBACK_REPLY` 并 `logger.error`。**截断但非空的也一样不发**——半句话在销售演示里意味着一个少了位数的价格（`RM 26` vs `RM 263.67`）。`MAX_REPLY_TOKENS` 抬到 **1024**，因为这个预算是回复文本和 tool_use 参数**共用**的，512 装不下两者；但抬高只是降低概率，兜底靠上面那个判断
  - **历史侧（两条）**：① webhook 改成**先构造、再记账**——发不出去的回复不进历史，整轮丢掉；② `_deserialise` 加载时丢掉 content 为空的消息。**第二条是关键**：没有它，已经被污染的号码永远卡着，只能手工删；有它，那些号码下一条消息就自己好了
  - **可观测**：新增 `events.SEND_FAILED`，`_handle_incoming_message` 兜底时同时写日志和导演台。演示时静默失败看起来和「模型在思考」一模一样，这条让它当场可见
  验证：334 passed（287 → 334，净增 47），外加**九处变异全部被测试捕获**（每个修复单独改坏一次确认变红）。⚠️ **旧测试的坑**：三个 send 测试和一个 media 测试原本 `patch.object(httpx, "post")` 返回裸 `MagicMock`，而 `MagicMock.is_error` 是**真值**——`send_raw` 一开始检查状态码，它们立刻全红。必须返回真的 `httpx.Response(200)`
  ⚠️ **这次事故暴露的更大问题**：出站这一整条腿此前**零可观测性**。任务 27（导演台 v2）应当把 `SEND_FAILED` 显式画出来

- 2026-08-30（轻量档）：`hotel` + `saas` 原本 30 个任务一个都碰不到，会保持静态 JSON 形态，和工具驱动的 `retail` 并列在菜单里落差太大。新增任务 11.2 给它们套同样的工具外壳，读 JSON / 写内存。剩下的差别（retail 后台真的长出东西）反而可以坦白讲成卖点：「接你们自己的系统是同样的工具接口」。
- 2026-08-30（RAG 的定位）：用户问怎么做 RAG。结论是**现在不需要**——六个 bot 全部素材 31 KB 约一万多 token，上下文有 100 万，prompt caching 一开重复读取几乎免费；RAG 解决的是装不下，差三个数量级。但「读客户自己的文档」值得做，**不是为了性能，是为了那句话：把你们的手册丢进来，五分钟变客服**。落成任务 15.1，用 Claude 原生的 `document` block + citations，零检索基础设施。真到装不下那天，下一步是关键词检索工具（`search_docs` 接 MySQL 全文索引），**不是向量库**：Anthropic 无 embedding 接口，上向量要引入新供应商 + 切块调参，且召回不准时极难 debug；结构化业务数据用关键词天然更合适。
- 2026-08-30（说服力五条）：盘完 33 个任务发现它们**全在教 bot「能做什么」，没有一个针对客户心里的异议**。补五条：**会说「我不知道」**（任务 11.3，抗砸场——客户一定会试着问倒它，而「乱答」是老板最怕的）、**成本以马币显示**（任务 12，「会不会很贵」是中小企业主真正的拦路问题，一行乘法就能终结）、**rojak 混语开场**（剧本 1 + 任务 11 验收，不是新功能是把已有能力演出来，本地化说服力极强）、**「正在输入」从可选项提为任务 12.1**（工具调用变慢后，没有它会让真实调用显得像性能差）、**演示收尾总结**（任务 19.1，利用「对话留在他手机里」这个 WhatsApp 独有优势——唯一一条你不在场时还能继续说服人的功能）。
- 2026-08-30（说服力第二轮）：再补五条。**对照组开关**（任务 12.2）—— 关掉工具跑同一个问题，让客户自己看两遍「编的」和「真的」，整场演示的核心主张变成当场可验证的实验；便宜得离谱，因为任务 2 的回归安全绳本来就要求这条路径存在且被测。**客户中途改主意**（剧本 1 加一步，7→8 步）—— 所有演示在客户按剧本走时都漂亮，一旦反悔就露馅，而真实生意里天天发生；接得住证明是助理，接不住证明是流程图。**三人并发**（任务 13 验收）—— 破除「一次只能应付一个人」的直觉，可能零代码但必须提前验。**故障演练开关**（任务 27.1）—— 「坏了怎么办」老板一定会想、未必会问，主动演比等他问有力。**PDPA 一页纸**（任务 29.1）—— 不写代码，但缺了它有些客户签不了字。另把「现场导入客户自己的 CSV」记进可选项。
- 2026-08-30（demo 线脱离网关）：用户第三次追问「号码不同，还需要网关分发吗」。前两次我都在推迟，而且给过一个循环论证（「网关必需，因为它持有凭据」——凭据在它手里恰恰是这个架构的结果，不是理由）。查证后做了一个 10 分钟可逆实验：把 Meta 的 Callback URL 从 `whatsappgateway.acuventech.com` 改到 `chatbot.acuventech.com/webhook/whatsapp`，`ai_chatbot` 用自己的凭据收发。**通了**——握手 200、消息直连进来、去重工作（5 个 POST 只触发一次业务逻辑）、出站 Graph API 200，网关侧零流量。
  判定成立的三个前提：① `ai_chatbot` 的 v1 直连路径（`GET/POST /webhook/whatsapp` + 四个凭据字段）当初刻意保留了，改动量约等于零；② 今天取消了测试 WABA 的订阅后，App 下只剩 demo 号一个 WABA，**没有东西需要分流**；③ 客服号本就该用自己的 App（它要走 Coexistence → Tech Provider → App Review，不该把 demo 的 App 拖进去），所以两条线永远不会挤同一个 callback URL。
  收益：批次 00 从 7 个任务缩到 4 个，省约 3 个 session，并且这一批「整个工程唯一有回归风险」的属性消失——因为不再碰那个同时扛着公司真实客服线的服务。代价：`acuven_aichat` 将来上线时要自己长一个公网 webhook（它现在只有内网路由）。网关继续部署着不动，零成本，客服号接入时再评估去留。
- 2026-09-04（批次 06 立项 + 两处自我更正）：任务 11 真机验收通过后，用户拍板改思路——手机号即身份、客户信息物理落盘、商品用可点列表、支持语音。六个前提逐条问定（身份机制 / 网页那条线 / 清理边界 / 表格形式 / 转录选型 / 存储选型），写成批次 06。
  **侦察推翻了我自己先前说的两件事，记在这里免得下次又搞错**：① 我原以为「ERP 定期 reseed 会干掉手工建的 earbuds SKU、要配重建脚本」——**错的**，`services/demo_reset.py` 的 `RESET_TABLES` 不含 `skus` / `customers`，只清交易单据和库存，主数据全活；② 我原打算 ERP 侧也用 `[DEMO]` 标记逐行删——**不需要**，erp_os 的 reset 是整表 TRUNCATE，全有或全无，标记只对 CRM 有意义。
  另外确认了一件本来打算自己造的东西 **erp_os 已经有了**：`POST /api/admin/demo-reset` + `demo_reset_nightly`（每天 3am，gated on `DEMO_MODE`）。反过来说，演示单在 erp_os 里**删不掉也取消不了**（没有 DELETE 路由，`cancel` 只接受 DRAFT / CONFIRMED，而我们的单都到了 FULLY_SHIPPED + INVOICED）——这才是 ERP 侧必须走 reset 的真正原因。
