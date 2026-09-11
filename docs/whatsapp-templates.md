# WhatsApp 模板消息（任务 18）

> 这份文档是给**你**用的：照着抄进 Meta 后台提交审核。
> 同时它也是**代码的合同**——`backend/app/services/notify.py` 里的模板名、语言代码和变量顺序必须和这里一字不差，改了这边就得改那边。
> 最后更新：2026-09-12

---

## 为什么需要模板

WhatsApp 只允许在**客户最后一条消息之后的 24 小时内**自由发消息。超出这个窗口，只能发**事先审核通过的模板**，否则 Cloud API 直接报错，客户什么都收不到。

任务 19 的主动推送发生在下单后约 30 秒，**永远落在窗口内**，所以演示当天走的是纯文本那条路。模板是给另外两种情况准备的：

1. 演示隔天回访（「您昨天那张单已出库」）——窗口早就关了
2. 演示当场如果客户半小时没说话，窗口虽然没关但已经开始逼近，模板是唯一稳的

**所以模板审核不过不影响演示**，但没有它，「主动推送」这件事就只能在窗口内成立，说服力少一半。

---

## 提交前先确认

- 后台路径：Meta Business Suite → WhatsApp Manager → **Message templates** → Create template
- 用**新 portfolio** 那个 App（Acuven Connect）下的 demo 号 `+60 17-394 8123`，不要提到公司客服号那条线上去
- 类别一律选 **Utility**（工具类）。选 Marketing 会进更严的审核队列，而且发给客户可能计费不同；订单状态通知本来就属于 Utility
- 三种语言要**分别提交三次**（同一个模板名，语言不同），Meta 是按「模板名 + 语言」存的
- 审核一般几小时，最慢 1-2 天。**先交了再回来做任务 19，别串行等**

---

## 模板一：`order_confirmed`（订单已确认）

| 字段 | 值 |
|---|---|
| Name | `order_confirmed` |
| Category | Utility |
| Header | 无 |
| Footer | 无 |
| Buttons | 无 |

变量顺序（三种语言必须一致，代码按位置填）：

| 变量 | 含义 | 示例值（提交时填这个） |
|---|---|---|
| `{{1}}` | 客户称呼 | `Kelvin` |
| `{{2}}` | 订单号 | `SO-2026-00001` |
| `{{3}}` | 含税总额 | `RM 657.80` |

### Body（三语，逐字复制）

**English（语言选 `English`，代码 `en`）**

```
Hi {{1}}, your order {{2}} is confirmed. Total: {{3}}. We will message you again as soon as it ships.
```

**中文简体（语言选 `Chinese (CHN)`，代码 `zh_CN`）**

```
您好 {{1}}，您的订单 {{2}} 已确认，合计 {{3}}。出库后我们会再通知您。
```

**Bahasa Melayu（语言选 `Malay`，代码 `ms`）**

```
Hai {{1}}, pesanan anda {{2}} telah disahkan. Jumlah: {{3}}. Kami akan menghubungi anda sebaik sahaja ia dihantar.
```

---

## 模板二：`order_shipped`（已出库 + 追踪号）

| 字段 | 值 |
|---|---|
| Name | `order_shipped` |
| Category | Utility |
| Header | 无 |
| Footer | 无 |
| Buttons | 无 |

| 变量 | 含义 | 示例值 |
|---|---|---|
| `{{1}}` | 客户称呼 | `Kelvin` |
| `{{2}}` | 订单号 | `SO-2026-00001` |
| `{{3}}` | 物流追踪号 | `DO-2026-00031` |

### Body（三语，逐字复制）

**English（`en`）**

```
Good news {{1}}, your order {{2}} has left our warehouse. The tracking number is {{3}}. Reply here any time if you need an update.
```

**中文简体（`zh_CN`）**

```
好消息 {{1}}，您的订单 {{2}} 已出库，物流单号 {{3}}。有任何问题随时回复这条消息。
```

**Bahasa Melayu（`ms`）**

```
Berita baik {{1}}, pesanan anda {{2}} telah keluar dari gudang. Nombor penjejakan ialah {{3}}. Balas mesej ini bila-bila masa jika anda perlukan bantuan.
```

---

## 写文案时踩过的 Meta 规则

这几条是文案长成现在这样的原因，改文案前先看一眼：

- **模板名只能用小写字母、数字和下划线**。`order_confirmed` 合法，`orderConfirmed` 不行
- **正文不能以变量开头或结尾**。所以每句都用「您好」「好消息」起头、用一句固定的话收尾，不是凑字数
- **两个变量不能挨着**。`{{2}} {{3}}` 会被拒
- **变量编号必须从 1 开始且连续**。跳号会被拒
- **提交时每个变量都要给示例值**，Meta 拿它判断这个模板是不是在发垃圾信息。示例值就填上表里那些
- 正文里**不要放促销词**（免费、优惠、限时），那会被判成 Marketing 而不是 Utility

---

## 审核通过之后

代码这边不需要改任何东西——`notify.py` 已经按上面的名字和变量顺序写好了。确认一下这三件事就行：

1. Meta 后台模板状态显示 **Approved**（三种语言各自都要 Approved，是分开审的）
2. 模板名拼写和上表一致
3. 变量个数是 3 个，顺序是「称呼 / 单号 / 金额或追踪号」

**如果你在后台改了模板名或变量顺序**，必须同步改 `backend/app/services/notify.py` 里的 `ORDER_CONFIRMED` / `ORDER_SHIPPED` 两个常量，否则发出去是一个 Cloud API 错误，客户那边什么都收不到。

## 发出去长什么样

代码最终 POST 给 Cloud API 的就是这个形状（`notify._template_payload` 生成）：

```json
{
  "messaging_product": "whatsapp",
  "to": "60173948123",
  "type": "template",
  "template": {
    "name": "order_confirmed",
    "language": { "code": "en" },
    "components": [
      {
        "type": "body",
        "parameters": [
          { "type": "text", "text": "Kelvin" },
          { "type": "text", "text": "SO-2026-00001" },
          { "type": "text", "text": "RM 657.80" }
        ]
      }
    ]
  }
}
```

语言代码怎么选：客户档案里**没有**语言字段可用（`UserProfile.language` 至今没有任何地方写入），所以模板固定发 `en`。窗口内的纯文本推送不受这个限制——它是三语一条，和 `llm.FALLBACK_REPLY` 同一个形状。
