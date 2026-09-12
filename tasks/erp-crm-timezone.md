# ERP / CRM 时间差 8 小时 — 排查记录

**2026-09-12。只读排查，两个仓库一行代码没动。** 起因：真机演示下单，手机上 16:49 下的单，
erp_os 后台显示 08:49。当时以为是「存的到底是 UTC 还是本地时间」的存储问题，**查下来不是**。

> ⚠️ 修的地方在 `E:\projects\erp_os` 和 `E:\projects\crm_os`，**不在本仓库**。
> 本文件只是把排查结论存下来，免得下次从头查。

---

## 结论

**显示层的 bug，不是存储的 bug，也跟容器 TZ 无关。**

后端把 naive datetime 序列化成 `"2026-09-12T08:49:00"`，**不带 `Z`、不带 offset**；前端
`new Date(String(val))`（erp `SOColumns.tsx:93`）和 `dayjs(msg.created_at)`（crm
`ConversationView.tsx:62`）按 ES 规范会把**不带 offset 的字符串当本地时间**读。
UTC 的数字被原样印出来，一次转换都没发生。

### 存的确实是 UTC

| 这一组 | 谁生成的 | 有多确定 |
|---|---|---|
| crm_os 全部 `created_at`/`updated_at`/`won_at` | `datetime.utcnow()`（`models/deal.py:36` 等十几个模型） | **确定**，代码级，无视容器 TZ |
| erp_os `confirmed_at`/`fully_shipped_at`/`cancelled_at`/`deleted_at` | `datetime.now(UTC)`（`services/sales.py:371,443`；`repositories/base.py:112`） | **确定**，同上 |
| erp_os `created_at`/`updated_at` | MySQL `CURRENT_TIMESTAMP`（`models/base.py:16,21`，没有 Python `default=`） | **推断**。取决于 `infra_mysql` 的 time_zone，那在 `vps_infra` 仓库里，代码里看不到。16:49→08:49 这个观察本身是它**现在**按 UTC 算的证据，但证明不了一直是 |

列类型是 `DateTime(timezone=False)` → MySQL **DATETIME**（不存时区、读写不转换）。
⚠️ `erp_os/docs/ddl.sql:70` 却写的是 `TIMESTAMP`，和 migration
（`alembic/versions/8058342b33b7:611`）打架。跑的是 alembic，所以大概率是 DATETIME，
但这是唯一一处文档和代码不一致的地方，值得一条 `SHOW CREATE TABLE` 定案。

### 改容器 TZ 没用

erp_os **早就设了** `TZ: Asia/Kuala_Lumpur`，四个服务全有（`docker-compose.yml:22-23,34,51,67,80`），
照样显示 08:49。`datetime.now(UTC)` 和 `datetime.utcnow()` 根本不看 `TZ`，而 `erp_backend`
的 TZ 也管不到 `infra_mysql` 的 `CURRENT_TIMESTAMP`。

本仓库 `docker-compose.prod.yml:24` 那条 `TZ=Asia/Kuala_Lumpur` 是为了**日志和审计时间戳**
（注释里写着「9pm 的演示归档到 13:00，按发生的钟点找不到」），**不是一回事，不能照搬**。

---

## 改了会影响什么

先回答最直接的那个问题：**不影响「正常」显示，因为现在没有一处是正常的。**
所有历史记录在屏幕上会整体 +8 小时——它们现在本来就全都早显示了 8 小时。数据库一个字节不动。

### 不受影响（查过，确认没事）

- **e-Invoice / MyInvois 提交：完全不碰，而且本来就是对的。**
  `integrations/myinvois_ubl.py:287-288` 的 `IssueTime` 是在 UBL builder 里用
  `datetime.now(UTC)` 现生成的、硬编码带 `Z`，**不走 `app/schemas/`**；`IssueDate` 用的是
  `business_date`（Date 列）。入站方向也已处理（`myinvois_real.py:63` 把 LHDN 的 Z 时间
  归一成 naive UTC）。有测试盯着（`tests/unit/test_myinvois_ubl.py:153`）。**无合规风险。**
- **没有任何表单把 datetime 写回去。** erp_os 的 SO/PO/DO/GR/调拨/盘点编辑页往返的全是
  `business_date`、`expected_ship_date` 这类 **Date 列**（`models/sales.py:53-54` 等），
  `YYYY-MM-DD` 进出无损。crm_os 前端没用 antd，唯一的日期输入是 `TaskForm.tsx:130`
  的 `due_date`，也是 Date。
- **导出/报表**：erp_os 后端没有 CSV 导出；唯一的 xlsx 是 crm_os 的**导入模板**
  （`routers/contacts.py:40-72`），没有时间列。聚合一律服务端 `func.date()` 出 date。
- **下游三个项目**：`ai_search_os` 直连数据库跑 SQL、不走 HTTP API（`backend/tools/executors.py:130`）；
  `rs-roof-pms` 根本不读这两个 API；本仓库只有 `backend/app/tools/crm.py:48` 把 `created_at`
  原样塞给模型，没有任何解析——多个 `Z` 反而让模型说的时间变对。
- **AutoCount 同步**（`crm_os/services/autocount_service.py:161`）解析的是厂商 API 的
  payload，不是 crm 自己的输出。

### 会跟着变（4 处）

