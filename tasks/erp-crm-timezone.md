# ERP / CRM 时间差 8 小时 — 排查记录与修复方案

**2026-09-12。只读排查 + 打真实线上系统实测，两个仓库一行代码没动。**
起因：真机演示，手机上 16:49 下的单，erp_os 后台显示 08:49。
当时以为是「存的到底是 UTC 还是本地时间」的存储问题，**查下来不是**。

> ⚠️ 修的地方在 `E:\projects\erp_os` 和 `E:\projects\crm_os`，**不在本仓库**。
> 复现/验收脚本是本仓库的 `backend/scripts/timezone_probe.py`（只读，只发 GET）。

---

## 一、结论

**显示层的 bug，不是存储的 bug，也跟容器 TZ 无关。**

后端把 naive datetime 序列化成 `"2026-09-12T08:49:20"`，**不带 `Z`、不带 offset**；前端
`new Date(String(val))`（erp `SOColumns.tsx:93`）和 `dayjs(msg.created_at)`（crm
`ConversationView.tsx:62`）按 ES 规范会把**不带 offset 的字符串当本地时间**读。
UTC 的数字被原样印出来，一次转换都没发生。

### 实测（2026-09-12 10:35 UTC，打的是线上 erp.kelvinpeng.com / crm.kelvinpeng.com）

跑 `backend/scripts/timezone_probe.py`，252 张销售单 + 133 张发票 + 28 个 deal + 30 个 contact：

```
--- erp sales order: every timestamp-shaped field found ---
  naive (needs the fix): ['created_at', 'updated_at']
  already zoned:         none
  date-only (hands off): ['business_date', 'expected_ship_date']
--- erp invoice ---
  naive: ['created_at', 'finalized_at', 'submitted_at', 'validated_at']
  date-only: ['business_date', 'due_date']
--- crm deal ---     naive: ['created_at', 'updated_at', 'won_at']
--- crm contact ---  naive: ['created_at', 'updated_at']   date-only: ['last_contact']
```

**线上没有一个时间戳带时区**，而 `business_date` / `due_date` / `last_contact` 是纯日期
（`"2026-09-12"`）—— 证实了「序列化器绝不能碰 `date`」这条约束是真实存在的，不是纸上推演。

### 存的确实是 UTC —— 这次是实测，不是推断

之前唯一不确定的一组是 erp 的 `created_at` / `updated_at`：它们由 MySQL 的
`CURRENT_TIMESTAMP` 生成（`models/base.py:16`，没有 Python `default=`），时区取决于
`infra_mysql`，代码里看不到。用两把**已知来源**的尺子量它：

1. **同一行上的 `confirmed_at`** —— 由 Python `datetime.now(UTC)` 写入
   （`services/sales.py:371`），铁定 UTC，无视任何时钟。
   注意：`confirmed_at` **只在详情接口里有，列表接口会丢掉它**，要按 id 逐个取。
   → 排除种子行后，**2 张真实写入的单，`created_at` 与 `confirmed_at` 相差 1 秒**。
2. **跨系统对照 crm 的 deal** —— crm 用 `datetime.utcnow()`（`models/deal.py:36`），
   同样铁定 UTC。deal 标题里带订单号，可以配对。
   → `SO-2026-00002`：erp `08:49:20` / crm `08:49:57`，**差 37 秒**，就是下单到建卡的真实间隔。

再加两条旁证：

- 你手机上 **16:49** 下的单，`created_at` 是 **08:49:20** —— 正好 8 小时，方向是 UTC。
- **erp / crm 全部数据里没有一行时间落在未来。** 一行若是在 `+08:00` 时钟下写的，
  它会比真实发生时刻早读 8 小时，近期的行就会跑到未来去。一行都没有。

**结论：两套系统的历史数据全是 UTC，没有混进本地时间的行。**

### 风险面比想象中小得多

erp 的 252 张单里 **250 张是 `SO-SEED-*` 种子数据**，`created_at` 全是
`2026-09-11T19:00:05` —— 那是**每晚 3 点（MYT）自动重置**跑出来的，19:00 UTC = 03:00 MYT，
又一条 UTC 的旁证。也就是说 **erp 的「历史」最多只有一天，每晚重新生成一次，根本没有多少
历史可以被改坏**。crm 的历史确实回溯到 2026-03-11，但 crm 全程 Python `utcnow()`，
按构造就是 UTC，任何时钟都影响不了它。

