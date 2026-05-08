# Argus 架构指南

本文档解释 Argus Agent 的三层记忆 + 自演化数据流，回答 issue #10 提出的"职责边界模糊"。

## 三层记忆

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 · ContextManager      (agent/context.py)                 │
│  - 范围：单次进程内的 system + user + assistant + tool 消息列表  │
│  - 生命周期：进程退出即丢                                        │
│  - 关键能力：token 计数、压缩（LLM 智能摘要 + 简单截断回退）     │
│  - 谁写：engine.run / run_stream                                 │
│  - 谁读：engine 在每轮 LLM 调用前压缩消息                        │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 · SessionIndex        (agent/session_index.py)           │
│  - 范围：跨会话 SQLite + FTS5 倒排索引                           │
│  - 生命周期：~/.argus/sessions/sessions.db，永久（用户手动清）   │
│  - 关键能力：关键词检索、最近条目查询                            │
│  - 谁写：session_search 工具（只在用户主动 search 时插入）       │
│  - 谁读：session_search 工具                                     │
│  - 旧名 `MemoryStore`，issue #10 改名；agent/memory.py 留 shim   │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 · MemoryMD            (agent/memory_md.py)               │
│  - 范围：~/.argus/memories/{MEMORY,USER,LESSONS}.md              │
│  - 生命周期：永久（人类可读，git diff 友好）                     │
│  - 关键能力：分类 append、容量条、§ 分隔解析                     │
│  - 谁写：                                                        │
│      MEMORY  : memory_manage 工具（LLM 主动调用）                │
│      USER    : agent.user_profile 周期性更新（LLM）              │
│      LESSONS : agent.lessons 启发式抽取（每轮结束，零 LLM）     │
│  - 谁读：engine._build_dynamic_prompt 在首轮注入 system          │
└──────────────────────────────────────────────────────────────────┘
```

**易混淆点**

- `agent/memory.py` 现在是**仅含 deprecation shim**，所有逻辑搬到 `agent/session_index.py`。
- "Layer 3 MemoryMD" 才是 LLM 视角下的"主记忆"。
- "Layer 2 SessionIndex" 只是给 `session_search` 工具做关键字检索，**不会**自动注入 system prompt。

## 自演化数据流（v10 milestone）

```
        用户输入
           │
           ▼
   ┌─────────────────┐
   │  engine.run     │── 每轮结束触发 5 个钩子（fire-and-forget）
   └─────────────────┘
           │
           ├─ A1 _track_skill_usage_after_run
           │     扫本轮工具调用，匹配 skills/ 中的 step 序列 → success_count++
           │     零 LLM；纯启发式
           │
           ├─ A3 _track_lessons_after_run
           │     正则匹配本轮 tool 错误 → 写 LESSONS.md
           │     零 LLM
           │
           ├─ C2 _track_failure_replays_after_run
           │     失败请求→ jsonl 结构化日志（默认关）
           │     零 LLM
           │
           └─ A2 _maybe_extract_skill_after_run
                 LLM 判断本轮是否值得抽出新技能 → 写 skills/
                 ⚠️ 烧 token；默认关，开关 [skills] auto_extract = true
                 60s 外层超时（skill_extractor）
```

**周期性任务**（独立进程，由 `make daemon` 或 cron 触发）

- `agent/curator.py daemon` —— 合并相似技能、归档陈旧技能（保护 pinned）
- `agent/user_profile.py` —— 用最近 N 个 session 摘要刷新 USER.md

## 文件位置一览

```
~/.argus/
├── config.toml              # 用户配置（issue #9 已统一通过 utils.config 读）
├── sessions/
│   ├── sessions.db          # SessionIndex 后端（FTS5）
│   └── *.json               # 单次会话快照（list_sessions / load_session）
├── memories/
│   ├── MEMORY.md            # Layer 3 主记忆
│   ├── USER.md              # Layer 3 用户画像
│   └── LESSONS.md           # Layer 3 避坑笔记
├── skills/
│   ├── *.md                 # agentskills.io 兼容格式（YAML frontmatter）
│   └── archive/             # curator 归档目录
├── projects/
│   └── *.json               # project_save / project_load（结构化目标状态）
├── output/
│   ├── reports/             # generate_report 输出
│   ├── screenshots/         # browser_screenshot 输出
│   └── logs/                # file_logger
└── curator_reports/
    └── *.md                 # 周期性 curator 运行报告
```

## 给贡献者的"放哪里"决策树

> 我要存一段信息，应该放哪一层？

```
是不是仅本次任务用？  ── 是 ──▶  Layer 1（ContextManager 自动管，无需新增 API）
        │
       否
        │
        ▼
是不是希望 LLM 在新对话开头就看到？
        │
       是 ──▶  Layer 3 MemoryMD：
                ├─ Agent 工作笔记/项目惯例 → MEMORY.md（memory_manage 工具）
                ├─ 用户偏好           → USER.md（user_profile 自动）
                └─ 失败避坑           → LESSONS.md（lessons 自动）
        │
       否（仅供按需检索）
        │
        ▼
              Layer 2 SessionIndex（session_search 工具）
              注：用户主动调用才命中，不会进 system prompt
```

工具能力（操作级别）放 `tools/`；可复用的固化流程放 `skills/`（YAML frontmatter）。
