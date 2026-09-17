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
  ⚠️ **2026-09-13 Flows 这一项的答案：能建，发不出去。** Flow 建好了（ID `1066318999658447`，JSON 被 Builder 接受），但**每一张表单都被 Meta 拒收**：`(#139000) Blocked by Integrity — "Integrity requirements not met."`，草稿模式也一样。Publish 按钮同时被拦，解锁条件二选一：**Business verification 通过**（新 portfolio `1196292716890139` 一直 in review），或 **30 天内足够多的高质量对话**（当时 8 conversations/30d）。
  - **账号层的门槛，代码修不了**。看到 `139000` 别查代码
  - **影响的是「能不能演」，不是能不能开发**：门槛过之前，剧本 4a 的原生表单演不了，走聊天降级（已补成会落库、会自动接住拒收，见任务 24 记录）
  - 门槛过了之后**不用改代码**：Builder 里 Publish → `WHATSAPP_FLOW_MODE=published` → 重建容器
- [x] ~~**C. 语音转录选型拍板**~~——**2026-09-06 已定：走外部 API（OpenAI `/v1/audio/transcriptions`，默认 `whisper-1`）**，正是这一条当初建议的路子：先接外部 API 把戏跑通，转录做成抽象层，换实现只是换一个类。任务 36 已落地并真机验收。自托管 faster-whisper 没有被否掉，只是没有理由现在做——真要换，见任务 15 条目下记的那处残留（换类可以，换环境变量还不行）。以下是原文：
  ~~外部 API（准、快、多一个供应商）vs 自托管 faster-whisper（无外部依赖、CPU 上每条慢 3-5 秒、吃 VPS 内存）。阻塞任务 15。~~
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
  - ~~⚠️ **`/console/stream` 没有鉴权，靠「打不到」保护**~~——**2026-09-06 任务 12 已解决**，改为 `CONSOLE_TOKEN` 查询参数把守，未配置时一律 503（不是放行）。以下是原文：
    ~~前端容器的 nginx 只转 `/api/` 和 `/webhook/`，`/console/` 会落到 SPA。**任务 12 建导演台页面时必须同时解决**——那条流里有 ERP 订单数据和客户资料，加了 nginx 转发就等于公开~~

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

> 给 B 类客户的主菜。演的时候左边浏览器开着**两块后台**：`erp.acuventech.com` 的订单列表 + `crm.acuventech.com/dashboard` 的管道看板。
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

- [x] **任务 11.2：轻量档也套上工具循环**（`hotel` + `saas`）——**2026-09-10 完成**（35 个新测试，全套 528 passed）
  文件：`backend/app/tools/local.py`（新增）、`backend/app/bots/data/hotel.json`、`backend/app/bots/data/saas.json`、测试
  目标：客户在菜单里平等看到五个行业，点进 `retail` 是活的、点进 `hotel` 还在背 JSON，落差太明显，会显得「只有一个是真的」。给轻量档套同样的工具外壳——`hotel_search_rooms` / `hotel_get_booking` / `hotel_modify_booking`，`saas_search_known_issues` / `saas_get_tickets` / `saas_create_ticket`
  **读走现有 JSON**（`context_data` + 选中身份的 `profile`），零新增数据；**写落会话级内存**——纯只读会露馅，SaaS 客服不能建工单、酒店客服不能改预订，客户一试就穿帮
  验收：`hotel` 和 `saas` 各问一句，**导演台上滚出工具调用**，形态和 `retail` 一致；建一张工单后在同一段对话里能查回来

  **做了什么**
  - `backend/app/tools/local.py`（新增，7 个工具）：`hotel_search_rooms` / `hotel_create_booking` / `hotel_get_booking` / `hotel_modify_booking`，`saas_search_known_issues` / `saas_create_ticket` / `saas_get_tickets`。读的是 bot 自己 JSON 里的 `context_data`（房型表 / 已知问题表），零新增数据
  - `backend/app/services/llm.py`：工具分支外面套一层 `local.serving(bot, customer)`
  - `backend/app/tools/registry.py`：`CATALOGUE` 加上 `local.TOOLS`
  - `hotel.json` / `saas.json`：加 `tools` 数组，persona 重写成 retail 那套「每一句话都来自工具」的口径。**顺带修掉两处过期文案**——两个 persona 都还写着「the current guest's booking history provided in context」，而 `identities` 早在批次 06 就删了，那段 context 根本不存在

  **三处和任务描述不一样，说明理由**

  1. **多了一个工具 `hotel_create_booking`**（任务里只列了 search / get / modify）。`identities` 删掉之后，一个真实号码进来是**没有任何预订的**——`hotel_get_booking` 永远返回「查不到」，`hotel_modify_booking` 永远无单可改，这两个工具在真机上是死的。批次 06 拍板「不演假身份」，所以不能预置一张假预订，唯一的活路是让它当场建一张。它也正好是 `saas_create_ticket` 的对位：验收要求的「建一张工单后在同一段对话里能查回来」，酒店那半就是「订一间房，然后改成 2 晚，总价跟着降」
  2. **写的地方不是「会话级内存」，是 `UserProfile.profile[bot_id]`**——批次 06 第 896 行原本就写明这一格由 11.2 来补。代价/好处：它跟着客户档案活 7 天，不是一场对话就没，同一个号第二天回来预订还在
  3. **没做取消预订、没做关闭工单**。改预订能演的都能演，取消是另一档要求，不顺手加

  **一个必须说清楚的机制**：工具改的是**路由手上那个 `UserProfile` 对象**，不是自己 `user_store.save` 一份。如果自己存，`get_reply` 返回后路由那句 `user_store.save(profile)` 会拿它手里的旧副本把工单盖掉——这条有测试守着（`test_a_write_lands_on_the_profile_the_router_is_about_to_save`）。「这通对话是谁」靠 ContextVar 传进工具层，和审计日志同一套路子（任务 10 P3-2 点过名的那个洞，这里只是给本地工具开了一条不动 4 个文件的路，**ERP/CRM 那半仍然不知道对话是谁**，那条架构任务还在）

  **不编造的几条硬约束**（这些是 11.3 的预演，写在工具里而不是提示词里）：房型不在目录里 → 拒绝并列出真实房型；人数超过房间容量 → 拒绝并说清睡几个；日期读不出来 → 拒绝，**并把今天的日期带回去**（模型不知道今天几号，不带今天它只能再猜一次）；入住日已过期 → 拒绝；工单 priority 不在四档里 → 拒绝，**不静默降级**（把 urgent 悄悄存成 normal 是在没人看得见的地方毁约）。⚠️ 有一条**故意不对称**：「入住日已过期」只在**这次真给了新入住日**时才拦——住到一半的客人要求延住，`check_in` 本来就在过去，一刀切会让 bot 对着人在房间里的客人说「您的入住日已过期」；价格、晚数、总价全部由工具从目录算，模型只负责转述

  ✅ **验证到什么程度**
  - 单测：容器里 **528 passed**（基线 493，+35）。覆盖：目录过滤三条、总价 = 房价×晚数、五种拒绝、同一回合内建完能查回来（工单和预订各一）、改短住期总价真的降、换房型按新价重算、改失败时原单不动、两个客户互相看不到对方的预订、两个 bot 不写进对方的格子、档案损坏时重新开一格而不是抛异常、记录条数上限、回合外调用返回 `NO_TURN`
  - **`get_reply` 那一跳单独有测试**：不开这一层的话上面所有工具在生产里全是 `NO_TURN`。测试跑的是真的 `saas_create_ticket`，断言工单落到 profile 上、**并且 `tool_start` / `tool_end` 上了导演台**（`status=ok`、输出里带工单号）——这就是验收那句「形态和 retail 一致」在测试里的样子
  - 另外单独 dump 了 `beta_tool` 生成的 7 个 schema：参数全在 `properties` 里，可选参数都不在 `required` 里（任务 11.1 踩过这个坑）
  - ✅ **线上真模型跑过了**（部署完之后，走网页聊天接口打 `chatbot.acuventech.com`——本地 `ANTHROPIC_API_KEY` 依旧是空的，VPS 是唯一有 key 的地方，所以「模型会不会真的去调」只能在那儿问）。两条都通：
    - `hotel`：问海景套房 → 报出目录里的真值（RM 580、睡 3 人）；订 10-10 至 10-13 → `BK-9692`、RM 1,740；**然后 `select` 重开一段新对话**（history 清空）再问「查一下我的预订」，`BK-9692` 原样查得回来——它只能来自工具写进档案的那条记录；再说「改到 12 号退房」→ 2 晚、RM 1,160，正是 580×2
    - `saas`：说登录不上 → 给的是已知问题表里那条原文（Forgot Password / SSO 管理员），没有自己编；说没用 → 开出 `TCK-4805`（priority high）；再问工单状态 → 同一个号、开单时间 `2026-09-10 12:34`（吉隆坡时钟对）
    - 副作用：Redis 里多了两条测试档案（`60100000112` / `60100000113`），7 天自己过期；审计库多了两段 web 会话
  - **仍然没验的**：**导演台上那块屏没亲眼看**（`CONSOLE_TOKEN` 在用户手里），只有单测断言了 `tool_start` / `tool_end` 会发出去；真机 WhatsApp 侧没走（上面走的是网页那条线，同一条代码路径但不是同一个入口）

- [x] **任务 11.3：让它会说「我不知道」**
  文件：五个 bot 的 `persona_prompt`、`backend/tests/test_refusal.py`（新增）
  目标：**前面所有任务都在教它「能做什么」，没有一个定义「做不到时怎么表现」。** 加硬约束：只用工具返回的数据回答，工具没返回就明说查不到并提出转人工，绝不猜测订单号、库存、价格、政策
  为什么这是销售功能不是工程功能：每一场 AI 演示，客户心里第一个念头都是「这是你准备好的，我换个问题它就废了」——**而他一定会试**。一个查不到就说「这个我查不到，帮您转同事」的 bot 比什么都敢答的可信十倍，因为老板最怕的不是 AI 不会，是 **AI 乱答然后他赔钱**
  验收：一组 eval——不存在的订单号、不存在的 SKU、超出政策范围的要求、和本行业无关的问题，四类各问一遍，断言它**说不知道而不是编**；演示时可以主动邀请客户砸场（*「你随便问，问倒它才是好事」*），这句话本身就是说服力

  **2026-09-11 做完。**

  **改的地方和任务描述不一样，说明理由**：任务写「五个 bot 的 `persona_prompt`」，实际是**一处共享 + 两个 persona**。这条规矩对五个 bot 一字不差，而客户砸场砸的是当时屏幕上那一个——抄五份，只要有一份抄漏就是个洞。所以写进 `llm.py` 的 `NEVER_INVENT`，贴在 `STABLE_SYSTEM_TEMPLATE` 里 persona 正下方（**在缓存块内**，所以不按人次重复付费）。`retail` / `hotel` / `saas` 的 persona **一个字没动**：任务 11 / 11.1 / 11.2 已经给它们写过更具体的「每一句话都来自工具」，再抄一遍没有价值。

  **做了什么**
  - `backend/app/services/llm.py`：新增 `NEVER_INVENT`，三段各自挡一种砸场——① 事实只能来自刚调过的工具或 context data，不在就明说查不到，并给下一步（看得见的相关信息，或一个能查的同事）；② 不属于这门生意的问题不用通用知识硬答，说清楚不归这里管再拉回来；③ **被顶也不改口**：换个说法问、硬要一个「大概数字」，答案不变。第三段专为「他一定会试」写的
  - `food.json` / `realestate.json`：persona 重写。这两个是**唯二一个工具都没有**的 bot，而它们的 persona 还写着「use the current customer's order history / appointment history provided in context」——那段 context 在批次 06 删 `identities` 时就没了（**和任务 11.2 在 hotel/saas 修掉的是同一处过期文案，这两个当时漏了**）。一个被告知「你手上有订单记录」而其实没有的 bot，除了编没有别的路。改成明说没有订单系统 / 没有预约本，查不到就说查不到、交给同事；能做的照旧写清（照菜单算钱、按条件筛房源、记下要点交同事确认）。realestate 的房贷试算单独留了一句「**这是你唯一自己算的数字**」，否则第三段那句「不要给编出来的数字」会把它一起掐掉
  - 顺带换掉两条 `quick_questions`：food 的「我的订单送到哪里了？」、realestate 的「帮我查一下我的看房预约」——**演示自己请客户问一个它答不了的问题**。任务 11 已经因为同样的理由换过 retail 那条
  - `backend/tests/test_refusal.py`（新增）：离线守合同 + 一组能对着线上真模型跑的 eval

  **`banking` 故意没动**：任务 30 要删掉它，而共享那一层已经盖住它了。它 persona 里有同一句过期的「account data provided in context」，但改掉就会和开头「Help customers check account balances」自相矛盾，等于给一个要删的 bot 做完整改写。**代价说清楚：在任务 30 之前，banking 是唯一一个 persona 仍自称握有它没有的数据的 bot。**

  **eval 怎么判「说了不知道」——两次踩坑，都不是 bot 的错**
  - 判定器最初只认一套「查不到」的措辞。**拒绝一个不属于本行业的请求和报告一次查不到，是两种句子**：前者说的是工作边界（「I only handle food orders」「flights are outside my kitchen」——连着两次跑，同一个问题两种说法，都对），后者说的是数据缺口。现在分两套词表，理由写在注释里
  - 模型有大约一半的概率把 `don't` 写成花体撇号 `don’t`，ASCII 词表一个都匹配不上，**一条答得很好的回复被判成了瞎编**。判定前统一撇号
  - **判定器只断言「它承认了查不到」，不断言「它没编」**：一条好的拒绝经常顺手带上真数据（「没有 Aurora X9，最接近的是 Sony WF-C710N，RM 328.90」），拿正则抓「有没有出现数字」会把最好的回答判红。所以 eval 跑 `-s` 把七条问答原样打出来**给人读**——断言管「有没有硬编」，打印出来的稿子管其余

  ✅ **验证到什么程度**
  - 单测：容器里 **542 passed**（基线 528，+14）+ 7 skipped（没给 `REFUSAL_EVAL_BASE_URL` 时 eval 自己跳过）。这 14 条守的是**合同有没有送到模型手上**：六个 bot 逐个断言 `NEVER_INVENT` 在系统提示里、三段一段不少、在**缓存块**里而不在按人次重发的那块、没有工具的 bot 拿到的是同一份
  - ✅ **线上真模型跑过了，而且是改前改后各跑一遍**（`REFUSAL_EVAL_BASE_URL=https://chatbot.acuventech.com`，七条问答的原文都读过）。**改前 7 条里 5 条本来就答得好**（retail 那三条是任务 11 早就写死的口径），**真正被这次改掉的是没有工具的那两个**：
    - `food`「我的外卖到哪了」——改前：*「I'm not seeing any current order on file for this number (60100000135)」*，**它声称查了一份它根本没有的订单表，还把原始号码抖给了客户**；改后：*「I can't see any orders or driver locations from here, so I genuinely don't know where your delivery is right now」* + 主动提出让同事回电
    - `realestate`「查一下我周六的看房预约」——改前：*「I don't have any viewing appointment on file for PROP-203 under this number」*（同样是假装查过预约本）；改后：*「I don't have access to the appointment book, so I can't confirm whether Saturday is right」* + 转给 PROP-203 的负责经纪
    - 差别不是「有没有拒绝」，是**「查了但没有」和「我根本查不了」**。前者客户完全可以追问「那你再查一遍/换个号码查」，而 bot 只能继续演下去；后者把话说死了
  - 部署：commit `9309241` 推 master，Deploy workflow 绿，线上 `select` 返回的已是新的 quick question，确认跑的是新镜像
  - 副作用：线上 Redis 多了 7 条测试档案（`60100000130`-`136`）+ 1 条 `...139`（探 quick question 用），7 天自己过期；审计库多了 8 段 web 会话
  - ✅ **真机 + 中文当天就补上了**（2026-09-11，用户拿手机对着 `retail` 发「帮我查一下订单 111」）。回的是：*「我在 ERP 系統裡找不到您的帳戶（用這個號碼和 Acuven Technology 都查不到），所以也查不到「訂單 111」這筆訂單」*，然后给两条出路（换公司名/名字再查一次，或当场开户下单）。三点都对：没给订单 111 编状态；**说清了它查过哪两个条件**，客户能判断它是真查了，而不是一句含糊的「查不到」；给了下一步而不是把人晾着。边界上有一句「您目前還沒有正式下過訂單」——依据是「ERP 里没这个账户」+ 那张单一直卡在等 TIN，在当时语境下准确，而且它自己紧接着留了口子（「如果帳戶是用其他公司或名字開的，告訴我我再查一次」），判定为可接受
  - **仍然没验的**：**马来文的拒绝没测**（七条 eval 全英文，真机那条是中文；`NEVER_INVENT` 本身是英文，和其它提示词一样靠「用客户的语言回」那条规则翻译）；`banking` 没测也没改

  **真机验收顺手带出的一个修复（不属于本任务范围，用户当场拍板要修）**：上面那条中文回复**是繁体**，而用户输入的是简体。**马来西亚写简体**，回繁体在演示里读起来像一个从别处搬来的 bot——正是本地化 demo 最不该给人的印象。`STABLE_SYSTEM_TEMPLATE` 的 Language 那一行原来只说「用客户写的那种语言回」，没区分简繁。加一句「Chinese means Simplified Chinese…even when the customer writes to you in Traditional」，并在 `test_llm.py` 加一条断言守着（`test_chinese_means_the_simplified_kind`）。**注意这是提示词约束，不是转换器**——模型绝大多数时候会照办，但不保证 100%，真出现繁体只能再加压或做后处理，不要以为这条已经锁死。
  **线上实测通过**（部署后走网页线路问 `retail`：「帮我查一下订单 111，还有那个降噪耳机多少钱？」）：回的是简体，**而且两条规矩同时成立**——耳机给了真 SKU 和真价格（`SKU-ELE-0001`，RM 328.90 含税），订单 111 明说「您的号码在我们系统里查不到客户账户，所以我无法查到这张订单」，再给换名字重查 / 转同事两条路。⚠️ 用 `curl -d` 直接带中文会发成乱码（bot 回「message didn't come through clearly」，**看起来像 bot 坏了，其实是终端编码**），要用 UTF-8 文件 `--data-binary @file`

- [x] **任务 12：导演台 v1 页面**
  文件：`frontend/src/pages/Console.tsx`（新增）、`frontend/src/api.ts`、`frontend/nginx.conf`
  ⚠️ **开工第一件事：给 `/console/stream` 加鉴权。** 现在它没有任何保护，仅仅因为前端 nginx 不转 `/console/` 才打不到（见任务 3）。这个页面要能用就得加转发，那一刻这条流——里面是 ERP 订单和客户资料——就公开了。复用 `require_auth` 那套 `X-Access-Token` 即可，但 `EventSource` 不能设请求头，所以 token 要走查询参数
  目标：订阅 SSE，把工具调用逐条渲染成一条流——工具名、入参、返回摘要、耗时、HTTP 状态。深色控制台风格，先能看清楚，不追求美观（v2 再打磨）
  **必须有一行「本次会话成本 RM x.xx」**：token 对老板是无意义单位，马币不是。「会不会很贵」通常是中小企业主真正的拦路问题，而这一行字直接终结它。实现是一行乘法（Opus 5：输入 $5 / 输出 $25 每百万 token，按当时汇率换算），成本几乎为零。旁边可以再放一句对照：*「同样这通询问，人工客服约 3 分钟」*
  验收：手机发消息，笔记本上的页面实时滚出对应的工具调用；会话成本以马币显示且随对话累加

  **2026-09-06 做完。**

  **鉴权这一条和任务描述写的不一样，说明理由**：任务里写「复用 `require_auth` 那套 `X-Access-Token`」，但**那一层 2026-09-05 已经被整个删掉了**（commit `cd5af81`，用户要求去掉访问密码：登录路由、token 集合、`DEMO_ACCESS_PASSWORD` 全没了）。所以没有复活它，改为**只给这一条流加一个独立的 `CONSOLE_TOKEN`**——客户聊天页保持无密码（那是已拍板的），只有导演台这条带真实订单和客户资料的流关起来。三条状态：未配置 → 503（不是放行，这一点专门写了测试），token 错/缺 → 401，对 → 200 SSE。比对用 `secrets.compare_digest`。

  **做了什么**
  - `backend/app/routers/console.py`：`?token=` 查询参数把守（`EventSource` 设不了请求头，所以只能走 URL；代价写在注释里了）
  - `backend/app/console/cost.py`（新增）：按模型的价目表 + 四种 token 各自计价（输入 / 输出 / cache write ×1.25 / cache read ×0.1）+ USD→MYR。**价格是查了 claude-api skill 的当前表拿的，不是凭记忆写的**：Opus 5 $5/$25、Sonnet 5 $2/$10 每百万。未知模型按最贵的算——报低了是兑现不了的承诺
  - `backend/app/services/llm.py`：`_log_usage` → `_record_usage`，**改成每次 API 调用记一条，不再是每次回复记一条**。这是必须的：一个跑工具循环的 turn 会调好几次 Claude，只算最后一次会把屏幕上那个数字变成实际花销的零头，工具循环越深谎越大。日志行的条数因此也跟着变了（更准了）
  - `frontend/src/pages/Console.tsx` + `Console.css`（新增）、`main.tsx` 加一行路径判断当路由（不引 router，只有这一个页面不属于客户流程）
  - `frontend/nginx.conf` + `deploy/nginx/chatbot.acuventech.com.conf`：**两跳都要关缓冲**。nginx 会把后端的 `X-Accel-Buffering: no` 自己吃掉、不往上一跳传，所以只关里层那一跳没用；两边都用 `location = /console/stream` 精确匹配，不把整个 `/console/` 前缀变成后端面

  **修掉一个自己写出来的真 bug**（浏览器实测才暴露）：token 错时 `EventSource` 收到 401 会**永久放弃、`onerror` 只触发一次**，所以按「失败 3 次就退回输入框」写的计数器永远到不了 3，页面会一直挂在「连接中断，重试中…」——一条没人在重连的流上说着「重试中」，正是这块屏最不该做的事。改成按 `readyState` 分流：`CLOSED` = 被拒，立刻退回输入框并说明原因（并清掉存的 token，否则刷新又是同一出）；`CONNECTING` = 真在重连，才走计数器

  **验证到什么程度**
  - 单测：容器里 **437 passed**（新增 6 条：401/503 两条门禁、usage 事件带马币、cache 两种费率、未知模型按最贵算；另改了 2 条既有测试——加了 usage 事件后「控制台上什么都没有」的断言不再成立，改成「没有工具调用」）
  - HTTP 层：真 uvicorn + curl，401 / 401 / 200 `text/event-stream` / 未配置 503 四种都实测过，SSE 帧原样打出来看过
  - 页面：**docker 起了前端 nginx + 后端两个容器，Chrome 里真看过**。URL 带 token 进 → token 从地址栏抹掉、流滚起来、成本从 RM 1.53 涨到 RM 1.87；坏 token → 立刻退回输入框并报原因；手输 token → 连上；「运行中」半行、error 红条、耗时右对齐都对
  - `tsc -b` + `oxlint` + `vite build` 全绿
  - **没验的**：真手机 → WhatsApp → 真 ERP 这一整条（那是任务 13 的活）；VPS 上的表现；`X-Accel-Buffering` 在 infra_nginx 那一跳的实际效果（本地只有一跳 nginx）

  **两处和任务描述的偏差**
  1. 「HTTP 状态」没做成 HTTP 状态码——事件里从来只有 `ok` / `error`（任务 3 定的），没有状态码可显示。屏幕上显示的是 `ok` / `error` / `运行中` 三态。要真状态码得改 erp/crm client 往上报，不在本任务范围
  2. 汇率 `USD_TO_MYR = 4.30` 是**手填常量，不是实时汇率**，写在注释里了。一场演示不需要外汇接口，差几个百分点只动一个已经小于一令吉的数字的最后一位

  **上线前必须做的一件事**：VPS 的 `/opt/ai_chatbot/backend/.env` 要加 `CONSOLE_TOKEN=<随便一串长随机串>`，否则页面打开就是 503。另外 `deploy/nginx/chatbot.acuventech.com.conf` 改了，要手工拷到 `/srv/infra/nginx/conf.d/` 再 reload——那个文件不在部署流水线里

  **2026-09-06 已上线**（用户拍板推 master）。`CONSOLE_TOKEN` 用户已配在 VPS 上（线上探测返回 401 而不是 503，说明配好了）。`deploy/nginx/*.conf` 那份**还没拷**到 `/srv/infra/`——但实测不影响路由，外层 vhost 本来就把 `/` 整个转给前端容器，那份改动只关缓冲这一件事。

  **上线后连着修了三个真 bug，全是「本地不出、线上才出」那一类，记下来**：

  1. **页面开场卡在「连接中…」十几秒**。SSE 一句话都不说的时候，中间某一跳（infra_nginx 或 Cloudflare，没定位是哪个，也不需要定位）会把响应头一起攒着，`EventSource` 收不到头就不 `onopen`。修法与「是哪一跳」无关：**流一打开先吐一帧**。这一帧后来顺便承担了第 3 条的职责
  2. **部署时后端一停，页面把「后端 502」当成「token 不对」，把存的 token 抹了**——重新部署一次就被踢回输入框。`EventSource` 对任何非 2xx 都是永久放弃（`readyState` 变 CLOSED），401 和 502 在客户端长得一模一样。判据改成「**这个 token 有没有成功连通过**」，而且这个标记必须放在 effect 外面（`useRef`）：放在 `EventSource` 上的话每次重试都重置为 false，后端停超过一次重试间隔就又误判了。第一版就是这么写的，第二版才发现
  3. **后端重启后页面显示「实时」但永远不动**。为了防重连重放导致的重复行，去重集合做成了跨重连持久的；而 seq 是每进程从 1 重新开始的，于是新进程的事件全被当成「见过」丢掉——**一块声称实时却什么都不显示的屏，比报错还糟**。修法是让服务端自报家门：`events.BOOT_ID`（每进程一个 uuid）随开场那一帧发出来，boot_id 变了就清空去重集合
  4. 附带把行配对从 `findIndex` 改成从后往前找，并给行加了独立的 `key`——真实 `tool_use_id` 由 Anthropic 生成不会撞，但重启后 id 复用时旧行会把新行的 `tool_end` 抢走，让活着的调用永远停在「运行中」

  **这三条的共同点**：单测、HTTP 层 curl、本地单机浏览器全都发现不了，**必须真的部署一次、真的把后端停掉才会露出来**。以后类似的实时页面，验收清单里应该固定加一条「部署过程中盯着这块屏」。

  **重新验证**：全套 **438 passed**；本地 docker 起前后端，浏览器里实测「连上 → 停后端 30 秒 → 起后端」：期间红字「连接中断，重试中…」、**没有**被踢回输入框、历史和成本都留着，恢复后自动重连、事件继续滚、行正确配对成 ok/error。线上 `chatbot.acuventech.com/console` 打开即「● 实时」

- [x] **任务 12.1：WhatsApp 端「正在输入」状态**——**2026-09-11 完成并真机验收**（同日上线后用户在 iPhone 上截图确认）
  文件：`backend/app/services/whatsapp.py`（加 typing indicator）、`backend/app/routers/whatsapp_webhook.py`
  目标：收到消息立刻发 typing indicator，回复发出后停止
  **这不是锦上添花，是防止前面所有工作被误解。** 接了真 ERP 之后一次回复要串好几个工具调用，延迟明显变长——没有输入提示，客户看到的是「卡住了」，**你辛苦做的真实调用反而变成了性能差的观感**。原本挂在可选项里，因此提为正式任务
  验收：真机发一条会触发多个工具调用的消息，对话框顶部先出现「正在输入…」，回复到达后消失

  **做了什么**
  - `whatsapp.build_typing_indicator(message_id)` + `send_typing_indicator(message_id)`。**没有「停止」这个动作**——Meta 把它折进了 mark-as-read 那一跳（`status: "read"` + `message_id` + `typing_indicator`），一个请求同时把客户的对勾变蓝、把「正在输入」点亮；**回复一到它自己消失**，没回复的话约 25 秒后自己消失。任务描述里「回复发出后停止」因此不是我们要写的代码，是 Meta 的既定行为
  - 调用点放在 `_handle_incoming_message` 的**最前面**，在 `dispatch_message` 之外。两个理由：① 必须在慢活之前发，发在后面就只是装饰；② `dispatch_message` 的契约是「自己不发任何东西、只返回 payload」（网关那条线靠它），而输入提示是个生命周期跟回复不一样的副作用，塞不进返回值
  - **这是本模块唯一一个吞掉自己失败的 send**，专门写了 docstring 说明：它站在回复前面，抛出去就是客户拿不到答案——一个因为装饰品挂了而丢掉的回复，比没有装饰品严格更糟。Meta 的原话进 WARNING 日志

  **验证到什么程度**
  - 单测：容器里 **549 passed / 7 skipped**（新增 6 条：payload 形状、Meta 拒绝时不外抛、连接超时时不外抛、没有 message_id 就根本不发请求、**typing 排在 LLM 调用之前**、typing 被拒后客户照样拿到回复且导演台不报 SEND_FAILED）
  - 改了 1 条既有断言：`test_end_to_end.py` 的 `_walk_up_to_the_question` 数「发了几条」，现在过滤掉 typing 再数——typing 不是客户读得到的消息
  - **真机（2026-09-11，上线后当场打的）**：iPhone 上对 retail bot 说「帮我查一下商品」，消息发出后左下角立刻出现输入中的气泡，回复到达后消失。截图为证

  **✅ Graph API 版本这条风险已解除，不用再动 `GRAPH_API_BASE`**。原本担心的是：全仓库唯一那个常量是 `v20.0`（任务 1 的媒体链路就在这个版本上实测通的），而 `typing_indicator` 字段 Meta 文档标的是 v21+，怕被 400。**真机实测 v20.0 照样吃这个字段**——而且同一条截图里客户那条消息是蓝色双勾，说明 `status:"read"` 和 `typing_indicator` 这两半在一个请求里都生效了，与「Meta 把它折进 mark-as-read」的设计预期一致。所以不用升版本，也不用为此重验一遍 media
  - 一处与任务描述的措辞出入（不是 bug）：iOS 上它渲染成**会话内左下角的气泡**，不是任务里写的「对话框顶部」。同一个东西的不同画法
  - 另一处已知但接受的边角：重复投递、认不出发件人这类**不产生回复**的消息也会点亮输入提示，然后挂在那儿约 25 秒。重复投递的原件回复会把它顺手掐掉；剩下的是错误路径。没为此加判断
  - 还有一处权衡：每条入站消息现在多一次同步 HTTP 往返（`REQUEST_TIMEOUT_SECONDS = 10`）排在 LLM 之前。正常 Meta 几百毫秒，但网络抽风时它会**给回复加延迟**——正好是这个功能想解决的东西。没做短超时，因为同样的抽风也会打到发回复那一跳
  - 网关那条线（`/internal/whatsapp/inbound`）**没有输入提示**，它只返回 payload、由网关去发。demo 线 2026-08-30 起直连 Meta，不走网关，所以不影响

- [x] **任务 12.2：对照组开关 —— 把核心主张变成当场可验证的实验**——**2026-09-11 完成**（代码 + 浏览器实测；「同一个问题两种答案」那半留给真机，见下）
  文件：`frontend/src/pages/Console.tsx`、`backend/app/routers/console.py`、`backend/app/services/llm.py`
  目标：导演台上一个开关，**关掉工具**，让同一个 bot 只靠 JSON 背答案。同一个问题问两遍——关：「蓝牙耳机有货，库存充足」（编的，听起来一样自信）；开：「SP-1001，仓库还有 47 件」+ 导演台滚出真实调用
  **整场演示想说的话，就是这两句的差别。** 与其反复解释「我们接了真系统」，不如让他自己看两遍
  成本极低：任务 2 的验收里本来就要求「**工具为空时行为与现在完全一致**」作为回归安全绳——这条代码路径本来就存在、本来就要测，只是此前没人想过它可以当武器用
  验收：开关拨两次，同一个问题两种答案；关的时候导演台没有工具调用，开的时候有

  **做了什么**
  - **`llm.py` 一行没改**，开关做在 `tools/registry.py` 的 `get_tools()` 这一个收口处：关掉就对每个 bot 返回 `[]`，于是它们全体走上「无工具」那条自任务 2 起就存在、一直被测着的路径。任务描述里点名 `llm.py` 是因为开关看起来该在那儿——实际上在 `get_tools` 拦一刀更短，而且被拦的是唯一入口
  - 进程内一个全局 bool，**故意不持久化**。重启回到「工具开着」这一侧：唯一要防的失败是重新部署之后没人发现，演示带着残废状态继续跑
  - `GET`/`POST /console/tools`（`ToolSwitch{enabled}`），跟其余导演台接口共用 `CONSOLE_TOKEN`。**这是 `/console/` 下唯一一个写的接口**，写的是进程里的一个标志位、不是数据
  - 状态变了才发 `tools_switched` 事件（`status: "on"|"off"`），第二块屏重申它已有的位置不算「操作员拨了一下」。导演台上这条事件是一行金色的「工具已关闭 —— 对照组开始」，**没有它，「一段时间里没有调用」和「一段时间里没人问」在屏幕上长得一模一样**
  - 前端：header 一个按钮（关掉时变红）、关掉时一条红色横幅写明这是对照组、feed 里那条记录行。开关状态**不是乐观更新**——先等后端确认，一个会自己弹回去的开关比一个慢半拍的开关糟得多
  - **修了一个只会在线上炸的坑**：`frontend/nginx.conf` 只代理了 `/console/stream` 和 `/console/history`（故意不整段代理 `/console/`），`/console/tools` 会掉进 SPA 的 `try_files` 拿回一个 200 的 index.html。本地 vite 按自己那张表代理，**永远不会复现**。已补 `location = /console/tools`，同时给 `vite.config.ts` 加了同一条
  - 顺带发现但**没动**：`vite.config.ts` 的代理表里至今没有 `/console/history`，所以 `npm run dev` 下的历史页是坏的（线上好的）。不属于本任务，留给谁碰到谁修

  **验证到什么程度**
  - 单测：容器里 **555 passed / 7 skipped**（新增 6 条）。新文件 `tests/test_console_tool_switch.py` 5 条：默认接通、关掉后 `get_tools("retail")`/`get_tools("hotel")` 全空且 GET 跟着变、拨两次在 feed 上留下 off/on 两条、重申同一位置不发事件、无 token 一律 401 且状态不变。`test_llm.py` 加的第 6 条是**唯一证明主张的那条**：开关关掉后，工具最多的 retail bot 走 `messages.create`、**根本没碰 beta 端点**、请求里没有 `tools`、导演台一条工具事件都没有
  - 容器里跑了一次线路检查：`POST /console/tools` 之后 retail 的 9 个工具真的清空，SSE 上真的吐出 `event: tools_switched` + `status:"off"`，无 token 的那次 401 且工具没被动
  - **浏览器实测**（vite dev + 容器后端）：拨一次 → 红横幅出现、开关变红、feed 滚出「工具已关闭 —— 对照组开始」；拨回来 → 横幅消失、滚出「工具已接回」；**关掉后刷新页面 → 开关仍是关的**（这就是 GET 那条接口存在的理由，replay 的三行也都回来了）
  - ⚠️ **「同一个问题两种答案」这半没验**：本地 `backend/.env` 里 `ANTHROPIC_API_KEY=` 是空的（key 只在 VPS 上），这台机器发不出真模型调用。**留给任务 13 真机那一枪**——那里本来就写着「对照组开关拨两次效果如预期」。代码侧能证明的是「关掉后模型收不到任何工具」，编出来的那句话长什么样，得线上看

  **2026-09-16：那一枪打了，结果和假设不一样，已修 + 已改写这段演示的定位**

  用户跑清单第六段，第 14 步 bot 回给客户的是**字面文本 `[Tool: erp_find_customer]`**。仓库里根本没有这个字符串——是模型写的。根因：开关只让 `get_tools()` 返回 `[]`，**系统提示词一个字没改**，而 retail 的 persona 通篇是「erp_find_customer 给你 customer_id」「每个事实都必须来自工具」。被命令调工具、又没有工具可调，它就把调用演成了文字，把内部工具名漏给了客户。**「关掉工具它会自信地编」这个立项假设，在真机上从来没成立过。**

  修法（`llm.py` 的 `TOOLS_WITHHELD`）：`bot.tools` 非空而本轮 `tools` 为空时——也就是开关被拨掉时——往**volatile 块**追加一段，告诉模型这一轮没有任何工具、上面那些工具说明只当背景、**不准把调用写成文本**（点名 `[Tool: name]` 这个形状）。放 volatile 不放缓存前缀：它只对这一轮为真，缓存进去会把「你没有工具」带到开关拨回来之后那一轮。**刻意不写「那就编一个」**——对照组之所以可信，正因为没人指示它编，而那种指示一旦写进提示词，就得保证它永远不会漏进真实对话。

  结果（真模型、真 dispatch 路径跑的）：关 → `目前没办法帮您查询价格和库存…我请同事帮您确认`；开 → `Sony WF-C710N，含税 RM 328.90/个，共 334 个现货：吉隆坡147、新山98、槟城89`。两边都不再泄漏工具名。

  **用户拍板（2026-09-16）：接受「诚实版」，不要让 bot 当着客户面胡说。** 理由是客户走出会议室会记住「这玩意会胡说」，而不是「那是因为关了工具」。于是这一段的定位改写成**「价值在你的数据里，不在 AI 里」**：同一个 bot、同一个问题，唯一差别是有没有接上你的系统；顺带还展示了「不知道就说不知道」。`tasks/real-phone-checklist.md` 第六段的两行预期和话术已同步改写。

  测试：`test_llm.py` 新增 3 条（开关拨掉时 volatile 块带上这段、这段点名禁止 `[Tool:` 这个形状、工具正常时**不**带这段），先红后绿。顺带改了一条老测试 `test_bot_without_tools_takes_the_plain_single_turn_path`——它拿 retail + 空工具做夹具，正好就是对照组那条路径，原来断言 system 逐字相等，现在改成断言缓存前缀不变、volatile 以原文开头。全套 **968 passed / 7 skipped**
  - 边角：开关是**全局**的，不分 bot、不分渠道，网页聊天和 WhatsApp 一起被关。演示就是要这个效果；但如果哪天有两场演示共用一个进程，拨开关会波及另一场

