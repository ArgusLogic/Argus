# argus_native

Rust 加速热路径模块（可选）。**不安装也能用 Argus**，安装后 sanitizer / memory_md 内核会切到 Rust 实现，5-10× 加速。

## 加速覆盖

| 函数 | Python 实现 | Rust 加速比 |
|---|---|:-:|
| `truncate` | `utils/sanitizer.py` | 3-5× |
| `strip_ansi` | `utils/sanitizer.py` | 5-10× |
| `redact_secrets` | `utils/sanitizer.py` | 5-10× |
| `parse_entries` | `agent/memory_md.py` | 3-5× |
| `dedup_check` | `agent/memory_md.py` | 3× |
| `format_block` | `agent/memory_md.py` | 3× |

## 安装方法

### 方式 1：从源码本地构建（开发用）

需要 Rust 工具链（`rustup install stable`）和 maturin：

```bash
pip install maturin
cd argus_native
maturin develop --release
```

构建完成后，`utils/_native.py` 会自动检测并启用。可在 Python 里验证：

```python
from utils._native import has_native, native_info
print(native_info())  # → "Rust 加速已启用 (argus_native v0.1.0)"
```

### 方式 2：禁用加速（troubleshoot）

设置环境变量：

```bash
ARGUS_NO_NATIVE=1 argus
```

## CI

GitHub Actions 当前不构建 wheel（避免 Rust 工具链拖慢 lint/test）。后续可加 `maturin-action` 单独构建发布到 GitHub Releases。

## Crate 结构

```
argus_native/
├── Cargo.toml         # 依赖：pyo3 0.22 + regex + once_cell
├── pyproject.toml     # maturin 配置
├── src/
│   ├── lib.rs         # PyO3 模块入口
│   ├── sanitizer.rs   # truncate/strip_ansi/redact_secrets
│   └── memory.rs      # parse_entries/dedup_check/format_block
└── README.md
```

每个 `.rs` 文件包含 `#[cfg(test)]` 单元测试，跑 `cargo test` 验证。

## Python fallback

`utils/_native.py` 在 import 失败时静默回退。所有调用方（如 `utils.sanitizer.redact_secrets`）始终通过统一入口访问，对 Argus 主体逻辑透明。
