# 小册子 WhatsApp 截图脚本

> 给 `docs/brochure/` 里的中英两份 PDF 配图用。每个行业一段对话，截**一张**最能说明问题的图。
> 最后更新：2026-09-18

## 通用要求

- 手机给 **+60 17-394 8123** 发 `menu`，选对应行业，**每段开始前都重新发一次 `menu`**，免得上一段历史混进来
- **竖屏截图**，一张图里最好能看到 3–5 个气泡：客户问 → bot 答 → 出单号 / 出结果
- 截图前把手机调成**浅色模式**，状态栏的电量、信号无所谓，我排版时会裁掉
- 每段做两次：**中文一次、英文一次**（共 10 张）。时间不够就先做中文，英文版暂时共用
- 文件名按 `retail-zh.png`、`retail-en.png` 这样命名，发给我或放进 `docs/brochure/shots/`
- bot 回得不对（尤其酒店、SaaS 这两个新后台）就把那张也截下来发我，别重试凑

---

## 1. 零售（菜单选「电商零售 Retail」）

| 中文 | English |
|---|---|
| `Boss 这个 earbuds 还有 stock 吗? 我要 2 个` | `Hi, do you have the Sony earbuds in stock? I want 2` |
| `确认下单` | `Confirm the order` |
| `好`（要发票时） | `Yes`（when offered the invoice） |

**要截到的**：单号 `SO-…` + 那张 **PDF 发票**的气泡。一屏装不下就截 PDF 发票那一屏。

## 2. 餐饮（菜单选「餐饮外卖 Food Delivery」）

| 中文 | English |
|---|---|
| `两份椰浆饭一杯拉茶` | `Two nasi lemak and one teh tarik please` |
| 给一个地址，比如 `Jalan Ampang 123, KL` | same |
| 等一会儿，不要发任何消息 | same |

**要截到的**：总价 → 单号 `FD-…` → bot **自己发来**的「餐好了，骑手约 10 分钟」。

## 3. 酒店（菜单选「酒店旅游 Hotel & Travel」）

| 中文 | English |
|---|---|
| `我想订槟城的房间，两个人` | `I'd like a room in Penang for two` |
| `这个周末，住两晚` | `This weekend, two nights` |
| 选一间，`确认` | pick one, `Confirm` |

**要截到的**：bot 把「这个周末」换算成具体日期 → 房型和价格 → 订单号 `BK-…`。

## 4. 地产（菜单选「房产咨询 Real Estate」）

| 中文 | English |
|---|---|
| `蒲种三房，60 万以内` | `3-bedroom in Puchong under RM 600k` |
| `我想约看房` | `I'd like to book a viewing` |
| `陈家明，第一间，下周六下午 3 点` | `Jason Tan, the first one, next Saturday 3pm` |

**要截到的**：两个房源 → 看房确认（日期、时间、房源）。

## 5. SaaS 客服（菜单选「技术支持 SaaS Support」）

| 中文 | English |
|---|---|
| `我登录不了` | `I can't log in` |
| （bot 给步骤后）`还是不行` | `Still not working` |
| `好，帮我开单` | `OK, open a ticket` |

**要截到的**：分步排查 → 工单号 `TCK-…`。

---

## 后台截图（5 张，电脑浏览器）

**等上面五段 WhatsApp 对话跑完再截**，这样后台里正好是刚才那几张单，跟手机截图对得上。

- 浏览器窗口开到**全屏**（宽 1440 左右最好），缩放 100%
- 只截网页内容区，不要带浏览器地址栏和任务栏
- 中英两份 PDF **共用**这 5 张，不用截两次；后台有中英切换的，切成**英文**再截
- 版面是横长条（约 2.4 : 1），我会从**左上角**往下裁，重要内容放在页面上半部分

| 文件名 | 打开哪里 | 要看得到 |
|---|---|---|
| `bo-retail.png` | `https://erp.acuventech.com` → Sales Orders | 刚下的 `SO-…` 在列表第一行 |
| `bo-food.png` | `https://chatbot.acuventech.com/admin#food` | 刚下的 `FD-…` 和它的状态 |
| `bo-hotel.png` | `https://chatbot.acuventech.com/admin#hotel` | 刚订的 `BK-…` |
| `bo-realestate.png` | `https://crm.acuventech.com/dashboard` → Pipeline | 刚约看房的那张客户卡片 |
| `bo-saas.png` | `https://chatbot.acuventech.com/admin#saas` | 刚开的 `TCK-…` 和优先级 |

截好后跟手机截图一起发给我，或放进 `docs/brochure/shots/`。