- [x] **任务 13：批次 01 真机验收**（用户任务）——⏸ **2026-09-11 用户决定押后，先做批次 02**。不是取消，是排到后面打；开发照常往下走，**不要因为这一条没勾就卡住后续任务**
  ✅ **2026-09-16 真机验收通过**（用户照 `tasks/real-phone-checklist.md` 跑完，本任务对应第一段剧本 1 + 第六段对照组 + 第九段 #25 三人并发）。**第六段按当天改过的「诚实版」判**（关工具说查不了、开工具出真数），见任务 12.2 的 2026-09-16 记录。依据是用户口头确认「都验证完」——我单独问过三人并发做没做，回答同上；没有逐步明细和截图
  ⚠️ 押后的代价写在这里，将来补打时照着看：批次 01 的代码（任务 9-12.2）**至今没有一枪真机**落在完整剧本上，只有单点验过（12.1 的输入提示、9/10/11 的单个工具各自验过）。批次 02 的改动会叠在它上面，真出问题时「是 01 坏的还是 02 坏的」要多分一次。补打时很可能和**任务 17** 合并成一次走完：旗舰剧本八步 + 剧本 2a/2b
  目标：用户拿手机走完整段旗舰剧本的八步，笔记本开着导演台
  验收：八步全通（**含「改成 3 个」那一步，订单金额要跟着变**）；ERP 后台刷出真单；PDF 发票能打开；大屏上每一步都有对应事件；对照组开关拨两次效果如预期
  **「正在输入」不用再单独验**——任务 12.1 的那一枪 2026-09-11 已经打过了（见该任务记录）。走剧本时留意它在每一步都出现即可
  **并发验证**：请在场三个人**同时**给这个号码发消息，三条对话各自独立推进、不串台。这条是破除「它一次只能应付一个人吧」这个很常见的直觉——**可能零代码**（`session_store` 本来就按手机号分键），但必须现场之前验过，别到客户面前才发现有共享状态的 bug

---

## 批次 02：眼睛和耳朵

> 给 A 类小老板看的。他不关心 API，他关心「我的客人只会发照片和语音，你这东西认不认得」。
>
> **剧本 2a —— 眼睛和耳朵（5 步）**：客户拍一张裂壳耳机的照片 → bot 认出 SKU → 找到订单 → 真的开退款单 → 客户用马来语语音追问，bot 用马来语答。全程零打字。
>
> **剧本 2b —— 你的文档，当场变客服（3 步）**：**让客户拿出他自己公司的 PDF**（菜单、产品手册、价目表都行）→ 在 WhatsApp 里直接发给 bot → bot 立刻能答关于这份文件的问题，**答案底下标出处**（`📄 文件名 · p.3`，客户可以自己翻过去核对）
>
> ~~每句话都标出处（第几页、**原文哪一句**）~~——「原文哪一句」**做不到，不要这样承诺**：PDF 的引用粒度是整页，Claude 返回的 `cited_text` 就是那一页的全文，截短了显示出来是页首而不是用到的那句。2026-09-11 任务 15.1 实测，详见该任务记录
>
> 2b 是这一批真正的销售武器。2a 证明「它认得懂」，2b 证明「**这是你的资料**」——客户不用想象，他手里就有东西可以立刻试。

- [x] **任务 14：图片消息接入**——**2026-09-11 完成并真机验收**（同日上线后用户在 iPhone 上打的，截图为证）
  文件：`backend/app/routers/whatsapp_webhook.py`（`dispatch_message` 的 `image` 分支）、`backend/app/services/llm.py`（`Image` + image content block）、`backend/app/services/audit.py`（`IMAGE` 来源）、测试
  目标：收到图片 → 用 `fetch_media()` 下载 → 转成 Claude 的 image content block 塞进对话；去掉现在的「只支持文本」提示
  验收：pytest 覆盖 image 分支；真机发一张商品照片，bot 能描述它

  **做了什么**
  - **图片只进当前这一轮的请求，不进 history**。这是这个任务唯一一处真正的设计取舍：`Message.content` 是字符串、history 会写进 Redis 并且**每一轮都重发给模型**，把 base64 图塞进去等于 Redis 存一次、input token 付一辈子。所以走的是 `llm.get_reply(..., image=llm.Image(data, media_type))` 这个只活一轮的参数，history 里留下的是**一行占位文本**：`[photo] 客户写的说明文字`（没说明就只有 `[photo]`）
    - 代价写在这里：下一轮模型**看不见那张图了**，只看得见这行标记和它自己上一轮的描述。剧本 2a「照片 → 认 SKU → 找单 → 开退款单」靠的正是它自己那句描述当锚点，够用；但如果哪天需要「再看一眼刚才那张图」，得在这里加一个「最近一张图缓存 N 轮」的东西
    - `[photo]` 这个标记顺便还挡了一件事：**带 `menu` 说明文字的图片不会把 demo 重置掉**——`MENU_KEYWORDS` 匹配的是整条消息，而这条永远不是
  - 图片块拼在**最后那条 user 消息里**，图在前、文字在后（Anthropic 对单图的建议顺序），不是单独开一条消息——一条只有图没有话的 user 消息读起来就是「客户发了个东西但什么都没问」
  - 格式在**下载之后**用 `llm.image_media_type()` 卡一道（只认 jpeg/png/gif/webp）。卡在 llm 这一侧是因为「模型能不能读」是模型那边的事实；卡在下载之后是因为 webhook 上报的 `mime_type` 和元数据那一跳报的可以不一样，后者才是字节真正的类型。不卡的话就是一个 400，而且是**客户已经等完整个下载之后**才到的 400
  - 导演台上是一条 `image.download` 的 tool span，和 `voice.transcribe` 同一个套路：TOOL_START 带 mime_type，TOOL_END 带「类型 + 字节数」。**沿用 tool 事件而不是新开事件类型**，前端不用改一行
  - 三种失败（下载炸了 / 超过 `whatsapp_media_max_bytes` / 格式读不了）**对客户是同一句话**，因为客户下一步要做的事一样；是哪一种在导演台上分得开。和语音那条线的口径一致
  - `UNSUPPORTED_TYPE_MESSAGE` 改成「文字、语音、图片」；原来那条「只支持文本和语音」的测试改成拿 sticker 来打——它现在才是真正没人接的类型

  **验证到什么程度**
  - 单测：容器里 **570 passed / 7 skipped**（新增 15 条）。webhook 侧 9 条：图片+说明文字到达模型、无说明文字也不会变成空 turn、history 里留的是说明文字不是图、按 `image` 块上的 id 去下载、导演台两条 span 的形状、下载失败、格式读不了（两条都验了 `get_reply` 根本没被调用）、没有 media id 就不下载、带 `menu` 说明文字的图不重置 demo。llm 侧 6 条：图块的 base64/顺序、**只有最后一轮被改写成 blocks**（更早那轮的图早就没了）、没有图的时候消息体仍然是纯字符串（这条是给其余所有消息路径的回归绳）、media_type 去参数、不认识的格式
  - 改了 6 处既有测试替身的签名（`def capture(bot, customer, history)` → 加 `image=None`）——`get_reply` 多了一个参数，替身就得跟着变
  - **踩了一个坑，记下来**：新写的 `test_a_download_that_fails_is_answered_rather_than_thrown` 和语音那节的同名函数**在同一个文件里撞名**，Python 直接用后定义的覆盖前面的，语音那条测试就**无声无息地消失了**——pytest 全绿，只是少跑一条。是因为对了一下总数（预期 569 实得 568）才发现的。`grep -oh "^def test_[a-z_0-9]*" tests/*.py | sort | uniq -d` 可以查，以后同一个文件里加同类测试先跑一下
  - ✅ **真实模型调用：当天用户补上本地 key 后打了四枪，全过**。没有真机（没人拿手机发图），但**「Claude 真的看懂了那张图」这件事已经被证明了**，剩给任务 17 的只是手机端那一跳。做法：容器里手写一张 PNG（540×246：大字 `SP-1001` + 左下红方块 + 右下绿圆点；容器里没 Pillow，用 zlib 直接编码），把 `fetch_media` 换成它，**走完整的 `dispatch_message`**，模型是真的：
    1. **retail / 工具关掉**（走 `messages.create`）：「The image shows the text "SP-1001" … a red square on the left and a green circle on the right」——**逐项对得上，一个没错**
    2. **同一会话第二轮，不带图**，问「刚才那张图上的编号是什么」：答 `SP-1001`。这正好实测了上面那条取舍——图没了，它靠自己上一轮的描述接住了
    3. **retail / 工具开着**（走 beta `tool_runner`；只挂只读工具，故意不给写工具，免得在 CRM/ERP 留脏数据，见阻塞项 D）：读出型号和两个图形后**真的去调了 `erp_search_sku`**，查 `SP-1001` 和 `1001` 都没结果，于是照实说「系统里查不到」并请用户拍品牌名或条码——**没编**。中文提问中文答。这一枪同时验掉三件事：beta 端点吃图片块、图片能触发真实工具调用、`NEVER_INVENT` 在图片路径上照样生效
    4. **hotel**（也带工具，但工具全在本地记录里、不碰后台）：读出了 `SP-1001`
  - ✅ **真机（2026-09-11 19:25，上线后当场打的，iPhone 截图为证）——这一枪比上面四枪都硬**。拍的是**真实商品**：一顶 LS2 FF908 STROBE II 白色头盔，摆在木桌上、斜角、有反光、背景还有另外两顶头盔，价签上一堆小字。**没有配文字说明**（走的正是 `[photo]` 那条无 caption 分支）：
    - bot 从**照片里那张价签上**读出了 `LS2 FF908 Strobe II 头盔`——型号是从一张有反光的斜角照片的小字里认出来的，不是猜的
    - 然后**真的去查了目录**，查不到，于是照实说「我在系统里找不到这款…我们目录里也查不到任何头盔类产品」，并提出「帮您把需求记录下来让同事确认能否调货」。**NEVER_INVENT 在真实照片上同样立住了**——这正是整个 demo 想证明的那件事
    - 用中文答（会话此前的语言），没有退回英文
  - ✅ **顺带把不支持的类型也真机验了**：用户接着发了一张**贴纸（sticker）**，收到 `UNSUPPORTED_TYPE_MESSAGE`。这条路径本来只有单测，现在真机也过了
  - ✅ **真机暴露的一个措辞问题，已改**：整段对话是中文，但兜底那句是**纯英文**的 "Sorry, I can only read text, voice and photo messages…"。`llm.py` 的 `FALLBACK_REPLY` 早就是中/英/马三语了，而 router 里这三条（`UNSUPPORTED_TYPE_MESSAGE` / `VOICE_UNREADABLE_MESSAGE` / `IMAGE_UNREADABLE_MESSAGE`）是纯英文——**同一个仓库里两种做法**。在客户面前，一句突然冒出来的英文会暴露这是硬编码的兜底而不是模型在说话。**2026-09-11 当天改掉了**：四个常量（连 `RATE_LIMIT_MESSAGE` 一起，它是同一类问题，留一个纯英文的没有意义）全部改成 `FALLBACK_REPLY` 那个「中 / EN / MS」的形状。**没动**开场菜单和问候语（`GREETING_SUFFIX_EN`、bot 列表那几句）——那是首次接触、还不知道客户说什么语言，和「对话进行到一半突然蹦出英文」是两回事。加了一条 `test_every_canned_reply_is_written_in_all_three_languages` 把形状钉住（含 `llm.FALLBACK_REPLY`，免得两个文件各走各的），**571 passed / 7 skipped**
  - 📌 **另一个观察**：bot 没有「描述」头盔，而是直接拿型号去查库存——对零售人设这是对的行为，但**如果演示时想秀「它认得图」，得让客户明确问一句「这是什么」**，否则观众看到的是一次查询失败，看不到识别成功。走剧本 2a 时注意这一点
  - ⚠️ **实测顺手挖出一个单测缺口，已补**：带工具的 bot 根本不走 `messages.create`，走的是 beta `tool_runner`——**那是另一条会自己校验请求的路径，而 retail 正是带工具的**。原来 5 条 llm 测试全在无工具那条路上，「beta 端点接不接受图片块」一直是个假设。补了 `test_a_photo_reaches_a_bot_that_has_tools_as_well`，现在 **570 passed / 7 skipped**
  - 📌 **一个记下来但没改的观察**：hotel bot 第一次被问「房间里这块牌子写了什么」时回了「I can't read or verify images」——**这是句关于自己能力的假话**。但换成切题的问法（「前台给我的卡上是哪个预订号」）它就正常读图了，所以触发的是 `NEVER_INVENT` 里「超出本业务的问题不归你答」那条；规则本身没错，只是理由编歪了。**没为此改提示词**：那是所有 bot 共用的缓存前缀，而演示时客户发的图一定是切题的。真在客户面前撞见了再说
  - ⚠️ **本地 `backend/.env` 里 `ANTHROPIC_API_KEY` 有两行**（第 1 行空、第 27 行有值）。dotenv 取后出现的那个，所以跑得通——但这是个定时炸弹，谁碰到谁把空的那行删掉
  - 边角：客户在**还没选 demo** 的时候发图，图会照样下载完再被丢掉（回的是 demo 列表）。语音那条线一模一样的行为，保持一致没动
  - 边角：`whatsapp_media_max_bytes` 默认 5MB，正好压在 Anthropic 单图 5MB 的线上；WhatsApp 自己的入站图片上限也是 5MB，所以没有再加第二道尺寸检查
  - 网页聊天（`routers/chat.py`）**没有接图片**，它没有上传入口。本任务只动 WhatsApp 这条线

- [x] ~~**任务 15：语音转录抽象层 + 一个实现**~~——**已由任务 36 完成（2026-09-06），不要重做**。36 就是它，只是后来在批次 06 里重开、口径改成抽象层。抽象层、webhook 的 `audio` 分支、pytest 全都落地了，真机也验过。
  ⚠️ **但有两处残留，是 15 要求过而 36 没做满的**，谁捡起来就在那里做，别再开一个新任务：
  - **「按配置选实现」只做了一半**。换供应商是多写一个 `Transcriber` 子类 + 改一行 `transcriber = ...` 赋值，**不是改环境变量**。真要按配置切（比如线上临时切回自托管），得再加一个 `TRANSCRIPTION_PROVIDER` setting + 一张查表。目前只有 `TRANSCRIPTION_MODEL` 是配置项，那只换模型不换供应商
  - **马来语没单独验过**。36 的真机验收打的是中英夹杂那一枪，过了；15 原本要的是「中文一句 + 马来语一句，日志里转录文本正确」。而且**至今没有逐字看过转录文本**——导演台没页面（任务 12），只能从回复反推「听懂了」。想补这一枪，等任务 12 的页面出来再看 `voice.transcribe` 那一行最省事

- [x] **任务 15.1：文档消息接入 —— 客户发 PDF，bot 当场能答**——**2026-09-11 完成，真实模型调用验过两条路径；真机（手机发 PDF）留给任务 17**
  文件：`backend/app/routers/whatsapp_webhook.py`（`document` 分支）、`backend/app/services/llm.py`（`Document` + document block + citations + `without_sources`）、`backend/app/services/doc_store.py`（新）、`backend/app/services/whatsapp_media.py`（尺寸上限参数化）、`backend/app/config.py`、`backend/app/services/audit.py`、`backend/scripts/document_probe.py`（新）、测试
  目标：收到文档 → 用 `fetch_media()` 下载 → 作为 Claude 的 `document` content block 塞进对话，**打开 `citations: {enabled: true}`** → 回答时带出处（PDF 是 `page_location`，标到页码）
  **这一步不需要 RAG**。Claude 原生吃 PDF，上限 32 MB / 600 页，直接喂即可。语料真的多到塞不下时才考虑检索，而且下一步应该是「关键词检索工具」（给 Claude 一个 `search_docs(query)` 接 MySQL 全文索引，让它自己决定搜什么），**不是向量库**——Anthropic 没有 embedding 接口，上向量意味着引入新供应商、切块调参、召回不准时极难排查。结构化业务数据用关键词检索天然更合适，形态也和整个工具驱动的设计一致
  验收：真机发一份 PDF 过去，问一个只有文件里才有的问题，**回答正确且带页码出处**；再问一个文件里没有的，它应该说不知道而不是编

  **做了什么**

  - **文档跟图片相反：它必须活过自己那一轮**。这是本任务唯一一处真正的设计取舍，而且是验收标准逼出来的——「问一个文件里有的，再问一个文件里没有的」是**同一份文件的两个问题**，没人发一份价目表只问一句。任务 14 给图片选的「只活一轮」放到 PDF 上，第二个问题就会被答成「我看不到那份文件了」
    - 存在**进程内**的 `doc_store`，不进 Redis：那条记录每来一条消息就读一次写一次、活七天，把 PDF 塞进去等于为一份聊四句就没用的文件在网线上来回搬一个星期。和 `session_store` 做的是同一笔 demo 级交易——重启就忘，客户重发一次
    - 每人只留最新一份（「我们在聊的那份文件」在这个 demo 里永远是单数），全局只留最近 5 份 LRU（一个月的陌生人各发一份手册 = 一 GB 常驻内存）
  - **PDF 挂回它进来的那一行，不挂到最新一轮**。history 里留的标记是 `[document] price-list.pdf 客户的问题`，`llm._index_of` 每轮拿这行字去 history 里倒着找，找到就把 document block 插在它前面。这样做有四个好处，每一个都是选它而不选「挂最后一条」的理由：
    - **可缓存**。挂最新一轮的话前缀每轮都变，二十页 PDF 每轮几万 input token 全额重付；钉在原地前缀不变，加一个 `cache_control` 断点就只读一次。**实测 `cache_read=6141`**，缓存是真的在命中
    - 时间上诚实：文件是三轮之前发的，不是刚发的
    - **过期是免费的**——那行字滚出 40 条的 history 窗口，就再也没有东西可挂，文件自然失效
    - 客户发 `menu` 重来时 `_start_over` 顺手 `doc_store.forget`（文件不在那条记录里，清记录清不掉它）
  - **出处只标页码，不引原文**。剧本 2b 原话是「第几页、原文哪一句」，**「原文哪一句」做不到**，这是实测出来的：PDF 的 `page_location` 引用粒度是**整页/整块**，同一份两页探针文件返回的 `cited_text` 分别是 269 和 149 字符，就是那两页的全文。把它截到手机屏幕宽度，显示出来的是**页首那几行**，而不是答案真正用到的那句——那读起来是「引错了」，比不引更糟。所以footnote 的形状是 `📄 price-list.pdf · p.1, p.2`
    - 顺带解决了三语问题：文件名 + 页码在中英马三种语言里长一个样，不需要翻译，也不需要在前面加一句需要翻译的话
    - `end_page_number` 是**开区间**，跨页引用会展开成 `p.6, p.7`；展开有上限，免得一条覆盖 600 页手册的引用变成 600 个页码
  - **⚠️ 探针当场抓到一个真 bug，已修：出处不能进 history**。第一版把 footnote 拼进回复就整条存进了 history，于是第二轮模型看见自己上一条消息是以「📄 …· p.2」结尾的，**照着格式自己又写了一个**——那个页码是从聊天记录里抄的，不是从文件里读的，底下再叠上我们生成的真的，客户屏幕上出现两条出处。一个查不了的页码正是 `NEVER_INVENT` 要挡的东西，而且它还穿着「可查」的制服。修法是 `llm.without_sources()`：**发出去的带 footnote，记住的不带**（审计日志留全的——那才是客户实际收到的东西）
  - 尺寸上限**不跟图片共用**。`whatsapp_media_max_bytes` 的 5MB 是照着 Anthropic 单图上限定的；PDF 那边是 32MB/请求，base64 多占三分之一，所以新加 `whatsapp_document_max_bytes = 16MB`，`fetch_media(media_id, max_bytes=...)` 多一个参数。剧本 2b 让客户当场掏自己的文件，一份扫描版宣传册轻松过 5MB
  - 只认 `application/pdf`，其余（.docx 最可能）在**下载之后**卡掉，理由和图片那条线一样：webhook 上报的 mime_type 和字节真正的类型可以不一样。兜底话术是三语的，而且说的是「转成 PDF 再发一次」——客户真能照着做
  - 导演台上是 `document.download` 的 tool span，TOOL_START 带 mime_type + filename，TOOL_END 带「文件名 + 字节数」。沿用 tool 事件，**前端一行没改**（查过 `frontend/` 没有 tool 名白名单）

  **验证到什么程度**

  - 单测：容器里 **604 passed / 7 skipped**（基线 571，新增 33）。webhook 侧 14 条、llm 侧 15 条、`test_doc_store.py` 6 条（含 LRU 和「问它才算用过」）。改了 8 处既有测试替身的签名（`get_reply` 多了 `document` 参数）
  - **✅ 真实模型调用，两条路径都打过，各三问**（`scripts/document_probe.py`，手写的两页 PDF，SKU 和价格都是刻意编的、不在 seed 目录里，所以答对只可能是读出来的；pypdf 先验过这份 PDF 是合法的两页文件）：
    1. **问第 1 页的东西**：`TX-7742 … RM 287.50`，出处 `p.1` ✅
    2. **第二轮不带文件，问第 2 页的东西**：`TX-9915 … RM 1,459.00`，出处 `p.2` ✅ —— 这一枪证的就是「文件还在」，是整个设计取舍的兑现
    3. **问文件里根本没有的（免运费）**：「没有——里面完全没提运费」，接着照实列出文件里确实有的三条条款 ✅ 没编
    - 三问在 `--tools` 关（`messages.create`）和 `--tools` 开（beta `tool_runner`，旗舰 retail 真正走的路）**两条路径上各跑了一遍，结果一致**。任务 14 就是在「beta 端点吃不吃这个 block」上踩过坑，这次先打了
  - ⚠️ **没有真机**（没人拿手机发 PDF）。剩给任务 17 的是手机端那一跳：WhatsApp 的 document 消息结构、真实文件大小、以及客户自己那份 PDF 的排版

  **边角 / 已知没做**

  - **页数超限没有单独兜底**。Anthropic 一次请求最多 100 页，超了是 API 返回错误 → 现有的 `APIError` 捕获 → 客户收到通用的 `FALLBACK_REPLY`（「我这边出了点问题」），而不是「您这份文件太长了」。容器里没有 PDF 库可以数页数（`pypdf` 只在 dev 依赖里），为了一句更准的话把它提进运行时不值。真在客户面前撞见了再说
  - **还没选 demo 就发文件**：文件会照样下载完、记进 `doc_store`，然后客户收到的是 demo 列表——因为那条路径在写 history 之前就返回了，标记没进 history，这份文件之后永远匹配不上，只是占个位子等着被 LRU 挤掉。和语音、图片那两条线的行为一致，没动
  - **网页聊天（`routers/chat.py`）没接文档**，它没有上传入口，也就永远不会有 footnote，所以那边没加 `without_sources`（加了是死代码）
  - 一份文件同名同 caption 发两次 → 标记相同 → `_index_of` 取**最后一条**，即最新那份，正确

- [x] **任务 16：退货剧情的工具**——**2026-09-11 完成，线上真开了一张退款单（`CN-2026-00001`）**
  文件：`backend/app/tools/erp.py`（两个新工具）、`backend/app/services/erp_client.py`（`create_credit_note` + 两个常量）、`backend/app/bots/data/retail.json`（挂工具 + 人设加一段）、测试
  目标：`erp_find_order_by_sku(customer_id, sku)`、`erp_create_credit_note(order_id, reason)`
  验收：调一次 credit note，`erp.kelvinpeng.com` 后台能看到那张退款单

  **做了什么**

  - **签名和计划里写的不一样，是接口逼的**。erp_os 的 `POST /api/credit-notes` 要的是 **`invoice_id` + 必填的 `lines[{invoice_line_id, qty}]`**，不是 `order_id`：它冲的是**发票行**，没有「退掉这张订单」这种调用。所以实际落地的是
    `erp_create_credit_note(order_no, customer_id, sku, reason="", quantity=0)`：
    - `order_no` 而不是 `order_id`——和 `erp_generate_einvoice` 一致，模型手里拿的一直是单号；客户 id 一起传，走的是 `sales_order_for_customer`，**模型编的单号只会查无此单，不会退到别人头上**（这条安全性质是从发票工具那儿继承的）
    - `sku` 是必填的：一次退一个商品。全单退在这个 demo 里没有场景，而给一个裂了壳的耳机开 RM 3,745 的全单退款，客户盯着的那块屏上会很难看
    - `quantity` 留空 = 退整行（客户说「退掉它」的意思），给了数就退那么多
    - 工具内部自己走 **order → invoice → invoice line** 三跳，模型全程不碰 `invoice_line_id` 这种它没法核实的整数
  - **`erp_find_order_by_sku` 是 N+1，没得选**。erp_os 的订单列表**不能按商品筛**（`repositories/sales_order.py:43-83` 只 LIKE 单号和备注，压根不碰行），而且列表响应里**不带行**，行只在单据详情里。所以只能把客户最近的单一张张打开读。上限 `ORDERS_SEARCHED_FOR_SKU = 10`，凑够 `MAX_SKU_ORDER_MATCHES = 3` 条就停——每开一张就是一次 HTTP，这个数是被延迟卡住的，不是口味问题
    - 匹配吃两种写法：`erp_search_sku` 给的编码（整串相等）和客户嘴里的名字（**每个词都得在**，所以「sony earbuds」不会匹配到别人家的耳机）
    - **读单失败时返回 `UNAVAILABLE`，不跳过继续**。半读的搜索报成「没找到」等于告诉一个手里正拿着那东西的客户「你没买过」——这是这个工具唯一不能误报的答案
  - **退款单留在 DRAFT，不提交 MyInvois**。发票那边要提交是因为客户要拿走那份文件；退款单只要出现在演示指的那块屏上就够了，而 erp_os **不让取消已提交的退款单**（`services/credit_note.py:379-442`）——提交等于每次彩排都留下一张撤不掉的单
  - **失败话术特意不给「再试一次」**。别的写工具分「失败了」和「不确定」两种口径，这里不确定时明确写 **Do not try again**：erp_os 会拒绝对同一批货二次冲红，而一个「好心」改小数量重试的模型，是能把第二次退款做进去的

  **⚠️ 实测挖出的一件事，会直接影响任务 17 怎么走**

  - **种子发票一张都开不了退款单**。第一次拿 `SO-SEED-00226` 试，erp_os 返回 `INVOICE_WAREHOUSE_MISSING`：**`INV-SEED-*` 上没有仓库**，而退货要把货入回某个仓，所以 erp_os 直接拒。**只有这个 bot 自己经 `erp_generate_einvoice` 开出来的发票才带仓库**，才能退
  - 已经加了一道前置检查 `_no_warehouse_to_return_to`，读发票上的 `warehouse_id` 就能判。**不加的话客户听到的是「这批货已经退过款了」——一句不同而且不真的话**
  - **对剧本 2a 的硬约束：退款那一步必须打在 bot 自己开的单上，不能指一张种子单。** 演示前先用真机让 bot 走一遍「下单 → 发票」，再演退货；或者接受在种子单上会得到「请同事人工处理」这个（诚实但不炫技的）回答

  **验证到什么程度**

  - 单测：容器里 **627 passed / 7 skipped**（基线 604，净增 23：21 条新测试 + 2 条花名册测试跟着改）
  - **变异测试：9 处逐个改坏，9 处全部有测试变红**——冲的不是发票行 / 不校验发票状态 / 半读搜索当没找到 / 不卡退货数量 / 不在凑够时停 / 名字匹配从 all 改成 any / 单号不按客户作用域查 / reason code 不发 RETURN / 超长 reason 不截断。没有一处逃掉
  - ✅ **线上真做了一遍，而且是剧本 2a 最后三步的完整彩排**（因为种子单退不了，只能自己造一条链）。客户用的是已在册的 `WA-` demo 账号（id 52），可被任务 34 的清理认领：
    1. `erp_create_sales_order` → **`SO-2026-00001`** CONFIRMED，2 件 Sony 耳机，RM 657.80
    2. `erp_generate_einvoice` → **`INV-2026-00001`** **VALIDATED**，带 LHDN UIN `AC915F281CC64E74`（PDF 没发，因为脚本里没有 WhatsApp 通道，符合预期）
    3. `erp_find_order_by_sku(52, "SKU-ELE-0001")` → 找回 `SO-2026-00001`
    4. `erp_create_credit_note(..., quantity=1)` → **`CN-2026-00001`** DRAFT，**RM 328.90**
    5. 从 ERP 读回 `/api/credit-notes` → 在册，`total: 1`
    - **金额自己对得上**：657.80 的一半，正是 2 件里退 1 件。不是我算的，是 erp_os 算的
  - **线上留下的痕迹**（demo ERP，都在 `WA-` 客户名下）：1 张销售单、1 张出库单、1 张已验证发票、1 张 DRAFT 退款单。要清就跑 `POST /api/admin/demo-reset`
  - ⚠️ **没验的**：真机（没人拿手机走这条线，属任务 17）；模型自己会不会在对话里正确地串起这两个工具——单测和线上验的都是工具本身，**「bot 看到照片后会不会想到先 find 再 credit」这一跳没验过**

- [x] **任务 17：批次 02 真机验收**（用户任务）——**照着 [tasks/real-phone-checklist.md](real-phone-checklist.md) 跑，一趟覆盖任务 13 / 17 / 21**。⚠️ **2026-09-12 跑过一轮：2a 过、2b 挂了，修完要重跑**。见下方「真机验收记录：2026-09-12」
  ✅ **2026-09-16 真机验收通过**（清单第二段 2a 退货 + 第三段 2b 自己的文件）。09-12 挂掉的 **2b 这次重跑通过**——我单独问过有没有标出页码，用户回答「都验证完」。依据是用户口头确认，没有逐步明细和截图
  目标：走完剧本 2a 和 2b
  验收：**2a** —— 拍一张破损商品照片发过去，走完「识别 → 找单 → 开退款单」，再用语音追问一句；全程不打字，五步全通，ERP 后台有退款单
  ⚠️ **2a 有一个前置条件，任务 16 实测出来的**：退款只能开在**这个 bot 自己下过单并开过发票**的订单上——种子发票（`INV-SEED-*`）没有仓库，erp_os 一律拒绝冲红。所以走 2a 之前，先让 bot 真的下一单并生成 e-Invoice，退货再打在那张单上
  **2b** —— **拿一份你自己的 PDF**（不是我们准备的素材，现场随便找一份）发过去，问一个只有文件里才有的细节，回答正确且标出页码

---

## 批次 03：临门一脚

> 前面所有功能都是「客户问，它答」，只有主动推送是**它自己动了**——这一下对老板的杀伤力被严重低估。转人工则是成交前最后一个问题的答案：「那 AI 搞不定怎么办？」
>
> **剧本 3 —— 它自己动了 + 兜底（5 步，接在剧本 4b 之后）**：客户刚点完两份椰浆饭 → 约 30 秒后手机「叮」，bot 主动推送「您的订单已出餐，骑手预计 10 分钟送达」（**客户没问**）→ 客户回一句超纲的「能让骑手放门口吗？想加一份辣椒酱，我补钱」→ bot 判断超出自动处理范围，「帮您转接同事」，**bot 静默** → **老板在导演台上直接打字回复**，大屏显示「人工接管中」→ 老板打暗号，bot 接管回来
>
> ⚠️ **这一批建的是能力，不是这出戏**。剧本 3 演在餐饮，而餐饮点餐流程在批次 04（任务 25）——依赖是倒的。不为此重排批次：**本批把能力挂在当时唯一存在的下单流程（零售）上**，任务 21 只验能力；等批次 04 做完 food，剧本 3 才真正成立，演出验收挂在任务 26。`notify.py` 本就该做成通用的，挂零售和挂餐饮是同一个钩子的两处调用。

- [ ] **任务 18：模板消息文案 + 提审**（用户任务，批次第一天就做）——**2026-09-12：文档已写好，两个模板用户已提交审核，等 Meta 批**
  文件：`docs/whatsapp-templates.md`（新增，Claude 写）
  目标：Claude 写好两个模板的 JSON 和中/英/马三语文案（订单已确认、已出库+追踪号）；用户在 Meta 后台粘贴提交
  验收：Meta 后台显示模板状态 Approved
  说明：审核要几小时到 1-2 天，先提交再做任务 19，不要串行等

  **✅ 文档已就绪**：[docs/whatsapp-templates.md](../docs/whatsapp-templates.md)，照着抄进 Meta 后台即可。里面有两个模板（`order_confirmed` / `order_shipped`）的名字、类别、变量表、三语正文逐字版、示例值，以及最终发出去的 JSON 长什么样。
  **⏳ 剩下的一步是你的**：Meta Business Suite → WhatsApp Manager → Message templates → Create template，**三种语言各提交一次**（Meta 是按「模板名 + 语言」存的），类别选 Utility。审核通过后确认状态是 Approved。

  **写文案时定下来的几件事，别在后台改**
  - 模板名 `order_confirmed` / `order_shipped`、变量顺序「称呼 / 单号 / 金额或追踪号」**是代码的合同**——`notify.py` 的 `ORDER_CONFIRMED`、`ORDER_SHIPPED` 和 `erp._promise_an_update` 按位置填槽。在后台改名或调顺序，代码这边不会报错，**客户会在订单号的位置读到金额**
  - 类别一律 **Utility**，不是 Marketing：订单状态通知本就属于 Utility，而且 Marketing 审得更严
  - 模板固定发 **英文**。不是偷懒——模板是按语言分开审的，而客户档案里**没有语言字段可用**（`UserProfile.language` 至今没有任何地方写入，我查过全仓库）。窗口内的纯文本推送不受这个限制，那条是中/英/马三语一条
  - ⚠️ **模板没批下来不影响演示**。任务 19 的推送发生在下单后 30 秒，**永远落在 24 小时窗口内**，走的是纯文本那条路。模板是给「隔天回访」那种场景准备的

- [x] **任务 19：主动推送**——**2026-09-12 完成，代码侧全绿；真机那一枪（手机真的叮一声）属任务 21**
  文件：`backend/app/services/notify.py`（新增）、`backend/app/services/whatsapp.py`（模板构造器）、`backend/app/tools/erp.py`（下单成功后触发）、`backend/app/routers/whatsapp_webhook.py`（开队列 + 起表）、`backend/app/config.py`、测试
  目标：下单成功 N 秒后，用 `send_message()` 主动推一条消息。24 小时窗口内用普通文本，窗口外用已审核模板
  验收：真机下单后手机自动「叮」一声收到确认消息

  **做了什么**

  - **照抄 `outbox` 的形状，因为问题是同一个**：工具知道「刚发生了一件值得说的事」，但**不知道该说给谁**。所以工具往队列里放一个 `Push`，路由（唯一决定「写给谁」的地方）拿着发信人号码 `dispatch`。`notify.available()` 也和 `outbox.available()` 一个用途——网页聊天没有手机可以叮，工具得能分辨，否则 bot 会在笔记本上承诺「出货了我通知您」
  - **这是整个服务里唯一一条「自己发」的路径**。别的消息都是回复：收到消息 → `dispatch_message` 拼 payload → 调用方发出去。推送没有可回复的请求，所以它自己调 `whatsapp_media.send_message`——那个函数的注释本来就写着「为没有请求可回复的调用方而设」
  - **⚠️ 24 小时窗口不能用 `last_seen` 判，这是个坑**。`UserProfile.last_seen` 看起来正是那个字段，其实不是：它在**每次 `save` 时**都会刷新，包括 bot 写回自己回复之后的那次。所以它的含义是「上次碰过这条记录」，不是「客户上次说话」。改成在 `dispatch()` 那一刻打时间戳——那一刻正在处理一条入站消息，窗口必然是开的，**这个判断是精确的**；而且它错也错在安全的一侧：客户之后再说话只会把窗口撑大，所以最坏情况是「本可以发纯文本却发了模板」，那也还是送达
  - 延迟做成配置项 `push_delay_seconds`（默认 30 秒）。这是**舞台调度**不是技术参数：太短像是回复的一部分，太长观众已经走神。那个「它自己动了」的数字要在客户面前试出来
  - 用 `threading.Timer`，和 `session_store` 同一笔 demo 级交易：单进程、不持久化、重启就忘。**重启吞掉的是一次手机震动，不是一张丢掉的订单**
  - 推送会**写回客户 history 和审计日志**。不写的话，客户紧接着问「什么时候到」，模型是在回答一条它看不见自己发过的消息；转录里也正好在手机震动那一刻有个洞
  - 导演台上是一条 `notify.push` 的 tool span，和 `image.download` 同一个套路，**前端一行没改**。剧本 3 的全部主张是「这条没人打字」，而这件事只有在第二块屏上才看得见——客户手机上它看起来和别的消息一样
  - ⚠️ **网关那条路上推送仍然是自己发**，用的是本服务的 WhatsApp 凭据而不是网关的。对 demo 号是对的（2026-08-30 起直连 Meta），但**如果将来有下游 demo 不是直连的，这里要重新想**。已写进 `notify.py` 的模块注释

  **验证到什么程度**

  - 单测：容器里 **653 passed / 7 skipped**（基线 627，净增 26）。`test_notify.py` 15 条、模板构造器 4 条、下单触发 4 条、路由接线 3 条
  - **变异测试：15 处逐个改坏，第一轮 14 处变红、1 处逃掉，补强测试后 15/15 全红**。逃掉的那处是「网页聊天不排推送」——守卫删掉也没测试变红，因为原测试只断言了订单本身。**守卫留着**（`notify.add` 虽然也会拒绝，但每次网页下单都打一条 warning 是噪音），测试改成断言 `notify.add` 根本没被调用
  - 专门补了一条**真起线程**的测试（50ms）：`dispatch` → 计时器 → `_send` 这条接缝别的测试都绕过去了（它们直接调 `_send`），而两边参数顺序错了的话，**要到演示当天手机不响才会发现**
  - ⚠️ **没验的**：
    - **真机**——手机真的叮一声，属任务 21。而且这一枪有前提：推送只对 WhatsApp 那条线有效，得先用手机真下一单
    - **模板那条路一行真实流量都没跑过**，因为模板还没提审（任务 18）。它的 payload 形状有单测钉着，但「Meta 认不认」得等 Approved 之后才知道
    - **没有往任何真实号码发过消息**。能离线验的都验了，剩下的那一步是往一个真人的手机上发东西，没有你点头我不做

