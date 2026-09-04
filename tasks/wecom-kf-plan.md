# 接入方案：企业微信「微信客服」渠道

状态：**待确认，尚未动代码**。2026-09-03 起草。
需求来源：临时需求，不在 `tasks/todo.md` 的六个批次里，按 CLAUDE.md「先计划、等确认」走。

已拍板的三个前提（2026-09-03 用户选定）：

1. 接的是**微信客服（kf）API**，不是企业微信自建应用——受众是外部微信用户，和现在 WhatsApp 的场景一一对应
2. 落在**当前仓库 `ai_chatbot_demo`**，作为 WhatsApp 之外的第二条真实渠道
3. **没有中国大陆主体**

---

## 一句话结论

技术上完全可做，而且**没有中国大陆主体不等于做不了**——未认证企业也能开微信客服，只是累计只能接待 100 位客户，对 demo 绰绰有余。真正的未知数只剩一个：**境外主体能不能开微信客服**，这一条我查不到官方明文，需要你注册一个账号实地点一下。

代价在另一头：现在的对话逻辑和 Meta 的报文格式是焊死的，接第二条聊天渠道**必须先做一次重构**，不是加一个 router 就完事。

---

## 一、前提查证（哪些验了、怎么验的、哪些没验）

### 验证过的

| 结论 | 来源 |
|------|------|
| 微信客服回调**不推消息内容**，只推 `Token` / `OpenKfId` / `Event`，企业收到后再主动调接口拉取 | 官方原文：「企业微信后台会将事件的回调数据包发送到企业指定URL；企业收到请求后，再通过读取消息接口主动读取具体的消息内容」 |
| 拉取接口 `POST https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token=ACCESS_TOKEN`，参数 `cursor` / `token` / `limit` / `open_kfid`，返回 `next_cursor` / `has_more` / `msg_list` | 官方文档 path/94670 |
| 回调里的 `token` **有效期 10 分钟**，可选但建议带上（影响频率限制） | 同上 |
| `sync_msg` 只能拉**最近 3 天**的消息，`limit` 默认/上限 1000 | 同上 |
| 标识符：`open_kfid`（客服账号，`wk` 开头）、`external_userid`（客户，`wm` 开头）、`servicer_userid`（接待人员） | 同上 |
| 存在官方的「境外企业 WeCom 认证」流程，有专门的帮助中心分类（含所需材料、在线填写指引、境外常见主体证件示例、开票与合同） | open.work.weixin.qq.com/help2/pc/20475 |

### 次级来源（多方一致，但没找到单一官方页面明文）

微信客服的接待上限按主体状态分三档：

- **企业未完成主体验证：累计**可接待 100 位客户（不是每天，是总共）
- 已验证未过期、未绑视频号：**每天** 100 位
- 已验证 + 已绑视频号：**不限**

对一个演示用途来说，「累计 100 位客户」够用——但要知道这是**累计**，跑掉就没了，不会每天重置。演示前别拿真实客户号乱试。

### 没验证的（风险都在这里）

1. **境外主体到底能不能开微信客服**——这是唯一的硬未知。官方有「境外企业 WeCom 认证」，WeCom 国际版也明确支持境外企业注册，但**没有任何一页写明微信客服对境外主体开放或不开放**。微信客服连的是消费者微信那一侧，存在只对大陆主体开放的可能。
2. **菜单消息（`msgmenu`）被点击后回调回来的具体形状**——是回一条文本消息（内容为菜单项的 `content`），还是一个带 `id` 的事件。这决定了 `_handle_interactive_reply` 那套 id 映射能不能照搬。
3. **文件消息的素材上传细节**（临时素材接口、有效期、大小上限），需要时再查。
4. **WXBizMsgCrypt 的实现细节**——官方有各语言示例代码，实现时照抄即可，但 Python 版需要 `pycryptodome` 之类的依赖，现在 `requirements.txt` 里没有。

> ⚠️ 按 CLAUDE.md 的高风险操作规则，注册/认证/登录这类动作我没有代做，也不会替你去点。第 1 条需要你自己注册一个企业微信（未认证即可）后，到后台看「微信客服」这个入口是否存在、能否开通。**这一步失败就整件事停住**，不要连续换主体重试。

---

## 二、为什么不能照搬 WhatsApp 那一套

微信客服和 WhatsApp 在四个地方形状不同，每一处都会打到现有代码：

