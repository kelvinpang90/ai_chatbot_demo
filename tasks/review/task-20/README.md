# 任务 20 的两轮冷审

两轮，13 条 finding（含 1 条审查方自己撤回），全部修完。逐条的内容在
`round-1/findings.json` 和 `round-2/findings.json`，`report.txt` 是
`validate_findings.py` 的输出。

## ⚠️ 这两轮不是自动跑出来的

`run_review.sh` 的 Stop hook **在后台任务里不会触发**——那个钩子要一个交互式
session「停下」才跑，而后台任务没有这个时刻。所以这两轮是开发方手工起的。

| | 原流程 | 这两轮 |
|---|---|---|
| 执行者 | `claude -p`（见 `run_review.sh:134`） | Claude 子智能体 **一样** |
| 提示词 | `reviewer_prompt.md` | 同一份的口径 **一样** |
| 触发 | Stop hook 自动 | 开发方手工 |
| **隔离** | 独立 worktree `review-<sha>`，**改不到被审代码** | **同一个 worktree，只有一句「不要改」的指令** |
| 记账 | `state.env` + 轮次上限 | 开发方自己记 |
| 产物 | `findings.json` | 自然语言报告，**事后按格式补录成这两份** |

**隔离那一行是最实质的弱化**，看结论时请把它算进去。审查方两轮都主动报告了
`git status --porcelain` 是干净的，但那是它的自述，不是机制保证。

## repro 是真跑过的

每个 `repro/` 目录里的测试都**在被审的那个 commit 上跑红过**，输出抄进了
`observed_failure`：

- `round-1/repro` 对 `b59bdf3`：**16 failed, 4 passed**（4 条正例通过，说明关键词表
  不是全坏，是不准）
- `round-2/repro` 对 `30bfc63`：**18 failed**

重跑的方法（把 `<sha>` 换成 `b59bdf3` 或 `30bfc63`）：

```bash
git worktree add --detach .claude/worktrees/review-<sha> <sha>
docker run --rm \
  -v "$PWD/.claude/worktrees/review-<sha>:/repo" \
  -v "$PWD/tasks/review/task-20/round-N/repro:/repro" \
  -w /repo/backend --env-file backend/.env -e REDIS_URL="redis://127.0.0.1:1/0" \
  ai_chatbot_test:latest python -m pytest -q /repro -p no:cacheprovider
```

`ai_chatbot_test:latest` 是照 `requirements-dev.txt` 建的镜像；`REDIS_URL` 指向一个
不存在的端口，逼 `user_store` 走内存回退。

## 两条值得单独记住的

1. **第 1 轮的修复引入了一条 P1 回归**（round-2 的 N1）：给 `notify._send` 加的接管
   守卫把任务 19.1 的收尾总结一起吞了，而端点仍然报成功。**修复是新代码，新代码要
   重新审**——这正是双 agent 审查两轮而不是一轮的理由。
2. **审查方的自评点出了它自己的盲区**：它擅长「什么输入产生什么错误输出」，不擅长
   「缺了什么不变量」。那个没有上限的接管标志，开发方在两轮记录里都主动写了，它两轮
   都只报症状（P1-1、P2-1）没报根因——直到对质阶段才把它提成 A1。