⚠️ 种子行**不能当尺子**：seeder 把 `confirmed_at` 倒填成过去某天的 `00:00:00`（假历史），
拿它比会得出「差 4000 小时」这种噪音。探针已经把 `SO-SEED-*` 和落在整点零分零秒的
stamp 都排除掉了。

### 改容器 TZ 没用

erp_os **早就设了** `TZ: Asia/Kuala_Lumpur`，四个服务全有（`docker-compose.yml:22-23,34,51,67,80`），
照样显示 08:49。`datetime.now(UTC)` 和 `datetime.utcnow()` 根本不看 `TZ`，而 `erp_backend`
的 TZ 也管不到 `infra_mysql` 的 `CURRENT_TIMESTAMP`。

本仓库 `docker-compose.prod.yml:24` 那条 `TZ=Asia/Kuala_Lumpur` 是为了**日志和审计时间戳**
（注释里写着「9pm 的演示归档到 13:00，按发生的钟点找不到」），**不是一回事，不能照搬**。

---

## 二、改了会影响什么

**直接回答「会不会影响系统现有的时间显示」：会，全部 +8 小时；但现在没有一处是对的，
所以没有「对的东西」会被改坏。** 数据库一个字节不动。

### 确认不受影响（查过代码 + 实测）

- **e-Invoice / MyInvois 提交：完全不碰，而且本来就是对的。**
  `integrations/myinvois_ubl.py:287-288` 的 `IssueTime` 在 UBL builder 里用
  `datetime.now(UTC)` 现生成、硬编码带 `Z`，**不走 `app/schemas/`，也不走响应序列化**；
  `IssueDate` 用的是 `business_date`（Date 列）。入站方向也已处理好
  （`myinvois_real.py:63` 把 LHDN 的 Z 时间归一成 naive UTC）。有测试盯着
  （`tests/unit/test_myinvois_ubl.py:153` 断言 `IssueTime` 以 `Z` 结尾）。**无合规风险。**
- **没有任何表单把 datetime 写回去。** erp 的 SO/PO/DO/GR/调拨/盘点编辑页往返的全是
  `business_date`、`expected_ship_date` 这类 **Date 列**（`models/sales.py:53-54` 等），
  `YYYY-MM-DD` 进出无损。crm 前端没用 antd，唯一的日期输入是 `TaskForm.tsx:130`
  的 `due_date`，也是 Date。
- **导出/报表**：erp 后端没有 CSV 导出；唯一的 xlsx 是 crm 的**导入模板**
  （`routers/contacts.py:40-72`），没有时间列。聚合一律服务端 `func.date()` 出 date。
- **下游三个项目**：`ai_search_os` 直连数据库跑 SQL、不走 HTTP API
  （`backend/tools/executors.py:130`）；`rs-roof-pms` 根本不读这两个 API；本仓库只有
  `backend/app/tools/crm.py:48` 把 `created_at` 原样塞给模型，没有任何解析——多个 `Z`
  反而让模型说的时间变对。
- **AutoCount 同步**（`crm_os/services/autocount_service.py:161`）解析的是厂商 API 的
  payload，不是 crm 自己的输出。

### 会跟着变（4 处，方案里都已覆盖）

1. **crm 不能靠 Pydantic 修**。`utils/response.py` 所有响应走手写 `json.dumps`，路由里
   **零个 `response_model`**——`app/schemas/` 只用于请求体。时间在约 20 个地方手工
   `.isoformat()` 出去（`deal_service.py:181`、`task_service.py:160`、`project_service.py:219`、
   `contact_service.py:445`、`activity_service.py:48`、`routers/pipeline.py:80`、
   `routers/users.py:55`、`routers/sales_targets.py:26`、`dashboard_service.py:395`、
   `routing_service.py:276`、`email_service.py:196`、`autocount_service.py:52` …）。
   而且 `routers/messages.py:188` 和 `services/whatsapp_service.py:385` **已经修过了**，
   **绝不能加成两个 Z**。→ 方案用的是「在唯一出口做幂等归一」，天然绕过这两个坑。

2. **库存流水的日期筛选**（`routers/inventory.py:72,76`）拿 MYT 日期直接比 naive UTC 列，
   `func.date()` 截的是 UTC 的天、边界在 MYT 早上 8 点，**现在就已经错了 8 小时**，
   只是显示也错了同样方向所以两边自洽。单改显示 → 一条记录显示成 12 号、却被
   「截止 11 号」的筛选捞出来。**必须同一轮一起改。**

3. **crm 的项目停滞告警会提前 8 小时变红**（`frontend/src/pages/Projects/steps.ts:50`
   的 `getStaleDays`）。方向是对的，但这是**行为变化不是显示变化**，
   上线第二天会有人问「怎么突然多了几个红的」。→ 只需要事先打招呼，不改代码。