| | WhatsApp（现状） | 微信客服 |
|---|---|---|
| **收消息** | webhook 直接推整条消息，`_extract_messages` 从 `entry/changes/value/messages` 里掏出来 | 回调只说「有新消息」，要拿 `token` 再调 `sync_msg` 带 `cursor` 拉。**一进一出的形状变成了「一个事件 → 拉回 N 条」** |
| **验签** | `X-Hub-Signature-256`，HMAC-SHA256，`whatsapp.verify_signature` | WXBizMsgCrypt：`msg_signature` 走 SHA1(token, timestamp, nonce, encrypt)，报文体是 AES-256-CBC 加密的 XML。**完全是另一套** |
| **URL 校验** | GET 回显 `hub.challenge` 明文 | GET 要把 `echostr` **解密后**回明文 |
| **交互组件** | `interactive list` / `quick reply buttons` | `msgmenu` 菜单消息 |

再加一条：**`cursor` 是有状态的**，而 WhatsApp 那边无状态。

### 这里有一个必须提前想到的边缘情况

`session_store` 是纯内存、单进程的（`docker-compose.yml` 就这么跑）。如果 `cursor` 也放内存，**容器一重启 cursor 就没了**，下一次 `sync_msg` 不带 cursor 会把最近 3 天的消息全拉回来——而去重用的 `_seen_message_ids` 同样是内存的，也一起没了。结果是：**重启后 bot 会把三天内的历史消息重新回一遍**，演示现场足够灾难。

处理方式（实现时二选一，建议前者）：

- **冷启动先空跑一次**：不带 cursor 调一次 `sync_msg`，只把 `next_cursor` 推到最新，**不回复任何一条**，之后才开始正常接待
- 或者把 cursor 落盘/落 Redis——但这个仓库现在没有任何持久化，为一个 demo 引入依赖不划算

---

## 三、现有代码的真实状况

`routers/whatsapp_webhook.py:70` 的 `dispatch_message()` **一个函数干了三件事**：传输解析、对话状态机、按 Meta 格式产出回复。它返回的直接是 `whatsapp.build_interactive_list(...)` 这种 Meta payload。

更要紧的是：**这个仓库已经有两条渠道，而它们是各写各的**——

- `routers/chat.py`：网页版。选 bot / 选身份是**显式 REST 端点**（`/chat/{id}/select`），有多语言（`_localize` + `lang` 参数）
- `routers/whatsapp_webhook.py`：把同一件事做成了**聊天里的状态机**（发列表 → 用户点 → 存 `session.bot_id`），而且**只有英文**（一路 `bot.name.en`）

`services/outbox.py` 的注释已经把这个割裂写在脸上了：

> "only the WhatsApp path opens an outbox. The web chat in `routers/chat.py` has no channel to put a document on"

微信客服属于**聊天型**渠道，形状和网页版那种 REST 选择器对不上，要复用的正是 `whatsapp_webhook.py` 里那个状态机。所以摆在面前的是二选一：

- **(A) 再抄一遍**——第三份状态机。改一次 bot 选择逻辑要改三个地方，必然漂移
- **(B) 把状态机抽出来**——推荐

---

## 四、推荐方案：抽一层渠道无关的对话核心

```
app/channels/
    replies.py        # 渠道无关的回复类型：Text / Menu / Document
    conversation.py   # 状态机，从 whatsapp_webhook.py 搬过来，返回 Reply 而不是 payload
    whatsapp.py       # Reply -> Meta payload（包住现有 whatsapp.build_*，行为不变）
    wecom.py          # Reply -> 微信客服 send_msg payload

app/services/
    wecom.py          # access_token 缓存 + sync_msg + send_msg + 素材上传
    wecom_crypto.py   # WXBizMsgCrypt：验签 / 解密 / 加密

app/routers/
    wecom_webhook.py  # GET 验 URL、POST 收事件
```

三个设计要点：

1. **`conversation.py` 不认识任何一个渠道**。它吃 `(session_key, 用户说了什么)`，吐一串 `Reply`。`session_key` 现在是手机号，微信客服这边就是 `external_userid`——`session_store` 本来就是按字符串 key 的，不用改。
2. **`Menu` 只描述「有哪些选项、每项的 id 和标题」**，至于渲染成 Meta 的 interactive list 还是微信客服的 `msgmenu`，由渲染器决定。截断长度（现在 WhatsApp 是 20/24/72 字符）属于渲染器的知识，不属于状态机。
3. **access_token 复用 `api_client.py` 已有的缓存套路**——那里已经有 `EXPIRY_MARGIN_SECONDS` 提前续期、`TRANSPORT_ERRORS` / `NEVER_REACHED_THE_SERVICE` 的异常边界。企业微信的 token 是 7200 秒，比 ERP/CRM 的 15 分钟宽松，但**同样不能每次调用都去换**。

