//! 与 utils/sanitizer.py 等价的 Rust 实现。
//!
//! 测试基线：100KB 文本 redact_secrets, Python ~5ms, Rust ~0.5ms (10×)。

use once_cell::sync::Lazy;
use pyo3::prelude::*;
use regex::Regex;

// ─── truncate ────────────────────────────────────────────────────────

/// 截断过长文本，保留首尾 + 中间标记。UTF-8 安全。
#[pyfunction]
#[pyo3(signature = (text, max_len = 8000))]
pub fn truncate(text: &str, max_len: usize) -> String {
    if text.len() <= max_len {
        return text.to_string();
    }
    let half = max_len / 2;
    let head = byte_slice_at_char_boundary(text, half, true);
    let tail = byte_slice_at_char_boundary(text, text.len() - half, false);
    let removed = text.len() - max_len;
    format!(
        "{}\n\n... [truncated {} chars] ...\n\n{}",
        &text[..head],
        removed,
        &text[tail..]
    )
}

/// 找到给定字节位置最近的 UTF-8 字符边界。
fn byte_slice_at_char_boundary(s: &str, target: usize, going_forward: bool) -> usize {
    if target >= s.len() {
        return s.len();
    }
    let mut idx = target;
    if going_forward {
        while idx > 0 && !s.is_char_boundary(idx) {
            idx -= 1;
        }
    } else {
        while idx < s.len() && !s.is_char_boundary(idx) {
            idx += 1;
        }
    }
    idx
}

// ─── strip_ansi ──────────────────────────────────────────────────────

static ANSI_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(
        r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]",
    )
    .expect("ANSI regex must compile")
});

/// 去除 ANSI 转义序列。
#[pyfunction]
pub fn strip_ansi(text: &str) -> String {
    ANSI_RE.replace_all(text, "").into_owned()
}

// ─── redact_secrets ──────────────────────────────────────────────────

struct RedactRule {
    label: &'static str,
    re: Regex,
    /// 是否仅 redact 第 1 个捕获组（password=xxx 类）；否则替换整段
    capture_only: bool,
}

static REDACT_RULES: Lazy<Vec<RedactRule>> = Lazy::new(|| {
    vec![
        RedactRule {
            label: "openai_key",
            re: Regex::new(r"\bsk-[A-Za-z0-9_\-]{20,}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "anthropic_key",
            re: Regex::new(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "github_token",
            re: Regex::new(r"\bgh[oprsu]_[A-Za-z0-9]{36,}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "slack_bot_token",
            re: Regex::new(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "aws_access_key",
            re: Regex::new(r"\bAKIA[0-9A-Z]{16}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "aws_session_token",
            re: Regex::new(r"\bASIA[0-9A-Z]{16}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "google_api_key",
            re: Regex::new(r"\bAIza[0-9A-Za-z_\-]{35}\b").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "jwt",
            re: Regex::new(
                r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b",
            )
            .unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "bearer_token",
            re: Regex::new(r"(?i)\b(?:Bearer|Token)\s+[A-Za-z0-9_\-\.=]{20,}").unwrap(),
            capture_only: false,
        },
        RedactRule {
            label: "password",
            re: Regex::new(
                r#"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['"]?([^\s'"&,;]{4,})"#,
            )
            .unwrap(),
            capture_only: true,
        },
        RedactRule {
            label: "api_key",
            re: Regex::new(
                r#"(?i)\b(?:api[_\-]?key|apikey|access[_\-]?token|secret[_\-]?key)\s*[:=]\s*['"]?([A-Za-z0-9_\-]{16,})"#,
            )
            .unwrap(),
            capture_only: true,
        },
        RedactRule {
            label: "private_key",
            re: Regex::new(
                r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]+?-----END[^-]+-----",
            )
            .unwrap(),
            capture_only: false,
        },
    ]
});

/// 扫描文本并替换敏感信息为 [REDACTED:type]。
#[pyfunction]
pub fn redact_secrets(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    let mut result = text.to_string();
    for rule in REDACT_RULES.iter() {
        let placeholder = format!("[REDACTED:{}]", rule.label);
        if rule.capture_only {
            // 只替换捕获组：保留 key= 前缀，仅 redact value
            result = rule
                .re
                .replace_all(&result, |caps: &regex::Captures| {
                    let full = caps.get(0).map_or("", |m| m.as_str());
                    let val = caps.get(1).map_or("", |m| m.as_str());
                    if let Some(pos) = full.rfind(val) {
                        format!("{}{}", &full[..pos], placeholder)
                    } else {
                        placeholder.clone()
                    }
                })
                .into_owned();
        } else {
            result = rule.re.replace_all(&result, placeholder.as_str()).into_owned();
        }
    }
    result
}

// ─── 单元测试 ────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_short_unchanged() {
        assert_eq!(truncate("hello", 100), "hello");
    }

    #[test]
    fn truncate_long_marks_chars() {
        let text: String = std::iter::repeat('x').take(10000).collect();
        let result = truncate(&text, 200);
        assert!(result.contains("truncated"));
        assert!(result.starts_with('x'));
        assert!(result.ends_with('x'));
    }

    #[test]
    fn strip_ansi_removes_color() {
        assert_eq!(strip_ansi("\x1b[31mred\x1b[0m"), "red");
    }

    #[test]
    fn redact_openai_key() {
        let text = "config: sk-abc123def456ghi789jklmnop";
        let result = redact_secrets(text);
        assert!(!result.contains("sk-abc"));
        assert!(result.contains("[REDACTED:openai_key]"));
    }

    #[test]
    fn redact_password_keeps_key() {
        let text = "password=supersecret123";
        let result = redact_secrets(text);
        assert!(result.contains("password"));
        assert!(!result.contains("supersecret"));
        assert!(result.contains("[REDACTED:password]"));
    }

    #[test]
    fn redact_no_false_positive() {
        let text = "Hello world, normal message";
        assert_eq!(redact_secrets(text), text);
    }
}