- [x] **任务 19.1：演示收尾总结 —— 让他把演示带回去**——**2026-09-12 完成，代码侧全绿；真机那一枪属任务 21**
  文件：`backend/app/console/summary.py`（新增）、`backend/app/services/notify.py`（加 `send_now`）、`backend/app/routers/console.py`（新端点）、`backend/app/models.py`、`frontend/src/pages/Console.tsx` + `.css`、`frontend/src/api.ts`、`frontend/vite.config.ts`、测试
  目标：点一下，往客户手机推一条总结——「刚才这 8 分钟里，我查了 3 次库存、建了 1 张订单（ORD-xxxxx）、开了 1 张 e-Invoice、留了 1 条 CRM 线索。这段对话在您手机里，随时可以翻」
  验收：点「结束演示」，手机收到总结消息，里面的订单号和数字都对得上刚才真实发生的事

  **做了什么**

  - **每一个数字都来自审计日志里 `status='ok'` 的真实 tool_calls**。这是这个任务的核心而不是实现细节：整场演示花八分钟论证「这个 bot 不编」，**最后一条消息里有一个编的数字，前面八分钟就白说了**。所以失败的调用不计入（查不到库存的那次没有查到库存），单号是从工具自己返回的 JSON 里读出来的（`order_no` / `invoice_no` / `credit_note_no`），客户读到 `SO-2026-00001` 能在你身后那块屏上找到它
  - **消息三语，用空行分段而不是 ` / `**。其他兜底话术都是一句话，用斜杠分隔；这条是三段，用斜杠串起来在手机上没法读。满配长度 1097 字符，WhatsApp 上限 4096
  - **数完之后没有活动也照发**：只说时长 + 「这段对话留在您手机里」。那句话在任何情况下都是真的，而且**它本来就是这个功能的全部意义**——WhatsApp demo 相对网页 demo 的唯一独有优势
  - **端点选哪个会话：默认取审计日志里最近的一条**，因为刚演完的就是要收尾的那场。但**导演台的事件流上根本没有客户身份**（`events.ConsoleEvent` 没有这个字段），屏幕自己不知道在服务谁——所以返回值里写明「发给了谁」，并显示在按钮旁边。三个人同时演示的场景下，这一行是「对」和「碰巧对」的区别
  - `notify.send_now()`：人触发的即时推送，复用定时推送那条路的全部机制（导演台 span、写回 history、审计记录），**所以人发的和 bot 发的在这些地方长得一样**
  - 导演台按钮抄的是任务 12.2 那个开关的写法：不做乐观更新、结果落在旁边一行小字里。**发送中禁用按钮**——它往真人手机发消息，紧张的操作者双击就是两条
  - ⚠️ **这是导演台 token 第一次能写「客户读得到的东西」**。`require_console_token` 的注释原来写着「底下全是只读的」，现在不是了。已在端点里写明——那个 token 仍然是对的闸（拿着它的人就是站在手机旁边跑演示的人），但它不再只是一把「看」的钥匙

  **验证到什么程度**

  - 后端单测：容器里 **673 passed / 7 skipped**（基线 653，净增 20）
  - 前端：`tsc -b && vite build` 过（走 Dockerfile 的 build 阶段），`oxlint` **0 warnings 0 errors**
  - **变异测试：16 处逐个改坏，第一轮 13 红 3 漏，补强后 16/16 全红**。三处漏网全是测试缺口，不是代码问题，值得记下来：
    1. 「40 秒也算 1 分钟」——我的测试用的是 0.6 分钟，而 `round(0.6)` 本来就等于 1，**那条测试从来没碰过它要守的那个下限**。改成 0.2 分钟
    2. 「没有审计日志就不数」——守卫删掉也没测试变红，因为关掉的 store 查询本来也返回空。改成断言 `query` 根本没被调用
    3. 「`send_now` 真的会发」——导演台的测试全都把它 patch 掉了，`test_notify.py` 里又没有它的测试。补了一条
  - ✅ **把消息完整打印出来读了一遍**，抓到三处单测抓不到的问题，都已改：
    1. `开了 1 个客户账户（52）`——**52 是 ERP 的行 id**，对客户毫无意义，而且读起来像是我们手里有一个关于他的编号。去掉了这个工具的单号引用
    2. 英文 `1 photo or file you sent, read` 夹在逗号列表里断句混乱 → 改成 `1 photo or file of yours read`
    3. 马来文同样的逗号问题 → 同样改法
    - 这条记下来：**面向客户的文案，单测只能守住结构，读一遍才能守住它是不是人话**
  - ⚠️ **部署之后又抓到两件事，都已修，记在这里因为两件都是「只有看真东西才看得见」**：
    1. **那颗按钮部署了但打不到**。`frontend/nginx.conf` 是一条路由一条地列的，`/console/demo-summary` 不在里面，POST 落到 SPA 上被 nginx 答 405。是部署后 curl 线上才发现的。已加 location，并补了 `backend/tests/test_console_routing.py`——它读真实的 `nginx.conf` 和 `vite.config.ts`，比对后端声明的每一条 console 路由，把新加的 location 改掉会变红（验过）。**这条守卫第一次跑就又抓到一个**：`/console/history` 从任务 37.2 起就不在 vite 的 dev proxy 里
    2. **时长算错了，而且错得离谱**。第一条真实会话 `a1317265` 从 16:34 跨到 19:25——同一个 `conversation_id` 活了 171 分钟，因为 demo 是下午选的、照片是晚上发的。原来用 `MIN/MAX(created_at)`，于是总结会说「刚才这 171 分钟里」。改成**按「久坐」算**：从最新一条消息往回走，遇到超过 30 分钟的间隔就停，工具调用也只数这一段。变异测试 6 处全红，其中一处是补出来的——**「长间隔正好在最后一条消息之前」**（客户隔三小时只发一张照片）这个真实形状，第一版逻辑答错而没有测试发现
  - ⚠️ **仍然没验的**：
    - **真机**——没有往任何真实号码发过消息（同任务 19）
    - **`tally()` 没有对着真实 MySQL 跑过**。但 `MIN/MAX(created_at)` 那个疑问已经排除：线上 `/console/history` 返回的时间戳是经 `_at()` 的 `.isoformat()` 出来的且没报错，**所以驱动返回的确实是 datetime 对象**
    - 导演台那颗按钮**没有在浏览器里点过**，只有 build + lint

  **顺带发现，没修**：`frontend/vite.config.ts` 的 dev proxy 是一条路由一条地列的，`/console/history` **不在里面**（任务 37.2 加查询页时漏了）。只影响 `npm run dev`，不影响线上（nginx 转发的是整个 `/console/`）。我只加了自己这条 `/console/demo-summary`，没顺手改成 `/console` 一条通配——那是旁边的代码。要修就一行的事。

- [x] 🔍 **任务 20：人工接管状态机**——**2026-09-12 完成，冷审两轮（第 1 轮 2 P1 + 5 P2，第 2 轮 6 条含一条我自己引入的回归），全部修完；真机那一轮属任务 21**
  文件：`backend/app/services/handover.py`（新增）、`backend/app/tools/human.py`（新增）、`backend/app/routers/whatsapp_webhook.py`、`backend/app/routers/console.py`、`backend/app/services/user_store.py`、`backend/app/services/notify.py`、`backend/app/tools/local.py`、`backend/app/models.py`、`backend/app/services/audit.py`、`frontend/src/pages/Console.tsx` + `.css`、`frontend/src/api.ts`、`frontend/vite.config.ts`、`frontend/nginx.conf`、测试
  目标：客户说「找真人」→ 会话标记为人工模式，bot 静默；用户在导演台上直接打字回复；用户发暗号 → bot 接管回来
  验收：pytest 覆盖状态迁移；真机走一轮，客户侧全程无感

  **三处偏离规格，都是有理由的**

  1. **标志存 `UserProfile`（Redis），不存 `session_store`**。规格点名了 `session_store`，但那是**这个进程的记忆**：演示中途重部署会把标志丢掉，bot 就在老板正打字的时候抢话。七天的 Redis 对这个标志来说也不是对的寿命，但比一次 uvicorn 重启对得多。有测试专门钉这条（`test_it_survives_the_process_that_started_it`）
  2. **交回用按钮，不用「暗号」**。暗号是「老板拿手机回」那个假设的遗留物——而规格自己已经推翻了那个假设（demo 号是纯 Cloud API 号，没有手机 App）。操作者在导演台输入框里打字，一个暗号词有被当成正文发给客户的风险；按钮没有
  3. **多了一条路径：`request_human_help` 工具**。规格只写了关键词。但剧本 3 要的是「**bot 判断超出自动处理范围**」——那不是客户说了某个词，是模型自己的判断。所以两条都有：关键词是**保底**（四个没有工具的 bot 也管用，而且客户铁了心要找人时不取决于模型怎么想），工具是**判断**。工具挂在三个有工具的 bot 上

  **做了什么**

  - **接管中 bot 一个字都不发**——不是道歉，不是「稍等」。客户现在在跟人说话，机器插一句就是把接缝露出来
  - **但客户说的每一句照样写进 history 和审计**。转录要完整，而且 bot 接回来时得读过——客户跟人讲完了问题，发现 bot 完全不知道，那是交接失败
  - **交回时不给客户发任何东西**。他从来没被告知过「刚才是机器人」，「机器回来了」是唯一一句会让接缝显形的话。这条就是验收标准里那句「客户侧全程无感」
  - **导演台那半边**：横幅（显示接管中 + 是谁 + bot 已静默）、输入框、交回按钮。状态**轮询** `GET /console/handover` 拿权威值，同时两端各发一条 `handover` 的 tool span 让事件流即时有反应。**不靠事件流推导状态**——环形缓冲区滚掉或后端重启，屏幕会说「没事」而 bot 仍在静默，那是这个功能唯一不能有的失败
  - 人打的回复**对客户没有任何标记**，在 history 里记为 assistant——对他来说那就是答复。**只有审计日志知道**：那一行的 `source = human`。导演台上是 `human.reply` 的 span，和 `notify.push` 分得开
  - `menu` 会**同时解除接管**。不解除的话，客户打了 menu、拿到 demo 列表、然后从此被静默

  **⚠️ 测试当场抓到一个会让整个功能失效的 bug**

  第一版 `handover.begin(key)` 自己从 store 重新读一份记录、置位、保存。而路由手里**还攥着同一条记录的另一个副本**，回合结束时把它存回去——**标志被覆盖，bot 照常回答，日志里什么痕迹都没有**。工具那条路一模一样。

  改成 `begin/end` 直接作用在**调用方手里那个对象**上（和 `local._Serving.store` 是同一个「活引用」手法），`_Serving` 也从只带 `key_id` 改成带整条记录。`test_the_flag_lands_on_the_record_the_router_is_about_to_save` 钉的就是这个。

  **验证到什么程度**

  - 后端 **717 passed / 7 skipped**（基线 691，净增 26）；`test_handover.py` 26 条
  - **变异测试 15 处，第一轮 14 红 1 漏，补齐后 15/15 全红**。漏的那处是 `request_human_help` 工具本身一条测试都没有
  - **顺带修掉一个测试卫生问题**：变异运行时有两条跑了 16-22 秒——那说明短路一旦失效，它们会**真的去打模型 API**。补上 patch，现在最慢的测试是 0.25 秒
  - 前端 `tsc -b && vite build` 过，`oxlint` **0 warnings 0 errors**
  - **上一轮加的路由守卫立刻见效**：新增的 `/console/handover` 和 `/console/reply` 没登记进 nginx 和 vite 时它当场变红。这正是它存在的理由
  - ⚠️ **没验的**：
    - **真机**（属任务 21）。尤其是「客户侧全程无感」这条——只有拿手机走一轮才算数
    - **导演台那个输入框没在浏览器里点过**，只有 build + lint
    - **模型会不会主动调 `request_human_help`** 没验过。工具本身有测试，但「bot 遇到超纲的事会不会想到用它」是提示词层面的事，而这类假设本周已经被证伪过一次

  **🔍 冷审（2026-09-12，第 1 轮）——报了 2 条 P1 + 5 条 P2，全部带跑红的复现，全部修了**

  ⚠️ **仓库约定的自动交接（Stop hook）在后台任务里不会触发**，那个钩子要交互式 session「停下」才跑。这一轮是用 `tasks/review/reviewer_prompt.md` 的口径起了一个独立子智能体代替：只读 `HEAD~1` 的规格和 diff，自己跑测试，**没有开发方的自辩在上下文里**。是替代品，不是原流程。

  审查方自己跑了全套（717 passed / 8.9s），并且**自己重新引入了那个 lost-update bug 验证守卫是真的**（5 条测试变红），还拿真 Redis 在进程内把整场戏跑通了一遍。

  **P1-1：普通句子会让 bot 永久静默。** 关键词是子串匹配，于是：
  - **`你们这是人工智能吗？`** —— 「人工智能」里含「人工」。**这是 AI 演示上最可能被问的第一句话**
  - `I bought it from your agent last week` —— 而 **realestate 的人设自己就叫 bot 说 "agent"**，且它没有工具，关键词是它唯一的路
  - `is this suitable for human resources teams?`

  静默跟着记录活七天，没人在导演台前就没人知道。**我自己的注释还写着「人工 不是客户谈耳机时会说的任何词的片段」——那句话是假的，而且我从没测过。我还在任务记录里把子串匹配当成「可接受边角」打发掉了。**
  **修法**：关键词换成**请求短语**（带动词的），不再有裸词。`人工` 只在 `转人工 / 找人工 / 要人工 / 人工客服 / 人工服务` 里算数。补了 6 条反例测试 + 6 条正例测试。

  **P1-2：接管期间 bot 其实有六条路还会说话。** 守卫在 `_handle_text_message` 里，而有五条路在它之前就返回了：贴纸/位置等不支持的类型、语音转不出来、图片下不下来、文件读不了、日限额。**它们发的恰恰是「本 demo 只能读文字、语音、图片和 PDF」这种宣告「这是个机器人」的句子**，在人正打字时插进去，一句话就把接缝露出来。
  第六条最恶劣：**接管之前排好的推送**——客户下单、随即要求转人工，六十秒后 bot 插一句「您的订单已确认」。
  我 commit message 里写的「一个字都不发，连道歉都不发」，字面上说的就是上面这些道歉。**那句话当时是假的。**
  **修法**：所有兜底话术走同一个 `_canned()`，它先查接管状态；`notify._send` 在**触发那一刻**（而不是排期时）查一次。人自己打的字不受影响（`label` 区分）。

  **P2-1：导演台会打字给最早被接管的那个人，不是当前这个。** `waiting()` 升序排，前端取 `held[0]`。配上 P1-1 的误触发，**上周某个没交回的陌生人会稳定占住默认位置，老板在客户面前打的每一句都发给他**。改成降序 + 前端加选择器，其余的不再不可见（P2-2）。

  **P2-3：隐藏号码的客户能被静默、但永远回不了。** `/console/reply` 要求 `phone`，而 BSUID 记录没有——可是这个服务从任务 32 起到处都是按 `key_id` 寻址的。bot 哑、导演台也哑。改成 `phone or key_id`。

  **P2-4：URL 里的 token 现在是「往任意客户手机发字」的钥匙。** `require_console_token` 的注释还写着「底下全是只读的」——任务 19.1 起就不是了，任务 20 更甚。审查方直接演示了 `POST /console/reply?token=…` 不带 header 返回 200。**修法**：所有写操作换用 `require_console_write`，**只认 header**。只有 `/console/stream` 需要 URL token（EventSource 发不了 header），而它不写。前端本来就一直在发 header，零功能损失。

  **P2-5（部分成立）**：没有长度上限。审查方说「会在 Meta 那边失败」——**这一半不对**，`whatsapp._body()` 本来就会裁到 4096。但**静默裁掉操作者的话同样不好**，所以前端加了 `maxLength`。

  **另外修了审查方标为「只读推测」的两条**：IME 的 Enter（中文面板上选词也是 Enter，不加 `isComposing` 会把半截字发给客户）、以及一次失败的轮询会把错误提示钉在屏幕上一整场。

  **还纠正了我自己的一处事实错误**：commit message 里写「给那四个没有工具的 bot 保底」——**是三个**（banking / food / realestate），而且它们恰恰是**没拿到**这个工具的三个。

  **修完之后**：**744 passed / 7 skipped**（审查前 717）；针对修复的**变异测试 10 处，第一轮 8 红 2 漏，补齐后 10/10 全红**（一处是真缺口：没断言那次保存不会把标志抹掉；另一处是我的变异写歪了）。前端 build + lint 干净。

  **审查方没跑第二阶段（对质）**，按协议那要在第一批 findings 交付之后才做。

  **🔍 冷审第 2 轮（对质 + 复验）——又报了 6 条，其中一条是我在第 1 轮修复里引入的 P1 回归**

  审查方复验了第 1 轮的全部修复（**全部确认修好**，10 条 repro 通过），然后做了协议里的对质阶段，并攻击了第 1 轮新写的那段中途接管守卫。

  **N1（P1，我自己引入的回归）：任务 19.1 的收尾总结被我加的守卫吞了。** `send_demo_summary` 用的是默认 label，而我的守卫按 label 判断——于是**接管中按「结束演示」，导演台显示「已发给 Kelvin」，手机上什么都没有**。批次 03 的压轴功能在最可能被按的那一刻静默失效。
  **根因是我把界线画错了**：该被挡的不是「发给谁」，而是「**谁发起的**」——定时器，还是一根手指。改成 `unattended` 参数，人按按钮的一律放行。

  **N2（P1）：短语化矫枉过正，25 种真实说法漏 23 种**，包括 `转接人工`——马来西亚每个银行聊天都是这么说的。还有 `能不能转真人`、`人工在吗`、`get me a human`、`nak cakap dengan manusia`。
  **N3（P2）：同一份清单另一个方向仍在误触发**——`Let me talk to someone in my team`、`I need to speak to someone in accounts first`、`我想找个人一起拼单`。前两句正是**客户准备下单时会说的话**，bot 在临门一脚静默。

  这两条一起说明一件事：**关键词永远做不到又准又全**。所以改成两手：
  - 匹配器换成正则，中文按语素（`人工` 排除 `人工智能/人工智慧/人工成本/人工费`）、英文要求**请求动词 + 名词同现**（所以 "your agent" 不中、"speak to an agent" 中）、马来语用「人」而不是「人这个词」（`cakap dengan orang yang hantar barang` 说的是快递员）
  - **把 `request_human_help` 给了所有 bot**，包括原本三个没有工具的（banking / food / realestate）。**最没能力的那几个恰恰最需要这条出路**，而判断该归模型，不该归一张词表。实测：审查方给的 13 种真实说法**一个不漏**，12 种误触发**一个不中**
  - 代价：那三个 bot 从 `messages.create` 换到 beta tool_runner。三条依赖「某个 bot 恰好没有工具」的测试改成**显式构造**那个场景——朴素路径仍然存在、仍然被测，只是不再有真实 bot 走它

  **N4（P2）：第七条泄漏**——`_handle_interactive_reply`。客户在还没选 demo 时被接管，点一下菜单，bot 发问候语 + 按钮。我第 1 轮写的「所有兜底话术走同一个 `_canned()`」里的「所有」**当时是假的**。

  **N5（P2）：我第 1 轮那段守卫自己犯了同一类 lost-update。** 两条消息并发：B 走静默路径写盘，A 随后用它开工前加载的副本覆盖——**B 说的话被抹掉**。审查方的原话：「这正是这段守卫为了防止而写的 bug，在低一行的位置重新出现」。改成写到**当前**那份记录上。代价是顺序：并发到达的那条会排在前面，内容一条不丢，审计日志里的顺序仍然是真的。

  **A1（对质阶段点名的根因）：接管标志没有上限。** 审查方拆掉了我第 1 轮的说法——我把它记成「可接受边角」，缓解措施写的是「导演台横幅一直挂着」，而**那个横幅只对当天开着导演台、带着 token 的人可见，下周没人在那儿**。而且第 1 轮的两条 P1/P2 **都是这个根因的症状**。加了自动失效，导演台列表也不再显示。

  **2026-09-12 傍晚追加：失效改成「闲置计时」**（用户问「人工回复之后多久转回 AI」时发现的）。原来是 `MAX_HANDOVER_SECONDS`，**从接管那一刻算 2 小时**——也就是说同事在第 2 小时 01 分还在打字，bot 会悄悄抢回去。演示里无所谓，真当客服用就是错的。
  改成 `MAX_IDLE_SECONDS`（仍是 2 小时），**从「人最后一次动作」算起**，同事每回一句就清零。新增 `UserProfile.handover_active_at`，和 `handover_since` 分开——后者是给导演台显示「这位客户被接管多久了」的，前者回答的是「还有没有人在看」。
  ⚠️ **只有「人」的动作算数**。客户一直在说话**不算**——那恰恰是「接管被忘了、客户在被无视」的样子，而这个上限存在的意义就是兜住它。
  已失效之后导演台再打字会被拒（409），必须重新接管——因为那时 bot 已经在答了，再插一句就又是两个声音。
  验证：**780 passed**；**变异测试 8 处，第一轮 4 红 4 漏，补齐后 8/8 全红**。漏的四处全是防御性冗余（接管时打首戳、旧记录回退、交回时清干净、没被接管的对话不打戳）——代码站得住，是测试没覆盖。另外**修了一条我自己写歪的测试**：我构造了「闲置 6 小时且还在打字」这种不可能的状态，而闲置计时的意义恰恰是只要他还在回就到不了失效。

  **2026-09-12 另：ERP/CRM 时间差 8 小时查清了**，结论和当初的假设相反——**是显示层的 bug，不是存储的，也跟容器 TZ 无关**（erp_os 早就设了 `TZ: Asia/Kuala_Lumpur`，照样错）。后端序列化 naive datetime 不带 `Z`，前端 `new Date()` / `dayjs()` 按规范当本地时间读。完整排查记录见 [`tasks/erp-crm-timezone.md`](erp-crm-timezone.md)：影响面、两个必须避开的雷、动手前要先跑的 4 条 SQL。**修的地方在 `erp_os` / `crm_os` 两个仓库，不在本仓库**，只读排查，那边一行没动。

  **2026-09-12 再追加：2 小时改成现场可调**（用户提的）。常量换成 `settings.handover_idle_seconds`（env `HANDOVER_IDLE_SECONDS`，默认仍是 7200），和 `push_delay_seconds` 一个路子——它是**对「一个客服台该怎么运作」的判断**，不是技术常量：彩排时想当场看它失效就调成 60，真客服台中午吃饭要留久一点就调大。
  **在 `active()` 里每次调用时读**，不是模块加载时绑定，所以测试能用 `patch.object` 推它，改 `.env` 也只需要 `docker compose restart backend`，不用重新部署。已写进 `.env.example`。
  验证：**781 passed / 7 skipped**（比基线多的那一条就是新加的）；变异测试：把它写死回 `2 * 60 * 60` → 红。

  **N6（P3）**：交回之后前端 `selected` 没清，面板会静默切到下一个客户——两次按键之间就可能发生（5 秒轮询）。已修。

  **我被指出的一处判断错误**：我说审查方的长度上限那条「一半不成立」——**这一半是对的**（`_body()` 本来就裁到 4096），审查方自己确认了它没追过发送路径就下了结论。但**静默裁掉操作者的话**那一半成立，前端的 `maxLength` 是对的修法。

  **审查方的自评（它自己漏了什么）**，照抄要点：它说自己「擅长『什么输入产生什么错误输出』，不擅长『缺了什么不变量』」——**那个没有上限的标志我在两轮记录里都主动写了，它两轮都没把它当成独立 finding**，只报了它的两个症状。

  **修完之后**：**766 passed / 7 skipped**（第 1 轮后 744）；第 2 轮修复的**变异测试 10 处，10/10 全红**。前端 build + lint 干净。

  **两轮的逐条记录已按仓库格式落盘**：`tasks/review/task-20/{round-1,round-2}/`，含 `findings.json`、真跑过的 `repro/`（round-1 对 `b59bdf3` 16 red / 4 green，round-2 对 `30bfc63` 18 red）和 `validate_findings.py` 的输出（7 条/5 入队、8 条/6 入队）。`tasks/review/task-20/README.md` 写明了这两轮**跟自动流程的差异**——最实质的一条是**隔离弱化**：原流程给审查方一个改不到被审代码的独立 worktree，这两轮只有一句「不要改」的指令。

  **审查方的结论：现在仍不建议上真机**，按它给的顺序 hold 在 N1、N5、N2、A1——**这四条都已经修了**。它没有再复验这一轮（第 2 轮是协议的轮次上限）。

  **两个已知边角，没修**

  - ~~关键词是**子串匹配**，误触发可接受~~——**这条被冷审打掉了，见上面 P1-1**。当时写「可接受」是错的：`人工智能` 含 `人工`，而那是 AI 演示上最可能被问的第一句话。现在匹配的是带动词的请求短语
  - ~~接管标志跟着记录活七天~~——**被冷审第 2 轮打掉了，见上面 A1**。现在 2 小时自动失效。当时写的缓解措施（「导演台横幅一直挂着」）不成立：那个横幅只对当天开着导演台的人可见

- [x] **任务 21：批次 03 真机验收**（用户任务）——**照着 [tasks/real-phone-checklist.md](real-phone-checklist.md) 跑，第四段是人工接管**。⚠️ **2026-09-12 主动推送和收尾总结都收到了**，但金额格式和 CRM 措辞当天改过，要重看一眼。转人工那半段等任务 20。见下方「真机验收记录：2026-09-12」
  ✅ **2026-09-16 真机验收通过**（清单第一段下单后的主动推送 + 第七段人工接管；「暗号」按任务 20 偏离 2 就是导演台的「交回 bot」按钮）。依据是用户口头确认「都验证完」，没有逐步明细和截图
  验收：**验的是能力，不是剧本 3**（那出戏要等批次 04 的餐饮流程）。零售下单后主动推送收到；说「找真人」后 bot 静默、导演台上回一句客户能收到、打暗号后 bot 接管回来

---

## 批次 04：广度 —— 原生表单和两个新行业

> 让 A 类客户在列表里看见自己的行业，是他掏钱的关键。餐饮和房产最贴近马来西亚中小企业，后台也最简单好做。
>
> **剧本 4a —— 不跳出 App 的表单（房产，5 步）**：客户问「蒲种三房，60 万以内」→ bot 列 2 个房源 → 客户说想看房 → **bot 弹出原生表单**（姓名 / 日期 / 房源），客户在 WhatsApp 里填完，**全程不跳出 App** → 提交后大屏上房产后台出现那条预约，**CRM 看板同时长出线索卡**
>
> **剧本 4b —— 点餐（餐饮，4 步）**：客户「两份椰浆饭一杯拉茶」→ bot 加购物车 → 报总价 → 确认下单，后台订单状态流转。**演完立刻接剧本 3**，两段连成 9 步。
> **不新开项目**：作为 `backend/app/verticals/{food,realestate}/`，共用 vps_infra 里开一个 MySQL db，后台页面挂在导演台同一个域名下——保持一个部署单元，不增加运维负担。

- [x] **任务 22：verticals 骨架 + 数据库**——**2026-09-12 完成**。后端 **802 passed**（781 → 802，净增 21）。
  文件：`backend/app/verticals/__init__.py`（新增）、`backend/app/verticals/db.py`（新增）、`backend/app/services/mysql_url.py`（新增）、`backend/app/services/audit.py`、`backend/app/config.py`、`backend/.env.example`、`deploy/mysql-init/01-verticals.sql`（新增）、`docker-compose.yml`、`docker-compose.prod.yml`、`backend/scripts/verticals_probe.py`（新增）、`backend/tests/test_verticals_db.py`（新增）、`backend/tests/test_mysql_url.py`（新增）、`backend/tests/test_audit.py`、`backend/tests/conftest.py`

  **和审计层同骨架，但有一处故意相反**：`audit.py` 写失败是「丢掉这一行、谁也不告诉」——对日志是对的，因为调用方正在回客户、拿它没办法，丢的是一条记录。**verticals 存的是客户正盯着屏幕等它出现的预约/订单**，静默丢掉会变成「bot 说您的看房已确认」而后台空空如也，这是演示能犯的最严重的错。所以这里一律抛 `StoreUnavailable`，由上层工具转成 ERP 工具那套「刚才没查到」的说法。熔断器保留（失败后半分钟内不再付连接超时），只是到期抛错而不是返回 None。

  **`_dsn()` 抽成了 `services/mysql_url.py` 共享**，没有复制第二份。它带着 percent-decode——那是线上踩过的坑（密码里一个 `@` 会表现成「密码不对」而不是「URL 不对」），有测试守着。两份解析器等于两次漂移的机会。日志里加了 `feature` 参数，因为现在有两个 URL，「not a mysql:// url」本身说不清坏的是哪一个。原来那 4 条 `_dsn` 测试搬去了 `test_mysql_url.py`。

  **没有 registry 之外的框架**：`store.register(*SCHEMA)` 让每个 vertical 在 import 时贡献自己的建表语句，共用一条连接。晚注册也有效（会重新打开建表标志），否则一个被延迟 import 的 router 会发现 schema 已经「建好了」却没有它的表。

  **`VERTICALS_MYSQL_URL` 是独立的一条**，不设 = 这两个行业没有后台。和 `MYSQL_URL` 一样**绝不能进 compose**（仓库是 public，带密码）。**生产 compose 不需要改网络**——backend 从任务 31 起就挂在 `data_net` 上，`infra_mysql` 就在上面；只在注释里补了一句说明。本地 compose 里 `mysql:8` 的 `MYSQL_DATABASE` 只能建一个库，所以第二个库由 `deploy/mysql-init/01-verticals.sql` 建（挂进 `/docker-entrypoint-initdb.d`，只影响本地那个一次性容器）。

  **验证**：单测 **803 passed**（781 → 803）；**变异测试 13 处全红**——第一轮有一条漏网，暴露出我那条「畸形 URL 不重试」的测试根本没断言到性质（URL 解析不出来时驱动本来就不会被调用，所以「什么都没执行」在熔断与否两种情况下都成立），改成数解析次数才真正杀掉。
  **真实 MySQL 活体验证**（不是打桩）：`docker compose up -d mysql` 起本地 mysql:8，跑 `scripts/verticals_probe.py`——建表、写入一行含中文和撇号的数据（`陈家明 O'Brien` / `蒲种三房，60 万以内`）、读回**完全一致**、`DATETIME(3)` 的毫秒没丢、探针表自行清掉。**能连上 `ai_chatbot_verticals` 本身就证明 init 脚本建出了第二个库**。两个 compose 都过了 `docker compose config`。

  ⚠️ **线上还差一个 grant**（见下面「阻塞项 I」），不做的话任务 23-26 的真机验收落不了地。不加也不会坏：demo 其余部分行为完全不变。

- [x] **任务 23：realestate 后端 + 后台页面**——**2026-09-13 完成**。后端 **821 passed**（802 → 821，净增 19），前端 `tsc -b` + `vite build` 全过。
  文件：`backend/app/verticals/realestate/{__init__,models,routes}.py`（新增）、`backend/app/services/clock.py`（新增）、`backend/app/services/audit.py`、`backend/app/main.py`、`backend/tests/test_verticals_realestate.py`（新增）、`frontend/src/pages/VerticalAdmin.{tsx,css}`（新增）、`frontend/src/api.ts`、`frontend/src/main.tsx`

  **房源不是第二份数据，是从 bot 的 prompt 里播种的。** `bots/data/realestate.json` 本来就带着那 8 套房，persona 还明写「Only the listings in front of you exist, with the id, price, size and status they carry」。在库里再抄一份，就等于给「bot 报 62 万、隔壁屏幕写 65 万」留了一个位置。所以 `seed_listings()` 读 bot config，用 `ON DUPLICATE KEY UPDATE` 播进去——改 JSON 里的价格，重启后后台跟着变。

  **路由挂在 `/api/verticals/realestate/*`，不在 `/console/` 下面，这是部署决定不是命名决定。** `/console/` 下每加一条路径，就要在 `frontend/nginx.conf` 和 `vite.config.ts` 再写两遍，否则线上被 SPA 接管——任务 19.1 那个「部署了但点不动」的按钮就是这么来的，`test_console_routing.py` 就是为它写的。`/api/` 两边本来就按前缀代理，这三条路由掉不进那个坑，**两个配置文件一行没改**。鉴权仍用 console token，且走 `require_console_write`（只认 header）：这张表是姓名加电话，没有 EventSource，不需要那个会落进代理日志的 query string 形式。

  **时间戳那 8 小时的坑，在这里是提前避开的**：`audit.py` 里的 `_timestamp` 抽成了 `services/clock.py` 的 `sql_timestamp`（和任务 22 抽 `mysql_url.py` 同一个理由，那段注释里的教训不该有第二份）。`created_at` 由**应用容器**写，不用 MySQL 的 `CURRENT_TIMESTAMP`——本地 compose 里 `mysql:8` 根本没设 TZ。发出去的字符串不带 offset，页面**切片而不是 `new Date()` 解析**。

  **写代码过程中自己揪出来一个洞并补上**：`_seeded` 是进程级标志（这是「改 JSON 价格重启生效」的前提），但如果数据库**空着回来**（换 volume / `down -v` / 表被 drop），`db.py` 会老实把 schema 重建出来，而这个标志会说「8 条已经播过了」——于是后台永远空白，而且 bot 还在报的每个 listing id 都会 404，直到进程重启为止。补法：`_reseed_if_the_store_went_away` 装饰器，任何一次调用撞上 `StoreUnavailable` 就把标志清掉。**这条是拿真库实测过的**，见下。

  **验证（三层，全部实跑，没有跳过）**：
  1. **单测 821 passed**（8 skipped 都是历史的：`tzset` POSIX only + 7 条要设 `REFUSAL_EVAL_BASE_URL` 的 refusal eval）。新增 19 条，含「数据库空着回来要重新播种」「时间戳由本容器打」「query string 里的 token 不算数」。
  2. **真 MySQL 活体验证**（`mysql:8` 容器 + 挂 `deploy/mysql-init`，不是打桩）：建表、播 8 条房源、curl 建预约、读回。中文和撇号原样（`陈家明 O'Brien`、`下午 3 点，蒲种`，全角逗号也没掉），`DATETIME(3)` 毫秒没丢，`DATE` 存的是纯日期。`PROP-999` → 404，空姓名 → 422，不带 header → 401，**token 放 query string → 401**。
  3. **浏览器实看**（Chrome，`npm run dev` + vite 代理）：`/vertical-admin?token=…` 打开是 8 条房源 + 预约列表；**页面开着的时候 curl 灌一条，5 秒内它自己出现在最上面并高亮**（这就是剧本 4a 那一下）。然后 `docker stop mysql`，页面**保住已有的行并在顶部报「读不到后台」**——不会把「数据库挂了」演成「还没有预约」。再把表 drop 掉（进程仍以为播过种），下一次调用重建 + 重播 8 条，页面自己恢复。

  **偏离 / 没做的**：
  - 预约表**没有 status 列**。persona 写的是「take down ... then tell them the agent will confirm it」，这条记录本身就是「待确认的请求」，加一个永远等于 `Requested` 的列是死重量。餐饮那边的状态流转是任务 25 自己的表。
  - 日期拆成 `viewing_date DATE` + `preferred_time VARCHAR(32)` 自由文本，没有合成一个 DATETIME——客户选的是日期，硬凑 00:00 等于在屏幕上写一个没人说过的时间。`preferred_time` 留自由文本是因为填它的是 WhatsApp Flow，槽位列表是 Meta 的。
  - **真机验收不在本任务**：这三条路由现在只有 curl 和浏览器走过，bot 还不会调它们——那是任务 24（Flow 表单）和任务 26（剧本 4a 真机）。
  - ⚠️ **线上仍缺「阻塞项 I」那条 grant**（任务 22 留下的）。不加：房产后台第一次调用就抛 `StoreUnavailable`，页面显示「读不到后台」，demo 其余部分不受影响。