**第一步是纯重构，不加功能**：把状态机搬走、WhatsApp 改走渲染器，现有测试必须一个不少地全绿。这一步绿了，才谈得上加微信客服。

---

## 五、任务拆分

粒度对齐 `todo.md` 的约定：1-3 个文件、单一目的、可独立验收。

- [ ] **W1：抽出渠道无关的对话核心**（纯重构，不加功能）
      `channels/replies.py` + `channels/conversation.py` + `channels/whatsapp.py`，`whatsapp_webhook.py` 瘦成传输层。
      验收：现有测试全绿（静态统计 186 个测试函数，`parametrize` 展开后只多不少），一行业务行为都不许变。
      ⚠️ **基线未实测**：起草这份方案的机器上没装依赖（`ModuleNotFoundError: No module named 'pydantic_settings'`），也没有可用的 venv 或容器，所以 186 这个数**是数出来的，不是跑出来的**。另外 `todo.md` 任务 1 里那个「全套 41 passed」是 2026-08-31 的旧数字，早已过时，不要再引用。W1 开工第一件事是先把绿色基线真跑出来。
- [ ] **W2：WXBizMsgCrypt**
      `services/wecom_crypto.py`，纯函数。验签、解密、加密三件事。
      验收：用官方示例代码里的测试向量写单测。**不需要任何凭据就能验收。**
- [ ] **W3：微信客服 API 客户端**
      `services/wecom.py`：`gettoken` 缓存、`sync_msg`、`send_msg`。
      验收：httpx mock 单测。
- [ ] **W4：回调路由**
      `routers/wecom_webhook.py`：GET 解密 `echostr` 回明文；POST 验签 → 后台拉 `sync_msg` → 交给 `conversation` → `send_msg` 发回。含**冷启动 cursor 快进**（见上文边缘情况）。
      验收：mock 回调打进去，断言拉取和发送的调用序列。
- [ ] **W5：菜单消息**
      `channels/wecom.py` 把 `Menu` 渲染成 `msgmenu`，并把点击回调映射回 bot/identity 选择。
      ⚠️ **依赖前面第 2 条未验证项**——点击回调的形状要先确认，可能需要退化成「让用户直接打字选」。
- [ ] **W6：文件外发**
      `outbox.drain()` 现在写死了 `whatsapp.build_document_message`，要按渠道分流；微信客服侧走素材上传拿 `media_id`。
- [ ] **W7：真机验收**
      需要：能开通微信客服的企业微信主体、`corpid`、`Secret`、回调 `Token`、`EncodingAESKey`，以及一个公网可达的回调地址。
      **2026-09-04 更新：主体和微信客服都已就绪，但 Secret 拿不到手 —— 它被回调配置卡着，而回调配置需要先有线上端点。详见附录 A 的顺序约束。**

W1 到 W6 全部可以在**没有任何企业微信凭据**的情况下写完并跑通测试。凭据只卡 W7。

---

## 六、阻塞项

- [x] ~~**境外主体能否开通微信客服**~~——**2026-09-04 解除，这个担心整个不成立**：用户注册用的是**中国大陆个体工商户**（广州荔湾…商贸服务店），后台显示**已认证**、有效期到 2027-9-4。微信客服已开通，客服账号已建好。境外主体那条路根本没走。
      连带修正：接待配额不是「累计 100 位」那一档。**已认证 = 每天 100 位**，用完次日重置，对演示完全够用。
- [ ] **回调地址**：微信客服要求公网可达。现在 `chatbot.acuventech.com` 已经在 VPS 上收 WhatsApp 回调，加一条 `/webhook/wecom` 路径即可，不需要新域名。
- [ ] **新依赖**：WXBizMsgCrypt 需要 AES 实现，`requirements.txt` 里现在没有加密库，要加一个（`pycryptodome`）。

## 七、还没决定的事

