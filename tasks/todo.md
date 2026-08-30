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

- [x] ~~**A. `erp_os` / `crm_os` 的 demo API 账号**~~——**2026-08-30 实测已解决，两边都不用新建账号**：
  - `erp_os`：`admin@demo.my` / `Admin@123`（出处 `erp_os/demo/setlist-15min.md`），对 `erp.kelvinpeng.com/api/auth/login` 实测 200
  - `crm_os`：`admin@crm.com` / `Admin123`（出处 `crm_os/backend/seed.py:82`），对 `crm.kelvinpeng.com/api/auth/login` 实测 200，role=admin
  - ⚠️ **两边都没有 API key 机制**，只有邮箱+密码换 JWT。access token 15 分钟过期、refresh 一次性、登录限流 10 次/分（连错 5 次锁 5 分钟）。所以客户端**必须缓存 token + 到期前刷新**，绝不能每次调用都登录——一场演示连调五六个工具就会撞限流
- [ ] **B. Meta 后台三个入口确认能点**——媒体权限、模板提审、Flows。用户已确认后台可用，但任务 18 的模板提审要在批次 03 第一天就提交（审核要几小时到 1-2 天）。
- [ ] **C. 语音转录选型拍板**——外部 API（准、快、多一个供应商）vs 自托管 faster-whisper（无外部依赖、CPU 上每条慢 3-5 秒、吃 VPS 内存）。阻塞任务 15。建议先接外部 API 把戏跑通，转录做成抽象层，之后换实现只是换一个类。

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

- [ ] **任务 1：Meta 媒体客户端（收图 / 收文件 / 发文件 / 主动外发）**
  文件：`backend/app/services/whatsapp_media.py`（新增）、`backend/app/config.py`、`backend/tests/test_whatsapp_media.py`（新增）
  目标：三个函数，全部直连 Graph API，用 `ai_chatbot` 自己的 `WHATSAPP_ACCESS_TOKEN`：
  - `fetch_media(media_id)` —— 两步：`GET /{media_id}` 拿临时 URL，再带 token 下载二进制，返回 bytes + `Content-Type`
  - `upload_media(bytes, mime, filename)` —— multipart 传给 `POST /{phone_number_id}/media`，返回 `media_id`
  - `send_message(payload)` —— `POST /{phone_number_id}/messages`，供主动推送用（收到消息时的回复走现有 webhook 同步路径，不用这个）
  验收：pytest 用 mock HTTP 覆盖三个函数的 URL / header / body；再用真实 `media_id` 拉一张图下来能打开，上传一个 PDF 拿到 `media_id`

- [ ] **任务 2：LLM 工具调用循环**
  文件：`backend/app/services/llm.py`、`backend/app/tools/registry.py`（新增）、`backend/tests/test_llm.py`
  目标：从单轮 `messages.create` 改成 SDK 的 tool runner（`@beta_tool` + `client.beta.messages.tool_runner()`）。工具列表按 bot 从 registry 取，**工具为空时行为与现在完全一致**——这是回归的安全绳
  验收：pytest 覆盖「无工具时输出不变」和「有工具时会调用并把结果喂回去」；`docker compose up` 后网页端问一句，确认回复正常（旧行为回归）

- [ ] **任务 3：事件总线 + 导演台 SSE 骨架**
  文件：`backend/app/console/events.py`（新增）、`backend/app/routers/console.py`（新增）、`backend/app/services/llm.py`（在 tool runner 的 per-turn 钩子里 emit）
  目标：内存 ring buffer 存事件（工具名、入参、返回、耗时、状态）；`GET /console/stream` 走 SSE 推给前端；每次工具调用前后各 emit 一条
  验收：`curl -N localhost:8000/console/stream` 订阅，另开一个终端发一条会触发工具的消息，看到事件实时滚出来

- [ ] **任务 4：模型选型与 prompt 缓存**
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

- [ ] **任务 8：ERP / CRM 只读工具 + 鉴权基类**
  文件：`backend/app/services/api_client.py`（新增，登录+token 缓存+刷新基类）、`backend/app/services/erp_client.py`、`backend/app/services/crm_client.py`（均新增）、`backend/app/tools/erp.py`（新增）、`backend/tests/test_erp_tools.py`（新增）
  目标：`erp_os` 和 `crm_os` 的认证方式**完全一样**（邮箱+密码 → JWT，15 分钟过期，refresh 一次性），所以先写一个共用基类管登录/缓存/刷新，两个 client 各自只填 base url 和账号。三个只读工具：`erp_search_sku(keyword)`、`erp_get_inventory(sku)`、`crm_lookup_customer(name_or_phone)`
  验收：pytest（mock HTTP）覆盖「token 未过期时不重新登录」「过期时自动 refresh」「refresh 失败回退重新登录」；再对着真实 `erp.kelvinpeng.com` / `crm.kelvinpeng.com` 各调一次，返回的是真数据