1. **crm_os 根本不能靠改序列化器修。**
   `utils/response.py:7` 所有响应走手写 `json.dumps`，路由里**零个 `response_model`**——
   `app/schemas/` 只用于请求体，从不参与序列化。时间是在约 20 个地方手工 `.isoformat()`
   出去的（`deal_service.py:181`、`task_service.py:160`、`project_service.py:219`、
   `contact_service.py:445`、`activity_service.py:48`、`routers/pipeline.py:80`、
   `routers/users.py:55`、`routers/sales_targets.py:26`、`dashboard_service.py:395`、
   `routing_service.py:276`、`email_service.py:196`、`autocount_service.py:52` …）。
   **两个坑**：`routers/messages.py:188` 和 `services/whatsapp_service.py:385` **已经修过了**
   （注释里点名了这个 bug），别加成两个 Z；另外谁要是图省事把 `.isoformat()` 删掉直接传
   datetime，`_Encoder` 只认 `Decimal`，当场 500。
   erp_os 相反：123 个 `response_model=`，Pydantic 层改一处就能落地。

2. **库存流水的日期筛选会变得「看着对不上」。**
   `routers/inventory.py:72,76` 拿 MYT 的日期直接比 naive UTC 列（`func.date()` 截的是 UTC 的天，
   边界在 MYT 早上 8 点），**现在就已经错了 8 小时**，只是显示也错了同样方向所以两边自洽。
   单改显示 → 一条记录显示成 12 号、却被「截止 11 号」的筛选捞出来。**这两处必须一起改。**
   （同类的服务端 UTC-day 聚合还有 `erp dashboard.py:110,150,217`、`reports.py:60-67`、
   `crm dashboard_service.py:41,48`、`routers/analytics.py:42` —— 这些改前改后都错 8 小时，
   属于另一个问题。）

3. **crm_os 的项目停滞告警会提前 8 小时变红。**
   `frontend/src/pages/Projects/steps.ts:50` 的 `getStaleDays` 现在系统性少算 8 小时，
   改完项目会比现在**早 8 小时**跨过 `watch`/`urgent` 门槛，告警数和排序
   （`pages/Projects/index.tsx:47,66-71`）都会动。方向是对的，但这是**行为变化不是显示变化**，
   上线第二天会有人问「怎么突然多了几个红的」。

4. **e-Invoice 的通知文案会跟界面打架。**
   `events/types.py:49` 的 `validated_at` 走事件总线（`services/einvoice.py:431,511` 填的
   naive `.isoformat()`），不是 Pydantic 字段，`events/handlers/notification.py:158` 直接把它
   拼进给用户看的文案。改完详情页对了、旁边的通知还早 8 小时。同一轮要一起改。
   （72 小时异议倒计时**不受影响**：`services/einvoice.py:80-97` 服务端算好秒数传整数，
   前端只是递减，本来就是对的。）

### 两个必须避开的雷

- **序列化器只能限定 `datetime`，绝不能连 `date` 一起。** 否则 `business_date` 变成
  `"...T00:00:00Z"`，在负时区浏览器上会退成前一天，每次保存都悄悄改单据日期。
- **别把 `_utc_now_naive()` 改成 tz-aware。** `erp dashboard.py:396→438` 有个 Redis 自往返
  （写 `.isoformat()`、读 `fromisoformat`、`:445-446` 相减），改了会在每次读缓存时
  `TypeError: can't subtract offset-naive and offset-aware datetimes`。

---

## 动手前要先连库确认的 4 件事

**我没连，也不该由排查阶段连。** 风险点只有一个：如果某些 erp `created_at` 是在
`infra_mysql` 曾经设成 `+08:00` 的时候写的，那些行**现在是对的**，改完会晚 8 小时。

1. `SELECT @@global.time_zone, @@session.time_zone, NOW(), UTC_TIMESTAMP();`
   —— `infra_mysql` 到底什么时区（它在 `vps_infra` 仓库）
2. `SHOW CREATE TABLE sales_orders;`
   —— 定 migration（DATETIME）和 `docs/ddl.sql:70`（TIMESTAMP）那场架。**如果真是 TIMESTAMP，
   MySQL 会按 session tz 在读的时候转，改法完全不同。**
3. `SELECT id, created_at, confirmed_at FROM sales_orders WHERE confirmed_at IS NOT NULL ORDER BY id;`
   —— `confirmed_at` 是 Python 写的、铁定 UTC。哪一行的 `created_at` 比相近的
   `confirmed_at` **早 8 小时以上**，就是在本地时间 DB 时钟下写的
4. crm_os 有没有走 raw SQL / seed 插进去的行（`alembic/versions/001_create_all_tables.py:42`
   留了个 `server_default=func.now()`，ORM 插入用不到它，但 `seed.py` 那条路会用到）

---

## 建议的改法

**改序列化器，不是改渲染层** —— erp 约 8 处渲染、crm 约 4 处，改渲染容易漏。
但注意上面第 1 条：erp 能一处改完，crm 是约 20 处手工 `+ "Z"`。

顺序：先跑上面的 SQL 1、2、3 → 确认没有混进本地时间的历史行 → 再动代码 →
erp 和 crm 分两个 PR（两套完全不同的改法，别混在一起）→ 第 2、4 条（库存筛选、
通知文案）跟主改动同一轮，否则改完当天就会有人报「显示和筛选对不上」。