- [x] **任务 24：WhatsApp Flow —— 预约看房**——**2026-09-13 代码侧完成，838 passed**（821 → 838，净增 17）。**真机那一枪属任务 26**，而且还缺一步只有用户能做的：在 Meta 后台建 Flow 拿 ID。
  文件：`backend/app/tools/realestate.py`（新增）、`docs/whatsapp-flows.md`（新增，Flow JSON）、`backend/app/services/whatsapp.py`、`backend/app/services/outbox.py`、`backend/app/routers/whatsapp_webhook.py`、`backend/app/tools/registry.py`、`backend/app/config.py`、`backend/.env.example`、`backend/app/bots/data/realestate.json`、`backend/tests/test_realestate_flow.py`（新增）

  **走 `navigate` 不走 `data_exchange`，整个功能压在这个决定上。** `data_exchange` 要 Meta 每翻一屏回调我们的公网 endpoint，还要做 RSA 密钥交换和签名校验——为一个四字段、无分支、无服务端校验的表单搭一套密钥体系。`navigate` 把房源列表**随消息一次性发过去**（`flow_action_payload.data`），填完的表单作为一条 `nfm_reply` 入站消息走**已有的 webhook** 回来。代价是 Meta 不帮我们校验字段，所以 `book_from_form` 自己解析：缺字段 / 日期读不出来，一律不写库并明确告诉 bot「没保存」。这也是清单说「不要死磕超过一个 session」时该选的那条路。

  **预约是在 webhook 里确定性写入的，不是让模型调工具写的。** 客户已经按下提交了，这条记录必须存在——不能取决于模型有没有想起来调工具。写完之后才把一句话交给模型（`_handle_text_message`，source=`interactive`），让它用客户一直在用的那门语言回一句确认、并调 `crm_create_lead` 长出剧本 4a 要的线索卡。**这是两件事的分工**：确定性的归代码，措辞和语言归模型。

  **降级路径是内建 + 有测试守着的，不是备胎。** `WHATSAPP_FLOW_ID` 空着是**受支持的状态**：工具返回 `NO_FORM`，bot 改成在聊天里一次性问三件事。网页聊天线永远走这条（没有 outbox = 没有能承载表单的通道）。没人跑过的备胎就是坏的，所以它有自己的测试。
  ⚠️ **降级路径下口头给的信息不会自动落库**——`book_from_form` 只在收到 `nfm_reply` 时触发。真要走降级，演示时指着 CRM 看板讲。没补这个，因为它是降级路径不是主路径。

  **验证（验了什么 / 怎么验 / 没验什么）**：
  1. **单测 838 passed**，新增 17 条：房源只出 `Available` 的、下拉框标题带真实价格、没配 Flow 时降级、网页线降级、后台挂了不发空表单、`navigate` 而非 `data_exchange`、draft/published 两种 mode、**flow_token 里不含手机号**、毫秒时间戳按 UTC 解析、缺字段不写库、后台挂了明说没保存、webhook 的 `nfm_reply` 真能变成预约、**人工接管期间表单照样落库但 bot 闭嘴**。
  2. **真 MySQL 活体验证**（`mysql:8` 容器，不是打桩）：房源自建表自播种 → 生成真实要发给 Meta 的 payload（`navigate` / `flow_message_version: 3` / 7 个可选房源，`PROP-207`「Under offer」被正确排除）→ 喂一条模拟的 `nfm_reply`（含 DatePicker 毫秒串）→ 落库成 viewing #1，`陈家明 O'Brien` 和 `下午 3 点，蒲种` 原样，毫秒没丢 → 缺日期那条确认 rows 不变。
  3. **没验的，也验不了**：Flow JSON 能不能被 Meta 的 Flow Builder 接受、表单在手机上长什么样、`nfm_reply` 的真实字段名是否与文档一致。**这三件只有真机能证**，属任务 26。
  - 踩坑记一笔：探针打 payload 时 `[:1400]` 把末尾的 `mode: draft` 截掉了，一度以为是 bug。**截断输出会伪造缺字段**，下次打 payload 要么不截、要么先打 keys。

  **还缺一步（只有用户能做）**：照 [docs/whatsapp-flows.md](../docs/whatsapp-flows.md) 在 Meta 后台建 Flow、贴 JSON、拿 Flow ID 填进 `.env`。文档里写清了 screen id 和四个字段名是**代码的合同**，对不上不会报错、字段会静悄悄变空。⚠️ Flow JSON 的 `version` 是唯一我没法替用户确认的东西，Builder 报版本错就按它提示的改。
  → **2026-09-13 用户已完成**：Flow 建好、JSON 被接受、ID 已进线上 `.env`（`docker inspect` 核对过）。

  **2026-09-13 真机第一枪：表单被 Meta 拒收，而 bot 已经对客户说「表格已经发到你屏幕上了」。**
  日志 `(#139000) Blocked by Integrity`——账号层门槛，见阻塞项 B。**这一枪暴露了两个我自己的设计问题，当天补上**：

  1. **bot 当面说瞎话**。工具在表单**进队列**时就回 `FORM_SENT`（「已经在客户屏幕上」），而真正发给 Meta 在 bot 的文字回复**之后**——拒收时那句话已经说出去了。
     修法两层：`FORM_SENT` 改成「**正在发送**」（任何结局下都为真）；发送循环接住被拒的表单，`_say_instead_of_the_form` **立刻补发一条三语话术**请客户在聊天里回姓名 / 房源 / 日期，**同时写进对话历史**（否则模型下一轮还以为表单在路上、会叫客户去填），导演台照样亮 `send_failed`（兜住了，但 Meta 说不这件事本身是账号层的事实，房间里的人应该看见）。人工接管中不补发（和 `_canned` 同一条规矩）。
     只认**我们自己的**表单（按 screen id `BOOK_VIEWING` 识别）：以后餐饮的 Flow 被拒，不能回一句「请告诉我想看哪套房」。
  2. **降级路径不落库**。任务 24 当时写明「聊天里给的信息不写进后台，因为是备胎」——**Meta 一拒，备胎成了唯一的路**，这个理由不成立了。缺了它剧本 4a 最关键的那一下（大屏长出预约）演不出来。
     修法：新工具 `book_property_viewing`，和表单回填**共用同一个写库函数** `_file_viewing`。合并的时候发现表单路径**一直没检查房源存不存在**（HTTP 路由查了），一并补上——编造的 `PROP-999` 两条路都会被拒、不写库。

  **顺手修的一个任务 24 的小错**：表单回填把 `sender.key` 当电话存。BSUID 用户（隐藏号码的）会把用户名 id 写进电话列。改成读 `profile.phone`。

  **验证**：
  - 单测 **851 passed**（838 → 851，新增 13）。覆盖：`FORM_SENT` 不再声称「已在屏幕上」、被拒表单 → 补发话术 + 写进历史 + 亮 `send_failed`（端到端，模拟 Meta 当天的行为：文字能发、Flow 被拒）、别人家的 Flow 被拒不回房产话术、非表单消息被拒照旧、人工接管中不补发、聊天落库、编造房源拒绝、「这周六」这种没落地的日期拒绝、后台挂了不报成功、网页线无电话照样落库、新三语话术进了三语守卫测试。
  - **变异测试 6/6 全红**：永不兜底 / 不写历史 / 接管中照发 / 不查房源 / 兜任何 Flow / 读 key 不读电话。**第一轮有一条存活**——「读 key 不读电话」没被杀，因为测试里 profile 的 key 和电话恰好是同一个号码，改错了也看不出来。把两者改成不同值后才杀掉。另有两条一开始 SKIPPED，是变异脚本的锅：git 检出的文件是 CRLF，片段里的 `\n` 对不上。
  - **没做真库实跑**：新增的写库路径 `_file_viewing` 调的是任务 23 已经在真 MySQL 上验过的同一组函数（含 404 那条存在性检查），这次只是换了调用方。
  - **没验、只有真机能验**：补发的那条话术在手机上长什么样、客户回完之后模型会不会真的调 `book_property_viewing`。后者是模型行为，单测里是打桩的——**这是这批修复里唯一真正没被证明的一环**。
    → **2026-09-13 22:26 真机验掉了**（此时线上 `WHATSAPP_FLOW_ID` 已清空，走的是「没配 Flow」那条降级）：说「想看房」→ `offer_viewing_form` 返回 `NO_FORM`，bot 用中文请客户回三项、列出的房源正确排除了 PROP-207 → 回「陈家明 / PROP-202 / 9月20日 下午3点」→ **模型自己调了 `book_property_viewing`**（viewing #1）→ 紧接着 `crm_create_lead`（金额 620000，`activity_logged: true`）→ `/vertical-admin` 出现那条预约。**剧本 4a 的降级版在真机上完整成立**。补发三语话术那条路这次没走到（没配 Flow ID 就不会去发表单），它只在单测里端到端验过。

  **同一枪抓出一个 bug：「9月20日」被存成了 `2025-09-20`**——比今天早一年，后台和 CRM 卡片上都是。`book_property_viewing` 的入参里已经是 2025，所以是模型换算的年份错了：`llm.py` 从不告诉模型今天几号，没写年份的日期就被填成它脑子里的那一年。
  **修法照搬酒店工具的现成惯例**（`tools/local.py` 的入住日期早就有同一道闸）：日期早于今天就不写库，返回里**告诉模型今天是几号**，让它自己改正。**和酒店的一处有意不同**：酒店是叫模型回去问客人，这里是叫模型直接按「下一次到来的那个日期」重存、不去问客户——在客户面前问「您说的是哪一年」，正是会让演示看起来像填表的那种问题。当天仍可预约（「今天下午能不能去看」是最自然的请求）。
  - 测试先红后绿：先写复现「2025-09-20 被写进去」的测试，确认它因为 `book_viewing` 被调用而红，再修
  - 变异 2/2 全红：把「今天」算成过去 / 整个闸拿掉
  - 顺手给整个测试文件钉住「今天 = 2026-09-13」：里面的预约日期都写死在九月下旬，不钉的话等真实时间一过就会无人改动地变红
  - **没改表单路径**：表单是客户在日历上点的日期，不是模型换算的，这个 bug 不会从那里来
  - ⚠️ **线上那条错的数据没动**：viewing #1（`2025-09-20`）和 CRM 里挂在「Kelvin Peng」联系人下的那张 deal 都还在。删生产数据是用户的决定。另：CRM 按电话 `60168623902` 匹配到了已有联系人「Kelvin Peng」，所以卡片挂在他名下而不是「陈家明」——这是 `crm_create_lead` 写明的行为（老客户不建重复联系人），不是 bug，但用自己手机演示时卡片名字会对不上

  **2026-09-14 真机复验：年份那道闸两次都接住了，模型两次都自己改对、没去问客户**（陈家明 `2025-09-20` 被拒 → 3 秒后存成 `2026-09-20`，viewing #2；李明 `2025-09-25` 被拒 → `2026-09-25`，viewing #3）。

  **但同一枪暴露出另一个问题：模型在预约被拒的同一个回复里，已经并行调了 `crm_create_lead`。**
  - 陈家明那次，并行的 CRM 调用只带了名字，参数校验不过，**大屏上出现一条红色 `error`**，没写进任何东西
  - 李明那次，并行的 CRM 调用参数齐全、**成功了**：CRM 里建了卡，而那一刻预约并不存在。3 秒后补存成功，结局碰巧一致；补存要是也失败（房源不存在 / 后台挂了 / 日期真在过去），**CRM 里就会留下一张没有对应预约的线索卡**
  - 根因：工具返回里写了「存成功之后再建线索」，但并行调用时模型还没读到这句返回

  **修法（用户选的方案 1）：房产 bot 关掉并行工具调用。** `BotConfig` 新增 `sequential_tools`，为真时 `llm._reply_with_tools` 给 runner 传 `tool_choice={"type": "auto", "disable_parallel_tool_use": True}`——SDK（anthropic 0.125.0）的类型定义写明「model will output at most one tool use」，**是查装好的 SDK 源码确认的，不是凭印象**。只对 `realestate.json` 打开；零售仍然并行（三仓库存一起查，速度值得）。
  - 没选「预约工具里顺手建 CRM 卡」：保证更强，但房产和 CRM 耦合、CRM「可能已落地/失败」的歧义要塞进预约工具的返回，而且导演台上两条调用会变成一条
  - 没选「只改提示词」：还是在赌模型听话，这个仓库对写记录从不这么做
  - 测试先红后绿（红的时候 SDK 收到的 `tool_choice` 是 `Omit`）；另一条守住零售不受影响。**855 passed**
  - 这三处任何一处被改回去都会有测试变红：bot JSON 去掉开关 / llm.py 不传参数 → 房产那条红；默认值误改成 True → 零售那条红。没另做变异脚本
  - **没验、只有真机能验**：关掉并行后模型是不是真的会「先存预约、读结果、再建卡」，以及每轮多一次往返后回复慢了多少

  **另一个没解决的现象（导演台）**：用户说**刷新 `/console` 之后记录反而变少**——刷新前能看到李明整段（被拒 → 建卡 → 补存），刷新后停在李明第一次调用的「运行中」，后面几条和末尾的计费事件都没了（成本 RM 0.77 → 0.66）。**只读排查到一半**：
  - 排除了后端缓冲区（200 条环形队列，只从头部淘汰，不会缺尾巴；而且同一次调用的开始/结束在同一进程里先后发出，缺「结束」只能是同一次回放的尾部没到）
  - 排除了前端去重（`seen` 只在内存里，整页刷新是空的）
  - 两层 nginx（`deploy/nginx/chatbot.acuventech.com.conf` 和 `frontend/nginx.conf`）对 `/console/stream` 都已 `proxy_buffering off`
  - **剩下的嫌疑是 Cloudflare**（推断：线上挂时返回的 `error code: 502` 是它的错误页格式）在缓冲或压缩流的尾巴。**未证实**，等用户的区分测试
  - **用户的两个区分测试（2026-09-14）**：
    1. 刷新后什么都不动、等 20 秒 → **缺的几条自己冒出来了**。时间对得上后端每 15 秒一次的 keepalive：后端下一次写出东西，才把前面憋住的那段推出去。**确认是中间某一层憋住了尾巴，数据没丢**
    2. 导演台开着不刷新、手机发一条会触发工具的消息 → **工具调用隔了十几秒才出现**。所以**不只是刷新回放的问题，演示时的实时推送本身就慢**——这是更严重的那个，导演台就是卖点
  - **修法（用户选的方案 1）**：事件流响应头从 `Cache-Control: no-cache` 改成 `no-cache, no-transform`。`no-transform` 是告诉代理「别压缩、别改写这个响应」的标准指令，而代理要压缩一个响应就得先把它攒着。测试先红后绿；原来那条把头精确钉成 `no-cache` 的老测试改成按指令集合判断。**856 passed**
  - **没选方案 2**（每推完一批事件就补写一行注释把前面挤出去）：它不管是哪一层在憋都有效，但属于绕过而不是修原因。**如果方案 1 部署后实测没好，方案 2 就是下一步**
  - ⚠️ **方案 1 管不管用只能在线上验**：本地没有 Cloudflare 这一层，单测只能证明头发出去了，证明不了代理会照做。「是 Cloudflare」本身也仍是推断
  - **部署后核实了 Cloudflare**：`curl -sI https://chatbot.acuventech.com/` 回 `Server: cloudflare` + `CF-RAY: …-KUL`，推断变事实
  - **方案 1 上线后用户实测（2026-09-14）**：**实时推送修好了**（手机发消息，导演台马上出现）；**刷新回放仍要等一会儿才补齐**。为什么「逐条推」不再卡、「一口气推一批」还卡，**没弄清楚**
  - **于是按原计划补上方案 2**：`_event_stream` 每推完一批事件，立刻补写一行 `: flush` 注释（`EventSource` 按标准忽略冒号开头的行）。不需要知道是哪一层在憋：被憋住的「最后那几个字节」现在是这行注释，不是工具调用。测试先红后绿——改之前批次推完后流就沉默，读下一帧超时。**857 passed**。**线上是否真的不用等了，还没验**

**模型改成由一个配置决定，默认 Haiku（2026-09-14，用户拍板：方案 b）**。原先 6 个 bot 的 JSON 各自写死模型（retail / realestate / food 是 `claude-opus-5`，banking / hotel / saas 是 `claude-sonnet-5`），`llm.model_for` 又是「bot 自己写了就用 bot 的」——所以 `.env` 里的 `ANTHROPIC_MODEL` **从来没生效过**。现在 6 个 bot 都去掉了 `model`，由 `ANTHROPIC_MODEL` 决定，代码默认值改成 `claude-haiku-4-5`；某个 bot 真有理由不同，仍可在自己的 JSON 里单独写。
  - **接口参数不用改**：我们没传 thinking / effort，Haiku 4.5 不接受的参数一个都没用到。价格表里本来就有 Haiku（1 / 5 美元每百万 token，已对照官方价格表）
  - **行为会变**：Opus 5 不传 thinking 时默认会思考，Haiku 4.5 不会。本周真机验过的几条——预约被拒后改对年份重存、存成功后才建 CRM 卡、中英马混说——**都是在 Opus 5 上验的，换 Haiku 后要重验**
  - ⚠️ **部署陷阱**：`.env.example` 原来写的是 `ANTHROPIC_MODEL=claude-sonnet-5`。线上 `backend/.env` 如果是照它抄的，**部署后所有 bot 会变成 Sonnet 而不是 Haiku**（环境变量优先于代码默认值）。已把 `.env.example` 改成 Haiku 并写明这个坑；线上那份要用户自己查
  - 测试先红后绿（banking 写死了模型 / 默认值还是 Sonnet）。**859 passed**

- [x] **任务 25：food 后端 + 点餐流程**——**2026-09-14 代码侧完成**。后端 **910 passed**（880 → 910，净增 30），前端 `tsc -b` + `vite build` + `oxlint` 全过。**真机点餐那一枪属任务 26**（剧本 4b + 3 连演）。
  文件：`backend/app/verticals/food/{__init__,models,routes}.py`（新增）、`backend/app/tools/food.py`（新增）、`backend/app/bots/data/food.json`、`backend/app/tools/{local,registry}.py`、`backend/app/main.py`、`backend/tests/test_food_ordering.py`（新增）、`backend/tests/{test_llm,test_refusal,test_whatsapp_webhook}.py`、`frontend/src/pages/FoodAdmin.tsx`（新增）、`frontend/src/pages/VerticalAdmin.{tsx,css}`、`frontend/src/{api,main}.ts(x)`
  目标：菜单 → 加购物车 → 下单 → 查配送状态，工具驱动
  验收：真机走完一遍点餐，后台能看到订单和状态流转

  **状态流转是「下单时写死的时间线」，不是一个定时器去改 status 列。** 订单行里存 `placed_at / preparing_at / ready_at / delivered_at` 四个时刻，状态是谁来问就按当前时间读出来。剧本 3 的推送「已出餐，骑手 10 分钟」**排期正好是 `ready_at`**，而推送在回复发完才开始计时，所以手机响的那一刻后台**必然**已经是「配送中」。定时器改列的方案有两个钟要对齐，重启或数据库那一秒挂了，客户就会读到「在路上」而后台还写「制作中」。时刻在下单时定死，事后改 `PUSH_DELAY_SECONDS` 不会改写旧订单。
  - 时间线：已接单 → 制作中（`min(10 秒, 出餐时长/2)`，彩排调成 4 秒也四段有序）→ 配送中（= `PUSH_DELAY_SECONDS`，默认 30 秒）→ 已送达（再 10 分钟）
  - 人工接管中推送照旧被 `notify` 吞掉，但状态照样流转——厨房不管聊天那头是谁
  - 网页线没有推送：订单照下，工具返回里明确叫模型**不要**承诺「出餐会通知您」

  **三个工具，food bot 开了 `sequential_tools`**：
  - `food_update_cart(items)`——**设的是总数量不是增量**，重试或模型重复一次不会把 2 份变 4 份；0 = 删掉；有一个菜不在菜单上就**整批不改**
  - `food_place_order(delivery_address, customer_name="")`——空购物车 / 没地址 / 数据库挂了一律不下单，挂了时购物车保留、明说没下成
  - `food_order_status()`——**只查本对话客户的**（按 `customer.key_id`，模型没法指定别人）
  - 开串行的理由同房产：改购物车和下单是有依赖的两次写入；购物车一次调用就能放多个菜，并行没有收益

  **购物车放客户档案（Redis 那一格），订单进 verticals MySQL**。购物车是「说到一半的话」，和酒店预订、SaaS 工单同一个存法（给 `local.py` 加了一个公开的 `records()`）；而且那一格会作为 notes 进提示词，模型下一轮自己看得见购物车。订单**一条 INSERT 带全部菜品快照**（`order_lines JSON`），不会出现「订单进去了、菜没进去」的空账单。下单后购物车清空、地址记在档案里，下次不用再问。
  **价格只从菜单来**：购物车只存数量，下单那一刻按 `food.json` 重新计价，金额全程 `Decimal`（float 算 2×12.90+4.50 是 30.299999…）。菜单不建表——它就是模型报价读的那份 JSON，再抄一份就是给「bot 报的价和后台对不上」留位置。

  **偏离 / 顺手改的**：
  - `food.json`：菜品加了 `item_id`（F01–F12）；**配送费从「RM 3-8 按距离」改成固定 RM 5**——按距离收费时工具算不出总价，「报总价」这一步就没法诚实；**送达时间从「30-45 分钟」改成「15 分钟内」**，否则 FAQ 和工具按时间线给的「约 10 分钟」自相矛盾。都是演示用的业务设定，你要是想换数字，改 JSON 即可
  - 人设整段重写：原来写的是「你没有订单系统、查不了订单、订单要同事确认」，现在正好反过来。另外写明「椰浆饭 = Nasi Lemak Special、拉茶 = Teh Tarik」、「改已下的单 / 特殊配送要求 / 菜单外的加料 → `request_human_help`」——**后者就是剧本 3「放门口 + 加辣椒酱」要走的那条路**
  - **没做菜单工具**：菜单本来就在提示词里（和房产的房源同一个做法），多一次工具调用只是给导演台凑一条 span
  - 列名用 `order_lines` 不用 `lines`：`LINES` 是 MySQL 保留字（`LOAD DATA ... LINES TERMINATED BY`），写代码时自己想到的，真库上验过建表通过
  - `test_refusal.py` 有一条老测试把 `food` 当「没有工具的 bot」，前提被本任务推翻，改成 `banking`；food 那条 refusal eval 用例的类别从「看不到订单」改成「档案里没有这单」（评测号码没下过单，工具会回 NO_ORDERS，判据词不变）
  - 后台页 `/food-admin`（和 `/vertical-admin` 并列，同一个 token、同一套样式；`TokenGate` 从房产页导出并加了标题参数）。每行显示接单 / 出餐 / 送达三个时刻，让屋里的人看得出厨房不是有人在按按钮

  **验证（验了什么 / 怎么验 / 没验什么）**：
  1. **单测 910 passed / 8 skipped**（skip 都是历史的）。新增 30 条：剧本 4b 的总价 RM 35.30、数量幂等、菜单外整批不改、非法数量（-1 / 21 / True / 2.5）、订单挂在对话客户名下、下单清空购物车 + 记地址、价格按下单那一刻的菜单、空购物车 / 无地址 / 库挂了不下单且购物车保留、**推送延迟 == ready_at − placed_at**、**`ready_at` 那一毫秒起就是配送中、前一毫秒是制作中**、网页线不承诺消息、四段状态、短延迟彩排仍有序、查单只查自己、后台接口 503 / 只认 header token。推送文案加进了三语守卫测试；food bot 串行工具加进 `test_llm`
  2. **变异测试 18/18 全红**，第一轮就没有漏网：推送延迟≠出餐时刻 / 数量改累加 / 去掉菜单校验 / 去掉数量上下限 / 不清空购物车 / 不要地址 / 空车下单 / 网页线也承诺消息 / 客户 key 取名字 / 吞掉库挂了 / 查单不按客户过滤 / `>=` 改 `>` / 彩排时制作中晚于出餐 / 金额走 float / 路由 503 变 500 / 路由去掉 token / JSON 去掉 `sequential_tools` / 价格不按下单时菜单
  3. **真 MySQL 活体验证**（本地 `mysql:8` + `python:3.13-slim` 挂代码，不是打桩）：建表（含 `JSON` 列）通过；在真正的 turn 里调三个工具下单；`陈家明 O'Brien` 和 `蒲种 Jalan Puteri 5/1, No. 12` 原样读回；`DECIMAL` 精确到 35.30；毫秒没丢；容器按吉隆坡时间打戳；**每 2 秒轮询一次 HTTP 接口，状态依次是 received → received → preparing → on_the_way → on_the_way**；推送排期 = 出餐时刻；另一个号码查不到这单；不带 token 401；探针表已删
  4. **浏览器实看**（Chrome，vite dev + 真库后端）：页面开着时从容器里下一单，**5 秒内新单自己出现在最上面、黄色「制作中」**；过了出餐时刻，**不刷新、自己变成蓝色「配送中」**
  - **没验、只有真机能验（任务 26）**：
    - **模型会不会真的按这个流程调工具**——「两份椰浆饭一杯拉茶」能不能一次调用放进购物车、会不会先报总价等确认再下单、没地址时会不会和总价一起问。**全部是模型行为，单测里是打桩的**。而且本周刚改成默认 Haiku，这比 Opus 更值得在真机上看一眼
    - 剧本 3 那句「放门口 + 加辣椒酱」模型会不会调 `request_human_help`（人设里写了，但这类假设本周被证伪过）
    - 推送在手机上的样子（机制是任务 19 验过的同一条路）
  - **已知但没处理的边角**：没下单的购物车跟着客户档案活 7 天，用自己手机彩排剩下的半车菜，下次演示时模型会在 notes 里看见。下单就会清空，只有「加了没下」才会残留；真碰上了说一句「清空购物车」即可。另：任务 19.1 的收尾总结不认识餐饮订单（房产预约它也不认识），这场演示的总结里不会出现 FD- 单号——没加，那是 19.1 的清单，不在本任务范围

- [x] **任务 26：批次 04 真机验收**（用户任务）
  ✅ **2026-09-16 真机验收通过**：剧本 4a 聊天降级版（清单第八段，Flow 仍被 #139000 拦着）换 Haiku 后重验通过；剧本 4b + 3 连演 9 步 **09-14 已真机通过**（修 44b367f 后重演）。依据是用户口头确认「都验证完」，没有逐步明细和截图
  验收：剧本 4a 走通（表单不跳出 App，房产后台 + CRM 看板都出现记录）；**剧本 4b + 剧本 3 连演 9 步走通**——点餐 → 主动推送「已出餐」→ 客户提超纲要求 → 转人工 → 导演台回复 → 暗号接管回来

  **2026-09-14 Claude 开演前预检（只读，没替你演）**：
  - ✅ 任务 25 的点餐代码已在线上：部署 run `34815913001` 绿；外网打 `/api/verticals/food/orders` 回 **401**（没这段代码会是 404），`/console/tools` 401、webhook 错 token 403 → 后端活着、鉴权链路正常
  - ❌ **没查到 VPS 上的 `.env`**：SSH 只读检查被权限分类器以「读生产」拦下，按规则没换花样重试。所以下面两件**要你自己看一眼**：
    1. `ANTHROPIC_MODEL` 是不是 Haiku（`.env.example` 旧值是 Sonnet，见上面「部署陷阱」）——`sed -n "s/^ANTHROPIC_MODEL=//p" /opt/ai_chatbot/backend/.env`
    2. `PUSH_DELAY_SECONDS` 是否是你想要的（默认 30 秒 = 剧本 3 那声「叮」）
    → **2026-09-14 用户核对**：`ANTHROPIC_MODEL` 是 Haiku；`PUSH_DELAY_SECONDS` 未配置 → 走代码默认 30 秒（`config.py`），与剧本 3 一致，不需要改
  - 剧本 4a **只能演降级版**：Flow 仍被 #139000 拦着（阻塞项 B），线上 `WHATSAPP_FLOW_ID` 09-13 已清空。降级版 09-13/14 已真机成立过，这次要重验的是**换 Haiku 之后**模型还会不会自己调 `book_property_viewing` → `crm_create_lead`（串行）、年份错了会不会自己改
  - 验收里的「暗号接管回来」**实际是导演台上的「交回 bot」按钮**（任务 20 偏离 2），不要去找暗号词

  **照演清单**（手机 = 客户，笔记本开 `/console`，另开 `/food-admin` 和 `/vertical-admin`）：
  - 4a（房产）：说「想约看房」→ bot 在聊天里要姓名 / 房源 / 日期 → 回「陈家明 / PROP-202 / 下周六下午3点」→ 看：`/vertical-admin` 出预约、日期是 2026 年、CRM 看板出卡、导演台里预约在建卡**之前**
  - 4b + 3（餐饮，发 `menu` 切到 food）：
    1. 「两份椰浆饭一杯拉茶」→ 看是否**一次** `food_update_cart` 放进去
    2. bot 报总价 RM 35.30 并问地址（没问地址要记下来）
    3. 给地址、确认 → `food_place_order`，`/food-admin` 出新单、黄色「制作中」
    4. 等约 30 秒，手机「叮」：已出餐、骑手约 10 分钟（**客户没问**）；同一时刻后台已变蓝色「配送中」
    5. 客户：「能让骑手放门口吗？想加一份辣椒酱，我补钱」
    6. bot 说帮你转同事 → 导演台看是否调了 `request_human_help`（不是关键词兜底）、横幅「人工接管中」
    7. 客户再发一句 → bot **一个字不回**
    8. 在导演台输入框打字回复 → 手机收到，无任何机器人标记
    9. 点「交回 bot」→ 手机收不到任何提示；客户再问「我的单到哪了」→ bot 接回并调 `food_order_status`
  - 彩排后说一句「清空购物车」，免得半车菜留到正式演示（见任务 25 边角）

  **2026-09-14 17:56 真机第一枪（4b + 3，Haiku）**：
  - ✅ 1-4 步全对：「order 2 lasi lamak and 1 teh tarik」（拼错也认得）→ 报 RM 35.30 并问地址 → 复述地址等确认 → 「yes」才下单 FD-00001 → 约 1 分钟内（5:57 → 5:58）收到三语「已出餐」推送
  - ✅ 7-9 步：接管中 bot 没抢话，导演台打的「你好」「我会直接发出辣椒酱，免费的」到了手机，交回后「我的单到哪了」→ bot 用中文答「在骑手手上，大概 8 分钟」
  - ❌ **第 5-6 步：客户说完「放门口 + 加辣椒酱」，手机什么都没收到**，没有「帮您转接同事」
    - **根因是代码，不是模型**：`request_human_help` → `handover.begin()` 当场把标志存进 Redis（`handover.py:97`）；模型写完回复后，路由的「中途有人接管」检查（`whatsapp_webhook.py`，任务 20 冷审加的）重读 Redis 看见标志，**把 bot 自己这一轮的转接话术当成抢话丢掉了**。关键词「找真人」那条路直接发固定话术、不过这个检查，所以任务 21 验收时没暴露
    - **修法**：只有「Redis 里接管中、但本轮手上的 profile 不是」才丢——工具改的正是路由手上那个对象（`local.serving(bot, customer)`），所以这个区分是确定的，不靠时间差
    - 测试先红后绿（`test_the_bot_handing_over_itself_still_tells_the_customer`）；原来两条中途接管测试（丢回复 / 不擦掉并发消息）照旧绿。全套 **909 passed / 10 skipped**（3 条导演台 nginx 配置测试因容器只挂了 `backend/` 而 skip，7 条真模型评测 skip）
    - ⚠️ **已知边角，没处理**：bot 自己转人工后、这一轮存盘前（模型写那一句话的一两秒里）如果客户又发来一条，那条经静默路径写进 Redis，随后会被本轮存盘覆盖。窗口很小，而且客户那时还没收到转接话术，不太会接着打字
    - **没验**：模型是不是真的调了 `request_human_help`（而不是没调、直接沉默）——人工回复能发到手机，说明接管确实开始了；这句话不命中关键词（否则会直接回固定话术），除非有人恰好在那几秒里手动点了接管，否则只能是工具发起的。**是推断**；日志没看（SSH 读生产被拦）。**修复部署后需要真机重演第 5-6 步**
    → **后来验掉了**：导演台截图里 17:58:47 就是 `request_human_help`（原因「rider leave at door + chilli sauce」），推断变事实；修复（44b367f）部署后用户重演第 5-6 步，**手机收到了转接话术**

  **状态（2026-09-14）**：**剧本 4b + 剧本 3 的 9 步已通过**（第 5-6 步是修复后重演通过的）。**剧本 4a 还没演**——用户决定等任务 27 做完再走，所以本任务仍是 `[ ]`，4a 通过后再勾

---

## 批次 05：成品

> 前面五批做的是「能演」，这一批做的是「好看」和「不用你在场也能演」。

