# 批次 09 上线步骤第 3–5 步：配第二把密钥，打通 CRM 经 chatbot 回复（操作清单）

2026-10-22 写，依据当天只读核对的 VPS 现状与 `acuven_crm_demo` 的代码（`30ef1cb`，`backend/app/config.py`、`services/chatbot_send_service.py`）：

- chatbot：已部署 C3 + C4 + 任务 43（镜像 `sha256:b5b062e4…`）；`/opt/ai_chatbot/backend/.env` 没有 `CRM_SEND_SECRET`，所以 `/internal/crm/send` 与 `/internal/crm/handback` 一律 503。
- CRM：`crm_os-backend-1` 跑 `30ef1cb`（含 CRM-TASK-013–016，2026-10-22 刚部署过）；`/opt/crm_os/.env` 只有 `CHATBOT_EVENTS_SECRET`，**没有 `CHATBOT_SEND_URL`、`CHATBOT_SEND_SECRET`**。两项缺任一，CRM 的回复、重试、交还都是 503 `NOT_CONFIGURED`。
- CRM 侧需要的配置**只有这两项**（代码里 `chatbot_send_service` 只读这两个设置）：
  - `CHATBOT_SEND_URL=http://ai_chatbot_backend:8000`——**只写到端口，不带路径**；CRM 自己拼 `/internal/crm/send`、`/internal/crm/handback`。容器名 `ai_chatbot_backend` 在 `proxy_net`、`data_net` 上都能解析，今天从两个网络打都通（回 503）
  - `CHATBOT_SEND_SECRET`——与 chatbot 的 `CRM_SEND_SECRET` **同值**，且**不能**与事件那把（`CHATBOT_EVENTS_SECRET` / `CRM_EVENTS_SECRET`）同值
  - CRM 侧没有「上一把密钥」这一项；换密钥时用 chatbot 的 `CRM_SEND_SECRET_PREVIOUS`
- 签名方案两边一致：`X-Acuven-Timestamp` + `X-Acuven-Signature: sha256=<hex>`，对 `<时间戳>.<原始 body>` 做 HMAC-SHA256。CRM 等 30 秒超时；chatbot 那边同一个 `request_id` 120 秒内重复会回 409。
- 两个 `.env` 都以换行结尾、没有 `\r`（10-21 核过），下面直接追加一行是安全的。

**全程在 VPS 上以 `ubuntu` 执行。每一步核对不符合预期就停下，把输出贴回来。CRM 部署很频繁——开始前 `docker ps` 看一眼 `crm_os-backend-1` 不是刚起几秒（部署进行中就等它跑完）。**

---

## 第 0 步：备份

```bash
cp -p /opt/crm_os/.env /opt/crm_os/.env.bak-20261022
cp -p /opt/ai_chatbot/backend/.env /opt/ai_chatbot/backend/.env.bak-20261022
ls -l /opt/crm_os/.env.bak-20261022 /opt/ai_chatbot/backend/.env.bak-20261022
```
期望：两个备份都在，CRM 那份 `-rw-------`。

---

## 第 3 步：生成第二把密钥，同值写进两边

### 3a. 确认还没人写过

```bash
grep -E '^(CHATBOT_SEND_URL|CHATBOT_SEND_SECRET)=' /opt/crm_os/.env
grep -E '^CRM_SEND_SECRET(_PREVIOUS)?=' /opt/ai_chatbot/backend/.env
```
期望：**两条都没有输出**。

### 3b. 生成并写入（值不打印）

```bash
SECRET=$(openssl rand -hex 32)
printf 'CHATBOT_SEND_URL=http://ai_chatbot_backend:8000\n' >> /opt/crm_os/.env
printf 'CHATBOT_SEND_SECRET=%s\n' "$SECRET" >> /opt/crm_os/.env
printf 'CRM_SEND_SECRET=%s\n' "$SECRET" >> /opt/ai_chatbot/backend/.env
unset SECRET
```

### 3c. 核对：两边同值、与事件那把不同值

```bash
send_crm=$(sed -n 's/^CHATBOT_SEND_SECRET=//p' /opt/crm_os/.env | sha256sum)
send_bot=$(sed -n 's/^CRM_SEND_SECRET=//p' /opt/ai_chatbot/backend/.env | sha256sum)
events=$(sed -n 's/^CRM_EVENTS_SECRET=//p' /opt/ai_chatbot/backend/.env | sha256sum)
[ "$send_crm" = "$send_bot" ] && echo SAME || echo DIFFERENT
[ "$send_bot" != "$events" ] && echo NOT_THE_EVENTS_KEY || echo SAME_AS_EVENTS_KEY
grep -c '^CHATBOT_SEND_SECRET=' /opt/crm_os/.env
grep -c '^CRM_SEND_SECRET=' /opt/ai_chatbot/backend/.env
sed -n 's/^CRM_SEND_SECRET=//p' /opt/ai_chatbot/backend/.env | tr -d '\n' | wc -c
grep '^CHATBOT_SEND_URL=' /opt/crm_os/.env
```
期望：`SAME`、`NOT_THE_EVENTS_KEY`、`1`、`1`、`64`、`CHATBOT_SEND_URL=http://ai_chatbot_backend:8000`。

### 3d. 先重建 chatbot

```bash
docker image inspect -f '{{.Id}}' ghcr.io/kelvinpang90/ai_chatbot_demo-backend:latest
docker inspect -f '{{.Image}}' ai_chatbot_backend
```
期望：两行**相同**（今天是 `sha256:b5b062e4…`）。不同就停下。

```bash
cd /opt/ai_chatbot
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```
**`-f docker-compose.prod.yml` 不能省。**

