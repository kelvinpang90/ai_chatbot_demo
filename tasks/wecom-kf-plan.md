# 接入方案：企业微信「微信客服」渠道

状态：**待确认，尚未动代码**。2026-09-03 起草。
需求来源：临时需求，不在 `tasks/todo.md` 的六个批次里，按 CLAUDE.md「先计划、等确认」走。

已拍板的三个前提（2026-09-03 用户选定）：

1. 接的是**微信客服（kf）API**，不是企业微信自建应用——受众是外部微信用户，和现在 WhatsApp 的场景一一对应
2. 落在**当前仓库 `ai_chatbot_demo`**，作为 WhatsApp 之外的第二条真实渠道
3. ~~没有中国大陆主体~~ —— **2026-09-04 作废**。用户当时的说法有误，实际注册用的是**中国大陆个体工商户**、且**已认证**。整份方案里所有围绕「境外主体」的担忧因此全部失效，保留在下文只为留痕。

---

## 一句话结论

**（2026-09-04 改写）** 技术上完全可做，**主体这一关根本不存在**——已认证的大陆个体工商户，每天可接待 100 位客户，对演示绰绰有余。微信客服已开通、客服账号已建好。

真正的成本是两笔：

1. **拿 Secret 之前得先有线上端点。** 微信客服的 Secret 被「回调配置」卡着，而企业微信保存回调配置时会当场验证。所以必须先写出能应答验证的 GET 端点并部署，才能拿到调 API 的凭据。**这颠倒了任务顺序**，详见附录 A。
2. **对话逻辑和 Meta 报文格式是焊死的。** 接第二条聊天渠道必须先做一次重构，不是加一个 router 就完事。

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

**我们落在第二档**：已认证、未绑视频号 → **每天 100 位，次日重置**。演示随便跑，不用省着用。
（起草时误以为会落在第一档那个「累计 100 位、用掉不回来」，那是未认证企业才有的限制。）

### 没验证的（风险都在这里）

1. ~~境外主体到底能不能开微信客服~~——**已作废，问题不存在**（主体是大陆个体工商户）。这条留着只为说明：起草时把它当成唯一硬阻塞，结论下早了。
2. **菜单消息（`msgmenu`）被点击后回调回来的具体形状**——是回一条文本消息（内容为菜单项的 `content`），还是一个带 `id` 的事件。这决定了 `_handle_interactive_reply` 那套 id 映射能不能照搬。
3. **文件消息的素材上传细节**（临时素材接口、有效期、大小上限），需要时再查。
4. **WXBizMsgCrypt 的实现细节**——官方有各语言示例代码，实现时照抄即可，但 Python 版需要 `pycryptodome` 之类的依赖，现在 `requirements.txt` 里没有。

> ⚠️ 按 CLAUDE.md 的高风险操作规则，注册/认证/登录这类动作我不代做。上面第 1 条已由用户在后台实地确认并截图（2026-09-04），结论见附录 A。

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

> ⚠️ **执行顺序不是 W1→W7。** 附录 A 发现 Secret 被回调配置卡着，所以实际顺序是：
> **W2 →（W4 的 GET 那半边 + 部署）→ 用户在后台填回调配置拿 Secret → W3 → W1 → W5 → W6 → W7**。
> W1 和前面几步互不依赖，插在哪都行，但必须排在 W5 之前——渲染器是 W1 的产物。
> 编号保持不变，方便交叉引用。

- [ ] **W1：抽出渠道无关的对话核心**（纯重构，不加功能）
      `channels/replies.py` + `channels/conversation.py` + `channels/whatsapp.py`，`whatsapp_webhook.py` 瘦成传输层。
      验收：现有测试**一个不少地全绿**，一行业务行为都不许变。
      ✅ **基线已实测（2026-09-04）：`254 passed`，1.78 秒。** 这是跑出来的，不是数出来的。
      两个流传中的旧数字都别再引用：`todo.md` 任务 1 里的「全套 41 passed」是 2026-08-31 的；本文件早前写的 186 是静态数的测试函数个数，`parametrize` 展开后实际是 254。