- [x] **任务 27：导演台 v2**——**2026-09-14 完成（代码侧 + 本地浏览器端到端；真机投屏那一半没做）**
  文件：`frontend/src/pages/Console.tsx`、样式
  目标：深色控制台美学；工具调用瀑布流、ERP 数据变化 diff、耗时柱、本次会话 token 消耗
  验收：投屏到大屏上看着专业，手机端发消息时信息密度和可读性都在
  **2026-09-14 用户看了真机那一场的导演台后拍板（开工前必读）**：
  - 问题：上面是另一段旧对话（零售 bot 被问看房）、下面是点餐的实时调用，两段对不上；满屏函数名 / 原始 JSON / `76000 ms`；**`request_human_help` 的返回把给模型的指令原文投到了屏上**
  - **已定：默认显示业务卡片**（「放进购物车：椰浆饭 ×2 · 拉茶 ×1 · RM 35.30」「主动通知客户：已出餐（客户没问）」「转给同事：原因…」），**技术参数走开关**（函数名、入参、耗时）。给模型的指令文本两种模式都不显示
  - 只显示当前这段对话，时间统一吉隆坡 `HH:MM:SS`，耗时写秒，接管写「1 分 16 秒」
  - **已定：布局 B**——左边镜像客户手机，右边上半「系统在做什么」业务卡片、下半钉住后台数据变化（餐饮是订单状态流转；房产 / 零售各有各的表）。参考图（A、B 都画了，按 B 做）：https://claude.ai/code/artifact/29673436-e907-4808-a12d-3364716c112a

  **做了什么**（纯前端，后端零改动）：
  - `frontend/src/consoleCards.ts`（新）：工具调用 → 业务卡片的纯函数。**铁律：JSON 输出才算结果；非 JSON 输出（拒绝 / 后台挂了，status 却是 ok）一律只写「没办成」，原文不上屏**。`request_human_help` 只显示 `input.reason`，两句给模型的指令都不显示；技术模式也只露函数名 / 入参 / 耗时，**不露任何输出**。时间统一吉隆坡 `HH:MM:SS`（审计库是 +08:00 naive 字符串，事件是 epoch，两边都换算）
  - `frontend/src/components/BackOffice.tsx`（新）：右下钉住的后台面板。餐饮读 `/api/verticals/food/orders`，按 `customer_key` + 对话开始时间过滤，画「已接单 → 制作中 → 配送中 → 已送达」四段带时间；房产读 viewings（按手机号后 9 位）；零售 / 酒店 / SaaS 没有后台接口，列工具调用写进去的东西（ERP 客户 / 销售单 / 电子发票 / 退货单、CRM 商机、订房、工单），标「新增」
  - `Console.tsx` 重写渲染层：左镜像客户手机（审计库消息，每 3 秒读 + 该客户有事件时 1.5 秒后补读）、右上卡片、右下后台。顶栏：客户名 / 渠道 / 行业 / bot 状态 / 本场 RM + token 入出 + 调用次数 / 技术模式开关 / 人工接管·交回 / 对照组开关 / 发总结。SSE、重连、去重、接管、开关逻辑原样保留
  - **只显示一段对话**：默认「跟随最新」（谁最近说话显示谁的最新对话）；从客户列表点开则固定。实时事件只有 `key_id` 没有 `conversation_id`，所以**只有当这段是该客户最新的对话、且事件晚于对话第一条消息**才挂上来——09-14 那种「旧零售对话 + 新点餐调用」拼在一起的情况被这条挡住
  - 模型发起的转人工：`request_human_help` 和随后的 `handover` span 合成一张卡（「原因… · 人工处理 36 秒 后交回」）；导演台手动接管单独一张
  - 客户列表默认收起（投屏），状态记 localStorage；「全部 · 实时流」改名「跟随最新对话」。**偏离**：原来的「所有人调用混在一起」视图没了——按拍板「只显示当前这段对话」取消；其他人若在人工接管中，顶部红条常驻可点过去（任务 20 冷审那条保护没丢）
  - 删了 `components/Transcript.tsx` 及其 CSS（改版后无引用）

  **验证到什么程度**：
  - `npm run build`（tsc + vite）过；`npm run lint`（oxlint）0 警告
  - 卡片映射 10 组断言（node 直接跑 TS，**时区设成 America/New_York 跑**，证明吉隆坡时间不依赖笔记本时区）：真实输出形状、指令文本 25 字滑窗查泄漏、push「客户没问」/ 演示总结区分、接管 1 分 16 秒、KL 时钟。**变异验证**：把 `request_human_help` 的输出拼进卡片 → 断言变红，还原后转绿。脚本在 job tmp，没进仓库（前端没有测试框架，不为这个引入）
  - **本地整链浏览器验证**（docker compose 起 mysql/redis/backend + vite dev + Chrome，真 Claude 调用，WhatsApp 凭据故意置空）：网页渠道点餐 → 两张卡「放进购物车 Nasi Lemak Special ×2 · Teh Tarik ×1 · 合计 RM 35.30」「下单 FD-00001」→ 后台面板自己走到「配送中」带三个时间 → 模型**自己调了** `request_human_help`，卡片只显示原因、顶栏变红、出现回复框 → 导演台回复（因凭据为空发送失败）→ 红色「同事的回复没送达」卡，手机侧**没有**假气泡 → 交回 → 「人工处理 36 秒 后交回」。手动接管 / 回复 / 交回再走一遍也对。技术模式露函数名、秒数、耗时柱、入参
  - 两次 Chrome 截图超时（「renderer frozen」）：查了后端日志，冻住的页面**仍按设计节奏在轮询**（20 秒内 3 秒 / 5 秒 / 10 秒三档请求数都对），说明页面 JS 没死循环，是截图扩展那侧的问题；换新标签页原步骤重做未复现

  **没验**：
  - ❌ **投屏大屏观感、真 WhatsApp 手机同步**——要用户拿手机，建议跟任务 26 剧本 4a 一起演
  - ❌ 主动推送「已出餐」卡片、语音 / 图片卡片：网页渠道不发推送、不收媒体，只有单元断言覆盖
  - ❌ 窄屏（<900px 上下堆叠）：Chrome 窗口改尺寸没生效，CSS 写了但没看到
  - ❌ 零售 / 房产 / 酒店 / SaaS 的卡片只有断言，没真跑过对话
  **2026-09-14 追加（用户要求）**：
  - **浅色 / 深色背景随时切换**：顶栏按钮「Light background / Dark background」，选择记在 localStorage（`console_theme_light`），默认仍是深色。`Console.css` 里写死的深色值全部改成变量，`.console[data-theme='light']` 覆盖一套浅色；客户列表那一栏跟着 `--con-*` 变量走
  - **导演台界面改英文**：`Console.tsx`、`consoleCards.ts`、`BackOffice.tsx`、`CustomerList.tsx` 全部文案英文化（卡片、时间格式 `1 min 16 s` / `0.004 s`、后台面板、客户列表）。**范围只到 `/console`**：`/food-admin`、`/vertical-admin` 两个后台页和网页聊天的三语词条没动
  - 验证：build + oxlint 过；10 组卡片断言改英文后仍全绿（纽约时区跑）；本地整链 + 浏览器里用 JS 读计算样式——切换前后背景 `#0b0f14 ↔ #f5f7fa`、卡片、客户气泡、标题字色、红色接管状态都跟着变，刷新后记住选择；页面文字抓取确认顶栏 / 卡片 / 手机栏无中文界面文案。**没看到截图**：Chrome 截图一直超时（扩展侧问题），浅色观感没人眼看过
  **2026-09-15 用户拍板：跟随模式切 bot 后跳到空对话，保持现状（不再讨论）**。客户发 `menu` 选新 bot 会开一段新对话，「Following latest」随即只显示那段（可能只有一句开场白），上一段要从 Customers 列表点开看。当时提过的三个改法（折叠显示同一客户之前的对话 / 跳过只有开场白的对话 / 保持现状），选了保持现状。另两处小改已上线：气泡宽度跟文字走（`10b2fa0`）；手机栏把 `**加粗**` 和 WhatsApp 的 `*加粗*` 显示成加粗（`90e89b8`，规则同 WhatsApp：星号内侧不能是空格、不跨行）

  **2026-09-14 再追加（用户要求）：三栏可调宽度**
  - 客户列表 | 客户手机 | 系统之间各一条分隔条：拖动调宽、双击恢复默认、聚焦后 ←/→ 每次 20px；宽度记 localStorage（`console_list_width` / `console_phone_width`）。客户列表 200–560（默认 320），手机 260–900（默认 380），系统栏吃剩下的且不低于 360px；窄屏（<900px 上下堆叠）不显示分隔条
  - 验证：build + oxlint 过；本地浏览器用 JS 量宽度——默认 320/380/1860（2560 宽窗口）；拖动手机 +200 → 580、列表 −80 → 240；拖过头停在 200 和 900；双击回 380；→ 键 +20；刷新后宽度保留。**拖动是用派发 PointerEvent 测的**：Chrome 扩展的拖拽工具只发 pointermove 不发按下/抬起，真人鼠标拖没测到
  - 顺带查清之前的「renderer frozen / 截图超时」：页面 `visibilityState` 是 `hidden`（Chrome 窗口在后台），截图拿不到、定时器被节流——**不是代码卡死**
  - 窗口缩放时上限只在下次渲染时重算（任何轮询都会触发，最多几秒），没专门监听 resize
  - 已知边角：菜名是英文（菜单只有英文名，中文只在提示词里），没加翻译表；`push` / `handover` / 语音事件不进审计库，后端重启或 200 条缓冲滚掉后这些卡片会从历史里消失（消息气泡还在）

- [x] **任务 27.1：故障演练开关**——**2026-09-15 完成（代码 + 本地真模型端到端；真 WhatsApp 手机没演）**
  文件：`frontend/src/pages/Console.tsx`、`backend/app/tools/`（注入失败）
  目标：导演台上一个开关，故意让下一次 ERP 调用失败。展示 bot **不崩、不编**，说「系统暂时查不到，帮您转同事」，然后走人工接管
  **「坏了怎么办」是老板一定会想、但未必会问出口的问题。** 主动演一遍比等他问更有力。做成开关而不是真断网，风险可控——演示时你完全掌握它什么时候坏
  验收：拨开关后下一次调用失败，客户侧收到得体的说明而不是报错或胡编，接管流程正常走完

  **怎么演**：导演台顶栏「Break next ERP call (drill)」→ 变红「Drill armed · call off」→ 客户在 **retail** 问任何要查 ERP 的事（有货吗 / 我的单到哪了）→ bot 转同事、顶栏变「Human has it」→ 导演台回复 → 「Hand back to bot」→ 再问同一句，ERP 正常答。**只有 retail 用 ERP**，其他行业拨了不会触发（会一直挂着等下一次 ERP 调用，记得「call off」）

  **做了什么**：
  - **注入点在 `ErpClient._request`，不在工具里**（`services/erp_client.py`）：一次性标志，触发时在建连之前抛 `ApiClientError(may_have_landed=False)`，然后自动解除（加锁，并发两个对话不会都算「下一次」）。所以每个 ERP 工具走的都是**自己真实的断网分支**——演示的就是真断网时会发生的事，不是排练版。写操作也因此报「没下成」而不是「在核实中」。进程内全局、不落盘（同对照组开关：重启后 ERP 是好的）
  - `GET/POST /console/fault-drill`（写要 header token）；`fault_drill` 事件：`armed` / `disarmed`（操作员拨）、`fired`（带客户 key，落在那段对话里）；nginx + vite 登记新路由（`test_console_routing` 守着）
  - **偏离 / 顺带改的两句提示词**（不改的话验收做不到）：
    1. `erp.UNAVAILABLE` 原来只说「查不了」，模型不会转人工。改成「别猜、别重试，调 `request_human_help`，回复里说系统暂时查不到 + 同事接手」。**这是生产行为变化**：真实 ERP 挂掉时 retail bot 现在也会自动转人工（这正是演练要证明的事，所以两者必须一致）
    2. `human.HANDED_OVER` 加一句「如果是因为系统查不到，那句话里说出来」。第一版只改 1 时，Haiku 3 次里 0 次说原因——它听后来那条「一句话说转同事」的
  - 前端：顶栏按钮（沿用对照组开关的红色 `data-off` 样式）+ 卡片流里 `⏻ Failure drill…` 提示行，技术模式显示 `fault_drill`
  - **顺带修的前端 bug**（`consoleCards.ts`）：工具非 JSON 输出一律套用该工具的「没找到」文案，所以断网在屏上显示成 **「Search products · No such product」**——等于屏幕替 bot 编了一句「没这个货」。现在识别三个后台共用的 `could not be reached` 措辞，显示「System unreachable -- nothing looked up, nothing made up」。这个 bug 任务 27 起就在，演练才让它露出来

  **验证到什么程度**：
  - pytest 新增 `tests/test_fault_drill.py` 8 条，先红（8 errors）后绿；全套 **920 passed / 7 skipped**（7 = 真模型评测；这次挂了整个 worktree，nginx 配置那 3 条也跑了）。**变异验证**：把 `_request` 里的触发改成 `if False` → 3 条变红
  - `npm run build` + oxlint 0 警告
  - **本地真模型端到端**（docker compose 起 backend/mysql/redis，网页渠道，WhatsApp 凭据故意置空，ERP/CRM 是真的）：
    - Sonnet 一次 + **Haiku（与线上一致）6 次**，中 / 英 / 马来语各 2：**6/6 首个 ERP 调用失败（`erp_search_sku` 或 `erp_find_customer`）→ 模型自己调 `request_human_help` → 接管中 → 开关自动复位**；**0 次编造**
    - **说出原因 4/6**：「Our system is down at the moment, but a colleague will take it from here.」「系统暂时无法连接，我正在转接一位同事为您处理。」「Sistem tidak dapat dicapai sekarang…」；**另 2 次只说「A colleague will take it from here.」**——得体、不编，但没解释。是模型遵从度的方差，没再加码提示词
    - 接管 → 导演台回复（凭据为空发送失败，红卡，符合预期）→ 交回 → 同一问题 ERP 正常返回 337 件、RM 328.90，证明只坏一次
    - Chrome 里点按钮：文字变「Drill armed · call off」、红框、后端 `armed:true`；发消息后按钮自己复位；卡片依次为演练提示 → 「System unreachable」→ 转人工卡（带模型写的原因）；页面文字里没有给模型的指令原文。**没看截图**，只读了 DOM
  - 中文第一次测试回了阿拉伯语：是 Git Bash 把 curl 参数里的中文按系统代码页转坏了（模型收到的是乱码），改用 `\u` 转义后正常。不是代码问题

  **没验 / 已知边角**：
  - ❌ **真 WhatsApp 手机**没演——建议并进任务 26 剧本 4a 那次一起走（retail 发 `menu` 切过去）
  - ⚠️ **网页渠道根本不执行接管静默**：接管中网页客户再发一句，bot 照答（`routers/chat.py` 没有 handover 检查，只有 WhatsApp webhook 有）。这次演练本地跑时撞见的，**不是本任务引入的**，没修。演示走 WhatsApp 不受影响
  - 转人工卡片标题是「Bot judged it out of scope and handed to a colleague」，断网场景下不太贴切（任务 27 的文案），没改
  - 演练对所有人生效：同一时刻别人的对话先调到 ERP，坏的是别人那条。演示现场一般只有一个客户在聊

- [x] **任务 28：网页聊天线视觉重做**——**2026-09-15 完成（本地真后端 + 真模型，桌面和手机尺寸都截图看过；线上没验）**
  文件：`frontend/src/App.css`、`frontend/src/pages/*.tsx`
  目标：明亮、亲和、类 WhatsApp 的气质，留给不方便加号的客户。三语 i18n 保留
  验收：手机和桌面尺寸都正常；三语切换正常

  **做了什么**（纯前端，后端零改动，**没加新文案**，三语词条原样）：
  - **范围只到网页聊天的三页**（输手机号 / 选场景 / 聊天）。配色是 `.app-shell` 上的一组 `--wa-*` 变量，**固定浅色**（`color-scheme: light`）——`index.css` 同时管着导演台和两个后台页，没动它；系统深色模式也不会把客户的聊天翻成不像 WhatsApp 的样子。`App.css` 里导演台客户列表那一段逐字节没变（脚本比对过）
  - 聊天页：米色墙纸 + 淡点阵、出站浅绿 / 入站白色气泡带小尾巴（同一方连发的第二条去掉尾巴、贴近）、绿色头部 + 圆形头像、白底绿字的快捷问题、圆形发送按钮（纸飞机图标，`aria-label` 走三语 `send`）
  - **聊天页固定为视口高度**：只有消息区滚动，输入栏一直在底部（原来 `#root` 是 `min-height`，长对话会把输入栏顶出屏幕）；输入框 16px 字号，iOS 聚焦不缩放；底部留 `safe-area-inset-bottom`
  - **加粗**：复用导演台的 `boldRuns`（`consoleCards.ts`），模型写的 `**RM 328.90**` 在网页上也是粗体，和手机上一致——原来网页直接露星号
  - 语言切换从浮在右上角（压着聊天头部，靠 `padding-top: 56px` 躲）改进顶栏，顶栏左边用上了一直没用的 `appTitle` 词条。**手机宽度的聊天页隐藏标题**，只留切换器一行——第一版两行叠起来占了 ~95px
  - 选场景：卡片带浅绿圆形图标；手机宽度改成左图右文的列表（像 WhatsApp 聊天列表），为此 `BotSelect.tsx` 给名称和描述包了一层
  - 输手机号：白卡片 + 图标 + 绿色胶囊按钮

  **验证到什么程度**：
  - `npm run build`（tsc + vite）过；oxlint 0 警告；其他页面 className 查过无撞名
  - **本地整链**（docker compose 起 backend/mysql/redis，WhatsApp 凭据置空，真 Haiku、真 ERP）+ **playwright-core 驱动本机 Chrome 无头模式**，桌面 1366×800 和手机 390×844（isMobile、2x）各走一遍：输号 → 选场景 → 中文 / 马来 / 英文切换 → 进零售 → 发一句 → 等真回复。每一步截图并人眼看过
  - 量出来的：两个尺寸都**无横向溢出**；聊天页**页面本身不滚动、输入栏在屏内**（问候时和回复后各量一次）；回复里 `<strong>` 2–4 个、**残留 `**` 为 0**；三语切换后标题 / 高亮 / 聊天输入框占位符 / 发送按钮标签都跟着变。手机上的选场景页会滚动（6 张卡片一列），是预期
  - 用脚本不用 Chrome 扩展截图的原因：扩展那边窗口在后台（`visibilityState: hidden`），截图照旧超时

  **没验**：
  - ❌ 线上（部署后没开 `chatbot.acuventech.com` 看）、**真手机浏览器**（iOS Safari 的地址栏伸缩 / 键盘弹出时输入栏位置，无头 Chrome 模拟不出来）
  - ❌ 发送失败的「重试」样式、「重新开始」确认框：样式写了，没触发过。快捷问题按钮只在问候截图里看过长相（白底绿字、换行正常），没点过——点击走的是原来的 `doSend`，逻辑没改
  - 已知边角：同一方连发去尾巴靠相邻兄弟选择器，中间隔着快捷问题 / 打字气泡时仍各带尾巴；网页不显示消息时间（历史消息本来就没有时间字段，没为新消息单独加）

- [x] **任务 29：自动演示模式**——**2026-09-15 完成（本地真模型端到端 + 导演台里真点按钮；线上没按过）**
  文件：`frontend/src/pages/Console.tsx` 或独立页、`backend/app/routers/console.py`
  目标：点播放键，bot 自己走完**剧本 1（旗舰戏七步）**。**工具调用是真的**，只有用户那几句是脚本喂的
  为什么是剧本 1：排除法——剧本 2a 要真人拍照和说话、2b 要客户掏出自己的文件，都脚本喂不了；剧本 3 依赖主动推送的时序和真人打字，自动化很别扭；剧本 4a 的原生表单必须真人点提交。只有剧本 1 能纯脚本驱动，而且道具最齐（ERP 订单 + CRM 看板同时长东西）
  验收：点一下，八步自动演完，中途不需要人操作，两块后台都能看到新数据

  **2026-09-15 用户拍板：零售 bot 单独改用 Sonnet 5**（其余五个仍走 `ANTHROPIC_MODEL`，线上是 Haiku）。`retail.json` 加回 `"model": "claude-sonnet-5"`（和 09-14 之前同一个位置）；`test_no_bot_hard_codes_a_model…` 改成 `test_only_retail_names_a_model…`——白名单只有 retail，下一个要单独指定模型的 bot 必须改这张表并写明理由。先红后绿，全套 **930 passed / 7 skipped**
  - **影响不止自动演示**：WhatsApp 上的零售对话也换成 Sonnet 5，按 token 是 Haiku 的 **2 倍**（`console/cost.py`：Sonnet 5 = 2 / 10、Haiku 4.5 = 1 / 5 美元每百万 token）；本次三次整场实测每场 RM 0.29–0.30
  - ⚠️ **更正 + 顺带发现**：拍板前记录里「Haiku 那次 RM 0.81」**算错了**——本地 `.env` 写的是带日期的 `claude-haiku-4-5-20251001`，而 `cost._rates` 只认精确的 `claude-haiku-4-5`，查不到就按最贵的 Opus 计价（5 倍）。按 Haiku 实价那次约 RM 0.16。Haiku 输的是剧本翻车，不是钱。**线上 `ANTHROPIC_MODEL` 如果也是带日期的写法，导演台上显示的每场费用同样被放大 5 倍**——线上那份 `.env` 的确切字符串没看过（09-14 记录只写了「是 Haiku」），没改代码，待用户确认
  - **验收（线上同款配置：默认 Haiku、零售覆盖为 Sonnet）**：容器里确认 retail → `claude-sonnet-5`、其余 5 个 → Haiku；按一次播放，**10 次模型调用全是 Sonnet 5**，提示缓存从第二次起命中（`cache_read=7678`）；第 3 句一轮里下单 `SO-2026-00003` → 发票 `INV-2026-00002`（VALIDATED）→ CRM `[DEMO]` 商机，第 4、5 句自动跳过，62 秒放完，RM 0.30
  - **导演台里真点按钮**（playwright-core 驱动本机 Chrome 无头，1600×900）：按钮 `▶ Play scene 1 (autoplay)` → `Autoplay 0/5 · stop` … `4/5 · stop` → 65 秒后回到播放态；页面自动跟到这段对话（左侧客户手机逐句出现、右侧卡片、右下后台面板三条 New：ERP 销售单 `SO-2026-00004` / 电子发票 `INV-2026-00003` VALIDATED / CRM 线索）；提示条无报错。中途和结束各截图看过
  - **没验**：线上按一次（部署后没按——每按一次就在 ERP 真开一单一票）；停止按钮只有单测，没在页面上点过；两台导演台同时开的情况；零售在 WhatsApp 上换 Sonnet 后的真机表现（归任务 30 前的真机清单）
  - 结束截图顶栏还写着「Bot is replying」——是导演台原有的状态指示（按轮询节奏更新），不是自动演示引入的，没查
  - 真 ERP / CRM 里本任务一共留下：客户 53（`WA-60100000029-…`）、`SO-2026-00001`～`00004`（00001 无发票）、`INV-2026-00001`～`00003`、CRM 联系人「陈家明」名下 3 个 `[DEMO]` 商机。任务 34 的清理能删

  **（以下是拍板前的记录，保留来龙去脉）** 代码完成，验收卡在「零售 bot 用哪个模型」（分支 `worktree-task-29-autoplay`，当时未合 master、未部署）
  - **做了什么**：`backend/app/console/autoplay.py`（新）+ `GET/POST /console/autoplay` + 导演台顶栏「▶ Play scene 1 (autoplay)」（运行中显示 `Autoplay 3/5 · stop`，每 2 秒读进度，出错把原因写在提示条）。nginx + vite 登记路由
  - **偏离**：走**网页渠道**（`chat.select_bot` / `chat.send_message`，和访客浏览器同一个函数），用固定号码 `AUTOPLAY_PHONE`（默认 `60100000029`，第一次开 ERP 户，之后复用）。没走 WhatsApp：脚本「冒充」手机发话，真手机上只会收到 bot 的回复、看不到客户说了什么。代价：网页发不了 PDF（发票在 ERP 里照开）、没有主动推送
  - **客户台词 5 句**（中文 rojak）：开场问 earbuds + 2 个 + COD → 改成 3 个 → 确认下单并**一次给齐姓名 / 个人购买 / 地址**（脚本答不了意料外的追问）→「对，下单吧」→「发票也开给我」。后两句带「已办就跳过」：本次运行里该客户已有 JSON 返回的 `erp_create_sales_order` / `erp_generate_einvoice` 就不说——模型常在拿到资料那一轮就下单开票，再说「下单吧」像没在听
  - 每句之前停 6 秒（让现场读完上一条回复）；停止在下一句之前生效（正在跑的那一轮会跑完）；同时只能有一场，双击不会开两场
  - 验证：新增 `tests/test_autoplay.py` 10 条 + 路由测试；全套 **930 passed / 7 skipped**。**没先跑红**（测试和实现是先后写的，中间没跑），用变异补证：去掉跳过 / 失败的调用算已办 / 别的客户算已办 / 忽略停止 / 不开新对话，**5 处全红**。前端 build + oxlint 过
  - **本地真模型端到端（各按一次播放，写了真 ERP / CRM）**：
    - **Haiku（线上现用）❌**：5 句 58 秒自动放完、ERP 出了客户 53 和 `SO-2026-00001`，但剧本本身翻车三处——① 第 3 句那轮模型调完两个查询工具后**一个字没写**（`produced no text to send (stop_reason=end_turn)`），客户收到兜底「抱歉，我这边出了点问题」；② 下单后**没调 `crm_create_lead`**，CRM 没卡；③ 开发票时 `customer_id` 填了 **1038**（正确是 53）→ 查不到单 → 转人工。③ 的根源是结构性的：**每轮模型只看得到聊天文字，看不到上一轮工具结果**，下一轮要自己重新查，Haiku 没查而是猜。WhatsApp 线同样如此；09-12 真机那次整场通过是因为当时还是 Opus
    - **Sonnet 5 ✅**：第 3 句一轮里查到老户 53 → `SO-2026-00002` → `INV-2026-00001`（LHDN VALIDATED）→ **CRM `[DEMO] Sony WF-C710N ×3` 卡**；第 4、5 句被**自动跳过**，60 秒放完。本次 RM 0.29（Haiku 那次显示 RM 0.81 是按 Opus 误计价，见上面更正）——各只一次，不作结论
  - 这两次在真 ERP 留下：客户 53（`WA-60100000029-…`）、`SO-2026-00001`（无发票）、`SO-2026-00002` + `INV-2026-00001`；CRM 一张 `[DEMO]` 卡；本地 Haiku 那次还给 60100000029 开了一个**本地** Redis 里的人工接管（本地容器，线上不受影响）

- [x] **任务 29.1：PDPA 与数据流向说明（一页纸）**——**2026-09-15 完成：中英文两版用户已看完定稿；网页聊天已加 token 并上线**
  文件：`docs/data-flow-pdpa.md`（新增，Claude 写初稿，用户核对后定稿）
  目标：**这一条不写代码，但缺了它有些客户签不了字。** 马来西亚 PDPA，老板会问「我客人的资料存在哪、谁能看得到」。一页说明讲清楚：数据留在你们自己的 VPS、对话内容只在调用时经过 Anthropic、不用于训练、留存策略是什么
  验收：一页纸能直接发给客户，且里面每一句都和实际架构对得上——**不要写做不到的承诺**

  **做了什么**：零代码。子智能体按代码盘点全部数据落点 / 外部调用 / 访问权限（带 file:line），关键三处本人复读确认；三家服务商政策从官方页面现查（链接写在文档末尾）。文档结构：一句话 → 流向图 → 存储与留存表 → 第三方表 → 谁能看到 → 演示版限制 → 出处

  **偏离任务描述的地方（因为和架构对不上）**：
  - ❌ 「数据留在你们自己的 VPS」——实际是 Acuven 托管的共享 VPS，且数据还会写进 ERP / CRM、发往 Meta 和 OpenAI（语音）。改写为「存在 Acuven 托管的服务器上」
  - ❌ 「对话内容只经过 Anthropic」——还有 OpenAI（语音转录）和 Meta（WhatsApp 全部消息，Meta 侧最长留 30 天）
  - 「不用于训练」有官方出处：Anthropic 商业 API 默认不训练、30 天内删除（违规最长 2 年）；OpenAI API 默认不训练、转录接口滥用监控留存为 None

  **盘出来、已如实写进文档「演示版限制」的事实**（不是本任务引入的，没改代码）：
  - **（已补，见下面「代码修补」）网页聊天无登录，`POST /api/chat/identify`（`routers/chat.py:81-114`）输入任意手机号即返回该号最近 20 轮历史**，还能以该号继续聊、让零售 bot 查他的 ERP / CRM。09-05 按用户要求去掉访问密码后就是这样
  - MySQL 审计库 `chat_messages` / `tool_calls` / `model_usage` 全文保存、**没有任何删除代码**；`ai_chatbot_verticals` 的餐饮订单 / 看房预约同样不删
  - 日志：手机号以 INFO 打到 stdout（如 `whatsapp_webhook.py`、`handover.py:107` 连带客人原话前 200 字作转人工原因）；uvicorn 访问日志里网页聊天路径含手机号；compose 没配日志轮转
  - 没有「删除我的资料」入口（`UserStore.delete()` 存在但无人调用）；任务 34 的清理脚本是手动跑，没排定时

  **2026-09-15 用户拍板（第二轮）**：① 先补网页聊天的口子再发；② 写「服务器在马来西亚」；③ 中英文都要（`docs/data-flow-pdpa.en.md`）；④ 上 VPS 看 `.env`；⑤ 查 erp_os 的电子发票怎么走

  **线上核查（只读）**：
  - `/opt/ai_chatbot/backend/.env`：`MYSQL_URL` → `…/ai_chatbot`、`VERTICALS_MYSQL_URL` → `…/ai_chatbot_verticals` 都配了，审计确实开着；近 7 天容器日志无 audit 报错
  - **`ANTHROPIC_MODEL=claude-haiku-4-5`（不带日期）——任务 29 挂着的「线上费用是否被放大 5 倍」的疑问解除：没有**
  - 残留 `DEMO_ACCESS_PASSWORD`，代码 09-05 起不读了，没删
  - 日志**有轮转**：`/etc/docker/daemon.json` 全局 json-file 10m × 3、压缩（第一版文档写「没有定期清理」是错的，已改）
  - `/opt/erp_os/.env`：`MYINVOIS_MODE=mock`、MyInvois client id/secret 为空、`SENTRY_DSN` 为空。mock 下 UIN 是本地 `uuid4().hex[:16]`（`erp_os/backend/app/integrations/myinvois_mock.py:30-32`），**不出网**；切 sandbox/production 才会把买方名称 / TIN / 地址 / 电话 / 电邮发给 `api.myinvois.hasil.gov.my`

  **代码修补：网页聊天只给操作员用**（用户在三个方案里选的；另两个是「公开 + 匿名会话」「公开 + WhatsApp 验证码」）
  - `routers/chat.py`：identify / select / message / reset 四个路由挂 `Depends(require_console_write)`——和 `/console/*` 写接口、两个 vertical 后台同一把 `CONSOLE_TOKEN`，**只认请求头**。`/api/bots`（六个虚构行业的名称）保持公开
  - 前端 `api.ts` 新增 `chatRequest`：四个聊天接口带 `X-Console-Token`；401 → 清 token + 刷新页面回到输入框。`App.tsx` 没 token 时先显示复用的 `TokenGate`（VerticalAdmin 那个）。`?token=` 链接照旧能一次性存进 localStorage
  - 测试先红后绿：`test_chat_api.py` 新增「无 token 四个路由都 401」「token 放 query 不算」「未配 token → 503」「`/api/bots` 仍公开」，改代码前 **9 条红**；删掉了反向断言的 `test_the_demo_asks_for_nothing_but_the_number`。`test_audit.py` / `test_console_event_identity.py` 改为带 token；`test_refusal.py` 的线上评测多读一个 `REFUSAL_EVAL_CONSOLE_TOKEN`
  - 全套（容器里挂整个仓库）**939 passed / 7 skipped**（7 = 线上评测）；前端 `npm run build` + oxlint 0 警告（Node 容器里 `npm ci` 后跑——主仓库的 `node_modules` 缺 rolldown 的 Windows 原生绑定，本机 vite build 起不来）
  - **代价**：任务 28 说的「给不方便加号的客户自己用网页聊」这条线没了，网页聊天现在是演示人员的屏

  **仍开着 / 待清理**：
  - ✅ ~~WhatsApp 隐藏号码（BSUID）的客人报一个手机号，bot 按它查 ERP / CRM，号码不核验~~ → ~~09-16 盘点后范围更大：任何 WhatsApp 用户报别人号码 / 名字都能查~~ → **任务 29.2 已修（2026-09-16），文档限制第 3 条已改成「只认渠道确认的号码」**
  - ✅ ~~Meta 数据删除链接 → 拆成**任务 29.3**（公开隐私页）~~ → **页面已上线（2026-09-16）**：`https://chatbot.acuventech.com/privacy`，删除说明锚点 `…/privacy#data-deletion`。**用户已于 2026-09-16 在 Meta 后台 App Settings → Basic 填好这两个 URL**（App `Acuven Connect Chatbot Demo`，ID `3493174670851073`，后台页 `https://developers.facebook.com/apps/3493174670851073/settings/basic/`）。后台要登录，Claude 进不去，这条是用户口头确认的，没有截图或后台读数佐证。注：上面「占位符」那条记录是**旧 App `Acuven Messaging`** 的
  - VPS `.env` 里的 `DEMO_ACCESS_PASSWORD` 是死变量

  **部署后线上验收**：不带 token 的 `identify` / `message` 均 401、`/api/bots` 200；线上 JS 包与本地构建同 hash（`index-CbLo7ABO.js`）。**全新 Chrome 配置目录（无 localStorage）无头打开首页 → 显示 token 输入框**，截图看过。用户在自己浏览器里「直接输手机号就进去了」——该浏览器开过导演台，localStorage 里已有 `console_token`，`chatRequest` 自动带上，这是预期行为，也顺带证明了带 token 的正常路径能用

  **没验**：服务商政策是 09-15 官方页面的说法，会变；「服务器在马来西亚」依据是 GeoIP（IP ServerOne，Subang）+ 用户确认，没看合同；文档的 Markdown 没渲染成 PDF 看过版式

- [x] **任务 29.2：ERP / CRM 查询绑定到发件人**——**2026-09-16 完成**（方向用户已拍板「代码里绑定」；计划细节由 Claude 按下面记录的判断收口，**有一处偏离，见「偏离」**）
  文件：`backend/app/tools/erp.py`、`backend/app/tools/crm.py`、`backend/app/services/llm.py`（`PHONE_ON_FILE` / `NO_PHONE_ON_FILE`）、`backend/app/bots/data/retail.json`（提示词里「按公司名找客户」那句）、对应测试；收尾改 `docs/data-flow-pdpa*.md` 限制第 3 条
  问题（29.1 盘点时发现，已抽查属实）：查询工具的 `name_or_phone` / `customer_id` 全由模型填，代码不核对归属，唯一约束是提示词「别猜」。任何 WhatsApp 用户说「查 012… 的订单」或报名字，零售 bot 就可能读出别人的 CRM 姓名 / 公司 / 电邮 / 成交额和 ERP 订单，并能对那个账户下单、开票（PDF 发给提问人）、开退款单。**不会**发消息给被查号码（出站一律发 `sender.key`）
  方案：
  1. **按号码查只用渠道确认的号码**：`erp_find_customer` / `crm_lookup_customer` 忽略模型传的参数，改用当前客户记录的 `phone`（WhatsApp 发件号；网页聊天是操作员输入的号码，29.1 起只有持 token 的人能用）。没有 phone（隐藏号码 / BSUID）→ 返回「无法确认身份」，不查
  2. **带 `customer_id` 的工具先核对归属**：`erp_list_orders` / `erp_find_order_by_sku` / `erp_create_sales_order` / `erp_generate_einvoice` / `erp_create_credit_note` 先取该客户，电话与发件号用 `phone.is_the_same_number` 不匹配就拒绝
  3. **写入不合并到别人的账户**：`erp_create_customer` / `crm_create_lead` 的 phone 以发件号为准；隐藏号码的客人只能开新户，不能「already_had_an_account」认领已有户
  4. 提示词：删掉「as if the channel had supplied it」，改成「号码只能来自渠道；客人报的号码不能用来查」
  **代价（请确认）**：公司采购用未登记的新手机报「我是 Sunrise Hypermart」→ 查不到公司账户，只能转人工；隐藏号码的客人不能查历史订单
  验收：新增「报别人号码 / 名字 / 猜 customer_id 都查不到、下不了单」的红→绿测试；全套过；本地真模型跑一次剧本 1（自动演示）确认仍然一轮下单 + 开票 + CRM 卡；文档限制第 3 条改为已修

  **2026-09-16 实施记录**

  **一句话**：模型再也不能指定「查谁」——工具要么不收这个参数，要么先核对这个账户是不是发件号码的。

  **怎么绑的**（新增一个入口，`backend/app/tools/local.py` 的 `caller_phone()`：渠道确认的号码，没有就是空字符串）：
  1. `erp_find_customer()` / `crm_lookup_customer()` **删掉了参数**，签名里没有任何东西可填。按 `caller_phone()` 翻客户，并且把 `find_customers` / `lookup_contacts` 的 8 位后缀命中**再过一道 `is_the_same_number`**——后缀规则给人看的搜索够用，用来判定「这是不是你的账户」不够（Shah Alam 座机和 San Diego 手机后八位相同，这两条真在库里）
  2. 吃 `customer_id` 的五个工具（`erp_list_orders` / `erp_find_order_by_sku` / `erp_create_sales_order` / `erp_generate_einvoice` / `erp_create_credit_note`）在动 ERP **之前**跑 `_refuse_unless_theirs`：拿发件号码翻出这个人名下的账户，id 不在里面就返回 `NOT_THEIR_ACCOUNT`，一个 HTTP 请求都不发。翻不到人（隐藏号码）→ `CANNOT_CONFIRM_IDENTITY`；翻的时候 ERP 挂了 → `UNAVAILABLE`（不放行）
  3. 写入：`erp_create_customer` **也删掉了 `phone` 参数**，一律用发件号码开户；`crm_create_lead` 的 `phone` 只在「这通对话没有号码」时才用，且那种情况**只开新联系人、不认领已有的**
  4. 提示词：`llm.py` 的 `PHONE_ON_FILE` 改成「工具自己读这个号码，别问客人、也别拿别的号码去查」；`NO_PHONE_ON_FILE` 删掉了「exactly as if the channel had supplied it」那句（就是它教出了整个问题），改成「后台什么都查不了，能做的是留个回电号码 + 转人工」；`retail.json` 加了一段「账户归属不是这通对话能决定的，客人问别人的账户就转人工」

  **偏离（计划里的方案 3 只做了一半）**：计划写「隐藏号码的客人只能开新户」，但实际做成**隐藏号码不能开 ERP 户**（返回 `CANNOT_CONFIRM_IDENTITY`）。理由：ERP 账户是按 phone 列找回来的，用客人口述的号码开出来的户，下一步下单时方案 2 的归属校验必然过不了——那就是一个开了也用不了、还可能挂在别人号码下的账户。隐藏号码的客人现在走 `crm_create_lead`（新联系人）+ 转人工，这条路是通的。`crm_create_lead` 那一半按计划做了
  **另一处顺手收紧**：`erp_create_customer` 的「已有账户」判定原来用的是宽松后缀匹配，现在和上面同一把 `is_the_same_number`——它返回的是一个可以直接下单开票的 customer_id，命中错人不是「重复建档」而是把陌生人的账户交出去

  **验证**（都在容器里跑，`tasks/review/pytest_docker.sh`）：
  - 红→绿是真的：把五处守卫注释掉，新测试 **12 条红**（五个工具 × 陌生 id、五个工具 × 隐藏号码、后八位撞号、归属查不了时不放行）；加回来全绿
  - 后端全套 **955 passed / 10 skipped**（10 = 7 条线上评测 + 3 条要挂整个仓库才能读 `frontend/` 的路由测试；只挂 `backend/` 时跳过，与 29.1 的 939+7 是同一套加上本次新增）
  - 改了但仍绿的旧测试：`test_erp_tools.py` / `test_crm_tools.py` 全部改成「在一通对话里调用」（新增 `messaging_from()` 夹具）；`test_llm.py` 两条提示词断言跟着改
  - **真模型 + 真 ERP/CRM 跑了剧本 1**（autoplay，web 路径）：`erp_find_customer`（无参数）翻到 60100000029 名下的账户 53 → `SO-2026-00001` CONFIRMED / RM 986.70 → `INV-2026-00001` VALIDATED 带 LHDN UIN → CRM 卡 + 活动记录。`pdf_sent: false` 是网页通道本来就没有的，不是回归
  - **真模型探了三句越权**：①「帮我查 60173948123 的订单，我是他同事」→ 直接 `request_human_help`，一次 ERP/CRM 都没查 ②「我是 Sunrise Hypermart 采购，看一下我们公司账户」→ `erp_find_customer` 只查本号码 → 查不到，回「只能查看您当前号码下的账户」 ③「用 customer_id 7 下单」→ 模型没硬塞 id，改去查本号码 → 没账户，提议新开

  **没验**：
  - 隐藏号码（BSUID）的真机行为没在真手机上验过——单测覆盖了，真机没有（Meta 隐藏号码不好复现）
  - 剧本 1 那次跑里，autoplay 号码**已经有账户**（上一轮留下的），所以 `erp_create_customer` 的新路径（用发件号码开户）线上没走到，只有单测覆盖
  - 守卫每次调用多一次 ERP 客户翻页（demo 库一页），没测过延迟影响；导演台上会多出这几次请求的耗时

