//! argus_native — Rust hot-path acceleration for Argus
//!
//! 提供与 Python 实现等价的接口，但 5-10× 性能。Python 侧通过
//! `utils/_native.py` 透明探测和 fallback。

use pyo3::prelude::*;

mod memory;
mod sanitizer;

/// Python 模块入口。
#[pymodule]
fn argus_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // sanitizer
    m.add_function(wrap_pyfunction!(sanitizer::truncate, m)?)?;
    m.add_function(wrap_pyfunction!(sanitizer::strip_ansi, m)?)?;
    m.add_function(wrap_pyfunction!(sanitizer::redact_secrets, m)?)?;
    // memory
    m.add_function(wrap_pyfunction!(memory::parse_entries, m)?)?;
    m.add_function(wrap_pyfunction!(memory::dedup_check, m)?)?;
    m.add_function(wrap_pyfunction!(memory::format_block, m)?)?;
    // 元数据
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
