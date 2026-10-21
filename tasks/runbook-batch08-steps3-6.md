# 批次 08 上线步骤第 3–6 步：打开第 1 阶段事件推送（操作清单）

2026-10-21 写，依据当天只读核对的 VPS 现状：
- chatbot：`/opt/ai_chatbot/backend/.env` 没有任何 `CRM_EVENTS_*`，日志是 `crm events off`；队列 `chat:crm_events` 与死信都是 0。
- CRM：`crm_os-backend-1` 跑 `853b5ad`（含 CRM-TASK-006–016），`/opt/crm_os/.env`（compose `env_file: .env`）没有任何 `CHATBOT_*`。
- 两个 `.env` 都以换行结尾、没有 `\r`，所以下面直接追加一行是安全的。
- 两边都在 `proxy_net` 与 `data_net` 上；chatbot 默认的 `CRM_EVENTS_URL` 是 `http://crm_os-backend-1:8000/internal/chatbot/events`，与 CRM 的路由一致，不用另配。

**全程在 VPS 上以 `ubuntu` 执行。每一步核对不符合预期就停下，把输出贴回来，不要往下走。**

---

## 第 0 步：备份两个 `.env`

```bash
cp -p /opt/crm_os/.env /opt/crm_os/.env.bak-20261021
cp -p /opt/ai_chatbot/backend/.env /opt/ai_chatbot/backend/.env.bak-20261021
```

核对：
```bash
ls -l /opt/crm_os/.env* /opt/ai_chatbot/backend/.env*
```
期望：各多出一个 `.bak-20261021`，权限与原文件相同（CRM 那份是 `-rw-------`）。

---

## 第 3 步：生成一把密钥，同值写进两边；先重启 CRM

### 3a. 生成并写入（值不打印到屏幕）

```bash
grep -E '^(CHATBOT_EVENTS_SECRET|CRM_EVENTS_SECRET)=' /opt/crm_os/.env /opt/ai_chatbot/backend/.env
```
期望：**没有任何输出**。有输出说明已经有人写过，停下。

```bash
SECRET=$(openssl rand -hex 32)
printf 'CHATBOT_EVENTS_SECRET=%s\n' "$SECRET" >> /opt/crm_os/.env
printf 'CRM_EVENTS_SECRET=%s\n' "$SECRET" >> /opt/ai_chatbot/backend/.env
unset SECRET
```

### 3b. 核对两边同值（只比哈希，不显示值）

```bash
a=$(sed -n 's/^CHATBOT_EVENTS_SECRET=//p' /opt/crm_os/.env | sha256sum)
b=$(sed -n 's/^CRM_EVENTS_SECRET=//p' /opt/ai_chatbot/backend/.env | sha256sum)
[ "$a" = "$b" ] && echo SAME || echo DIFFERENT
grep -c '^CHATBOT_EVENTS_SECRET=' /opt/crm_os/.env
grep -c '^CRM_EVENTS_SECRET=' /opt/ai_chatbot/backend/.env
sed -n 's/^CRM_EVENTS_SECRET=//p' /opt/ai_chatbot/backend/.env | tr -d '\n' | wc -c
```
期望：`SAME`、`1`、`1`、`64`。

### 3c. 重建 CRM 后端，让它读到密钥

CRM 的 compose 要求 `CRM_BACKEND_IMAGE` / `CRM_FRONTEND_IMAGE` 两个变量（没设会直接报错），这里取**正在跑的镜像**，保证版本不变：

```bash
cd /opt/crm_os
CRM_BACKEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' crm_os-backend-1) \
CRM_FRONTEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' crm_os-frontend-1) \
docker compose up -d --no-build --force-recreate backend
```
（重建期间 CRM 后台约 20 秒不可用。）

核对（等 30 秒左右再跑）：
```bash
docker ps --filter name=crm_os-backend-1 --format '{{.Image}}  {{.Status}}'
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' crm_os-backend-1 | grep -c '^CHATBOT_EVENTS_SECRET='
```
期望：镜像标签仍是 `…:853b5adb7e15910ea13785e99115e429cf385c7b`、状态 `(healthy)`；第二行 `1`。

chatbot 这一步**不用重启**：开关还关着，它现在不读这把密钥；第 5 步重建时一起读进去。

---

## 第 4 步：连通性预检（不发事件）

```bash
docker run --rm --network proxy_net curlimages/curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://crm_os-backend-1:8000/internal/chatbot/events
```