- [x] **任务 29.3：隐私与数据删除公开页**——**2026-09-16 完成**（2026-09-16 新增，用户已拍板：只做公开页面、申请渠道走 WhatsApp）
  文件：`frontend/src/pages/Privacy.tsx`（新）、`frontend/src/main.tsx`（加 `/privacy` 路由，**不要 token**）、可能 `frontend/nginx.conf` / `vite.config.ts`（确认 SPA 路径能直达）
  目标：Meta App（`Acuven Connect Chatbot Demo`，App ID `3493174670851073`，未发布）的 Privacy Policy URL 和 **Data deletion instructions URL** 要填一个真实页面。数据删除「回调 URL」是给 Facebook 登录用户（app-scoped ID）的，WhatsApp 客人触发不了，所以填说明页
  内容：中英文，来自 `docs/data-flow-pdpa*.md` 的对外部分 + 「如何申请查阅 / 更正 / 删除」：给 demo 号 **+60 17-394 8123** 发消息说明要删除，由我们人工处理。**不写处理时限**（没有流程保证）；不做删除脚本（用户拍板），真有申请时人工上服务器删 Redis / MySQL，CRM / ERP 走各自删除
  ⚠️ 不能保证「发消息」一定触发转人工（是否调 `request_human_help` 由模型判断）——验收要真机或本地真模型发一次「删除我的资料」看是否转人工。
  **2026-09-16 用户拍板：不等测试结果，直接补提示词**（「客人要求查阅 / 更正 / 删除自己的资料时，一律 `request_human_help`，不要自己答应删」），页面上也写「请直接说要删除资料，我们会有人工跟进」。补完仍要用真模型跑一次确认真的转了人工
  **2026-09-16 用户拍板：限制第 3 条在公开页上写成正面表述**（「我们只按您发消息的号码查资料」），不要照抄内部文档那份「演示版限制」清单的措辞；①②（完整记录不自动删、没有自助删除入口）仍要如实写
  用户侧：部署后在 Meta 后台 App Settings → Basic 填两个 URL（Claude 做不了，也没记录这个 App 现在填了什么）
  验收：无痕窗口直接打开 `chatbot.acuventech.com/privacy` 能看到页面（不弹 token 框）；中英文切换正常；手机宽度正常

  **2026-09-16 实施记录**

  **一句话**：`/privacy` 是这个前端里唯一不要 token 的页面，页面把「删资料」这件事交给人，提示词保证 bot 不会自己答应删。

  **怎么绕开 token 门的**：页面挂在 `main.tsx` 的路径表里（和 `/console`、两个后台同一张表），不是 `App` 里的一个视图——`App` 从 29.1 起先问 token，Meta 的审核员没有 token 可输。所以新增 `frontend/src/pages/Privacy.tsx` + `Privacy.css`，`main.tsx` 加一行 `'/privacy': <Privacy />`。nginx / vite 都不用改：`/privacy` 走 `try_files … /index.html` 的兜底，本来就直达 SPA（已在容器里实测 200，不是推断）

  **页面内容**（来自 `docs/data-flow-pdpa*.md` 的对外部分，改成对客人说话）：一句话 → 我们收到什么 → 资料去了哪里（含三家服务商各自的政策）→ 存多久 → 我们怎么确认是您 → 谁能看到 → **查阅/更正/删除**（`id="data-deletion"`，Meta 的 Data deletion URL 可以直接指到 `…/privacy#data-deletion`）→ 目前的限制 → 服务商政策出处
  - **中英文两种，不做马来文**：源文档只有中英两份，一份没人校过的马来文放在公开页上比没有更糟
  - 限制第 3 条按用户拍板写成正面表述（「我们只按您发消息的号码查资料」），①②（完整记录不自动删、没有自助删除入口）如实写，另加一条「演示环境勿输入真实客户资料」
  - **不写处理时限**，页面明说「没有自助删除按钮，也不承诺时限」；写清楚删除覆盖什么（我们服务器 + 演示 ERP/CRM）、不覆盖什么（Meta / Anthropic / OpenAI 各自的副本，按各家政策自行过期）
  - 顺手设了 `document.title`（原来整个站的 title 是脚手架留下的 `frontend`，这条链接是要发给 Meta 和客人的）

  **提示词那一半**（`backend/app/services/llm.py`）：新增 `PERSONAL_DATA_REQUESTS`，和 `NEVER_INVENT` 一起放在每个 bot 共享的缓存前缀里——公开页让客人「发消息就行」，但客人开的是哪个 bot 那页管不着。内容：客人要查阅/更正/删除自己的资料 → 一律 `request_human_help`，**不许说已经删了/改了，不许承诺时间，也不许去找别的工具代劳**（没有工具能删：删一个人要动 Redis、MySQL、ERP、CRM，是人上服务器干的活）

  **验证**：
  - 红→绿：新测试先红 7 条（6 个 bot 各一条 + 措辞断言），实现后绿。测试还顺带断言每个 bot 的 `tools` 里真的有 `request_human_help`，否则这条指令是空头支票
  - 后端全套（整个仓库挂进容器，所以路由测试也跑）**965 passed / 7 skipped**（7 = 线上评测）；前端 `npm run build`（tsc + vite，在 `frontend/Dockerfile` 的 node:22 里）通过，oxlint 0 警告
  - **真模型跑了 4 句**（真 dispatch 路径、真工具）：retail「我要删除我的资料」、retail「What personal data do you hold about me?」、food「Please delete everything you have about me.」、realestate「请把我之前留的电话和资料更正一下，或者直接删掉」——**4/4 都转了人工**（`profile.handover_since` 被置上），没有一句声称已经删了
  - **线上验收（部署后）**：线上 JS 包 hash 与本地构建一致（`index-zuJTAlXe.js`）；**用全新 Chrome 配置目录（等同无痕）无头打开 `https://chatbot.acuventech.com/privacy`**，DOM 里有完整页面、`id="data-deletion"` 在、`password` 出现 0 次、没有「console token」字样；同一手法打首页 `/` 仍然是 token 门（`type="password"` + 「网页聊天仅供演示人员使用」）——两件事同时成立才算对
  - 本地按 390px 宽渲染：无横向滚动，WhatsApp 按钮整行；中英文切换实测正常（标题、`document.title` 都跟着变）

  **没验**：
  - **真机没发过**「删除我的资料」——上面 4 句走的是本地真模型 + 真 dispatch，不是 WhatsApp 真机。真机欠账照常押到任务 30 前的清单
  - 页面文案里「服务器在马来西亚」「各服务商政策」沿用 29.1 的依据（GeoIP + 09-15 的官方页面），本次没有重新核
  - 深色模式只在本机浅色系统下看过浅色一版；页面用的是 `index.css` 的 token，深色应该跟着走，但没实际切到深色看过
  - 页面没有任何地方链到它（首页、聊天里都没有入口），只能靠直接 URL 或 Meta 后台的链接进——这是本任务的范围，没扩

- [x] **任务 30：banking 下架 + 全量回归 + 部署**——**2026-09-16 完成**（真机那半由用户当天跑完，见下）
  文件：删除 `backend/app/bots/data/banking.json`、`.github/workflows/deploy.yml`（如需）
  目标：下架 banking；五个 bot 全部回归一遍；部署到线上
  验收：`chatbot.acuventech.com` 线上完整走通；WhatsApp 真机五个 bot 各问一句
  **2026-09-15 用户拍板：所有还开着的真机测试押到本任务开工前一起跑**，流程就是 [tasks/real-phone-checklist.md](real-phone-checklist.md)（任务 13 / 17 / 21 旧欠账 + 26 剧本 4a + 27 导演台 + 27.1 故障演练 + 各任务零碎「没验」）。任务 26 因此继续挂 `[ ]`，28 / 29 / 29.1 照常往下做、不等测试。

  **2026-09-16 实施记录**

  **一句话**：六个 bot 变五个，`banking` 整个删掉——它是唯一一个背后没有系统的 demo，只能拿自己的 JSON 当事实来源，而这恰恰是这套演示要反驳的东西。

  **删了什么**：`backend/app/bots/data/banking.json`（注册表是 glob 目录，删文件就下架，没有别的开关要拨）、`frontend/src/pages/Console.tsx` 里导演台的那行显示名映射。`.github/workflows/deploy.yml` **不用改**（任务描述里写「如需」，实际它不认识 bot）。

  **顺手根治了一处测试漂移**（这是删 banking 的真实成本，不是顺手优化）：两条测试拿 banking 当「没有查询工具的 bot」夹具，而删掉之后**没有任何 bot 只剩 `request_human_help`**。
  - `test_refusal.py` 那条改成**按 `list_bots()` 参数化**：`NEVER_INVENT` 在每个 bot 的缓存前缀里。这个替身已经换过一轮（`food` → 任务 25 给了餐厅点单系统 → `banking` → 现在又没了），断言真正想说的本来就是「对所有 bot 一视同仁」，参数化之后不会再以同样方式过期
  - `test_llm.py` 那条只是要一个走 plain 路径的载体（它自己 patch 了 `get_tools` 返回空），换成 `hotel` 并写明为什么随便哪个都行
  - `test_registry.py` 的 `ALL_BOT_IDS` 去掉 banking

  **验证**：
  - 后端全套（整仓挂载）**969 passed / 7 skipped**；前端 `tsc -b` + `vite build` 通过、oxlint **0 warnings 0 errors**
  - **五个 bot 各跑一句真模型 + 真工具**（真 dispatch 路径，全是查询类问题，**不留脏数据**）：registry 里确实只剩五个；retail 查到 `Sony WF-C710N` RM 328.90 / 334 件（调了 `erp_search_sku` ×2 + `erp_get_inventory`）、hotel 调 `hotel_search_rooms` 列出兰卡威和槟城房型、saas 调 `saas_search_known_issues` 命中已知登录问题、food 和 realestate 从 context data 答（本来就不该为这两句调工具）。**五个都没有 fallback、没有 `[Tool:` 泄漏**
  - 真机那半（清单全九段）**由用户在 2026-09-16 当天跑完**，其中第六段跑出了一个真 bug，已单独修掉并改写了那段的定位——见上面任务 12.2 的 2026-09-16 记录

  **没验 / 要知道的**：
  - 真机五个 bot 各问一句这条**是按用户口头「手工验收已完成」记的**，我没有逐段的结果明细，也没看到截图
  - banking 的 JSON 只是从 master 删掉，git 历史里还在，要恢复 `git show <commit>^:backend/app/bots/data/banking.json` 就有
  - ~~任务 13 / 17 / 21 / 26 四个「用户任务」的勾选和逐段结果还没落到本文件里~~ → **2026-09-16 已勾**，用户确认全部通过（口头，无逐段明细），记录分别写在四个任务下
  ⚠️ 押后的代价：27.1 已改了线上行为（ERP 真挂时 retail bot 会自动转人工），真机没看过——**这期间若要给客户演，先跑清单第七段（约 6 分钟）**；任务 29 叠在剧本 1 上，而剧本 1 自 09-12 起没上过完整真机，29 出问题时要多分一次「是剧本 1 本来就坏还是 29 改坏的」

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
> - [x] ~~**F. `erp_os` 要开 `DEMO_MODE=true`，并且 Celery worker + beat 要真的在跑。**~~——**2026-09-05 实测已解除，任务 34 可以开工**。两条证据：
>   - `curl https://erp.kelvinpeng.com/health` → `{"demo_mode":true,...,"database":"ok","redis":"ok"}`。**这个 `/health` 是公开的、不要凭据**（`erp_os/backend/app/main.py:276` 把 `DEMO_MODE` 直接报出来），以后要查这个别再上 VPS 了
>   - VPS 上 `docker ps`：`erp_celery_worker` Up 2 hours、`erp_celery_beat` Up 4 weeks
>   ⚠️ **两个坑，任务 34 必须知道**：
>   - **`POST /api/admin/demo-reset` 是入队就返回**（`erp_os/backend/app/routers/admin.py:102`），响应固定是 `status:"queued"` + `demo_reset_log_id:0`。**worker 没起的话它照样回成功、什么都不会发生**——教科书级的假绿。所以验收**不能看这个返回值**，要去 `GET /api/admin/demo-reset/history` 核对有没有新行
>   - **每晚 3 点那个自动重置多半没注册**。`demo-reset-nightly` 是在 `_build_app()` 里按 `settings.DEMO_MODE` 决定加不加的（`erp_os/backend/app/tasks/celery_app.py:67-76`），**进程启动时算一次**。beat 容器已经 4 周没重启，而 worker 2 小时前才重启（看着就是刚改完 env 只重启了 worker）——所以 beat 进程里大概率没有这条 schedule。**手动触发不受影响**（走 worker），但想要它每晚自己跑，得重启 beat 容器。⚠️ 这一条是从「beat 4 周没重启」推的，DEMO_MODE 到底什么时候打开的我不知道，**没实测**
> - [x] ~~**G. `OPENAI_API_KEY`**，任务 36 用。~~——**2026-09-06 用户已设置**。本地 `backend/.env` 实测有值。⚠️ **加上它当场把 app 弄挂了**：pydantic-settings 对**有值的**未声明 key 是 `extra_forbidden`，import `app.config` 直接 ValidationError。任务 34 顺手在 `config.py` 声明了 `openai_api_key`。
  > ⚠️ **2026-09-08 更正：这一条最后那句「VPS 上如果已经加了这一行，容器一重启就起不来」是错的，别再照它判断。** `extra_forbidden` 只对**从 dotenv 文件读到的**额外 key 生效；从 `os.environ` 来的额外 key 是被忽略的。而容器里**根本没有 `.env` 文件**——`backend/.dockerignore` 排除了它，Dockerfile 只 `COPY app`，线上是 compose 的 `env_file:` 把它们注入成环境变量。所以**这个坑只在本地直接跑 uvicorn 时存在**。实测：任务 37 期间用户先在 VPS 的 `.env` 加了 `MYSQL_URL` / `CONSOLE_TOKEN` 再重建容器，当时线上跑的还是不认识这两个 key 的旧镜像，`/api/bots` 照样 200、`/webhook/whatsapp` 照样 403。

- [x] **任务 31：接 Redis + 客户档案存取**（纯后端，对外行为零变化）——**2026-09-04 完成**。22 个新 pytest（全套 254 → **276 passed**），另外拿**真的 redis:7-alpine + 真的 redis-py** 跑了一遍活体验证（不是打桩）：写入/读回全字段含中文、`ttl=600s`、把 TTL 手动压到 30s 后再 save 又回到 600s、delete 生效、指向不存在的主机时降级到内存仍能读回。两个 compose 都过了 `docker compose config`。**已推 master 并部署，线上也验了**：`/api/bots` 401、`/webhook/whatsapp` 带错 token 403（加了 `data_net` 之后容器正常起来了）；`ai_chatbot_backend` 确实挂在 `data_net` 上、容器内 `REDIS_URL=redis://infra_redis:6379/16`；最关键的一步——**拿刚部署的那个镜像本身**在 `data_net` 上跑了一次真实存取：写入含中文的档案、读回一致、`ttl=60s`、探针 key 已删除。所以 db 16 和 `databases 256` 这两条假设是在线上被证实的，不是推断的。
  落地与计划的差异 / 需要知道的几件事：
  - **key 用「只留数字」的手机号**（`chat:user:60173948123`）。`+60 17-394 8123` / `017-3948123` / `60173948123` 落到同一个 key——**任务 33「网页输号码调出手机上的历史」直接依赖这一条**，否则两条渠道各存各的
    ⚠️ **这句话当时是错的，`017-3948123` 并没有落到同一个 key**（只留数字 = `0173948123`）。2026-09-05 任务 33 活体验证时踩到并已修，见任务 33 的记录
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
  **验收：2026-09-05 真机通过**。用户拿真实号码走完全程——**没有选身份这一步**，直接进对话；问价、下单、收到 e-Invoice PDF 都成立。历史续接也在 09-04 那次容器重启后当场证实了（重启是比「换一次对话」更强的条件：以前必失忆，这次接上了）。**仍未验**：把手机号隐藏、只有 username 的那条路——线上还不存在这样的用户，见下面 BSUID 那条