4. **e-Invoice 的通知文案**（`events/handlers/notification.py:158` 把
   `events/types.py:49` 的 naive `validated_at` 直接拼进用户可见文案）走的是事件总线，
   **不经响应序列化**，改完详情页对了、通知还早 8 小时。**同一轮一起改。**
   （72 小时异议倒计时**不受影响**：`services/einvoice.py:80-97` 服务端算好秒数传整数。）

---

## 三、修复方案 —— 已实施（2026-09-12）

> **状态：两个仓库都已按下述方案改完、测完、合进各自主分支，但都还没推。**
> - `erp_os` `7c83fa3`（已 ff-merge 进 `main`）—— **没推**，因为本地 `main` 上还压着一条
>   你未推送的 commit `56ca47c`（MyInvois adapter），推 erp 会连它一起部署。
> - `crm_os` `58ef7df`（已 ff-merge 进 `master`）—— **没推**，等 erp 先上、验过再上，
>   顺序见下面「上线顺序」。
>
> 实际落地与原方案的两处偏差：
> 1. 正则从 `^...$` 改成 **`fullmatch`**。变异测试发现「去掉 `^`」这条变异杀不掉——
>    因为用的是 `re.match`，它本来就锚定开头，`^` 是冗余的。`fullmatch` 把
>    「整串就是时间戳」这个意图直接写出来，变异才有意义（改成 `match` / `search` 都红）。
> 2. erp 的 wiring 测试当场抓出一个**真实例外**：OCR 那个 SSE 端点用
>    `EventSourceResponse`，流式响应本来就不能走 JSON 响应类。它唯一的日期字段是
>    `business_date`（纯日期），所以无需处理。例外集合已钉死，将来再多一个会报错要人决定。


### 核心思路：每个仓库**一个出口**，一条正则，幂等

两套系统架构完全不同，但都存在**唯一的 JSON 出口**，在那里做归一，就不可能漏字段、
不可能漏 schema、以后新加的字段自动覆盖：

| | 出口 | 改动量 |
|---|---|---|
| erp_os | `FastAPI(...)` 的 `default_response_class`（`main.py:130`，**现在没设**） | 新增一个 Response 类 + 一行参数 |
| crm_os | `app/utils/response.py` 的 `_render()`（`ok()` 和 `fail()` 都走它） | 改一个函数 |

两边共用同一个归一函数：

```python
# 一个**完整匹配**的 naive ISO datetime。完整匹配是安全阀：
# 标题、备注、地址这类散文字段永远不会整串只是一个时间戳，
# 而一个整串就是时间戳的字符串，本来就是时间戳。
NAIVE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")

def _mark_utc(value):
    """递归地给 naive ISO datetime 打上 Z。

    幂等：已经带 Z 或带 +08:00 的匹配不上，原样放过——crm 里那两处
    已经修好的地方（messages.py:188 / whatsapp_service.py:385）因此不会变成两个 Z。
    纯日期（"2026-09-12"）也匹配不上：没有 T。business_date 不会被动。
    """
    if isinstance(value, str):
        return value + "Z" if NAIVE_ISO.match(value) else value
    if isinstance(value, list):
        return [_mark_utc(v) for v in value]
    if isinstance(value, dict):
        return {k: _mark_utc(v) for k, v in value.items()}
    return value
```

**为什么是字符串层而不是 `field_serializer`**：
- erp 有 **30 个 schema 模块、123 个 `response_model`**，走类型层要么给每个 schema 加基类
  （30 处编辑，漏一个就静默错），要么逐个字段改注解（100+ 处）。出口只有 1 处。
- crm **根本没有 response_model**，类型层无从下手，只有出口层可行。
- 两边同一个机制，一份心智模型，不是两套。
- **幂等由正则保证**，不靠人记得哪里改过。

**为什么不怕误伤散文字段**：正则是 `^...$` 完整匹配。一个字段整串正好是
`2026-09-12T08:49:20` 且不该被当成 UTC —— 这种东西不存在；真存在的话它也是个时间戳。

### 分两个 PR，不要混

**PR 1 — erp_os**
1. 新增 `app/core/json.py`：`UtcJSONResponse(JSONResponse)`，`render()` 里先 `_mark_utc(content)`。
2. `main.py:130` 的 `FastAPI(...)` 加 `default_response_class=UtcJSONResponse`。
   四个异常处理器（`main.py:187,198,209,222`）里直接构造的 `JSONResponse` 也换成它
   —— 它们的 `timestamp` 已经带 `+00:00`（实测确认），换了不变，但省得下次有人加个不带的。
