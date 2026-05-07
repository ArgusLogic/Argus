# Argus Agent —— 开发/部署常用任务（issue #11）
#
# Windows 用户：建议在 Git Bash / WSL / msys 下运行 make。
# 仅 PowerShell 的用户可直接运行下方等价命令（见 README "本地开发"）。

PYTHON ?= python
PIP    ?= $(PYTHON) -m pip

.PHONY: help install install-dev playwright config setup test lint format \
        type clean dev-setup

help:
	@echo "Argus Agent 常用命令："
	@echo "  make install       - 仅装运行依赖（pyproject 主依赖）"
	@echo "  make install-dev   - 装运行 + 开发依赖（pytest / ruff / mypy）"
	@echo "  make playwright    - 安装 Playwright Chromium（首次必须）"
	@echo "  make config        - 复制 config.example.toml -> ~/.argus/config.toml"
	@echo "  make setup         - install-dev + playwright + config 一键完成"
	@echo "  make test          - 跑全部 pytest"
	@echo "  make lint          - ruff check"
	@echo "  make format        - ruff format"
	@echo "  make type          - mypy 类型检查"
	@echo "  make clean         - 清理 __pycache__ / .pyc / pytest 缓存"

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

playwright:
	$(PYTHON) -m playwright install chromium

config:
	@$(PYTHON) -c "import os, shutil; \
home = os.path.expanduser('~/.argus'); os.makedirs(home, exist_ok=True); \
dst = os.path.join(home, 'config.toml'); \
shutil.copy('config.example.toml', dst) if not os.path.exists(dst) else print('已存在，跳过：', dst)"
	@echo "配置已就绪：~/.argus/config.toml （记得填 api_keys）"

setup: install-dev playwright config
	@echo ""
	@echo "✅ 安装完成。下一步：编辑 ~/.argus/config.toml 填入至少一个 api key，然后运行 'python main.py'。"

test:
	$(PYTHON) -m pytest tests/ -q

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

type:
	$(PYTHON) -m mypy agent tools utils main.py

clean:
	@$(PYTHON) -c "import pathlib, shutil; \
[shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; \
[p.unlink() for p in pathlib.Path('.').rglob('*.pyc')]; \
shutil.rmtree('.pytest_cache', ignore_errors=True); \
shutil.rmtree('.mypy_cache', ignore_errors=True); \
shutil.rmtree('.ruff_cache', ignore_errors=True); \
print('已清理 __pycache__ / .pyc / pytest/mypy/ruff cache')"
