//! 与 agent/memory_md.py 等价的 Rust 实现（条目解析、去重、容量条渲染）。

use pyo3::prelude::*;

const SEP: &str = "§";

/// 从 MD 文本切分出条目列表（剥离首部 # 标题，按 § 分隔，去空白）。
#[pyfunction]
pub fn parse_entries(raw: &str) -> Vec<String> {
    if raw.trim().is_empty() {
        return Vec::new();
    }
    // 跳过文件头 # 行（仅第一段连续注释）
    let mut body_start = 0;
    let mut seen_first_non_comment = false;
    for (i, line) in raw.lines().enumerate() {
        if !seen_first_non_comment && line.starts_with('#') {
            // 持续跳过头部 #
            continue;
        }
        seen_first_non_comment = true;
        body_start = i;
        break;
    }
    let body: String = raw
        .lines()
        .skip(body_start)
        .collect::<Vec<_>>()
        .join("\n");
    let trimmed = body.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }
    trimmed
        .split(SEP)
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// 检查新内容是否与现有条目重复。
/// 规则：精确匹配 OR 子串匹配（处理 strip 后）。
#[pyfunction]
pub fn dedup_check(entries: Vec<String>, new_content: &str) -> bool {
    let cleaned = new_content.trim();
    if cleaned.is_empty() {
        return false; // 空内容不算重复（调用方会另外拒绝）
    }
    for e in &entries {
        let trimmed = e.trim();
        if trimmed == cleaned || trimmed.contains(cleaned) {
            return true;
        }
    }
    false
}

/// 把条目列表渲染为带容量条的 system prompt 块。
///
/// 输出格式：
/// ```text
/// ══════════════════════════════════════════════
/// {header} [{pct}% — {used}/{cap} chars]
/// ══════════════════════════════════════════════
/// {entry 1}
///
/// {entry 2}
/// ...
/// ```
#[pyfunction]
pub fn format_block(entries: Vec<String>, header: &str, cap: usize) -> String {
    let used: usize = entries.iter().map(|e| e.len()).sum();
    let pct: usize = if cap > 0 {
        ((used as f64) / (cap as f64) * 100.0).round() as usize
    } else {
        0
    };

    let bar = "═".repeat(46);
    let title = format!("{} [{}% — {}/{} chars]", header, pct, used, cap);

    let mut out = String::with_capacity(used + 200);
    out.push_str(&bar);
    out.push('\n');
    out.push_str(&title);
    out.push('\n');
    out.push_str(&bar);
    out.push('\n');

    if entries.is_empty() {
        out.push_str("(空)\n");
    } else {
        for (i, e) in entries.iter().enumerate() {
            out.push_str(e);
            if i + 1 < entries.len() {
                out.push_str("\n\n");
            } else {
                out.push('\n');
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_empty() {
        assert!(parse_entries("").is_empty());
        assert!(parse_entries("   ").is_empty());
    }

    #[test]
    fn parse_with_header() {
        let raw = "# Argus Memory\n\nfirst\n§\nsecond\n";
        let entries = parse_entries(raw);
        assert_eq!(entries, vec!["first", "second"]);
    }

    #[test]
    fn parse_skips_blank_entries() {
        let raw = "# H\n\nA\n§\n  \n§\nB\n";
        assert_eq!(parse_entries(raw), vec!["A", "B"]);
    }

    #[test]
    fn dedup_exact() {
        let entries = vec!["foo".into(), "bar".into()];
        assert!(dedup_check(entries.clone(), "foo"));
        assert!(!dedup_check(entries, "baz"));
    }

    #[test]
    fn dedup_substring() {
        let entries = vec!["this is a long entry with foo inside".into()];
        assert!(dedup_check(entries, "foo inside"));
    }

    #[test]
    fn format_block_empty() {
        let result = format_block(vec![], "MEMORY", 1000);
        assert!(result.contains("0%"));
        assert!(result.contains("(空)"));
    }

    #[test]
    fn format_block_with_entries() {
        let entries = vec!["alpha".into(), "bravo".into()];
        let result = format_block(entries, "MEMORY", 1000);
        assert!(result.contains("alpha"));
        assert!(result.contains("bravo"));
    }
}