3. **同一轮**修 `routers/inventory.py:52-76` 的日期筛选：把 MYT 的
   `date_from` / `date_to` 转成 UTC 区间再比，别再用 `func.date()` 截 UTC 的天。
4. **同一轮**修 `events/handlers/notification.py:158`：`validated_at` 拼进文案前先转 MYT。

**PR 2 — crm_os**
1. `app/utils/response.py`：`_render()` 里 `content = _mark_utc(content)`；
   顺手给 `_Encoder.default` 加上 `datetime` 分支（`isoformat() + "Z"`），
   这样以后有人直接传 datetime 不会 500。
2. 不动那 20 个 `.isoformat()` 调用点，也不动已经修好的那两处 —— 幂等正则自己处理。

### 验收：探针就是验收脚本

`backend/scripts/timezone_probe.py` 改前改后各跑一次，看
`naive (needs the fix)` 那一行**清空**、`already zoned` 收下全部字段、
`date-only (hands off)` **一个不少**：

```
docker run --rm -e PYTHONPATH=/repo/backend \
  -v "E:\projects\ai_chatbot_demo\.claude\worktrees\<wt>:/repo" \
  -v "E:\projects\ai_chatbot_demo\backend\.env:/repo/backend/.env:ro" \
  -w /repo/backend python:3.13-slim \
  sh -c "pip install -q -r requirements.txt && python scripts/timezone_probe.py"
```

改前基线（本文件第一节那三段输出）已经留档，直接对比即可。

另外在两个仓库各加**单元测试**，按本仓库的惯例配变异测试：
- naive → 加 Z
- 已带 `Z` / 已带 `+08:00` → **不变**（幂等，这条挡的是双 Z）
- `"2026-09-12"` 纯日期 → **不变**（这条挡的是 `business_date` 被毁）
- 嵌套 dict / list 里的时间戳 → 也要被打上
- 散文里含时间戳的字符串（如 deal 标题）→ **不变**

### 回滚

改动是纯显示层，`git revert` + 重新部署即可，数据库无需任何操作。
erp 侧回滚面只有一行 `default_response_class`；crm 侧只有一个 `_render()`。

### 上线顺序

1. 跑探针留基线（已做，见上）
2. PR 1（erp）合并部署 → 跑探针 → 看 erp 三段是否全部变 `already zoned`
3. 肉眼看一眼后台：随便开一张单，`created_at` 应该显示成 MYT（比现在晚 8 小时读数）
4. PR 2（crm）合并部署 → 同样两步
5. 提前跟用到 crm 项目看板的人说一句：**停滞告警会提前 8 小时变红**

---

## 四、两个必须避开的雷

- **序列化器只能碰 `datetime`，绝不能碰 `date`。** 本方案靠正则里那个 `T` 挡住了
  （`"2026-09-12"` 匹配不上）。如果有人改成给所有日期字段加时区，
  `business_date` 会变成 `"...T00:00:00Z"`，在负时区浏览器上退成前一天，
  **每次保存都会悄悄改单据日期**。
- **别把 `_utc_now_naive()` 改成 tz-aware。** `erp dashboard.py:396→438` 有个 Redis
  自往返（写 `.isoformat()`、读 `fromisoformat`、`:445-446` 相减），改了会在每次读缓存时
  `TypeError: can't subtract offset-naive and offset-aware datetimes`。
  本方案只动出口、不动任何写入路径，所以不会踩到——**但别顺手去"统一"它**。

---

## 五、仍然没确认的（不影响动手，但值得知道）

1. `infra_mysql` 的 `@@global.time_zone` 到底设的什么。**不需要它了**——
   上面两把尺子已经证明写入时钟是 UTC，比读配置更直接。但如果哪天有人动了
   `vps_infra` 的 MySQL 时区，这个 bug 会以另一种形式回来。
2. `sales_orders.created_at` 到底是 `DATETIME`（migration
   `8058342b33b7:611` 这么说）还是 `TIMESTAMP`（`docs/ddl.sql:70` 这么说）。
   两者在本方案下**行为一致**（都读出 naive UTC，我们只在出口打标），
   所以不挡路；但这份文档和代码打架的事本身该清掉。
3. crm 有没有走 raw SQL / `seed.py` 插进去、吃了
   `server_default=func.now()`（`alembic/versions/001_create_all_tables.py:42`）的行。
   实测「没有一行在未来」已经给了很强的旁证，但没有逐行比对过。
