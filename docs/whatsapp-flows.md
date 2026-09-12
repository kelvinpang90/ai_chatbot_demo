# WhatsApp Flow —— 预约看房表单（任务 24）

> 这份文档是给**你**用的：照着把 Flow JSON 贴进 Meta 后台，建出表单、拿到 Flow ID。
> 同时它是**代码的合同**——screen id、每个字段的 `name`，必须和
> `backend/app/tools/realestate.py` 里的常量一字不差。对不上不会报错，**字段会静悄悄变成空的**，
> 然后表单提交回来被判定为「读不出来」。
> 最后更新：2026-09-13

---

## 一句话

客户说想看房 → bot 调 `offer_viewing_form` → 客户手机上弹出原生表单（姓名 / 房源 / 日期 / 时段）→
**全程不跳出 WhatsApp** → 提交后那条预约出现在 `/vertical-admin`，CRM 看板同时长出线索卡。

---

## 最重要的一个设计决定：走 `navigate`，不走 `data_exchange`

Flow 有两种驱动方式：

| | `data_exchange` | `navigate`（本项目用这个） |
|---|---|---|
| 每翻一屏 | Meta 回调**我们的公网 endpoint** | 不回调，数据一次性随消息发过去 |
| 要不要建 endpoint | 要，而且要做 RSA 密钥交换 + 签名校验 | **不要** |
| 表单提交怎么回来 | 走那个 endpoint | 走**已有的 webhook**，一条 `nfm_reply` 入站消息 |
| 工作量 | 几天 | 几小时 |

这是个四个字段的表单，没有分支、没有翻屏、没有服务端校验。`data_exchange` 换不来任何东西，
却要多维护一套密钥和一个公网入口。所以房源列表是在发送时就塞进
`flow_action_payload.data` 的（见 `whatsapp.build_flow_message`），客户选的每一套房都真实存在、
价格和 bot 报的一致。

⚠️ **代价**：`navigate` 下 Meta 不校验字段，表单提交回来的内容**必须由我们自己解析和校验**，
`book_from_form` 就是干这个的——缺字段、日期读不出来，一律不写库、并明确告诉 bot「没保存」。

---

## 一、在 Meta 后台建 Flow

后台路径：**WhatsApp Manager → Flows → Create flow**

1. 名字随便取（例如 `Book a viewing`），Category 选 **Other**（或 Appointment booking，按后台当时给的选项）
2. 建的时候选 **Endpoint: 不接**（不要填 endpoint URL，不要开 data exchange）
3. 进 **Flow Builder → Edit JSON**，把下面整段贴进去，保存
4. 保存后 Builder 会校验；**有红字先看下面「版本号」那条**
5. 拿到 **Flow ID**（一串数字，在 Flow 列表或 URL 里），填进 `.env`

⚠️ **版本号是唯一我没法替你确认的东西。** 下面写的是 `"version": "7.0"`。
Meta 的 Flow JSON 版本在涨，Builder 只接受它当时支持的那几个。**如果它报版本错误，
把 `version` 改成 Builder 提示的那个即可**，其余结构不用动。这是照着贴之前唯一要留意的地方。

---

## 二、Flow JSON

```json
{
  "version": "7.0",
  "screens": [
    {
      "id": "BOOK_VIEWING",
      "title": "Book a viewing",
      "terminal": true,
      "data": {
        "listings": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": { "type": "string" },
              "title": { "type": "string" }
            }
          },
          "__example__": [
            { "id": "PROP-202", "title": "Bangsar South, KL · 2BR · RM 620,000" },
            { "id": "PROP-203", "title": "Petaling Jaya · 4BR · RM 980,000" }
          ]
        }
      },
      "layout": {
        "type": "SingleColumnLayout",
        "children": [
          {
            "type": "TextSubheading",
            "text": "KL Homes Realty"
          },
          {
            "type": "TextBody",
            "text": "Tell us who you are and when suits you. Your agent will call to confirm."
          },
          {
            "type": "Form",
            "name": "booking",
            "children": [
              {
                "type": "TextInput",
                "name": "customer_name",
                "label": "Your name",
                "input-type": "text",
                "required": true
              },
              {
                "type": "Dropdown",
                "name": "listing_id",
                "label": "Property",
                "required": true,
                "data-source": "${data.listings}"
              },
              {
                "type": "DatePicker",
                "name": "viewing_date",
                "label": "Preferred date",
                "required": true
              },
              {
                "type": "TextInput",
                "name": "preferred_time",
                "label": "Preferred time (optional)",
                "input-type": "text",
                "required": false
              },
              {
                "type": "Footer",
                "label": "Submit",
                "on-click-action": {
                  "name": "complete",
                  "payload": {
                    "customer_name": "${form.customer_name}",
                    "listing_id": "${form.listing_id}",
                    "viewing_date": "${form.viewing_date}",
                    "preferred_time": "${form.preferred_time}"
                  }
                }
              }
            ]
          }
        ]
      }
    }
  ]
}
```