| 结果 | 含义 | 怎么办 |
|---|---|---|
| `401` | 网络通、CRM 已读到密钥（签名不对被拒） | 往下走 |
| `503` | CRM 没读到密钥 | 停下，回到 3c 核对 |
| `000` / 连接错误 | 容器名或网络不对 | 停下，`docker ps` 核对容器名 |
| 其他 | 意外 | 停下，贴输出 |

---

## 第 5 步：打开 chatbot 的事件开关

### 5a. 先确认重建会用回同一个镜像

```bash
docker image inspect -f '{{.Id}}' ghcr.io/kelvinpang90/ai_chatbot_demo-backend:latest
docker inspect -f '{{.Image}}' ai_chatbot_backend
```
期望：两行**相同**（今天看到的是 `sha256:57b5f11b…`）。不同说明本机 `:latest` 被换过，重建会换版本——停下。

### 5b. 加开关并重建

```bash
grep -q '^CRM_EVENTS_ENABLED=' /opt/ai_chatbot/backend/.env && echo ALREADY_THERE || printf 'CRM_EVENTS_ENABLED=true\n' >> /opt/ai_chatbot/backend/.env
grep '^CRM_EVENTS_ENABLED=' /opt/ai_chatbot/backend/.env
```
期望：没有 `ALREADY_THERE`，第二行是 `CRM_EVENTS_ENABLED=true`。

```bash
cd /opt/ai_chatbot
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```
**`-f docker-compose.prod.yml` 不能省**（2026-09-13 事故）；`restart` 读不到新的 `.env`，必须 `--force-recreate`。

### 5c. 核对

```bash
docker ps --filter name=ai_chatbot_backend --format '{{.Image}}  {{.Status}}'
docker logs ai_chatbot_backend 2>&1 | grep 'crm events'
```
期望：`Up` 几秒到几十秒；日志有一行
`crm events on, delivering to http://crm_os-backend-1:8000/internal/chatbot/events`。

如果看到的是 `crm events: CRM_EVENTS_ENABLED is on but …, so they stay off`，说明缺了密钥或 Redis——停下，贴这一行。

---

## 第 6 步：真机验收（你拿手机做）

先记一个基线：
```bash
docker run --rm --network data_net redis:7-alpine sh -c \
  'redis-cli -h infra_redis -n 16 LLEN chat:crm_events; redis-cli -h infra_redis -n 16 LLEN chat:crm_events:dead'
```
期望：`0`、`0`。

然后依次做，每做一项看一眼 CRM 收件箱：
1. 手机给 demo 号发一条文字 → CRM 收件箱出现这个联系人和这条消息
2. bot 回复 → CRM 里显示为「AI · 行业」
3. 说「转人工」→ CRM 显示「接管中」和到期时间
4. 在导演台（控制台）回复这位访客 → CRM 显示为控制台回复，到期时间往后延
5. 在导演台点「交还」→ CRM 显示接管结束
6. 手机上把 bot 的消息读掉 → CRM 里送达对勾随之变成已读

做完再查：
```bash
docker run --rm --network data_net redis:7-alpine sh -c \
  'redis-cli -h infra_redis -n 16 LLEN chat:crm_events; redis-cli -h infra_redis -n 16 LLEN chat:crm_events:dead'
docker logs --since 30m ai_chatbot_backend 2>&1 | grep 'crm events'
docker logs --since 30m crm_os-backend-1 2>&1 | grep -i 'chatbot event'
```
期望：队列回到 `0`、死信 `0`；chatbot 日志除了 `crm events on` 没有 ERROR；CRM 日志没有 `chatbot event rejected`。

说明：打开开关之前的对话**不会补进 CRM**，只有之后的消息会出现。

---

## 回滚（任何一步出问题需要退回时）

只关推送（最常用）：
```bash
sed -i 's/^CRM_EVENTS_ENABLED=true$/CRM_EVENTS_ENABLED=false/' /opt/ai_chatbot/backend/.env
cd /opt/ai_chatbot && docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```
已入队没送出的事件留在 Redis 里不丢，重新打开后接着送；真要丢弃才 `DEL chat:crm_events`。

完全退回今天之前：用第 0 步的备份覆盖两个 `.env`，再按 3c、5b 的命令各重建一次。

---

## 做完之后

把第 4 步的状态码、5c 的那行日志、第 6 步最后三条命令的输出贴回来。我记进 `tasks/todo.md` 批次 08，然后就可以按批次 10 的上线步骤推 C3 + C4。