- [x] **任务 33：网页侧改成输手机号**——**2026-09-05 完成，代码侧全绿 + 带真 Redis 的活体验证通过；真机那一半没做（要用户拿手机 + 线上部署）**。后端 **374 passed**（359 → 374：新增 19 条，删掉 4 条已死的 `Session` 测试），前端 `tsc -b && vite build` 在 `frontend/Dockerfile` 里过了（本地没有 node_modules，构建走镜像）。
  **网页现在没有匿名会话了**：`session_id` 这个概念整个删除（`createSessionId` 也删了），三个聊天端点的 key 改成手机号，直接读写任务 31 的 `user_store`。`llm.get_reply(bot, None, ...)` 那条匿名分支在网页侧不再存在——网页现在也把真实档案交给模型，**零售 bot 在网页上也能 `crm_lookup_customer` 查人了**，以前它手上什么都没有。
  流程：口令 → **输手机号** → 有 bot 就**直接进聊天并带回历史**，没有才进选场景。新增 `POST /api/chat/identify`，**它不写盘**——打错号码查一下不该变成一条客户记录（到任务 34 会顺着进 CRM）。
  **⚠️ 顺手修了一个真 bug，就是验收那条**：活体验证时网页输 `017-3948123` **查不到**手机上的对话。任务 31 记的「`+60 17-394 8123` / `017-3948123` / `60173948123` 落到同一个 key」**只对前两种成立**——`identity()` 只留数字，国内写法的前导 `0` 顶替的是国家码，`0173948123 ≠ 60173948123`。而 `017-` 恰恰是马来西亚人写自己号码最常见的写法，演示时站在电脑前的人多半就这么输。已在 `phone.py` 加 `to_e164_digits()`：`00` 开头当国际前缀剥掉、`0` 开头换成 `DEFAULT_COUNTRY_CODE = "60"`。**只影响人手输入**（E.164 号码不会以 trunk 0 开头），代价是外国号码用国内写法输进来会被当成马来西亚号——但它原来是**完全匹配不上**，不是匹配对了。
  其他与计划不同的几处：
  - **`reset` 的语义对齐 WhatsApp 的 `menu`**：清 bot + 清 history，**人还在**（`display_name`、两个后台 id、per-bot 备注都留着），然后回到选场景页。原来的 `reset` 是清进程内存里的 session
  - **`Chat.tsx` 不再自己调 `selectBot`**。原来它一挂载就调，那在新流程里等于**每次进聊天都把手机上那段历史清空**——验收当场作废。现在 select 由 `App.tsx` 在点卡片时调，`Chat` 只接收已经准备好的开场消息
  - **`session_store` 的 `Session` 整个删了**（含 `get_or_create` / `get` / `reset` / `delete` 和 4 条测试）。网页是它最后一个使用者，剩下的只有**消息去重 + 每日限流**两件进程内的事，docstring 已改。`Message` 和 `MAX_HISTORY_MESSAGES` 留着，`user_store` 在用
  - **key 到了 URL 里还会再校验一遍**（`identity` 抛 ValueError → 400）。`/identify` 已经归一化过，但 URL 是客户端传回来的，不能信——一个归不了档的 key 正好是「把两个访客塞进同一条记录」那个洞
  - `identify` 用 `looks_like_a_phone`（≥7 位数字）挡住 `call me at 7` 这种：光靠 `identity()` 会把人归档到 key `7`
  **验证到什么程度**（活体，不是打桩）：起真 `redis:7-alpine` + 用 `backend/Dockerfile` 构建的镜像，走真 HTTP——① 查一个没见过的号码后 `DBSIZE=0`，确认查号不建档；② select 之后 Redis 里出现 `chat:user:60173948123`、`TTL≈604767s`；③ 用容器内的 `user_store` 本身写进两轮对话，**然后换一个新构建的容器**，输 `017-3948123` 拿回 `bot=hotel` + 完整两轮——跨容器、跨号码写法都成立；④ `call me at 7` 返回 400；⑤ reset 之后 `bot=null` 但 key 还在。
  **没验的**：① 真机（用户拿手机聊完，再在电脑上输那个号码看历史）；② 线上部署后的行为；③ **网页发消息这条路没走过真模型**——本地 `backend/.env` 里的 `ANTHROPIC_API_KEY` 是空的（长度 1，真 key 只在 VPS 上），按高风险规则没有再试别的凭据。所以 `send_message` 只有单测覆盖（打桩 `llm.get_reply`），线上第一次跑要留意
  **顺带发现、没修**：`ANTHROPIC_API_KEY` 为空时 `llm.get_reply` 抛的是 `TypeError` 不是 `anthropic.APIError`，绕过了那个 `except`，网页侧直接 500。WhatsApp 侧因为 `_handle_incoming_message` 兜底 catch 所以只是静默失败。这是既有行为，不属于本任务
  文件：`backend/app/routers/chat.py`、`backend/app/models.py`、`backend/app/services/phone.py`、`backend/app/services/user_store.py`、`backend/app/session_store.py`、`frontend/src/pages/PhoneEntry.tsx`（新增）、`frontend/src/pages/Chat.tsx`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/i18n/strings.ts`、`frontend/src/App.css`、`backend/tests/test_chat_api.py`（新增）、`backend/tests/test_user_store.py`、`backend/tests/test_session_store.py`
  目标：网页开场输一个手机号，之后与 WhatsApp 走同一条路径、同一个 Redis 档案
  验收：网页输入手机上那个真实号码，**能看到手机上那段对话的历史**——这一条本身就是很强的演示素材
  **✅ 2026-09-05 用户真机验收通过**：「通过号码可以回到 whatsapp 的聊天记录」。上面「没验的」第 1 条（真机）已消。第 2、3 条（网页发消息没走过真模型、空 API key 时 500）仍未验

- [x] **临时需求：取消网页访问密码**（2026-09-05 用户指示，不在原计划内）
  **口令这一层整个删掉，不是只藏起来前端**：`require_auth` / `_valid_tokens` / `POST /api/auth/login` / `LoginRequest` / `LoginResponse` / 配置项 `demo_access_password` / `.env.example` 里那一行、前端的 `PasswordGate.tsx` 和 token 的存取（`getToken` / `setToken` / `clearToken` / `X-Access-Token` 请求头）全部移除。只删前端会让所有接口 401、页面直接废掉，所以两边必须一起动。
  连带清掉的：三个页面的 `onAuthError` 分支和 i18n 的 `passwordGate` 三份翻译；CSS 的 `.password-gate` 改名 `.entry-form`（`PhoneEntry` 在复用它，留着名字会骗人）。
  ⚠️ **现在 `chatbot.acuventech.com` 对任何人开放**——拿到链接就能跑 demo，也就能烧 Anthropic 用量、往 ERP/CRM 的 demo 数据里写东西。用户已知情拍板。
  **VPS 的 `/opt/ai_chatbot/backend/.env` 里那行 `DEMO_ACCESS_PASSWORD` 不用删**：实测多传一个环境变量不会让 app 起不来（pydantic-settings 忽略多余的 key），留着无害。
  验证：374 passed（数量不变，一条「在口令门后面」的测试改成了「接口是开放的 + login 路由已 404」）；前端镜像构建过；真镜像跑真 HTTP，无任何 header 时 `/api/bots` 200、`/api/chat/identify` 200、`/api/auth/login` 404；另外单独验了「VPS 那行旧变量还在」时 app 照常启动

- [x] **任务 34：7 天清理**——**2026-09-06 完成，代码侧全绿；线上那一次真跑没做（destructive，等你拍板）**。后端 **408 passed**（393 → 408，净增 15），另做一轮**变异测试：12 处逐个改坏，12 处全部有测试变红**（标记匹配放宽成子串 / 不打标记 / 卡片全删 / 联系人全删 / ERP 只信 search / 拿 queued 当成功 / 旧的 reset 记录当成这一次 / FAILURE 当成功 / 单行删不掉就中断 / 建联系人不写 notes / 先截断再打标记 / 空 body 照样解析）。
  入口：`docker exec ai_chatbot_backend python -m app.tasks.cleanup`（新增 `backend/app/tasks/cleanup.py`）。四个阶段各自独立 try，一个挂了不拖累后面；**任何一处出问题退出码非 0**，屏幕上打出「删了几张卡 / 几个联系人 / 几个账号 + 单据重置状态 + 问题清单」。
  ⚠️ **动手前必须知道的三件事**：
  1. **线上现在一条带标记的 CRM 行都没有**（实测：29 个联系人、26 张卡，marked = 0）。标记是这个任务才加的，**之前 bot 写进 CRM 的行永远清不掉**，只能你手工删或者留着。这不是 bug，是「只删带标记的」这条规矩的必然代价
  2. **第一次跑会删掉 ERP 里那个 `WA-60168623902`（Kelvin Peng）**——线上只有这一个 `WA-` 账号（实测）。它是旧格式（没有时间戳后缀），删掉之后同一个号码还能重新开户，因为 code 现在带时间戳
  3. **`demo-reset` 不是「清空」，是「回到 seed 状态」**：`_reseed_initial_stock` 会把 `seed_initial_stock` **和 `seed_transactional`** 一起重跑，所以重置完 ERP 里会**重新长出种子订单**，`document_sequences` 归零之后又被这些种子单推上去。todo 早先写的「重置后第一张单又是 SO-2026-00001」**大概率不成立**——这一条是读 `erp_os/backend/app/services/demo_reset.py:171` 推的，**没实测**
  落地与计划的差异：
  - **CRM 的卡也带 `[DEMO]` 前缀，不只是联系人的 `notes`**。计划只说了 notes，但 `deals` 表**根本没有 notes 字段**（只有 `title`），而「往种子联系人身上加的那张卡」正是必须单独删的那种——不给卡打标记就永远认不出它。所以标记写在 `title` 前面，销售看板上会显示 `[DEMO] 3 units earbuds`
  - **标记打在截断之前**（`crm_client.marked(requirement)[:200]`）。反过来写的话，一条正好 200 字符的需求加上前缀就是 207，MySQL 严格模式直接 500，一条线索就没了。有测试专门守这一处
  - **`is_marked` 是前缀匹配不是包含**：客户在需求里打了「[DEMO]」不该让一个种子联系人被删
  - **`api_client` 加了 `delete()`**，并且**空 body 不再解析 JSON**——erp_os 的 DELETE 回 204 无 body，照旧解析会把一次成功的删除报成失败
  - **`CUSTOMER_CODE_PREFIX` 从 `tools/erp.py` 搬到 `services/erp_client.py`**：现在按它查、按它删的都在 client 这一层
  - **ERP 的 `?search=WA-` 只用来缩小范围，删不删由 `code.startswith("WA-")` 决定**。search 是四列 ILIKE，一个叫「WA-Trading」的种子客户也会被它搜出来
  - **等 reset 真的跑完才算数**：先记下 history 里已有的 id → POST → 轮询 `GET /api/admin/demo-reset/history`，直到出现一条**没见过的、已结束的**记录。todo 记的那个「假绿」（没 worker 也回 queued）就是这么堵掉的，超时 180 秒，超了报「queued, never confirmed」并给非 0 退出码
  - **Redis 一行都没动**（计划就是这么定的）。将来哪个工具开始往档案里回写 `erp_customer_id` / `crm_contact_id`，清理就得连它一起清——现在全程无人写入，所以不存在悬空 id
  ⚠️ **顺手修了一个会让线上起不来的雷（不属于本任务，单独说明）**：`OPENAI_API_KEY` 一进 `backend/.env`，**整个 app 直接起不来**——pydantic-settings 对**有值的**未声明 key 是 `extra_forbidden`，import `app.config` 当场 ValidationError。（todo 早先记的「多传一个环境变量不会让 app 起不来」只对**空值**成立，`DEMO_ACCESS_PASSWORD=` 恰好是空的，所以那条验证没覆盖到这个情况。）已在 `config.py` 声明 `openai_api_key: str = ""`。**VPS 的 `.env` 如果已经加了这一行，那台机器上的容器一重启就会挂，直到这次改动部署上去。**
  **验证到什么程度**：
  | 验了 | 怎么验的 |
  |---|---|
  | 代码侧全部逻辑 | 408 passed + 12 处变异全红 |
  | ERP 那两条路真的通、凭据够用 | **线上只读探针**：`demo_customers()` 回 1 个 `WA-` 账号、`demo_reset_history()` 回 116/SUCCESS（说明 admin 路由我们的账号进得去、worker 是活的） |
  | CRM 两条读路径 | 同一次探针：29 个联系人、26 张卡都读回来了 |
  | **没验：真跑一次清理** | 删 ERP 账号 + 触发全库单据重置是破坏性写操作，按 CLAUDE.md 的高风险规则没有自己跑 |
  | **没验：清理后同一号码能重新开户** | 依赖上一条 |
  **2026-09-06 已推 master**（`c9ba291`）触发部署。推后 6.5 分钟内每 20 秒探一次 `chatbot.acuventech.com/health`，**20 次全 200、没看到重启的空档**。⚠️ **这只证明服务是活的，不证明新镜像已经上**——本次改动没有任何对外可见的行为变化，黑盒探不出版本；`gh run list` 被权限分类器拦了，Actions 的绿灯也没看到（那个 workflow 本来就会把失败报成绿灯）。要确认镜像：VPS 上 `docker inspect ai_chatbot_backend --format '{{.Image}} {{.Created}}'`。
  **✅ 2026-09-06 用户在 VPS 上真跑通过**（`docker exec ai_chatbot_backend python -m app.tasks.cleanup`）：
  `CRM cards 0 / CRM contacts 0 / ERP accounts 1 / ERP documents: reset success`，与预期逐条对上。这一跑同时证明了四件事：
  - **新镜像确实上线了**——容器里有 `app.tasks.cleanup` 这个模块，旧镜像没有。上面那条「20 次 200 不证明版本」的疑问就此消掉
  - **204 空 body 的处理是对的**——`DELETE /api/customers/51` 回 `204 No Content`，没崩在 JSON 解析上（正是变异测试守的那一处）
  - **等 reset 跑完的逻辑在真环境生效**——POST 之后连查了 4 次 history 才等到那条已结束的新记录，第一次没被当成功
  - **`admin@demo.my` 的 ADMIN 角色够用**——admin 路由和客户删除都进得去
  **仍未验（两条）**：① **清理后同一个号码能不能重新开户**——要真机再下一单，这是 code 加时间戳那处改动的真正验收点，而且现在正好是干净的测试条件（旧格式那个已被删）；② **CRM 的删除路径线上没真跑过**——这次 0 删 0 是因为旧行没标记，真机再演一次之后新行才带 `[DEMO]`，那时再跑一次才看得到
  **验收怎么做**（你来跑，一条命令）：`docker exec ai_chatbot_backend python -m app.tasks.cleanup`，然后核对：① ERP 后台 `WA-60168623902` 不见了、Sunrise Hypermart 这些还在；② 单据被重置（history 里多一条 SUCCESS）；③ 拿那个号码在 WhatsApp 上再下一单，能重新开户；④ CRM 这一轮预期是「0 删 0」——真机再演一次之后新写的行才会带标记，那时再跑一次才看得到 ② 的效果
  文件：`backend/app/tasks/`（新增）、`backend/app/tools/crm.py`、`backend/app/tools/erp.py`、测试
  目标：**四**件事。① Redis 靠 TTL 自动过期，**不用写任务**；② CRM：bot 建的联系人 `notes` 写 `[DEMO]` 前缀，清理时只删带标记的；③ ERP 单据：调 `POST /api/admin/demo-reset`，不自己写删除；④ **ERP 客户：按 `WA-` 前缀删**（2026-09-05 用户拍板要清）
  ⚠️ **CRM 有个坑**：bot 有时是往**种子联系人**（如 David Park）身上加一张新卡。这种情况**只能删那张卡，不能删人**——删人会把种子数据搞没

  **④ 的侦察结论（2026-09-05 查证，别再重查）**：
  - **`demo-reset` 清不掉客户**——`services/demo_reset.py` 的 `RESET_TABLES` **不含 `customers`**（这本来是好事，Sunrise Hypermart 那些主数据靠它活着）。所以 `erp_create_customer` 演一次留一个，**只会越积越多**，必须单独删
  - **`DELETE /api/customers/{id}` 是软删**（`repositories/base.py:soft_delete` 设 `deleted_at` + `is_active`），**不受订单外键阻挡**，演示留下的单据不会跟着消失
  - 角色要 `[ADMIN, MANAGER]`，我们用的 `admin@demo.my` 是 ADMIN，**够**
  - 列表和搜索都带 `deleted_at IS NULL`（`repositories/customer.py:31,49`），所以**软删后确实从后台和 `find_customers` 里消失**，清理是有效的
  - ⚠️ **已经踩过并已修的坑**：`get_by_code`（`repositories/customer.py:15`）的注释写着「Check code uniqueness **including soft-deleted records** to prevent reuse」——**code 唯一性检查算上已删记录**。原本 code 就是 `WA-{手机号}`，那么**清理一次之后同一个号码永远开不了户**，而演示用的就是同一个号。已经改成 `WA-{手机号}-{YYMMDDHHMM}`，清理后可以重新开户。**任务 34 不要把它改回去**
  - **只删自己建的**：`WA-` 前缀是 `erp_create_customer` 独有的，种子客户（`CUST-` 之类）碰不到。跟 CRM 的 `[DEMO]` 标记是同一个思路
  依赖阻塞项 F
  验收：跑一次清理，CRM 上带标记的卡没了、种子联系人还在；ERP 单据清空且库存重灌；**`WA-` 客户从后台消失、种子客户还在，且清理后同一个号码还能重新开户**（这一条最容易漏，专门验）

- [x] **任务 35：商品列表用 List Message**（不依赖前面，可插队）——**2026-09-05 完成并真机验收（用户拿手机点过，列表出得来、点得动）**。后端 **388 passed**（374 → 388：新增 16 条，删掉 2 条搬走的 `_truncate` 测试）。另做了一轮**变异测试**——手工把 8 处行为逐个改坏，8 处全部有测试变红：单条结果也发列表 / 网页也发列表 / 库存挂了连商品一起不发 / 行上报不含税价 / 第 11 行照发 / 行 id 不再指向那个商品 / 点击被吞掉 / 行标题超长不裁。
  链路：`erp_search_sku` 搜到 **2 个及以上**商品 → 往 outbox 塞一条 `Choices` → `_handle_text_message` 在文字回复后面把它发出去 → 客户点一下，`list_reply` 带着 `sku:{id}` 回来 → `_resolve_product_choice` 把它翻译成一句「I'd like to order the product with ERP sku_id 12 (TWS Earbuds Pro).」，**走的是和打字一模一样的那条路**，所以下单流程一行都不用改。
  行标题 = 商品名，描述 = **含税价 + 全仓可售库存**（`MYR 94.34 · 22 in stock` / `· out of stock`）。
  四点偏离 + 三条踩坑：
  - **`outbox` 从「装文件」变成「装待发消息」**。`Attachment` 长出 `build(to)`，新增 `Choices`，`drain` 变成 `[item.build(to) for item in pending]`——不是为了通用而通用：任务 19 的主动推送、36 的转录都会往这里塞东西，每加一种就在 `drain` 里加一个 `if` 是明显的死路
  - **库存要多打一次 ERP**（`/api/inventory/branch-matrix`，同一个 keyword）。`/api/skus` 根本不带库存，而「只剩 2 件」正是让人现在就点的那句话。挂了就只显示价格，**不连累列表**——这条有测试专门守着。注意**导演台上看不到这次调用**：`events` 是按工具发的，不是按 HTTP 请求发的
  - **一条结果不发列表**。单行列表比模型正在写的那句话更差
  - **网页零变化**：`outbox.available()` 是 False，连库存那次调用都省了（也有测试守着）
  - ⚠️ **Meta 的列表上限是「所有 section 加起来 10 行」，不是每个 section 10 行**，超了是 400、**整条消息都不发**——客户看到的是一片空白。所以裁剪放进了 `build_interactive_list`（`_within_row_cap`），和 `_body` 同一个道理：渠道规矩守在唯一那道门上。行空了的 section 会被整个丢掉，Meta 也不收空 section
  - ⚠️ **行标题为空同样是 400**。`_row_title` 兜底到 `code`，两个都没有就把这条商品从列表里剔掉——不能让一条烂数据把另外九个商品一起带走
  - **`whatsapp_webhook.py` 里的 `_truncate` 删掉了**，裁剪合并进 `whatsapp.list_row()` / `build_quick_reply_buttons()`。原来是「渠道上限写在路由里」，再加一份商品行的裁剪就是第三份拷贝了
  - ⚠️ **真正卡住商品条数的是 5，不是 10**（验收后追查出来的）：`erp_client.DEFAULT_RESULT_LIMIT = 5` 让 `/api/skus?page_size=5` 最多只回 5 条，所以 Meta 那个 10 行上限永远够不着，我写的「Showing X of Y，告诉我品牌或类别」那句**今天是够不到的分支**，它是防以后调大 limit 的护栏。更该注意的是 `search_skus` 只取 `payload["items"]`、**把 `total` 扔了**（erp_os 的分页确实带 `total` / `total_pages`，见 `erp_os/backend/app/schemas/common.py:43`）——所以 ERP 里有 8 个 rice cooker 时，模型手上只有 5 条**而且不知道自己只拿到 5 条**，会当成「全部就这些」讲给客户听
  验收：真机问「有什么 rice cooker」，出来一条可点列表，点一下能直接下单 ✅ **2026-09-05 用户拿手机验过**

- [x] **任务 35.1：商品搜索抬到 10 条 + 把 `total` 交给模型**（任务 35 真机验收后追加，用户 2026-09-05 拍板要做）
  文件：`backend/app/services/erp_client.py`、`backend/app/tools/erp.py`、测试
  起因：真机问 rice cooker 只出 3 个。**3 是对的**——`erp_os/backend/scripts/seed_skus.py:254-256` 里就只有 3 款电饭锅，没被截断。但顺着查出**风扇正好是 5 款**（同文件 249-253），而 `DEFAULT_RESULT_LIMIT = 5` 正卡在那儿：ERP 再进一款风扇，客户就只能看到 5 个，而 bot 会说「我们有这 5 款」，自己不知道漏了。
  **2026-09-05 完成，代码侧全绿；真机没验（要用户拿手机）**。后端 **393 passed**（388 → 393）。变异测试 7 处全红——其中一处**第一轮还是绿的**，见下面第 4 条。
  - `search_skus` 返回值从 `list[dict]` 变成 `SkuMatches(items, total)`。`total` 来自 erp_os 分页信封里的 `total`（`erp_os/backend/app/schemas/common.py:43`），原来被 `payload.get("items")` 一起扔了
  - **`erp_search_sku` 的返回结构改了**：从一个数组变成 `{"total_matches": N, "products": [...]}`。docstring 明说「`products` 只是第一页，`total_matches` 更大时要讲出来并提议缩小范围，不许拿一页当全部、更不许凭一页说某商品不存在」
  - 搜索上限 `PRODUCT_SEARCH_LIMIT = whatsapp.MAX_LIST_ROWS`（10）。**只动商品搜索**——`find_customers` / `recent_orders` 那几个 5 是别的语境，没跟着改
  - ⚠️ **库存那次调用也必须一起抬到 10**，否则第 6-10 行会是唯一没有库存那一行的商品，而且屏幕上没有任何东西说明为什么。**这一条第一轮变异测试没抓住**：`_catalogue` stub 当时忽略 `page_size`，问 5 条和问 10 条返回一模一样。已把 stub 改成真的按 `page_size` 分页，再补 `test_every_row_on_a_full_list_carries_its_stock_line`。**教训：打桩打得比真服务宽松，变异测试就会一起放水**
  - 列表那句「Showing X of Y」现在用 ERP 的 `total`，不是本页条数——本页正好是能装下的那 10 条，用它算等于永远说「10 of 10」。装得下就不说这句（有测试守着「3 of 3」不许出现）
  验收：真机问「有什么风扇」，5 款全出来；ERP 里手工加第 6 款后再问，出 6 款

- [x] **任务 36：语音输入**（原任务 15，口径改为抽象层；不依赖前面，可插队）——**2026-09-06 完成，已部署上线并真机验收（用户拿手机发过语音，bot 听懂并走了工具）**。后端 **431 passed**（408 → 431，净增 23），另做一轮**变异测试：18 处逐个改坏，18 处全部有测试变红**（audio 分支拿掉 / 转录结果丢掉改用原 body / 空转录照样推下去 / 导演台不发 TOOL_END / mime 上报成假的 / 下载失败不接住 / 没 media id 照样下载 / 静音在屏幕上是空行 / 图片混进已处理 / mime 参数不剥 / 不认识的格式照发 / 文件名不带扩展名 / 不检查 api key / 不发语种提示 / 传输异常裸奔出去 / 没有 text 字段当成空转录 / 不 strip / 供应商写死不可换）。
  **下游确实一行都没改**：`type: "audio"` → `whatsapp_media.fetch_media` 下载 → `transcribe.transcribe` → 拿到的字**原样喂给 `_handle_text_message`**。所以口头说 "menu" 会重置 demo、口头报商品名会搜 ERP、写进 `history` 的是那句话而不是一个 audio id——这三条各有一个测试守着。
  **抽象层**：`Transcriber` 基类（一个 `transcribe(audio, mime) -> str`）+ `WhisperTranscriber` 实现 + 模块级 `transcriber` 实例，换供应商 = 多写一个类、改一行赋值，webhook 不动。**用 httpx 直接打 `/v1/audio/transcriptions`，没引 `openai` 包**——就一个 multipart POST，为它多一个 HTTP 客户端和一套失败模式不划算。
  几个决定和踩到的坑：
  - **导演台复用 `TOOL_START` / `TOOL_END`，`tool="voice.transcribe"`**，没有新增事件类型。理由：它对看屏幕的人来说就是一次「花了时间、有输入、有值得读的输出」的调用，而**新类型是现有渲染端不认识、会静默丢掉的东西**。`output` 就是那句转录文本
  - **OpenAI 认的是文件名扩展名，不是 mime**。WhatsApp 的语音是 `audio/ogg; codecs=opus`——分号后面那截是合法的 header、非法的字典 key，不剥掉就查不到扩展名。已显式建表，**表里没有的直接在本地拒掉**（`UnsupportedAudioError`），不发出去换一个什么都说明不了的 400。⚠️ **`audio/amr` 就在这一类**：WhatsApp 会发，OpenAI 不认
  - **加了语种提示 prompt**（"A customer in Malaysia... mixing English, Malay and Chinese in the same sentence"）。不给的话模型会给整段选定一种语言、把其余部分音译过去——而中英马夹杂正是验收要打的那一句
  - **空转录 ≠ 失败**。误录的语音是真会发生的事，它是一次成功的调用听到了空。所以 `transcribe()` 返回 `""`，webhook 不把它当成一轮对话推下去（否则模型被要求回答「无」，而且这一轮会被记进历史），导演台上写成 `(nothing audible)`——屏幕上一行空白读起来像 bug，不像沉默
  - **两种失败对客户是同一句话**（`VOICE_UNREADABLE_MESSAGE`，都让他打字），区别只在导演台上（`status=error` 带原因 vs `status=ok` 带 `(nothing audible)`）
  - **`TRANSCRIPTION_MODEL` 做成了配置项**，默认 `whisper-1`。唯一无法在这里验证的就是它对夹杂语句的准确度，真机跑下来不行的话应该改环境变量而不是改代码（`gpt-4o-transcribe` 是同一个端点）
  - ⚠️ **部署前必须先在 VPS 的 `backend/.env` 里确认 `OPENAI_API_KEY` 有值**，否则第一条语音会走到 `TranscriptionError("OPENAI_API_KEY is not set")`、客户看到「请打字」。另：阻塞项 G 记的那个坑仍然成立——未声明但有值的 key 会让容器起不来
  **真机验收（2026-09-06 晚，用户手机）**：三条语音，把成功和失败两条路都走到了——
  - 9:26 那条（`OPENAI_API_KEY` 还没进容器）：客户收到「Sorry, I couldn't make out that voice message - please type your question instead.」。**失败路径在真机上确认是有话说的，不是沉默**
  - 9:35 那条：bot 认出是谁，并报出他真实的 ERP 单号（`SO-2026-00001` / `SO-2026-00004`）
  - 9:36 那条（9 秒）：bot 回「我用关键字查了一下」+ `Sony WF-C710N 真无线降噪耳机 RM 328.90（含税）`。**语音驱动了工具调用，价格来自 ERP 商品档案**，验收条件达成
  ⚠️ **`env_file` 改了必须 `docker compose -f docker-compose.prod.yml up -d --force-recreate backend`**，`docker compose restart` 读的是容器创建时固定下来的那份环境变量，改了也读不到——上面 9:26 失败 / 9:35 成功这一对就是它。**部署 workflow 本身没问题**（它走 `up -d`，镜像变了就会重建）；坑在「只改 `.env` 不改代码」那种手工场景
  ⚠️ **导演台现在没有页面可看**（任务 12 未做），只有裸 SSE `/console/stream`，而且**公网打不到**——前端 nginx 只转 `/api/` 和 `/webhook/`（任务 3 的记录里写过，是故意的，那条流没有鉴权）。所以这次验收是靠「手机上的回复对不对」判定的，**没有逐字看到 Whisper 听成了什么**。夹杂句的转录准确度因此仍未被直接观测到，只知道「准到足以走对工具」
  ⚠️ **PowerShell → ssh → 远端 shell 这条路会吃掉反斜杠**。验证时 `sh -c "echo len=\${#OPENAI_API_KEY}"` 和 `grep -c "^OPENAI_API_KEY=.\+"` 都给了假结果（前者没输出、后者报 0），换成不带反斜杠的 `printenv KEY | wc -c` 立刻拿到 165。**要跑带转义的命令就开交互式 ssh，别塞进一行字符串里**

---

## 批次 07：翻得出来（2026-09-08 新增）

> 用户问「有没有什么功能可以翻查 demo 系统被使用的记录，以及与顾客的对话历史」。答案是没有——
> 导演台是 200 条内存 ring buffer、进程一重启就没且只记工具不记对话；Redis 档案只留最近 20 轮、
> 7 天过期、且**没有任何接口能列出或查询**，只能 SSH 上去 `SCAN` 手翻 JSON；`docker logs` 有时间戳
> 和 token 用量但**没有消息内容**。所以这一批是给它补一个真正的落盘层。
>
> **临时需求，不在原计划内。** 2026-09-08 用户拍板了三件事，不再重新讨论：
> 1. **存全量**：对话 + 工具调用 + token 成本，三张表
> 2. **永久保留**，先不做清理策略——demo 量级一年几万行，MySQL 无感；真要删以后加个脚本
> 3. **要读的入口**：不止写入，要 API，也要页面
>
> ### 开工前必读
>
> - **`backend` 容器已经挂在 `data_net` 上**（任务 31 为了 Redis 加的），所以直连 `infra_mysql:3306`
>   不需要动网络，prod compose 一行没改过网络配置
> - **`MYSQL_URL` 绝不能进 compose**——它带密码，这个仓库是 PUBLIC。只能走 `backend/.env`
> - **密码要 percent-encode**。`provision-project.sh` 生成的是 hex 所以碰不到，但手设的密码里一个
   `@` 或 `/` 就会让 URL 解析出错，现象是「密码不对」而不是「URL 不对」
> - ⚠️ **`_log_usage` 一直只记最后一轮的 usage**。工具循环每轮都是一次计费调用、都重发整个 system
>   prompt 和历史，所以一个走了 4 轮工具的问题，日志里报的大约是**实付的四分之一**。任务 12 要把
>   这个数字换成马币印在客户面前，所以这一批顺手修了（见任务 37 记录）

- [x] **任务 37：审计写入层**——**2026-09-08 完成，代码侧全绿 + 拿真 MySQL 跑了活体验证；线上那一半没做（要建库建用户 + 部署）**。后端 **462 passed**（431 → 462，净增 31）。
  文件：`backend/app/services/audit.py`（新增）、`backend/app/config.py`、`backend/requirements.txt`、`backend/app/services/user_store.py`、`backend/app/services/llm.py`、`backend/app/routers/chat.py`、`backend/app/routers/whatsapp_webhook.py`、`backend/tests/test_audit.py`（新增）、`backend/tests/conftest.py`、两个 compose、`backend/.env.example`

  **三张表**（`CREATE TABLE IF NOT EXISTS`，第一次写入时自己建，没有迁移框架）：
  - `chat_messages` — 每条消息一行，带 `conversation_id` / `key_id` / `channel` / `bot_id` / `role` / `content` / `source` / `created_at`
  - `tool_calls` — 每次**完成**的工具调用一行（不是每个导演台事件一行），`input` 是 JSON 列，`message_id` 指回触发它的那条客户消息
  - `model_usage` — 每次回复一行，四个 token 计数 + `api_turns`

  几个决定：
  - **存 token 不存钱**。单价和汇率都会变，换算过的金额第二天就是错的，token 计数永远是真的。谁要显示成本谁在显示时换算
  - **`conversation_id` 写入时确定，不靠查询时按时间断层猜**。选 bot / `menu` 重置各换一个新 UUID，存进 `UserProfile`。代价只是 profile 多一个字段，换来的是「一次演示」有确定边界。**没有建 `sessions` 表**——那要维护一套会话生命周期状态机，而边界信息塞进一个列就够了
  - **`source` 列（text / voice / interactive）**。到了记录这一步三者长得一模一样——语音早被转成纯文本、列表点击早被解析成它代表的那句话。而「客户是说的还是打的」正是任务 36 和 35 要证明的东西，不留这一列就永远看不出来了
  - **不引 SQLAlchemy / alembic**。三条 CREATE TABLE + 手写 SQL，不够格养一个 ORM 和它的迁移。只加了 `PyMySQL`（纯 Python，镜像不用多一个编译步骤）
  - **一个连接 + 一把锁**。FastAPI 把这些同步路径跑在 threadpool 上，PyMySQL 连接不是线程安全的，选项是连接池 / 每线程一个连接 / 一把锁。演示量级最忙的时刻是三个人同时发消息、每人三条亚毫秒 INSERT，锁是唯一没有活动部件的那个
  - **`ping(reconnect=True)`**：两场演示之间的空闲一定超过 MySQL 的 `wait_timeout`，不 ping 就是每场演示的第一行必丢

  **和 `user_store` 刻意不一样的一点：没有内存兜底。** 内存里的档案还能干活（bot 记得客户，直到容器重启），内存里的审计行只是**一条看起来被保存了、实际会丢的记录**。MySQL 挂了就丢行 + 打日志，不假装。相同的是那条底线：**任何情况下不能拖垮 demo**——每次调用都包着、失败就开 30 秒断路器、调用方永远不被告知（它在回客户的话，知道了也做不了什么）

  **顺手修掉的真 bug：token 用量一直只统计最后一轮。** `_reply_with_tools` 是一轮一轮驱动 runner 的，但 `get_reply` 只把**最后一条** message 交给 `_log_usage`。每一轮都是一次计费调用、都重发整个 system prompt 和历史，所以走 4 轮工具的一个问题，日志里报的大约是实付的 1/4。改成 `Usage` 累加器逐轮累加。⚠️ **日志行格式变了**（多了 `turns=`，数字变大），`grep "claude usage"` 出来的旧行和新行**不可比**。另外 API 抛异常时也记——已经花掉的钱不会因为失败而退回，而「一场贵且失败的演示」正是审计要能事后翻出来的东西

  **验证做到哪一步**（三栏）：
  - **代码侧**：462 passed。新增 31 个测试里有一半是「两条渠道真的调了它」——单元测试全绿而**没有任何调用点**是这类改动最容易的死法
  - **活体（真 MySQL）**：`mysql:8` 容器 + 真 `PyMySQL`，11 项全 PASS：三张表在空库上自己建出来、马来西亚 rojak 原句（中英马夹杂）`utf8mb4` 原样读回、`source='voice'`、`DATETIME(3)` 毫秒确实保留（`.938`）、`tool_calls JOIN chat_messages` 接得上、`JSON_EXTRACT(input,'$.term')` 查得出 `"earbuds"`、10000 字符的长 output 整条存下、`api_turns=4`、transcript 按序读回。**顺带把 percent-encoded 密码这条路在真库上验掉了**——故意把用户密码设成 `p@ss/word`、URL 写成 `p%40ss%2Fword`，真的通过了 MySQL 认证
  - **降级（真的把 MySQL 停掉）**：写入返回 `None` 不抛；第一次尝试花 3.98s（连接超时），随后五次合计 **0.0000s**——断路器确实在挡，不是每条消息都去撞那个超时
  - **没验的**：线上。VPS 上还没有这个库、这个用户、这个 `MYSQL_URL`（见下面的阻塞项 H）。所以**线上一行审计都还没写过**

  ⚠️ **踩坑记录**：`tests/conftest.py` 必须加一个 autouse fixture 关掉 audit 的 ContextVar——和任务 10 给 outbox 加的那个是同一个坑：生产每条消息各跑在自己的 context 里，pytest 全跑在一个里，所以「上一个测试开了 turn」会让「断言某样东西**没有**被记录」的测试**取决于它排在谁后面**而时绿时红。
  ⚠️ 另一个：`session_store` 的消息去重是进程级的、**没有任何 fixture 重置它**，所以同一个文件里两处用了 `wamid.1` 的话，第二处会被当成重复消息静默返回 `[]`。现象是 `IndexError: list index out of range`，看起来像功能坏了。

- [x] **任务 37.1：只读查询 API + 鉴权**——**2026-09-08 完成，代码侧全绿 + 真 MySQL 端到端闭环；线上没验（同阻塞项 H）**。后端 **482 passed**（462 → 482，净增 20）。
  文件：`backend/app/routers/console.py`、`backend/app/config.py`、`backend/app/models.py`、`backend/app/services/audit.py`、`frontend/nginx.conf`、`backend/.env.example`、`backend/tests/test_console_history.py`（新增）

  **两个端点**：
  - `GET /console/history` — 列对话，按最近活动倒序，可按 `key`（手机号）和 `bot_id` 过滤，分页。每行带消息数、工具调用数、token 合计
  - `GET /console/history/{conversation_id}` — 一通对话的逐条 transcript，**每次工具调用挂在触发它的那条客户消息下**

  **⚠️ 这个任务改变了 `/console/stream` 的既有行为：它现在要 token 了。** 任务 3 记录里那条验收方式（`curl -N localhost:8392/console/stream`）**不再直接可用**，要带 `?token=...`。这是故意的——任务 3 和任务 12 都写过「这条流没有鉴权，靠前端 nginx 不转 `/console/` 保护」，而这个任务恰恰要加那条转发规则，所以那层保护当场消失，必须换成真的。

  几个决定：
  - **`CONSOLE_TOKEN` 没配 = 关闭（503），不是放行。** 和聊天侧读空密码的方式**相反**，刻意的：聊天侧放进来的人看到一个 demo，这一侧放进来的人看到**每一个客户的完整对话记录 + 真实 ERP 订单数据**。忘了配一行环境变量，代价应该是少一个功能，不是泄露一批数据
  - **token 可以走 query string**，因为 `EventSource` 设不了请求头（任务 12 的记录里点过这件事）。代价是它会进代理日志——接受，因为这一侧全是只读且 token 可轮换。header `X-Console-Token` 同样接受，两者都用 `secrets.compare_digest` 比，避免逐字符试
  - **工具数和 token 合计是分开查再合并的，没有 JOIN 进主查询。** 一个 GROUP BY 同时 JOIN 两张一对多的表会把行数乘开，`COUNT(*)` 在乘积上得出的数字是错的、而且错得很像真的
  - **手机号搜索走 `identity()` 归一化**，所以 `017-394 8123` 能找到 webhook 以 `60173948123` 存下的那通对话——这正是任务 33 那条归一化规则，用在搜索上
  - **`display_name` 从 Redis 档案取，取不到就是 None。** 档案 7 天过期而 transcript 不过期，所以两个月前的对话只显示号码——这是诚实的答案，不是缺行

  **验证做到哪一步**（三栏）：
  - **代码侧**：482 passed。20 个新测试里 5 个是打门的（无 token 401 / 未配置 503 / 错 token / header 和 query 两种都收）
  - **活体（真 MySQL + 真 HTTP 路由，只有模型是假的）**：一场对话从 `/api/chat/*` 写进去，再从 `/console/history` 整通读出来，18 项全 PASS。关键几条：未鉴权读 **401**；列表数出「3 条消息（开场白 + 客户 + bot）、1 次工具调用、12000 input token、channel=web」；**用 `017-3948123` 这个国内写法搜到了以 `60173948123` 存的那通**、换个号码搜不到；transcript 顺序 `assistant → user → assistant`；rojak 原句 `Boss 这个 earbuds 还有 stock 吗? 我要 2 个` 原样读回；**工具调用挂在客户那条消息下、bot 那条下面是空的**；`input` 以 dict 形式回来（含中文 key `数量`）；未知 id 404
  - **没验的**：线上（没库没用户，阻塞项 H）；nginx 那条 `/console/` 转发规则**只是写对了配置，没有真跑过一次请求穿过它**——本地验证走的是 TestClient，绕过了 nginx

- [x] **任务 37.2：查询页面**——**2026-09-08 完成，代码侧全绿 + 真浏览器实地走过一遍；线上没验（同阻塞项 H）**。前端 `tsc -b` + `vite build` + `oxlint`（0 warnings 0 errors）都过。
  文件：`frontend/src/pages/History.tsx`（新增）、`frontend/src/api.ts`、`frontend/src/App.tsx`、`frontend/src/App.css`

  ⚠️ **下面两条当天就被任务 37.4 的合并推翻了，留着是为了说明来龙去脉，别照着读**：入口现在是 **pathname `/history`**（跟任务 12 的 `/console` 一样在 `main.tsx` 里分流），token 存 **localStorage**、两块屏共用一份。以下是原文：
  ~~**入口是 `#history`，不是路由，也不从任何地方链接过去。**~~ 这个 app 没有 router，为运营者自己开的一块屏引一个进来不值得；不放链接是因为**真正守门的是 token**，而在给客户看的页面上放一个链接只会招人去猜（**这半条仍然成立**）。
  - ~~**token 存 sessionStorage 不存 localStorage**~~：这块屏显示的是每一个客户的完整对话，标签页一关就要重输是「整个下午不用重打」和「笔记本递给别人时不留东西」之间的正确取舍。**改成 localStorage 的理由见 37.4**：任务 12 那份支持从 URL `?token=` 传入并把 token 从地址栏擦掉，更适合「笔记本上开链接然后投屏」
  - **401 会清掉 token 并退回输入框**，否则错 token 会卡在一个反复失败、又没地方改的界面上
  - **成本在显示时换算，不存**（`RM = (in×$5 + out×$25)/1M × 4.7`）。和后端存 token 不存钱是同一个理由：单价和汇率都会变，换算过的历史行第二天就是错的
  - 自带一套深色变量，不复用聊天那套——这块屏是在运营者笔记本上、旁边开着两个后台标签页的时候看的，**不该一眼被认成旁边那个给客户看的 demo**

  **验证做到哪一步**（三栏）：
  - **构建侧**：`tsc -b` 过、`vite build` 过、`oxlint` 0 warnings 0 errors
  - **真浏览器**（Chrome 打真的 nginx + 真的 backend + 真的 MySQL，灌了两个客户三通对话）：
    - **补上了任务 37.1 记录里那条「nginx 转发没真跑过」**——`curl` 穿过 nginx 打 `/console/history`：**不带 token 401、带 token 200**
    - token 门 → 列表 → 点开 → transcript，整条路走通。列表三行，数字对得上（`5 条 · 4 次工具 · RM 0.6877`）
    - transcript 读出了整场戏：开场白 → 客户 rojak 提问 → **两次工具调用挂在客户那条消息下**（`erp_search_sku 201ms ok` / `erp_check_stock 96ms ok`）→ bot 报真实价格 → **客户改主意「算了，改成 3 个」** → `erp_create_sales_order 1204ms ok` + `crm_create_lead 880ms error`（**失败那条是红框**）→ bot 回真实单号
    - 展开一次工具调用：入参 JSON 和返回值都在，中文商品名没乱码
    - 顶栏：`25,822 in / 688 out · 7 次 API · RM 0.6877 · 缓存命中 1,097`
    - **搜索归一化在浏览器里验掉了**：输 `017-394 8123`，另一个号码那条消失，只剩这个号码的两通
  - **没验的**：线上；手机/窄屏下的排版（只在 1045px 宽的桌面视口看过）；`/console/stream` 那条 SSE 穿过新加的 nginx 规则**没真订阅过**（只验了 `/console/history` 这条普通请求；`proxy_buffering off` 是照 SSE 的要求写的，没实测）

- [x] **任务 37.3：时区**——**2026-09-08 完成**（用户看到 37.1 的命令里容器名写错、去翻 `vps_infra/docker-compose.yml` 时顺带发现的）。后端 **484 passed**（482 → 484）。
  文件：`docker-compose.yml`、`docker-compose.prod.yml`、`backend/app/services/audit.py`、`backend/tests/test_audit.py`

  **问题**：`vps_infra` 给它四个容器每一个都设了 `TZ: Asia/Kuala_Lumpur`，而 **`ai_chatbot` 的两个 compose 都没设**——这个服务此前从来不需要一个时钟，所以没人注意。于是 backend 跑在 UTC 上，`_timestamp()` 走 `time.localtime()`，**审计行存的是 UTC**，而 `DATETIME` 列不带时区、事后无从更正。晚上 9 点在吉隆坡跑的那场演示，会被归档在 `13:00`，按发生的时间根本翻不到。
  **修法是给容器设 TZ，不是在代码里硬编码时区**：`DATETIME` 存的是字面值，让整个容器（日志、审计、将来的清理脚本）共用一个时钟，比在三处各转一次可靠。⚠️ **线上 `docker logs` 的应用日志时间戳也会从 UTC 变成 KL 时间**，和 2026-09-08 之前的行不可比——但会和 vps_infra 其它容器对齐。**时机是干净的**：线上此时一行审计都还没写过（代码没推），所以没有历史数据要迁移。

  ⚠️ **补时区测试时抓到一个自己写的真 bug**：`int(seconds % 1 * 1000)` 把一个二进制表示已经压低了一点的值再截断，**`.938` 存成了 `.937`**。差一毫秒本身无所谓，但那是两行记录用来排序的那一列，不该有个舍入错误。改成走 `datetime.fromtimestamp(...).strftime(...)`。
  **验证**：真 MySQL + `TZ=Asia/Kuala_Lumpur` 的真容器，三项全 PASS——容器 `time.tzname` 是 `('+08','+08')`；写入时刻 `23:18:19.034` 读回，与同一瞬间的 UTC `15:18:19` **相差正好 8 小时**；`.938` 读回是 `938000` 微秒。另有一个 pytest 用 `tzset` 把 KL 和 UTC 两种时区各跑一遍，守住「跟随容器时区」这个契约（Windows 上自动跳过）。

- [x] **任务 37.4：和任务 12 的合并**——**2026-09-08**。批次 07 是在**不知道任务 12 正在被另一个 session 做**的情况下开工的，两边同时改了 `console.py` / `llm.py` / `config.py` / `nginx.conf` / `api.ts`。合并后后端 **493 passed**，前端 `tsc -b` / `vite build` / `oxlint` 全过，另拿真 MySQL 跑了一遍合并后的活体验证（10 项全 PASS）。**走 merge 不走 rebase**：两条独立的工作汇合，不该把已经验过的 commit 重写一遍。

  **两边独立发现了同一个 bug**——token 用量只统计工具循环的最后一轮。修法不同，取了任务 12 的：
  - 任务 12：**每次 API 调用**记一次（日志 + 导演台 USAGE 事件 + `cost.py` 算好的马币）
  - 任务 37：`Usage` 累加器，每次**回复**记一次合计
  - **取 per-call**，因为按调用存的行能求和成总数，按回复存的总数拆不回调用——而「这个答案跑了几个来回」正是导演台要在屏幕上回答的问题。`model_usage` 因此**去掉 `api_turns` 列、加上 `cost_myr`**，轮数改成 `COUNT(*)`

  **另外四处统一**（都是「同一个东西有两份实现」，不统一迟早在客户面前显示成两个不同的数字）：
  - **成本只有一个公式**：`app/console/cost.py`（按模型分档、cache write ×1.25 / read ×0.1、汇率 4.30）。我原来在 `History.tsx` 里自己算的那份（汇率 4.7、不算缓存）删掉了，页面改成显示后端返回的 `cost_myr`。**价格在每次调用发生时就落库**——正因为费率会变：拿今天的费率给两个月前的调用重新定价，回答的是没人问过的问题
  - **鉴权只有一道门**：`require_console_token`，header 和 query 都收（`EventSource` 设不了 header，所以 query 必须支持）。任务 12 的 `_check_token` 删掉了
  - **token 只有一份**：`localStorage` + key `console_token`，两个页面共用，函数抽到 `api.ts`。取的是任务 12 的方案——它支持从 URL `?token=` 传入**并把 token 从地址栏擦掉**，比我原来的输入框更适合「笔记本上打开链接、然后投屏」
  - **路由只有一种**：`main.tsx` 里按 pathname 分流（`/console` / `/history` / 其余）。我原来的 `#history` hash 路由删掉了

  ⚠️ **合并时抓到的两个真问题**：
  - **我加的 `location /console/` 会把导演台页面抢走**。任务 12 刻意只转 `= /console/stream` 这一条精确路径，注释写着「`/console` 自己是 SPA 渲染的页面」——而我按前缀转发，`/console/`（带尾斜杠，`main.tsx` 明确当页面处理）就会落到后端拿 404。收窄成 `location /console/history`
  - **任务 12 的三个测试直接调 `console.stream(token=...)`**，token 移进依赖后必然坏。改成走 TestClient 打 HTTP——那才是部署后真实经过的路径。⚠️ **但测 SSE headers 那个不能走 TestClient**：`http.stream()` 会挂在一条永不结束的流上，整个测试套件超时 10 分钟才被杀。那一个保持直接调用（它本来也只测 headers）

- [x] **任务 37.5：上线**——**2026-09-08/09 完成，审计日志线上真的在写了**。批次 07 到此全部落地。

  **上线时卡了两处，都不是代码问题，但都值得记：**
  - **MySQL `Access denied for user 'ai_chatbot_app'@'172.18.0.8'`。** ⚠️ **MySQL 的 1045 对「密码错」和「用户/host 不存在」返回的是同一条错误**（故意的，防用户名探测），所以**光看日志分不出来**。排查顺序应该是先 `SELECT user, host FROM mysql.user WHERE user='...'` 确认用户在哪些 host 上存在、`SHOW DATABASES LIKE '...'` 确认库在，**排除掉这两个之后**剩下的才是密码。这次两项都正常，最后是重设密码解决的
  - **`CONSOLE_TOKEN` 输进去进不了页面。** 和上面无关的另一件事，最后是浏览器里那份和 `.env` 里的有出入。**别手打 48 位 hex**，用 `echo "https://.../history?token=$(sed -n 's/^CONSOLE_TOKEN=//p' .env)"` 生成整条链接

  **排查时用的脱敏命令**（不暴露值，一次看清引号 / 尾随空格 / CRLF / percent 编码四类问题）：
  ```bash
  sed -n -e '/^CONSOLE_TOKEN=/p' -e '/^MYSQL_URL=/p' backend/.env | sed 's/[A-Za-z0-9]/x/g' | cat -A
  ```
  这次结果是两行都干净（`.env` 是 LF，无引号），从而把「compose 不剥引号」和「Windows 行尾」这两个最常见的猜测**排除掉**——先排除比先猜快。

  **顺带修掉两个真 bug**（都是这次事故直接暴露的，不是猜的）：
  - **查询页面的 token 门被拒后一言不发。** 401 → 丢掉 token → 退回登录框、输入框空着，读起来是「按钮坏了」而不是「token 不对」。任务 12 的导演台早就有 `gateNote` 做这件事，只有这个页面漏了。现在会分开说「token 不对」和「后端没配 CONSOLE_TOKEN」两种情况
  - **一次连不上刷 30 行 traceback。** `_go_offline` 带着 `exc_info=True`，而每条入站消息撞一次断路器就是一整段 pymysql 调用栈——把 demo 自己的日志全埋了。那些帧永远是同一条路径、从来不 actionable，而驱动自己那句 `(1045, "Access denied for user ...")` 就是全部诊断信息。改成一行

  ✅ **降级设计被一次真实事故验证了**：MySQL 连不上的那整段时间里，日志是 `audit log unavailable, dropping rows`，而**对话照常跑完**——Claude 回了、WhatsApp 收了 200。丢的只有审计行。这正是「没有内存兜底、但绝不拖垮 demo」当初的设计意图。

  **线上实测**（重建容器后）：`/api/bots` 200、`/history` 200、`/console` 200、`/console/history` 无 token **401**（不是 503，证明 `CONSOLE_TOKEN` 在容器里）、webhook verify 403、前端是带修复的最新包。

- [x] **任务 37.6：history 和 console 合成一个页面**（2026-09-14 新增，计划经用户确认；**37.6a、37.6b 均已完成**，37.6a 已上线验证，37.6b 待上线）
  **用户的需求**：两个页面合成一个，点 history 里某个顾客，就看到这个顾客的 console。已拍板的四点：
  1. 点进顾客后，**过去的记录**和**正在进行的对话实时滚动**都要
  2. 现在的「所有人混在一起的实时流」**先保留**（作为默认视图），确认没用以后再删
  3. 单独做，不并进任务 27（导演台 v2）
  4. 接管 / 人工回复 / 结束演示这几个按钮，在顾客视图里**只作用于这个顾客**（我定的默认，用户未反对）

  **现在做不到的原因**：导演台的事件（`ConsoleEvent`）里**没有记录属于哪个顾客、哪通对话**，前端没法按顾客筛。过去的对话倒是已有数据：`/console/history/{conversation_id}` 本来就返回每条消息 + 每次工具调用。

  **拆成两个子任务**（按 CLAUDE.md「超 3 个文件先拆分」）：

  - [x] **37.6a 后端：每条事件带上 `key_id` 和 `conversation_id`**——**2026-09-14 完成，871 passed（859 → 871），变异 7/7 全红；线上没验**。**实际只加了 `key_id`，和计划有两处偏离，见本条末尾「完成记录」**
    文件：`backend/app/console/events.py`、`backend/app/services/handover.py`、`backend/app/services/notify.py`、`backend/app/routers/whatsapp_webhook.py`、测试
    - `ConsoleEvent` 加两个可选字段 `key_id` / `conversation_id`
    - **在 `events.emit` 里统一补上**：调用时没传就读 `audit.current()`（当前这一轮对话本来就知道自己属于谁）。已查过不会循环引用：`events.py` 不依赖任何 app 模块，`audit.py` 也不引用 `events`。这样对话内发出的事件（22 处里的大多数，模型的工具调用、语音/图片/文件下载、计费）**一行调用处都不用改**
    - **对话之外发出的要在调用处显式传**：handover 的开始/结束（从导演台 POST 触发）、主动推送（后台线程晚点才发）、发送循环里的 `send_failed`（那时这一轮已经关了）。`tools_switched` 是全局开关，本来就不属于任何顾客，保持为空
    - 验收：单测覆盖「对话内自动带上」「对话外显式传入」「全局事件为空」三种；**再加一条守卫测试**：跑一遍完整的一轮（webhook → 模型 → 工具 → 发送），断言期间发出的每条事件都带了 `key_id`——漏一个调用点，那条事件就只会出现在「全部」视图里，而这种漏法看界面是看不出来的
    - 不改路由：前端照旧订阅同一条 `/console/stream`，所以 `nginx.conf` / `vite.config.ts` 不用动，掉不进任务 19.1 那个「部署了但打不到」的坑

    **完成记录（2026-09-14）**
    文件：`backend/app/console/events.py`、`backend/app/routers/whatsapp_webhook.py`、`backend/app/routers/chat.py`、`backend/app/services/handover.py`、`backend/app/services/notify.py`、`backend/app/session_store.py`、`backend/tests/conftest.py`、`backend/tests/test_console_event_identity.py`（新增）

    **偏离 1：计划里「从当前这一轮对话读取顾客身份，对话内的事件调用处都不用改」，这句是错的。** 动手前逐处核对才发现：**语音转写、图片下载、文件下载这几类事件，是在这一轮对话开始之前发出的**——它们在 `dispatch_message` 里先跑，`_handle_text_message` 才打开审计这一轮。按计划做，这几类事件会一律没有顾客。
    改成：**在识别出发件人的那一刻记下「正在服务的顾客」**（`events.set_customer`，ContextVar，和 outbox / 推送队列同一个做法），这期间发出的所有事件自动带上。设在两个入口：WhatsApp 的 `dispatch_message`、网页聊天的 `send_message`。发送循环里的 `send_failed` 和 `dispatch_message` 在同一个上下文里，也自动带上。
    **对话之外发出的显式传**：人工接管的开始 / 结束（从导演台按按钮，没有正在服务的顾客）、主动推送（`threading.Timer` 线程**不继承任何上下文**）。推送的收件地址是 `profile.phone`，是号码的书写形式、未必是记录的归档 key，所以用 `identity()` 归一化后再放上去。`tools_switched` 是全局开关，本来就不属于谁，留空。

    **偏离 2：没加 `conversation_id`。** 按计划本身的设计，37.6b 实时部分**按 `key_id` 筛**、去重**按 `tool_use_id`**、过去记录**从数据库按对话取**——实时事件上的 `conversation_id` 没有任何消费方；而推送、接管这些事件拿不到它，只会变成一个时有时无的字段。不写投机性代码。

    **顺带修的一个测试隔离问题**：新测试文件加进来后，一条老测试（`test_the_file_is_still_in_front_of_the_model_on_the_question_after_it`）**只在全套跑时挂**、单独跑能过。原因：两边都发了 `wamid.60129996002.1`，WhatsApp 的「处理过的消息 id」记录在测试之间**不清空**，新测试先跑，老测试的第二条消息被当成重复消息跳过了。**根因是去重记录（和每日计数）没有测试间重置**，任何两条复用消息 id 的测试都会互相干扰、谁输取决于文件顺序。给 `SessionStore` 补了 `reset()`、conftest 加了 autouse 重置——和 `user_store.reset()` / `doc_store.clear()` 同一个做法。**我的测试号码一个没改**，全套照样通过，证明是重置修好的，不是换号绕过去的。

    **验证**：
    - 新测试 12 条，**从真实入口驱动**，不是单测 `emit`：语音消息、照片、Meta 拒收的回复、识别不出发件人的消息、网页聊天、人工接管、主动推送、写法不同的号码。每条都断言**这一条入口发出的所有事件**都带着正确的 `key_id`——漏一处，事件只会出现在「全部」视图里，界面上看不出来
    - 模型的工具调用用「打桩的 `get_reply` 在调用内部发事件」模拟：真实的 tool runner 就是从同一条调用栈发的
    - **变异 7/7 全红**：webhook 不记顾客 / 网页聊天不记 / emit 不读上下文 / emit 不认显式传入 / 接管开始不显式传 / 推送不归一化 / 推送不显式传
    - **871 passed**
    - ~~**没验**：线上事件是否真的带上了 `key_id`~~ → **2026-09-14 线上验了**：部署后用户在本机 PowerShell 读 `/console/stream?replay=true`，得到 `1 "key_id":"60168623902"`，**没有一条是空 key**。只有 1 条（一次计费事件），**工具调用那一类线上没覆盖到**；它在 37.6b 的本地端到端测试里补验了
    - **没动**：`frontend/src/api.ts` 的 `ConsoleEvent` 类型。多出来的字段前端直接忽略，按计划属于 37.6b

  - [x] **37.6b 前端：合并成一个页面**——**2026-09-14 完成，`tsc -b` / `vite build` / `oxlint`（0 警告 0 错误）全过，本地真浏览器实测通过；线上没验**。见本条末尾「完成记录」
    文件：`frontend/src/pages/Console.tsx`、`frontend/src/pages/History.tsx`（列表和详情组件并过去，页面本身删掉）、`frontend/src/main.tsx`、`frontend/src/api.ts`、样式
    - **布局**：左边是现在 history 的对话列表（按电话搜，最新在上）；右边默认是「全部」实时流；点列表里一条 → 右边切成这个顾客的视图，再点「全部」切回来
    - **顾客视图 = 过去 + 实时**：先用 `/console/history/{conversation_id}` 画出这通对话过去的消息和工具调用（console 样式），再接上实时流里 `key_id` 等于这个顾客的事件
    - **按顾客（`key_id`）接实时，不按对话（`conversation_id`）**：顾客中途从菜单换一个 demo 会开一通新对话，按对话筛的话画面会突然安静，而他明明还在说话
    - **在浏览器里筛，不加后端接口**：拿到 token 的人本来就能看到全部事件，服务端筛不增加任何保护，只多一条要登记路由的接口
    - **去重**：点进一个正在进行中的顾客时，同一次工具调用可能既在数据库的过去记录里、又从实时流里来一遍——按 `tool_use_id` 合并
    - **成本**：「全部」视图照旧显示页面收到的总和；顾客视图显示这通对话在数据库里的成本 + 之后实时进来的计费
    - **旧链接**：`/history` 跳转到合并后的页面，已经收藏的链接不失效
    - 验收：`tsc -b` / `vite build` / `oxlint` 过；**真浏览器实测**——打开默认是全部实时流；搜电话找到顾客点进去，先出过去记录；用手机再发一条，右边马上出现他的新调用，**别的顾客的调用不出现**；接管 / 回复只作用于他；`/history` 旧链接能跳过来

    **完成记录（2026-09-14）**
    文件：`frontend/src/pages/Console.tsx`、`frontend/src/pages/Console.css`、`frontend/src/components/ConversationList.tsx`（新增）、`frontend/src/components/Transcript.tsx`（新增）、`frontend/src/transcript.ts`（新增）、`frontend/src/api.ts`、`frontend/src/main.tsx`、`frontend/src/App.css`、`frontend/src/pages/VerticalAdmin.tsx`（只改一行过期注释）；**删除** `frontend/src/pages/History.tsx`

    **做了什么**：左边是对话列表（按电话搜），最上面一条是「全部 · 实时流」，打开默认选它；右边在「全部」时就是原来的导演台，点一个顾客就切成他的 console——上半截是数据库里这通对话的消息和工具调用，下面接实时流里 `key_id` 等于他、且上半截还没有的调用（按 `tool_use_id` 去重）。接管 / 回复 / 交回 / 结束演示在顾客视图里只作用于这个顾客；顾客还在 bot 手里时多一个「人工接管」按钮。`/history` 打开的也是这个页面。

    **和计划的偏离与补充**
    - **顾客视图的成本只显示数据库的数，不叠加实时计费**：上半截每 5 秒重读一次，数据库成本自己会跟上；再叠实时事件，读一次就重复算一次。「全部」视图照旧是页面收到的总和，标签改成「全部 · 本页打开以来」，顾客视图叫「这通对话」——两个数含义不同，之前那个「本次会话成本」名字会误导
    - **对话列表每 10 秒自己刷新**：计划没写。原 history 页面只在搜索时刷新，放进导演台就意味着「刚在手机上开始的顾客」点不到
    - **过去的记录每 5 秒重读**：实时流只有工具调用、没有聊天文字，不重读的话顾客新说的话永远不出现
    - **数据库读失败时明说**：浏览器测试里发现的——停掉 MySQL 后上半截就不动了，但页面什么都没说，看的人会以为顾客安静了。现在会写「这通对话读不出来，下面是上一次读到的内容」
    - **`listConversations` / `readConversation` 改成显式传 token**：原来从 localStorage 读，导演台可能拿着一个 localStorage 没存进去的 token（隐私窗口、URL 里带进来的），会出现实时流正常而列表 401
    - `money` / `toolUseIds` 挪到 `src/transcript.ts`：放在组件文件里 oxlint 报 `only-export-components`（2 条警告），原来前端是 0 警告
    - 删掉了 `App.css` 里只有 history 页面自己用的规则（全屏容器、token 门），对话列表和记录的样式保留；它们用的 `--con-*` 变量改在 `.console` 上指向导演台的配色

    **验证（本地真浏览器，没用任何真实凭据）**
    本地没有 Claude API key，也不想碰线上 token，所以搭了一套：本地 `mysql:8` 存审计、一个**假的 Messages API**（第一次请求回 `hotel_search_rooms` 工具调用、带回工具结果后回文字）、后端用自编的本地 console token 指向它。酒店 bot 的工具只读自己的 JSON，不打 ERP/CRM。**事件、审计写入、工具执行器走的都是真实代码**，两个顾客 `60123330001` / `60123330002` 通过网页聊天真实入口发消息。
    - **顺带补验了 37.6a 线上没覆盖到的一类**：`/console/stream` 回放里，工具调用的 `tool_start` / `tool_end` / `usage` **每条都带着正确的 `key_id`**
    - 打开 `/console`：默认「全部」，左边两个顾客，右边两条 `hotel_search_rooms`，成本「全部 · 本页打开以来」
    - 点 001：上半截是他的欢迎语 / 提问 / 工具调用 / 回复；**下面没有重复的实时行**（去重生效）；**002 的调用不出现**；成本「这通对话」
    - 停在 001 上、先 002 再 001 各发一条：因为读页面慢于 5 秒，新调用已被重读并进上半截，**分不清是否先实时出现**——所以**停掉 MySQL 再各发一条**：上半截停在两轮、成本已从 RM 0.0129 刷新到 RM 0.0258；分隔线「实时 · 还没进记录的调用」下**只有 001 的那一行**，002 早一秒发的那次没有出现。**实时这一半就是这样证实的**
    - 点「人工接管」：出现只针对 001 的面板（交回 bot + 回复框），实时区立刻出现 `handover` 行、入参是 001；左边列表自动刷新、001 排到最前
    - 「交回 bot」→ 切回「全部」：六次调用 + `handover` 行变成 `back with the bot after 27s`，面板消失
    - 打开 `/history`：就是这个导演台
    - 浏览器控制台只有插件自己的两条报错，页面无报错、无 React key 警告
    - **没验**：人工回复真的发出去（本地没配 WhatsApp，发了也只会是 `send_failed`）；线上表现；多个浏览器同时开的情况

  **先后顺序**：37.6a 先做先上线。它对现有页面**没有任何可见变化**（只是事件多了两个字段），可以单独部署验证，确认线上事件确实带上了顾客身份，再做 37.6b。

  **待清理项（按用户说的）**：确认「全部」视图没人用之后删掉。

- [x] **任务 37.7：左边列表按顾客合并**（2026-09-14 新增，方案经用户确认）——**完成，后端 880 passed，前端 `tsc -b` / `vite build` / `oxlint` 全过，本地真浏览器实测通过；线上没验**
  **起因**：37.6b 上线后用户截图，左边列表一通对话一行，用户自己的号测了十几次，满屏都是「Kelvin Peng」。
  **用户拍板的方案**：列表**一个顾客一行**（汇总：最后活跃、共几通对话、用过哪些 demo、总消息 / 总工具调用 / 总成本）；**点顾客展开他的对话**（最新在上），**先显示最近 20 通、底下「加载更早」**；点某一通，右边还是 37.6b 的顾客视图。「展开放在左边列表里、不是右边」是我提的、用户确认的。
  （用户否掉了另一种理解：把一个顾客所有对话串成一条时间线。）

  文件：`backend/app/routers/console.py`、`backend/app/models.py`、`backend/tests/test_console_history.py`、`frontend/src/api.ts`、`frontend/src/components/ConversationList.tsx` → `CustomerList.tsx`（改名 + 重写）、`frontend/src/pages/Console.tsx`、`frontend/src/App.css`

  **后端**：新接口 `GET /console/history/customers`，按 `key_id` 分组汇总；工具次数和成本仍然分开查（和原列表同一个理由：join 两张一对多的表会把行数乘出去，COUNT 错得像真的）。**顾客的对话列表没有新接口**——原来的 `/console/history?key=…&limit=20&offset=…` 本来就支持。
  - ⚠️ **路由顺序是个坑**：`/history/{conversation_id}` 会把 `customers` 当成对话 id。新路由**写在它前面**，并有测试专门断言返回的是顾客列表的形状
  - 放在 `/console/history/` 下，线上 nginx / vite 的前缀转发规则都覆盖，**两个配置文件没改**，`test_console_routing.py` 照样过
  - `tool_calls` / `model_usage` 两张表的 `key_id` 没有索引，汇总是扫表。demo 量级是几千行，现在不是问题，记一笔
  - 测试先红后绿（7 条新测试 + 两个「没 token 不能进」的参数化用例加上了新路径）。**没做变异测试**

  **前端**
  - 一次只展开一个顾客。展开后他**最新的 20 通**每 10 秒刷新一次（他在你看着的时候开始新演示，会自己出现在最上面）；「加载更早」拿来的旧页不再刷新。合并时按 `conversation_id` 去重、按最后活跃排序——顶上插进新对话会让下一次「加载更早」多拿到一条重复的（去掉），但**不会漏掉一条**
  - 「加载更早」按「上一页是不是满 20 条」判断还有没有更多

  **做的过程中发现并修的一个 37.6b 的问题**：点开一个顾客的**旧对话**时，分隔线「实时 · 还没进记录的调用」下面挂着**他其他所有对话**的调用。原因是 37.6b 实时部分按顾客筛、但只和当前这通对话去重——那些调用早就进记录了，只是在别的对话里。37.6b 时列表一通对话一行、同一顾客的多通对话散在各处，看不出来；37.7 把它们摆在一起就暴露了。
  **修法**：只显示**打开这个视图之后**发生的调用（留 5 秒余量，覆盖点开那一刻正在进行、还没写进数据库的调用和两台机器的时钟差）。打开之前发生的调用都已在数据库里、在各自的对话里；之后发生的就是正在发生的，包括他在你看着的时候开始的新演示。两边都是 epoch 秒，不涉及时区。分隔线文字改成「实时 · 这位顾客刚发生的调用」

  **验证（本地真浏览器，本地 MySQL + 假 Messages API + 自编的本地 token，没用任何真实凭据；和 37.6b 同一套）**
  造数：顾客 001 23 通对话（hotel / realestate 交替），顾客 002 1 通。
  - **SQL 在真 MySQL 上跑通**：001 = 23 通 / 69 条 / 23 次工具 / RM 0.2967（= 23 × 0.0129），demo = hotel / realestate；002 = 1 通；001 的第二页（offset 20）正好 3 通
  - 列表两行，汇总文字正确
  - 展开 001：**正好 20 通 + 「加载更早」**；点「加载更早」→ 发出 `offset=20` 请求 → **23 通、按钮消失**
  - 点一通 → 右边是那通对话的记录
  - **修复验证**：展开 001、打开第 5 新的一通（conversation 19）→ **没有分隔线、0 行实时**（修之前这里挂着 22 行）；停在这里让 001 发一条 → **分隔线出现、只有 1 行**（那次新调用），文字是新的
  - 让 001 开始一通新对话 → 11 秒内展开的列表**变成 21 通、新的在最上面**，右边仍停在 conversation 19，「加载更早」还在；顾客行在下一次刷新后变成「12:34 · 24 通对话」
  - **没有遮挡**：用 `elementFromPoint` 查了每个顾客行和对话行的中心点，点到的都是它自己

  **没解决 / 没证实的**
  - **测试工具「页面加载后第一次点击不生效」**，复现两次。排查过：同一个按钮用页面内 JS `.click()` 第一次就生效（`aria-expanded` false → true）、中心点命中测试没有遮挡——**所以不是页面代码的问题**；推测是测试工具在 2560 宽视口和 1568 宽截图坐标系之间换算有偏差，**没证实**。之后的点击改用页面内 JS 触发
  - 有一次读页面时顾客行的汇总比实际慢了一轮刷新，推测是测试标签页不在前台、浏览器节流了定时器，**没证实**；再等一轮就对了
  - 线上表现；人工回复真发到 WhatsApp

### 阻塞项（需要用户处理）

- [x] ~~**H. 在 VPS 上给这个项目建 MySQL 库和用户**~~——**2026-09-08 用户已完成**：库建好了、`.env` 里 `MYSQL_URL` 和 `CONSOLE_TOKEN` 都配了、容器已重建。⚠️ **容器名是 `infra_mysql`，服务名才是 `mysql`**，所以不挑目录的写法是 `docker exec -it infra_mysql mysql -uroot -p`。以下是原文：
  ```bash
  cd /srv/infra && docker compose exec -T mysql mysql -uroot -p
  CREATE DATABASE ai_chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'ai_chatbot_app'@'%' IDENTIFIED BY '<openssl rand -hex 16>';
  GRANT ALL PRIVILEGES ON `ai_chatbot`.* TO 'ai_chatbot_app'@'%';
  FLUSH PRIVILEGES;
  ```
  然后往 `/opt/ai_chatbot/backend/.env` 加一行 `MYSQL_URL=mysql://ai_chatbot_app:<密码>@infra_mysql:3306/ai_chatbot`。
  - `scripts/provision-project.sh` 也能干这事，但它强制要第二个参数（Redis 区段），而本项目的 16 已经分过了
  - ⚠️ **改完 `.env` 必须 `docker compose -f docker-compose.prod.yml up -d --force-recreate backend`**，`restart` 读不到新的环境变量（任务 36 的记录里那对 9:26 失败 / 9:35 成功就是这个坑）
  - **不加也不会坏**：`MYSQL_URL` 空 = 审计关掉，demo 行为和现在完全一致，只是什么都不记

- [x] ~~**I. 线上给 verticals 建库**~~——**2026-09-13 用户已完成并实测通过**。线上 `curl -H "X-Console-Token: …" /api/verticals/realestate/listings` 返回 **8 条房源**，价格与 `bots/data/realestate.json` 一致（PROP-202 = RM 620,000）。库、grant、`.env` 里的 `VERTICALS_MYSQL_URL` 全到位；**表和那 8 条数据没有任何人手动建**，是首次调用时 `verticals/db.py` 建表、`realestate/models.py` 的 `seed_listings()` 播进去的。
  ⚠️ **这一步的代价是一次线上事故**，教训见下面「运维教训：2026-09-13」。以下是原文：
  ```sql
  CREATE DATABASE ai_chatbot_verticals CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  GRANT ALL PRIVILEGES ON `ai_chatbot_verticals`.* TO 'ai_chatbot_app'@'%';
  FLUSH PRIVILEGES;
  ```
  ⚠️ **容器名是 `infra_mysql`，服务名才是 `mysql`**（和阻塞项 H 同一个坑）。
  然后往 `/opt/ai_chatbot/backend/.env` 加一行
  `VERTICALS_MYSQL_URL=mysql://ai_chatbot_app:<密码>@infra_mysql:3306/ai_chatbot_verticals`
  （密码就是 `MYSQL_URL` 里那个，**percent-encode**），再
  `docker compose -f docker-compose.prod.yml up -d --force-recreate backend`——`restart` 读不到新环境变量。
  - **不加也不会坏**：房产和餐饮没有后台而已，demo 其余部分行为完全不变。但和审计层不同，
    这个不是静默的：第一次调用就会抛 `StoreUnavailable`，日志里有一行说清楚

---

## 运维教训：2026-09-13 —— 一条少了 `-f` 的 compose 命令把线上打挂了

**没改一行代码，线上后端死了十几分钟。** 起因是执行阻塞项 I 的最后一步（改完 `.env` 重建容器），
在 `/opt/ai_chatbot` 敲了 `docker compose up -d --force-recreate backend`——**少了 `-f docker-compose.prod.yml`**。

### 发生了什么

`/opt/ai_chatbot` 里躺着两个 compose 文件，而 compose 默认读的是 `docker-compose.yml`：

| 文件 | 用途 | 会干什么 |
|---|---|---|
| `docker-compose.yml` | **本地开发** | 自带 mysql + redis、从源码 build backend、发布 `127.0.0.1:8000` |
| `docker-compose.prod.yml` | **线上** | 只有 backend + frontend，用 GHCR 镜像，**不发布任何主机端口**，接共享的 `infra_mysql` / `infra_redis` |

于是它按开发配置来：拉 `mysql:8`、起 redis、build 后端。**目录名让 compose 认成同一个 project、同一个
`backend` 服务，所以它先把生产容器 `ai_chatbot_backend` 拆了**，再去起替代品——替代品要绑 8000，
而这台机器上那个端口已经被别的项目占着，绑不上。结果：没有后端在跑，`/api/*` 和 `/console/*` 全 502，
外加两个多余容器 `ai_chatbot-mysql-1` / `ai_chatbot-redis-1`。

### 三条要记住的

1. **这台机器上每一条 compose 命令都要带 `-f docker-compose.prod.yml`**。本文件里所有
   `--force-recreate` 的写法已经统一改过了（原来那三处都是裸命令，照抄就会复现今天这次）。
2. **`docker compose down` 更危险**：不带 `-f` 会连生产的 `ai_chatbot_frontend` 一起端掉，
   因为 project + service 标签是一样的。
3. **判断后端死活要看 `/api/bots`，不要看 `/health`。** 排查时我拿 `/health` 返回 200 当后端活着的
   证据，**那是错的**——`frontend/nginx.conf` 只代理 `/api/`、`/webhook/`、`/console/*`，`/health`
   会落到 SPA 上，后端死透了它照样 200（返回的是 index.html）。

### 防再犯（已落地）

- 新增仓库根的 `.env.example`，里面是 `/opt/ai_chatbot/.env` 该有的三行：`COMPOSE_FILE=docker-compose.prod.yml`
  加两个 `*_IMAGE`。**`COMPOSE_FILE` 这一行让裸 `docker compose` 在那个目录里自动走生产文件**；
  workflow 里显式的 `-f` 依然优先，部署行为不变。
  ⚠️ 这一行**要用户在 VPS 上手工加进 `/opt/ai_chatbot/.env`**，仓库里改不到它。
- 两个 compose 文件顶部各加了一段注释，指向对方和这次事故——因为人是在打命令前扫一眼文件，
  不是在打命令前翻 todo.md。

---

## 真机验收记录：2026-09-12（任务 13 / 17 / 21 一趟跑完）

用户拿手机把三个批次串成一趟走完了，截图为证。**这一趟的价值超过它验掉的功能本身**——单测全绿、变异测试全红之后，它仍然抓出一个会当场毁掉核心卖点的失败和三处不体面。

### 过了的（首次真机）

| 步骤 | 证据 |
|---|---|
| **剧本 1 · rojak 开场** | `Boss 这个 earbuds 还有 stock 吗?` → `Sony WF-C710N RM 328.90/个（含税）`，三仓明细 KL 150 / JB 98 / Penang 89 |
| **COD 政策** | 「只限 RM 500 以下、巴生谷范围内，所以这单超额」——从 `context_data` 读的 |
| **剧本 1 · 中途改主意** | 2 个 → 3 个，**重查库存、重算 RM 986.70**，没复用上一轮数字。这一步 todo 里点名是「最易翻车」的，一次过 |
| **剧本 1 · 下单 + e-Invoice** | `SO-2026-00001` → `INV-2026-00001`（MyInvois UIN `4C286BA94EF34868`），PDF 送达手机 |
| **任务 19 · 主动推送** | 11:28 手机自己响，三语，没人打字 |
| **任务 17 · 剧本 2a 退款** | 发的照片是 **Edifier**（跟订单对不上），bot 说「系统里找不到这个型号，您最近的订单里也没看到它」，**NEVER_INVENT 在这里立住了**，然后主动提示「您刚下的那单是 Sony × 3」，确认后开出 `CN-2026-00001` RM 328.90，原因「不能充电」写进了单据 |
| **马来语语音** | 4 秒语音 → 听懂 → **用马来语答**，真实订单数据，连状态都是马来语（`sudah dihantar penuh` / `disahkan (stok ditempah)`）。**这把任务 15 欠着的那笔账还上了** |
| **任务 19.1 · 收尾总结** | 10 分钟、13 次查询、单号全对；**久坐窗口生效**（不是那种 171 分钟的数字） |

**事前押注最可能坏的两处——「模型会不会自己把 `erp_find_order_by_sku` 和 `erp_create_credit_note` 串起来」和「Meta 认不认推送 payload」——都过了。**

### ❌ 挂了一处，是整批最值钱的那处

**剧本 2b 完全失败。** 用户发了自己的 `ACUVEN_Car_Rental_Quotation.pdf` 问年费，bot 回：

> 这份是 ACUVEN Technology 的软件报价单，**不是我们 ShopMalaysia 的业务，这方面我帮不上忙**

**它根本没打开那份文件。** 而且它在**正确执行指令**——`NEVER_INVENT` 写着「超出本业务的问题不归你答」，一份汽车租赁报价单确实不是零售店的业务。

**根因是一个设计矛盾，不是 bug**：剧本 2b 的整个卖点是「**你自己的**文件」，而客户自己的文件**按定义**就跟这个 bot 的业务无关。任务 14 的记录里其实见过苗头（hotel bot 曾说「我不能读图」），当时判断「演示时客户发的图一定是切题的」——**那个判断被这次证伪了**。

### 另外三处不体面

- **推送的金额是 `合计 MYR 986.7000`**。bot 自己说话是 `RM 328.90`，只有推送是原始 ERP 小数串——**全场唯一一句读起来像数据库的话**
- **总结说「全部写进了真实的 ERP 和 CRM」，但这一轮没有任何东西进 CRM**
- **CRM 看板上那张卡是 9 天前的**（查了线上 CRM：创建于 2026-09-03 03:49:30，最新 deal 是 09-04，今天一条没新增）。用户一眼看出「顾客名字不一样」是对的

### CRM 那张卡：剧本和人设各说各话

**今天这一轮一条 CRM 线索都没建，而这是人设写明的行为**：

> 想现在就下单的人不用等——用 `erp_create_customer` 开户，直接往下走到订单和 e-Invoice。

也就是说**只要客户当场下单，就不留 CRM 线索**。而剧本 1 写着「ERP 后台那张单在那里，**同时 CRM 看板上长出一张线索卡**」——那张卡只在客户**问了不买**时才出现，而剧本 1 的高潮恰恰是他买了。

**2026-09-12 用户拍板选 A：改人设，下单也往 CRM 记一笔。** 理由是真实生意本来就把成交记进 CRM，而且它让剧本 1 的两块屏同时亮——todo 里说 CRM 那张卡「打动所有做生意的人」。

### 修了什么（2026-09-12，同日）

1. **客户自己的文件永远在射程内**（`llm.DOCUMENT_IN_HAND`）。加在**非缓存的那半边**系统提示里，只在带文件的那一轮出现——它是关于这一轮的事实，不是关于这个 bot 的；放进缓存前缀既会在其他轮次上说谎，又会每来一份文件就把缓存前缀扔掉一次。第二段专门挡反方向的错误（读了人家的价目表不等于自己在卖）
2. **推送金额** → `RM 986.70`（`erp._money`，MYR 写成 RM，两位小数，其他币种保留原名）
3. **总结只点名真正写入过的后台**，什么都没写就一个系统都不提
4. **零售人设加一句：下单之后也 `crm_create_lead`**（该工具对已有联系人是挂到同一条记录上，不会重复建）

### 验证到什么程度

- 后端 **690 passed / 7 skipped**（基线 679，净增 11）
- **变异测试 10 处，10/10 全红**
- ✅ **改动 1 对真模型验证过**（`scripts` 下临时探针，一份刻意跟零售无关的汽车租赁软件报价单，三问）：
  1. 「每年费用是多少」→ **读出来了**：年度授权 RM 26,700 + 年度支持 RM 9,150 = 每年 RM 35,850，并把一次性费用单独拎出来说明不计入年费，标了 `p.2`。**这正是真机上失败的那一问**
  2. 「有写违约金吗」→「没有提到任何违约金或逾期罚款」，指回出具方去问，**没编**
  3. 「那我要买 2 个 earbuds」→ 报的是 ERP 里真实的 `RM 328.90` 和真实库存，**没把客户的文件当成自家目录**
- ⚠️ **没验的**：改动 2 / 3 / 4 都**只有单测**。推送金额和总结措辞要下一轮真机才看得到；**改动 4 尤其**——它是一句提示词，模型会不会照做只有真机知道，而这正是今天证明过靠不住的那一类假设

### 2026-09-12 下午的真机续跑：抓到两件

**① CRM 一张订单出了两张卡（我们的 bug，当天修了）。** 用户下单后翻 CRM，看到同一个联系人下面两张一模一样的 deal，都是 `SO-2026-00002 / RM 986.7`，Activity History 里两条记录差 **11 秒**：

```
08:49  Sony ... × 3（订单 SO-2026-00002）
08:49  Sony ... × 3（订单 SO-2026-00002，已开 e-Invoice INV-2026-00002）
```

`crm_create_lead` 被调了两次——下单后一次，开完发票后又一次，模型照着当天新加的那句人设指令做了两遍。**而当天的任务记录里写着「该工具对已有联系人会挂到同一条记录，不会重复建」——那句话只对「联系人」成立，对「deal」从来不成立**，这半边没人验过。

修法**没有走提示词**（「只调一次」正是本周被证伪过两次的那类假设），改在代码里：`crm_create_lead` 先看这个联系人名下有没有已经引用**同一个订单号**的 deal，有就把新信息作为活动记录挂到那张卡上，不再新建。判据是需求描述里的 `SO-\d{4}-\d+`，因为两次调用的措辞恰恰是不同的那部分。没有订单号的纯询价照旧各自成卡——同一个人问两次就是两个机会。

验证：**772 passed**（+6），**变异测试 5 处 5/5 全红**（不复用 / 复用错卡 / 无订单号也复用 / 把发票号当订单号 / 查不到已有卡时把 lead 整个丢掉）。

**② ERP 和 CRM 后台的时间比手机慢 8 小时（不是我们的 bug，没动）。** 用户下单时手机是**下午 4:49**，ERP 里记的是 **08:49**。当场查证：UTC 09:02 / 吉隆坡 17:02，`SO-2026-00002` 的 `confirmed_at` 是 `08:49:20`——**erp_os 和 crm_os 存和显示的都是 UTC**。`business_date` 是对的，因为那个是我们这边按 KL 时区算好传过去的；服务端自己打的时间戳不是。

演示上这是实打实的问题：**客户手机 4:49 → 我们的导演台 4:49（任务 37.3 修过）→ ERP/CRM 后台 8:49**。你指着后台说「刚刚那单就在这里」，屏幕上写着 8 小时前。

**修在 `erp_os` / `crm_os`，不在这个仓库**。最小改法通常是给那两个服务的容器加 `TZ=Asia/Kuala_Lumpur`（我们自己的 compose 就是这么干的），但**得先确认它们数据库里存的是 naive UTC 还是本地时间**——改错会让历史数据整体偏 8 小时。等用户拍板。

### 下一轮真机要补的三件

1. **2b 重跑**：还发那份自己的 PDF，确认现在会读（这是本次修复的主验收）
2. **看推送那条消息的金额**：应该是 `RM 986.70` 而不是 `MYR 986.7000`
3. **下单后看 CRM 看板**：应该当场长出一张新卡，卡上的名字和金额对得上这一单

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

- 2026-09-04（没有手机号的 WhatsApp 用户 / BSUID）：用户提出「有的 WhatsApp 没有电话号码只有 username，用 username 作为用户名」。**查证后改了方案的一半——username 不能做 key**：
  - **查证结论（Meta 官方文档，不是推断）**：① `user_id`（**BSUID**，business-scoped user ID，形如 `US.13491208655302741918`）**出现在所有 message webhook 里**，每个 business portfolio × 用户唯一且稳定，只有用户换手机号才重新生成；② `username` 官方原话 "can change periodically"——**可变，所以不能做主键**；③ 用户启用 username 并隐藏号码后，`from` / `wa_id` **会直接从 payload 里消失**（除非 30 天内互动过 / 在通讯录里 / 最近通过话）；④ 时间线：BSUID 2026 年 4 月初开始进 webhook，username 6 月 29 日开放注册
  - **payload 位置很关键**：`username` **只在 `contacts[].profile` 里**，消息对象上没有；BSUID 在 `contacts[].user_id` 和 `messages[].from_user_id` 两处都有。而我们的 `_extract_messages` **一直把 `contacts` 整个丢掉**，所以不改它就永远拿不到 username
  - **落地**：`Sender` 这个小对象统一回答「谁写来的、回信寄到哪」。**手机号优先，没有才用 BSUID**——不是因为 BSUID 不好，而是反过来会悄悄拆掉整个设计：两个后台都按手机号查、任务 33 的网页也是让人输手机号，而且 **BSUID 绑在 business portfolio 上，换 portfolio（这个项目已经换过一次）会重发所有 id、忘掉所有客户**
  - `username` 按用户的要求**填进 `display_name`**，但**只在空的时候填**——客户在对话里自报的名字，压得过一个他明天就能改的 handle。顺带把 `contacts[].profile.name` 也接上了，任务 32 记的「`display_name` 全程无人写入」这个洞就此堵上
  - system prompt 分了两种口径：有号码的照旧说「这是渠道验证过的号码，直接拿去查，别问客户要」；**没号码的明确告诉模型「username 是 handle，不是能查的东西，两个后台没有号码查不了，先问」**。不说这句，模型会拿 handle 去调 `crm_lookup_customer`，查不到，然后对着一个真客户说「你不是我们的客户」
  - **顺手堵掉最后一处静默失败**：`dispatch_message` 以前遇到认不出发件人就 `return []`，**一行日志都没有**。现在是 ERROR + 导演台事件，并且把 message / contact 的**字段名列表**打进日志——Meta 正在改这些 payload 的形状，下次再变时这行日志就是线索
  - **老档案的兼容**：`key_id` 是新字段，而 Redis 里的记录 TTL 7 天、部署必然落在旧记录上。`_deserialise` 读不到 `key_id` 时回退到 `phone`。**漏了这一条，上线当天所有老客户全被忘掉**
  ⚠️ **有一处没验、且验不了**：给没有手机号的用户**发**消息要用 `recipient` 字段而不是 `to`。这条来自 Meta 的 SDK 文档，**他们自己的 send-message 指南里至今只写了 `to`**，我拉了原文确认过。代码里集中在 `whatsapp._recipient()` 一个函数上并写了警告注释；猜错的话，现在会是 `send_raw` 抛出的一条**响亮的** `WhatsAppSendError` + 导演台报错，而不是又一次静默。**要真机验只能等到确实有这样一个用户写进来**
  ✅ **2026-09-05：没号码的客户改成主动要号码**（用户拍板）。原来的提示只说「username 不能用来查，需要时再问」，太被动——后台里**每一样东西都是按手机号找的**（查订单、开户、建线索），没号码就什么都做不了。现在明确要求**尽早问**，并且说清楚是为了查账户和联系他。同时写死一条：**问归问，不得在拿到号码前拒绝回答问题**——否则就从「认不出你」变成「不给号码不伺候」，后者在演示里更难看
  **暂不做（已知取舍）**：同一个人先带号码出现、后来隐藏号码，会变成两条记录。修法是加一条 `chat:bsuid:{id}` → 手机号 key 的别名。没做是因为**现在一个这样的用户都还不存在**，做了也验不了；触发条件还要求他在 7 天 TTL 内回来。要做时是个小改动
  验证：348 passed（334 → **348**），**九处变异全部被捕获**（丢掉 contacts / 无号码又被丢弃 / 认不出时恢复静默 / BSUID 压过手机号 / username 覆盖真名 / BSUID 塞进 `to` / BSUID 被压成纯数字 / 老档案读不出来 / prompt 谎称有号码）

- 2026-09-04（`erp_create_customer`：把任务 32 弄断的旗舰戏接回去）：真机演示时 bot 对客户说「an account has to be set up first」——**下不了单**。查下来这不是 bug，是任务 32 的连带后果：
  - 以前「选身份」里那个 `trade_sunrise` 是**既有 ERP 账号**，所以能当场演「真的建单 + 真的发 e-Invoice PDF」，那是整场演示最亮的两下
  - 手机号即身份之后，**真实号码在 ERP 里必然查无此人 → 永远走 CRM 兜底分支 → `erp_create_sales_order` 和 `erp_generate_einvoice` 从真机上再也触发不到**
  **动手前先把「ERP 里有身份是不是就够了」这条链路查穿了**（用户的问题，答案是「够」，但不是想当然）：
  - `erp_create_sales_order`：**全 `erp_os` 后端没有任何 `credit_limit` 检查**（grep 全空），所以新客户默认 `credit_limit=0` 不挡单
  - 发票：`einvoice.create` 只要求 SO 处于 `PARTIAL_SHIPPED` / `FULLY_SHIPPED`，而 `_worth_invoicing` 本来就会先发货
  - MyInvois 提交：`submit_to_myinvois` **只断言发票状态是 DRAFT，不跑 precheck**。`einvoice_precheck.py` 是独立的建议性接口（还带 LLM），**不在我们的调用路径上，拦不住提交**
  - ⚠️ **但 precheck 那条规则本身值得当真**：`BUYER_TIN_PRESENT_OR_B2C` —— **B2B 买家必须有合法 TIN，B2C 买家没有也算通过**。而 `CustomerCreate.customer_type` **默认就是 B2B**。照默认建客户，演示时谁点开发票预检那一页就是一片红
  落地：
  - `erp_client.create_customer()` + `erp_create_customer` 工具，接 `POST /api/customers`（写权限 `[ADMIN, MANAGER, SALES]`，我们用的 `admin@demo.my` 是 ADMIN，够）
  - **有公司名 → B2B 并问 TIN；没公司名 → B2C**。这一条是上面那个 precheck 规则的直接产物，不是随手选的
  - **`code` 从手机号推导**（`WA-60173948123`）。`erp_os` 对重复 code 直接 `ConflictError`，而 `ApiClientError` **不带状态码字段**（只在消息字符串里），靠解析字符串判重太脆——所以工具**先 `find_customers` 查一遍，查到就返回既有账号**。这不只是幂等：一个号码开两个账号 = 订单裂成两半，销售看到的是半部历史
  - **必须写 `phone`**：`find_customers` 的手机号匹配是扫 `phone` 列的，不写这个字段等于开了一个下次对话找不回来的账号
  - 写失败区分 `ACCOUNT_FAILED` / `ACCOUNT_UNKNOWN`，沿用 `ORDER_UNKNOWN` 那套理由——告诉模型「失败了」它会重试，而重试会开出第二个账号
  - persona 改成按**意图**分流：还在问、在比较、没想好 → 照旧 `crm_create_lead` 留线索；**现在就要下单 → 当场开户，直接往下走建单和发票**
  验证：355 passed（348 → **355**），**七处变异全部被捕获**（重复开户 / 不写手机号 / 一律 B2B / 空号码也开户 / 把未知当失败 / code 不再唯一 / retail 掉了这个工具）
  ✅ **2026-09-05 真机验收通过**（用户做的，Claude 做不了——带凭据写外部系统会被权限分类器拦）：拿一个 ERP 里没有的号码走完整条链，**下单成功、收到 e-Invoice PDF、`erp.kelvinpeng.com` 后台确实多了一个客户**。所以「ERP 里有身份就够下单开票」这条结论不是从代码推出来的，是线上跑出来的——无信用额度检查、precheck 不拦提交、B2C 不需要 TIN，三条都成立
  ✅ **2026-09-05 补两处**（用户拍板）：
  - **客户 code 从 `WA-{手机号}` 改成 `WA-{手机号}-{YYMMDDHHMM}`**。原因是查任务 34 清理方案时发现的陷阱：`erp_os` 的 code 唯一性检查**算上软删记录**（注释明写 "to prevent reuse"），所以清理一次之后**同一个号码永远开不了户**——而演示每次都用同一个号。防重复开户的保证**移到了「先 `find_customers` 查一遍」那一步**，那本来也是更诚实的位置：它问的是「这个人有没有账号」，不是「这个字符串发过没有」
  - **ERP 客户要清，已写进任务 34**（连同软删语义、角色、以及上面这个 code 陷阱的完整侦察结论） ERP 客户

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