### 这份 JSON 和代码的对应关系（改一边就要改另一边）

| Flow JSON | 代码 | 不一致会怎样 |
|---|---|---|
| `screens[0].id` = `BOOK_VIEWING` | `realestate.SCREEN` | 表单打开是空白屏 |
| `data.listings` | `build_flow_message(data={"listings": [...]})` | 房源下拉框是空的 |
| `customer_name` | `realestate.FIELD_NAME` | 字段读成空 → `FORM_UNREADABLE`，不写库 |
| `listing_id` | `realestate.FIELD_LISTING` | 同上 |
| `viewing_date` | `realestate.FIELD_DATE` | 同上 |
| `preferred_time` | `realestate.FIELD_TIME` | 只是丢掉时段，预约照常保存 |
| `on-click-action.name` = `complete` | —— | 不是 `complete` 的话表单不会回传 |

**`DatePicker` 回传的是毫秒时间戳字符串**（不是 `2026-09-21`），`_as_date` 按 UTC 解析——
那个午夜就是以 UTC 计的，用本地时间读会让格林威治以西的人早一天。三种格式都收：
毫秒、`YYYY-MM-DD`、`DD/MM/YYYY`。

---

## 三、填 `.env` 并重建容器

```
WHATSAPP_FLOW_ID=<后台拿到的那串数字>
WHATSAPP_FLOW_MODE=draft
```

```bash
cd /opt/ai_chatbot
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```

（`restart` 读不到新环境变量——这个坑本仓库踩过两次。）

**`WHATSAPP_FLOW_MODE` 的用法**：

- `draft` —— Flow 还没发布时用。**只有 Meta App 的拥有者本人**能打开草稿 Flow，
  所以你自己的手机可以试，别人的不行。
- `published` —— Flow 发布之后**必须改回来**。Meta 对已发布的 Flow 传 `mode: draft` 会报错。

所以顺序是：贴 JSON → 存草稿 → `MODE=draft` 自己手机试一遍 → 后台点 Publish → `MODE=published` → 再重建一次容器。

---

## 四、没有 Flow 也能演（降级路径）

`WHATSAPP_FLOW_ID` 空着不是坏掉，是**一个受支持的状态**：

- `offer_viewing_form` 返回 `NO_FORM`，bot 改成在聊天里一次性问三件事（姓名 / 房源 / 日期）
- 客户答完，bot 照样说「已记下，经纪会打电话确认」
- **网页聊天线永远走这条**——那条线没有 WhatsApp 可以承载表单

计划里写明了「不要在 Flow 上死磕超过一个 session」。降级路径是**内建并且有测试守着的**
（`test_without_a_flow_configured_the_bot_is_told_to_ask_in_chat`），不是留着应急的备胎——
没人跑过的备胎就是坏的。

⚠️ 但要注意：**降级路径下客户答完，预约不会自动写进后台**。`book_from_form` 只在收到
`nfm_reply` 时触发；聊天里口头给的信息目前只有 CRM 线索卡那条记录。要把口头信息也落库，
得再给 bot 一个写预约的工具——**没做，因为这是任务 24 的降级路径而不是主路径**，
真要走降级，演示时指着 CRM 看板讲即可。

---

## 五、验收（任务 26 的一部分）

真机上跑一遍：

1. 手机 WhatsApp 发「有没有 60 万以内的三房」→ bot 列房源
2. 说「我想去看看」→ **表单弹出来**
3. 填完提交 → **全程没跳出 WhatsApp**
4. `/vertical-admin` 五秒内出现那条预约，最上面一行高亮
5. CRM 看板出现线索卡，金额是那套房的价格

第 3 步是这出戏的核心，第 4、5 步是它的证据。