- [x] **W2：WXBizMsgCrypt** —— **2026-09-04 完成**
      `services/wecom_crypto.py` + `tests/test_wecom_crypto.py`，**19 个测试全绿**。
      两处偏离原计划：
      - **只做接收半边，没写 encrypt。** 回微信客服的消息走 `send_msg` API，不是从回调原路返回，所以这个代码库永远不需要加密。一个没人用的加密函数出了错也没人会发现——按 CLAUDE.md「不写投机性代码」砍掉了。
      - **没用官方测试向量。** 测试自己造密文做往返，所以证明的是「解析器自洽 + 每种畸形输入都被拒」，**不是「和腾讯逐字节一致」**。真正的一致性只有企业微信接受回调 URL 那一刻才算验过。这一点写在测试文件的模块 docstring 里，别让后人误读绿灯。
      依赖：`requirements.txt` 增加 `cryptography>=43,<47`。
- [ ] **W3：微信客服 API 客户端**
      `services/wecom.py`：`gettoken` 缓存、`sync_msg`、`send_msg`。
      验收：httpx mock 单测。
- [~] **W4：回调路由** —— **GET 半边 2026-09-04 完成，POST 半边待做**
      `routers/wecom_webhook.py` + `tests/test_wecom_webhook.py`，**15 个测试全绿**。已接进 `main.py`，路径 `/webhook/wecom`。
      - ✅ **GET**：验签 → 解密 `echostr` → 回**裸明文**（不带引号/BOM/换行，测试里按字节断言）。四种失败各有出口：签名错 401、发给别家企业的 401、没有 `echostr` 400、**没配凭据 503**（没配置是部署状态，不是伪造请求，不该谎报 401）。
      - ✅ **POST**：目前只验签 + 回 200，**不处理消息**。理由写在 docstring 里：回调配置一存下企业微信就开始 POST，全都 404/405 会在账号上堆成投递失败；而回调本来就不带消息内容，`sync_msg` 三天内还能补拉，所以先签收不办事是安全的。
      - `<Encrypt>` 是**手写字符串切割**取的，没过 XML 解析器——这个 body 在验签之前是未认证、外部可达的，不该变成文档树。5 种畸形 body 断言返回空串而不是抛异常。
      - [ ] **待做**：POST 真正拉取 → `sync_msg` → `conversation` → `send_msg`，含**冷启动 cursor 快进**（见上文边缘情况）。依赖 W3。
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
- [x] ~~**新依赖**~~——2026-09-04 已加 `cryptography>=43,<47`（不是原计划的 `pycryptodome`；`cryptography` 维护更活跃、wheel 更全，两者都能做 AES-256-CBC）。
- [ ] 🚨 **域名主体校验（2026-09-04 实测撞上，当前头号阻塞）**

      在自建应用的「Message-receiving server configuration」里填 `https://chatbot.acuventech.com/webhook/wecom`，企业微信当场红字拒绝：

      > Domain entity verification failed. Configure a domain name whose **filing entity** is the same as or related to the current company entity.

      企业微信要求回调域名的 **ICP 备案主体**与企业主体一致或关联。`chatbot.acuventech.com` 属于 Acuven（马来西亚）、跑在境外 VPS 上，**不可能**备案到「广州荔湾…商贸服务店」名下。**这是政策管控，代码层面无解。**

      查证情况：找到两个撞上同一报错的 GitHub issue（`chatgpt-on-wechat#1092`、`wecom-chatgpt#11/12`），**都没有任何回复，无已证实的绕过方法**。「填 IP 代替域名」这条也没找到任何确认可行的记录。

      如果非走回调不可，代价是：域名 + **中国大陆服务器** + ICP 备案（约 10-20 个工作日，需个体户营业执照和法人实名）。而且备案域名必须解析到大陆服务器，意味着还要在大陆放一个中转——虽然只需要中转「收回调」这一跳，`sync_msg` / `send_msg` / LLM 都还能留在境外 VPS 上（`qyapi.weixin.qq.com` 境外可达）。

      #### 「买个主体一致的域名指向 VPS」为什么不是一步到位（2026-09-04 用户提问）

      **备案不是域名的属性，是「域名 + 大陆接入商」的属性。** 流程是：在阿里云/腾讯云**先买一台大陆服务器**（通常要求 3 个月起）→ 拿到备案服务号 → 用它提交备案 → 管局审核 10-20 工作日。没有大陆服务器就发起不了备案，光买域名备不了案。

      备案通过之后，DNS 解析确实可以自己改。企业微信查的**大概率是工信部备案库里的主体名，不是当前解析到哪个 IP**——所以「备案域名 + 解析指向境外 VPS」很可能能通过校验。

      ⚠️ 但这有个**会在最坏的时间点炸**的风险：接入商（阿里云）会定期核查，发现备案域名解析到非本平台/境外 IP，可以**注销接入**。一旦注销，企业微信侧的校验重新失败——**可能就在演示前夕**。

      所以真要走这条，更稳的形态是：**让那台大陆服务器实际承载 `/webhook/wecom` 这一跳**，备案是真实的、经得起核查。而且这一跳很薄——回调本来就不带消息内容，大陆那台只需要应答握手 + 回 200，`sync_msg` / `send_msg` / LLM 全留在境外 VPS。

      成本对照：域名 ¥30-70/年 + 大陆轻量服务器 ¥60-100/月（备案常要求买满 3 个月）+ 10-20 工作日审核 ≈ **3-4 周和几百块**；而下面的轮询方案如果成立，是 **0 元 0 天**。**所以先验证轮询，再决定要不要花这笔钱。**