- [ ] **任务 9：ERP 写入工具 —— 创建销售订单**
  文件：`backend/app/tools/erp.py`（扩展）、测试
  目标：`erp_create_sales_order(customer_id, items)`，走 `erp_os` 的 `sales_order` 路由，返回订单号
  验收：调一次，然后**在浏览器里打开 `erp.kelvinpeng.com` 的订单列表，那张单在那里，状态正确**

- [ ] **任务 9.1：CRM 写入工具 —— 自动建线索**
  文件：`backend/app/tools/crm.py`（新增）、`backend/tests/test_crm_tools.py`（新增）
  目标：`crm_create_lead(name, phone, requirement, amount)` —— 依次调 `POST /api/contacts`（建联系人）、`POST /api/deals`（建商机，带 `amount`，**会出现在管道看板上**）、`POST /api/deals/{id}/activities`（记一条来源=WhatsApp 的活动）
  ⚠️ **不要设 `is_gateway=True`**。`crm_os` 有 `utils/demo_scope.py` 按这个标记做范围过滤，设了反而可能在主列表里看不见，正好毁掉这个镜头
  验收：调一次，`crm.kelvinpeng.com` 的**看板上那张卡在那里**，标题和金额对得上；卡里能看到那条活动记录

- [ ] **任务 10：e-Invoice PDF 生成 + 发进 WhatsApp**
  文件：`backend/app/tools/erp.py`（扩展）、`backend/app/services/whatsapp_media.py`（用上传接口）
  目标：`erp_generate_einvoice(order_id)` 拿到 PDF → 走 `upload_media()` → 构造 document 消息 payload
  验收：手机上收到 PDF 发票并能打开，内容对得上刚才那张单

- [ ] **任务 11：retail bot 改造成工具驱动**
  文件：`backend/app/bots/data/retail.json`、`backend/app/bots/registry.py`
  目标：`retail` 的 `persona_prompt` 改成「用工具查，不要编」；`context_data` 里的静态商品/订单表删掉（改由工具实时查），只留 FAQ 和政策类文本；bot 元数据加 `tools` 字段声明它能用哪些工具
  验收：问「我的订单到哪了」，日志显示走的是工具调用而不是背 JSON；再用 rojak 话问一句（`"Boss 这个 earbuds 还有 stock 吗?"`），同样正确走工具——**老板看到自家客人的说话方式被听懂，比任何技术指标都管用**

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
  文件：`frontend/src/pages/Console.tsx`（新增）、`frontend/src/api.ts`
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

- [ ] **任务 20：人工接管状态机**
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

## 评审记录

（每个任务完成后，如有偏离原方案的地方或踩坑教训，记录在这里）