核对（等 10 秒）：
```bash
docker ps --filter name=ai_chatbot_backend --format '{{.Image}}  {{.Status}}'
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' ai_chatbot_backend | grep -c '^CRM_SEND_SECRET='
docker logs ai_chatbot_backend 2>&1 | grep 'crm events'
```
期望：`Up` 几秒；`1`；`crm events on, delivering to …`（事件推送不受影响）。

---

## 第 4 步：预检（不发消息）

```bash
for p in send handback; do printf '%s ' $p; docker run --rm --network proxy_net curlimages/curl -s -o /dev/null -w "%{http_code}\n" -X POST http://ai_chatbot_backend:8000/internal/crm/$p; done
```

| 结果 | 含义 | 怎么办 |
|---|---|---|
| 两条都 `401` | chatbot 读到了密钥，不带签名被拒 | 往下走 |
| `503` | chatbot 没读到密钥 | 停下，回 3d |
| 其他 | 意外 | 停下，贴输出 |

公网再打一次，确认 `/internal/` 仍不对外：
```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" -X POST https://chatbot.acuventech.com/internal/crm/send
```
期望：`405 text/html`。

### 4b. 再重建 CRM 后端

```bash
cd /opt/crm_os
CRM_BACKEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' crm_os-backend-1) \
CRM_FRONTEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' crm_os-frontend-1) \
docker compose up -d --no-build --force-recreate backend
```

核对（等 30 秒）：
```bash
docker ps --filter name=crm_os-backend-1 --format '{{.Image}}  {{.Status}}'
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' crm_os-backend-1 | grep -E '^CHATBOT_SEND_URL='
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' crm_os-backend-1 | grep -c '^CHATBOT_SEND_SECRET='
```
期望：镜像标签与重建前相同、`(healthy)`；`CHATBOT_SEND_URL=http://ai_chatbot_backend:8000`；`1`。

---

## 第 5 步：真机验收（你拿手机 + CRM 收件箱 + 导演台）

先记基线：
```bash
docker run --rm --network data_net redis:7-alpine sh -c \
  'redis-cli -h infra_redis -n 16 LLEN chat:crm_events; redis-cli -h infra_redis -n 16 LLEN chat:crm_events:dead; redis-cli -h infra_redis -n 16 --scan --pattern "chat:crm_send:*" | wc -l'
```
期望：`0`、`0`、`0`。

依次做（契约第十节 + 批次 10 + 任务 43）：

1. **开窗口**：手机给 demo 号发一条文字（CRM 只允许回 24 小时内来过消息的访客）
2. **回复**：在 CRM 收件箱回这位访客一句 → 手机收到；CRM 显示已发出、「客服 · 你的名字」、**接管中**，到期时间约 **24 小时后**
3. **导演台**：这位访客显示在接管中；工具流里有一条 `crm.reply`，带客服名字
4. **接管期间 bot 不插话**：手机再发一句 → bot 不回；CRM 收件箱出现这句
5. **续期**：CRM 再回一句 → 到期时间往后延
6. **交还 AI**：CRM 点「交还 AI」→ CRM 立刻显示未接管；手机再发一句 → bot 回复
7. **送达对勾**：手机读掉客服那句 → CRM 里对勾变已读
8. **窗口外被拒**：在 CRM 找一位最后入站消息超过 24 小时的联系人回复 → CRM 发送前就拒绝（提示窗口已关闭），手机什么都收不到
9. **导演台的接管时长**：在导演台接管一位访客 → 到期时间显示 24 小时后；然后交还
10. **任务 43**：用一个还没选 demo 的状态（发 `menu` 可以回到这个状态）照 10-21 截图打一遍——「转人工」→ 导演台交还 → 发「1」→ 收到菜单。导演台「Customer's phone」里要能看到「1」和 `[list] 欢迎！…` 那一行，与 CRM 一致

做完再查：
```bash
docker run --rm --network data_net redis:7-alpine sh -c \
  'redis-cli -h infra_redis -n 16 LLEN chat:crm_events; redis-cli -h infra_redis -n 16 LLEN chat:crm_events:dead; redis-cli -h infra_redis -n 16 --scan --pattern "chat:crm_send:*" | wc -l'
docker logs --since 1h ai_chatbot_backend 2>&1 | grep -E 'internal/crm/(send|handback)' | grep -oE 'HTTP/1.[01]" [0-9]{3}' | sort | uniq -c
docker logs --since 1h ai_chatbot_backend 2>&1 | grep -cE 'ERROR|Traceback'
docker logs --since 1h crm_os-backend-1 2>&1 | grep -cE 'ERROR|Traceback'
```
期望：队列 `0`、死信 `0`；`chat:crm_send:*` 的数目等于第 2、5 步发出的条数（每条保留 48 小时，用来防重发）；`/internal/crm/send` 与 `/handback` 都是 `200`（第 8 步被 CRM 自己拦下，不会到 chatbot）；两边 ERROR 计数为 `0`。

---

## 回滚

只停「CRM 经 chatbot 回复」（事件推送不受影响）：
```bash
sed -i 's/^CRM_SEND_SECRET=.*/CRM_SEND_SECRET=/' /opt/ai_chatbot/backend/.env
cd /opt/ai_chatbot && docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```
之后 chatbot 对这两个接口一律 503，CRM 当作「明确没发出」，输入框里的文字留着；已经发出的不受影响。

完全退回今天之前：用第 0 步的备份覆盖两个 `.env`，再按 3d、4b 各重建一次。

---

## 做完之后

把 3c、4、4b 的核对输出，第 5 步每一项通过与否，以及最后四条命令的输出贴回来，我记进 `tasks/todo.md`（批次 09 第 3–5 步，任务 43 的真机一项）。