- [ ] ⚠️ **企业可信IP：备案问题可能从另一扇门回来（2026-09-04 实测中发现）**

      `wecom_probe.py` 第一次实跑结果：

      | 调用 | 结果 |
      |---|---|
      | `gettoken` | ✅ `errcode=0` —— **Secret 正确，凭据链路是通的** |
      | `kf/account/list` | ❌ `errcode=48002 api forbidden`，hint 里带 `from ip: <用户本机IP>` |

      48002 = 「API接口无权限调用，应用的权限与所调用的接口不匹配」。两种可能，**必须按顺序排除**：

      1. **应用还没在微信客服里授权**（最可能，而且这一步本来就没做）——微信客服 → `API` → `Apps that can call APIs` → `Setting`，勾上应用 + 指定客服账号。免费，先做这个。
      2. **企业可信IP 没配**——查到的说法：「**2022年6月20日之后新创建的自建应用必须在管理端配置可信IP，仅配置的可信IP能调用接口**」。我们这个应用是 2026-09-04 新建的，正好落在这条规则里。

      **第 2 条要是成立，麻烦就大了**：多处资料称「配置企业可信IP前，请先设置可信域名或接收消息服务器URL」——而这两样**都要备案域名**。那样的话备案就绕不过去了，轮询也救不了，因为连 `sync_msg` 都调不动。

      ⚠️ **尚未确定**：`gettoken` 成功说明可信IP没有卡死所有接口（也可能 `gettoken` 本身豁免）。到底是原因 1 还是原因 2，**得先做完授权再跑一次才知道**。

      要看的地方：自建应用详情页里有没有「企业可信IP / Trusted IP」一栏，以及它**允许直接填 IP**，还是提示「请先设置可信域名或接收消息服务器URL」。
      - 允许直接填 → 把 **VPS 的公网 IP** 加进去（本机 IP 只够本地测试用），**备案依然可以绕开**
      - 提示要先设域名 → 备案绕不过去了

- [ ] 💡 **逃生路线：改成轮询，可能让上面这条整个消失（未验证，优先试）**

      回调的作用只是通知「有新消息」。而 `sync_msg` 本来就是**我们主动去拉**的，带 `cursor`、消息保留 3 天。**如果不配回调也能调 `sync_msg`，那就根本不需要备案域名。**

      这条**尚未验证**，但验证成本极低：自建应用的 Secret 现在就能拿，在微信客服里授权一下，直接调 `sync_msg` 看返回什么。

      - 成立 → 轮询（3-10 秒一次）代替回调，备案问题消失，`/webhook/wecom` 那个端点先留着不用
      - 不成立 → 才需要认真评估备案那条路值不值得
      - 需要留意：回调带的 `token` 会影响 `sync_msg` 的频率限制，不带 token 轮询可能被限流更狠；轮询间隔要和企业微信的接口配额对一下

- [ ] **部署**：`/webhook/wecom` 的 GET 已经能应答，但在域名问题解决前**部署了也没用**——企业微信根本不接受这个域名。部署时要先在 VPS 的 `/opt/ai_chatbot/backend/.env` 里填好 `WECOM_CORPID` / `WECOM_TOKEN` / `WECOM_ENCODING_AES_KEY`，否则端点一律返回 503。

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

### ⚠️ 走的是自建应用（这条来回改过两次，以截图为准）

留个账，免得后人再绕：

1. **09-03 初版**：说微信客服的 API 由**自建应用**去调 —— **对的**
2. **09-04 上午**：据搜到的二手中文教程「填完回调配置后点查看Secret」，改成「微信客服自己发 Secret，不用自建应用」—— **错的**
3. **09-04 下午**：用户展开 `API` 面板截图，面板里**根本没有回调配置、也没有「查看Secret」**，只有两行：
   - `WeChat Developer's ID` → Link
   - `Apps that can call APIs` → Setting，说明文字：*"Custom apps can call the WeChat Customer Service API. A specified customer service account must be configured so that the chat history-related APIs can be called."*