- 2026-08-27（立项）：v1 的 `tasks/todo.md` 归档为 `tasks/todo-v1-mvp.md`。
- 2026-08-27（架构侦察）：确认 `ai_chatbot_demo` **自己不持有 Meta 凭据**——它挂在 `whatsapp_gateway` 后面，通过 `POST /internal/whatsapp/inbound` 收消息、**同步返回** payload 列表由网关代发。七件武器里有四件（收图、收语音、发文件、主动推送）突破了这个同步请求-响应契约。解法不是把凭据复制一份给 demo（那会让两个项目抢同一个号的状态），而是给网关加三条反向内网 API 借出能力。`dispatch_message` 的返回值语义保持不变，`crm_os` 和 `acuven_aichat` 零改动——这是批次 00 单独验收的全部理由。
- 2026-08-27（选型）：ERP 一侧决定走 `erp_os` 自己的 REST 路由（`sales_order` / `sku` / `inventory` / `invoice` / `customer` 都是现成的），不裸连 MySQL。理由：写入要经过业务逻辑，否则演示时刷新后台看到的可能是一张状态不对的脏单，当场翻车。
- 2026-08-30（决定）：**`crm_os` 从网关的 demo 路由里彻底移除**，WhatsApp 线专供 `ai_chatbot`。网关侧已落地（`demos_registry` 删掉 crm 条目，demo 号加 `default_route="ai_chatbot"` 直连、不再发选择菜单）。CRM demo 只在网页/现场演示。菜单代码保留，服务于未注册号码兜底。
- 2026-08-30（阻塞项 A 解除）：两套系统的 demo 账号本来就 seed 好了，实测线上可登录，**不需要新建**。同时确认两边都无 API key 机制，只有短命 JWT，因此新增鉴权基类（任务 8）。顺带发现 `crm_os` 的 `POST /api/auth/register` **完全开放**——无鉴权、无邀请码，任何人都能注册出一个 `sales` 角色账号。现在里面是 seed 假数据所以影响有限，真放客户资料前必须堵上。归属 crm_os 项目。
- 2026-08-30（补剧本）：原计划只有批次 01/02 写了剧本，03/04/05 只有工程验收条件——一段自己写着「杀伤力被严重低估」的功能却没有能讲给客户听的戏。补齐剧本 3、4，并指定任务 29 演剧本 1。**剧本会反过来定义验收标准**（剧本 1 那七步直接定义了任务 13），所以补在开工前而不是做到那批再说。
- 2026-08-30（剧本 3 挪到餐饮）：「你的餐出锅了」比「订单已确认」画面感强，加辣椒酱这种要求本来就该人来拍板。挪完后演出分布从「零售 3 出」变成零售 2 出、餐饮 1 出（最长的一出，9 步）、房产 1 出。
- 2026-08-30（轻量档）：`hotel` + `saas` 原本 30 个任务一个都碰不到，会保持静态 JSON 形态，和工具驱动的 `retail` 并列在菜单里落差太大。新增任务 11.2 给它们套同样的工具外壳，读 JSON / 写内存。剩下的差别（retail 后台真的长出东西）反而可以坦白讲成卖点：「接你们自己的系统是同样的工具接口」。
- 2026-08-30（RAG 的定位）：用户问怎么做 RAG。结论是**现在不需要**——六个 bot 全部素材 31 KB 约一万多 token，上下文有 100 万，prompt caching 一开重复读取几乎免费；RAG 解决的是装不下，差三个数量级。但「读客户自己的文档」值得做，**不是为了性能，是为了那句话：把你们的手册丢进来，五分钟变客服**。落成任务 15.1，用 Claude 原生的 `document` block + citations，零检索基础设施。真到装不下那天，下一步是关键词检索工具（`search_docs` 接 MySQL 全文索引），**不是向量库**：Anthropic 无 embedding 接口，上向量要引入新供应商 + 切块调参，且召回不准时极难 debug；结构化业务数据用关键词天然更合适。
- 2026-08-30（说服力五条）：盘完 33 个任务发现它们**全在教 bot「能做什么」，没有一个针对客户心里的异议**。补五条：**会说「我不知道」**（任务 11.3，抗砸场——客户一定会试着问倒它，而「乱答」是老板最怕的）、**成本以马币显示**（任务 12，「会不会很贵」是中小企业主真正的拦路问题，一行乘法就能终结）、**rojak 混语开场**（剧本 1 + 任务 11 验收，不是新功能是把已有能力演出来，本地化说服力极强）、**「正在输入」从可选项提为任务 12.1**（工具调用变慢后，没有它会让真实调用显得像性能差）、**演示收尾总结**（任务 19.1，利用「对话留在他手机里」这个 WhatsApp 独有优势——唯一一条你不在场时还能继续说服人的功能）。
- 2026-08-30（说服力第二轮）：再补五条。**对照组开关**（任务 12.2）—— 关掉工具跑同一个问题，让客户自己看两遍「编的」和「真的」，整场演示的核心主张变成当场可验证的实验；便宜得离谱，因为任务 2 的回归安全绳本来就要求这条路径存在且被测。**客户中途改主意**（剧本 1 加一步，7→8 步）—— 所有演示在客户按剧本走时都漂亮，一旦反悔就露馅，而真实生意里天天发生；接得住证明是助理，接不住证明是流程图。**三人并发**（任务 13 验收）—— 破除「一次只能应付一个人」的直觉，可能零代码但必须提前验。**故障演练开关**（任务 27.1）—— 「坏了怎么办」老板一定会想、未必会问，主动演比等他问有力。**PDPA 一页纸**（任务 29.1）—— 不写代码，但缺了它有些客户签不了字。另把「现场导入客户自己的 CSV」记进可选项。
- 2026-08-30（demo 线脱离网关）：用户第三次追问「号码不同，还需要网关分发吗」。前两次我都在推迟，而且给过一个循环论证（「网关必需，因为它持有凭据」——凭据在它手里恰恰是这个架构的结果，不是理由）。查证后做了一个 10 分钟可逆实验：把 Meta 的 Callback URL 从 `whatsappgateway.acuventech.com` 改到 `chatbot.acuventech.com/webhook/whatsapp`，`ai_chatbot` 用自己的凭据收发。**通了**——握手 200、消息直连进来、去重工作（5 个 POST 只触发一次业务逻辑）、出站 Graph API 200，网关侧零流量。
  判定成立的三个前提：① `ai_chatbot` 的 v1 直连路径（`GET/POST /webhook/whatsapp` + 四个凭据字段）当初刻意保留了，改动量约等于零；② 今天取消了测试 WABA 的订阅后，App 下只剩 demo 号一个 WABA，**没有东西需要分流**；③ 客服号本就该用自己的 App（它要走 Coexistence → Tech Provider → App Review，不该把 demo 的 App 拖进去），所以两条线永远不会挤同一个 callback URL。
  收益：批次 00 从 7 个任务缩到 4 个，省约 3 个 session，并且这一批「整个工程唯一有回归风险」的属性消失——因为不再碰那个同时扛着公司真实客服线的服务。代价：`acuven_aichat` 将来上线时要自己长一个公网 webhook（它现在只有内网路由）。网关继续部署着不动，零成本，客服号接入时再评估去留。
