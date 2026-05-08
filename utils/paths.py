"""集中管理 Argus 所有数据路径，统一存放到 ~/.argus/ 目录。

目录结构：
~/.argus/
├── config.toml          # 用户配置文件
├── history              # 命令行输入历史
├── sessions/
│   └── sessions.db      # 会话 + 记忆数据库
├── output/
│   ├── reports/         # 侦察报告
│   ├── screenshots/     # 浏览器截图
│   └── logs/            # 运行日志
├── workspace/           # 默认工作区（启动时 cwd 切到此）
└── skills/              # 提炼的技能 (如果有)
"""

import os

# ─── 基础目录 ────────────────────────────────────────────────────────────────
SECAGENT_HOME = os.path.join(os.path.expanduser("~"), ".argus")

# ─── 配置文件 ────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(SECAGENT_HOME, "config.toml")

# ─── 命令历史 ────────────────────────────────────────────────────────────────
HISTORY_PATH = os.path.join(SECAGENT_HOME, "history")

# ─── 会话 & 记忆数据库 ──────────────────────────────────────────────────────
SESSIONS_DIR = os.path.join(SECAGENT_HOME, "sessions")
DB_PATH = os.path.join(SESSIONS_DIR, "sessions.db")

# ─── 输出目录 ────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(SECAGENT_HOME, "output")
REPORTS_DIR = os.path.join(OUTPUT_DIR, "reports")
SCREENSHOTS_DIR = os.path.join(OUTPUT_DIR, "screenshots")
LOGS_DIR = os.path.join(OUTPUT_DIR, "logs")

# ─── 默认工作区 ──────────────────────────────────────────────────────────────
# Argus 启动时把 cwd 切到这里，所有"无路径前缀"的产物（save_file / generate_report
# 副产物 / 临时 PoC / LLM 写文件）都默认落在这。CLI --workspace <path> 可临时覆盖。
WORKSPACE_DIR = os.path.join(SECAGENT_HOME, "workspace")

# ─── 技能目录 ────────────────────────────────────────────────────────────────
SKILLS_DIR = os.path.join(SECAGENT_HOME, "skills")
SKILLS_ARCHIVE_DIR = os.path.join(SECAGENT_HOME, "skills_archive")
CURATOR_REPORTS_DIR = os.path.join(SECAGENT_HOME, "curator_reports")

# ─── 记忆目录（MD 文件存储，Hermes 风格） ───────────────────────────────────
MEMORIES_DIR = os.path.join(SECAGENT_HOME, "memories")
MEMORY_MD_PATH = os.path.join(MEMORIES_DIR, "MEMORY.md")
USER_MD_PATH = os.path.join(MEMORIES_DIR, "USER.md")
LESSONS_MD_PATH = os.path.join(MEMORIES_DIR, "LESSONS.md")


def ensure_dirs() -> None:
    """确保所有必需目录存在。启动时调用一次即可。"""
    for d in [SECAGENT_HOME, SESSIONS_DIR, REPORTS_DIR, SCREENSHOTS_DIR, LOGS_DIR, SKILLS_DIR, MEMORIES_DIR, WORKSPACE_DIR]:
        os.makedirs(d, exist_ok=True)