一个产品层面的问题，顺带提一句、不展开：**demo 的受众是马来西亚中小企业，他们的客户主要在 WhatsApp 上，不在微信上。** 微信客服这条线拿去给谁看，值得先想清楚——如果是给做中国生意的客户看，那很成立；如果不是，投入产出比要打个问号。这是你的判断，不是我的。

---

## 附录 A：后台实况与剩余步骤（2026-09-04，据用户截图核实）

### 已经就绪的

| 项 | 状态 |
|---|---|
| 主体 | 广州荔湾…商贸服务店（**个体工商户**），中国大陆 |
| 认证 | **已认证**，有效期至 2027-9-4 |
| `corpid` | 我的企业 → 企业信息 → 最底部「企业ID」，`ww` 开头。**值不写进本文件**，见下面的保密约定 |
| 微信客服 | **已开通**，开关已打开 |
| 客服账号 | 已建：`未来智能科技客服` |
| 可见范围 | 未来智能科技（全公司），成员 1 人 |

### ⚠️ 更正：Secret 不来自自建应用

本文件 09-04 上午那版附录写着「微信客服本身不单独发 Secret，要建自建应用去调」——**这是错的，或者至少不是唯一路径**。

微信客服应用详情页描述文字右边那个 **`API` 小按钮**就是入口。官方指引：「企业管理员可以在『企业微信管理后台-微信客服应用』处开启API。**按照指引填写回调配置后即可开启成功。开启后再点击查看Secret**，管理员复制出Secret，即可用于后续获取接口调用凭证 accesstoken」。

所以**不需要建自建应用**，微信客服自己就发 Secret。自建应用那条路（「通过API管理会话消息」→「企业内部开发」→ 绑定自建应用）是**另一种模式**，用于把会话消息托管给已有的自建应用——我们没有这个需求，走简单的那条。

### ⚠️ 这带来一个顺序约束，直接改变任务顺序

「**填回调配置**」是「**拿到 Secret**」的**前置条件**，不是后置。而企业微信保存回调配置时会当场发一次验证请求，**答不上来就存不下**。

推论：**在写出一个能应答回调验证的线上端点之前，我们连 Secret 都拿不到。**

所以任务顺序要调整成：

1. **W2（WXBizMsgCrypt）** —— 不需要任何凭据，先做
2. **W4 的精简版** —— 只做 GET 那半边：解密 `echostr`、回明文。**部署上线**
3. 用户在后台点 `API` → 填回调配置（URL `https://chatbot.acuventech.com/webhook/wecom`，`Token` 和 `EncodingAESKey` 后台可随机生成）→ 验证通过 → **点「查看Secret」拿到 Secret**
4. 剩下的 W1 / W3 / W5 / W6 再按原计划走

（W1 那个重构和上面互不依赖，什么时候插进来都行，但必须在 W5 之前——渲染器是 W1 的产物。）

### 待确认：客服账号现在「No receptionist」

截图里客服账号显示 **No receptionist**（没有接待人员）。官方文档说「客服的接待人员需要在应用的可见范围内，API接口才可正常使用，否则返回 `errcode 60030`」，但**没有明说纯 API 托管、一个真人接待都不配时是否可行**——文档同时又提供了完整的「接待人员管理」API，暗示这套设计里预期有真人。

处理方式：**先不配，直接试**。真撞上 `60030`，就把管理员本人加成接待人员（可见范围本来就是全公司，1 个成员，加进去没有副作用）。不值得为这个提前纠结。

### W7 真机验收需要的凭据清单（已修正）

| 名字 | 从哪来 |
|------|--------|
| `corpid` | 我的企业 → 企业信息 → 最底部「企业ID」 |
| `Secret` | **微信客服应用** → `API` 按钮 → 填完回调配置后「查看Secret」 |
| `Token` / `EncodingAESKey` | 同上，填回调配置时自己生成 |
| `open_kfid` | 客服账号已建好，用 API 拉列表拿，或后台看 |

对应到 `config.py`，新增四个必填环境变量：`wecom_corpid` / `wecom_secret` / `wecom_token` / `wecom_encoding_aes_key`。

> 🔒 **这个仓库是 PUBLIC。**四个值一律走环境变量、**不给默认值、不写进任何被 git 跟踪的文件**——包括本方案文件。照抄 `erp_password` / `crm_password` 现在的写法。`corpid` 单独看不算凭据（没有 Secret 用不了），但它是企业的唯一标识，同样不入库。真实值只放 VPS 的 `/opt/ai_chatbot/backend/.env`。