**结论回到第 1 版：Secret 来自自建应用。** 那个「查看Secret」的流程要么是大陆版控制台的旧形态，要么根本不存在于这个版本。**二手教程输给截图。**

⚠️ 教训：这一条连着两轮都是拿搜索结果当权威改结论。**后台长什么样只有截图说了算**，官方文档的措辞和实际控制台可以不一致。

### 顺序约束（依然成立，只是换了位置）

回调配置不在微信客服这边，而在**自建应用的「接收消息服务器配置」**里。但企业微信保存这个配置时**照样会当场发验证请求，答不上来就存不下**——所以「先有线上端点」这个约束没变，只是配置的位置换了。

任务顺序不变：

1. ✅ **W2（WXBizMsgCrypt）** —— 已完成
2. ✅ **W4 的 GET 半边** —— 已完成，**待部署**
3. 部署后，用户在**自建应用**里填回调配置 → 验证通过
4. 从**自建应用**取 Secret，在微信客服 `Apps that can call APIs` 里授权这个应用 + 指定客服账号
5. 剩下的 W1 / W3 / W5 / W6 按原计划走

（W1 那个重构和上面互不依赖，什么时候插进来都行，但必须在 W5 之前——渲染器是 W1 的产物。）

### 代码不受影响

自建应用的回调和微信客服的回调**用同一套 WXBizMsgCrypt**，`receiveid` 同样是 `corpid`（企业内部开发一律如此）。所以 `wecom_crypto.py` 和 `wecom_webhook.py` **一行都不用改**，`config.py` 那四个变量也够用——kf 的 `gettoken` 只要 `corpid` + `secret`，不需要 `agentid`。
自建应用的 POST 回调体里多一个 `<AgentID>` 元素，我们只取 `<Encrypt>`，无所谓。

### 待确认：客服账号现在「No receptionist」

截图里客服账号显示 **No receptionist**（没有接待人员）。官方文档说「客服的接待人员需要在应用的可见范围内，API接口才可正常使用，否则返回 `errcode 60030`」，但**没有明说纯 API 托管、一个真人接待都不配时是否可行**——文档同时又提供了完整的「接待人员管理」API，暗示这套设计里预期有真人。

处理方式：**先不配，直接试**。真撞上 `60030`，就把管理员本人加成接待人员（可见范围本来就是全公司，1 个成员，加进去没有副作用）。不值得为这个提前纠结。

### W7 真机验收需要的凭据清单（已修正）

| 名字 | 从哪来 |
|------|--------|
| `corpid` | 我的企业 → 企业信息 → 最底部「企业ID」 |
| `Secret` | **自建应用**的 Secret（App Management → Self-built → 该应用） |
| `Token` / `EncodingAESKey` | **自建应用** → 接收消息服务器配置，填的时候随机生成 |
| `open_kfid` | 客服账号已建好，用 API 拉列表拿，或后台看 |

还要在**微信客服 → `API` → `Apps that can call APIs` → Setting** 里，把这个自建应用授权进去，并指定它能管的客服账号（`未来智能科技客服`）——否则接口调不通。

对应到 `config.py`，新增四个必填环境变量：`wecom_corpid` / `wecom_secret` / `wecom_token` / `wecom_encoding_aes_key`。

> 🔒 **这个仓库是 PUBLIC。**四个值一律走环境变量、**不给默认值、不写进任何被 git 跟踪的文件**——包括本方案文件。照抄 `erp_password` / `crm_password` 现在的写法。`corpid` 单独看不算凭据（没有 Secret 用不了），但它是企业的唯一标识，同样不入库。真实值只放 VPS 的 `/opt/ai_chatbot/backend/.env`。

---

## 附录 B：本地怎么跑测试（2026-09-04 实测可用）

之前几轮一直说「本机跑不了测试」，那是没建 venv。建一个就能跑，Windows 上从仓库根目录：

```bash
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m pytest -q
```

实测 `254 passed`，1.78 秒，不需要任何 `.env`、不联网、不碰 ERP/CRM。`.venv` 已被 `.gitignore` 挡住，不会污染工作区。

⚠️ 注意区分：**这套只能跑单元测试**。凡是要真打 Graph API / 企业微信 / ERP / CRM 的验证，仍然受 CLAUDE.md 的高风险规则约束，也仍然会被权限分类器拦（见 `todo.md` 任务 1 的记录），那些得你手工跑。
