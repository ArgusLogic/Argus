"""Stage 2: auth_login 工具 + credentials_lookup 工具。

让 Argus 能在已授权场景下自动登录靶场（DVWA / AltoroJ / 自家应用）。

设计要点：

  1. 凭据通过 ``utils.credentials`` 占位符机制传递；LLM 上下文里的 password
     永远是 ``${CRED_<host>_PASS}`` 占位符，AgentEngine 在执行前才展开真值。
  2. auth_login 复用现有 BrowserPool（``tools.browser``）：登录成功后 cookies
     自动留在 ``_pool._context``，后续 browser_* / http_request 自动继承。
  3. 表单字段自动探测（user_field / pass_field / submit）按候选选择器列表
     依次试，第一个能 query_selector 到的胜出。LLM 也可显式传 selector。
  4. success_indicator 三种模式：URL 子串 / page selector 命中 / 页面文本含。
     省略则用启发式："URL 不再含 'login' / 'signin'"。
  5. 失败返回明确诊断（哪一步出错），方便 LLM 转人工。
"""

from __future__ import annotations

import contextlib

from agent.tool_registry import registry
from tools.browser import _retry_on_broken_pipe, get_page, get_pool
from utils.credentials import make_placeholder_hint
from utils.sanitizer import sanitize_url

# 表单字段自动探测候选（按优先级从高到低）
_USER_FIELD_CANDIDATES: tuple[str, ...] = (
    "input[name='username']",
    "input[name='user']",
    "input[name='uid']",
    "input[name='userid']",
    "input[name='email']",
    "input[name='login']",
    "input[id='username']",
    "input[id='user']",
    "input[id='uid']",
    "input[id='email']",
    "input[type='email']",
    "input[type='text']",  # 兜底
)

_PASS_FIELD_CANDIDATES: tuple[str, ...] = (
    "input[type='password']",
    "input[name='password']",
    "input[name='passw']",
    "input[name='pwd']",
)

_SUBMIT_CANDIDATES: tuple[str, ...] = (
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('登录')",
    "button:has-text('Login')",
    "button:has-text('Sign in')",
    "button:has-text('Sign In')",
)


@registry.tool(
    name="credentials_lookup",
    description=(
        "【作用】查 ~/.argus/credentials.toml 拿目标的用户名 + 密码占位符（永远不返回明文）。"
        "【关键参数】host：不带 scheme，含端口，如 '127.0.0.1:8080' / 'demo.testfire.net'。"
        "【何时用】登录前第一步——确认是否已配凭据。返回里密码字段是 ${CRED_<host>_PASS} 占位符，"
        "直接当 password 参数传给 auth_login，AgentEngine 执行前自动展开真值，LLM 上下文永远见不到明文。"
        "【避坑】(1) 未配返回 '未找到' → 提醒用户存到 credentials.toml，不要让用户在 chat 贴明文；"
        "(2) 返回里 ${CRED_*_PASS} 是设计中的占位符，不是 bug；"
        "(3) host 大小写敏感且含端口，写 '127.0.0.1' 而非 'http://127.0.0.1:8080/'；"
        "(4) 凭据 BOM 解析问题已防御，但用户改文件时仍要用 utf8NoBOM。"
    ),
    params={
        "host": {
            "type": "string",
            "description": "host 或 host:port，如 '127.0.0.1:8080' 或 'demo.testfire.net'",
        },
    },
)
async def credentials_lookup(host: str) -> str:
    return make_placeholder_hint(host)


@registry.tool(
    name="auth_login",
    description=(
        "【作用】用浏览器自动填表 + 提交完成登录；成功后 cookie 留在浏览器 context，后续 browser_* / "
        "http_request(use_browser_session='true') 自动继承登录态。"
        "【关键参数】login_url（登录页完整 URL）；username / password（推荐用 ${CRED_*_USER/PASS} 占位符，"
        "AgentEngine 自动展开）；user_field / pass_field / submit_selector 默认 'auto' 自动探测，标准表单一般无需手填；"
        "success_indicator='auto' 启发式判 URL 不再含 'login'，特殊站点可传具体子串。"
        "【何时用】(1) DVWA / AltoroJ / JuiceShop 等靶场登录；(2) 凭据流标准入口——先 credentials_lookup 拿占位符，"
        "再 auth_login。任何依赖 session 的 vuln_* / crawl_* / 受保护 http_request 都要先这一步成功。"
        "【避坑】(1) 非标登录（验证码/多步/SSO）会失败，回退到 browser_fill+browser_click 手糊；"
        "(2) success_indicator='auto' 对 login.php?error=... 这种 URL 仍含 'login' 的站点判错误，要传具体 URL/text；"
        "(3) 同一参数失败 ≥2 次必须换思路（换选择器 / 换提交方式），不要重试死循环；"
        "(4) 不要直接传 password 明文，明文虽然会被 scrub 但白白占用 LLM 上下文。"
    ),
    params={
        "login_url": {
            "type": "string",
            "description": "登录页完整 URL，如 'http://127.0.0.1:8080/login.php'",
        },
        "username": {"type": "string", "description": "用户名（明文或 ${CRED_*_USER} 占位符）"},
        "password": {"type": "string", "description": "密码（明文或 ${CRED_*_PASS} 占位符）"},
        "user_field": {
            "type": "string",
            "description": "用户名输入框 CSS 选择器；'auto' 自动探测",
            "required": False,
        },
        "pass_field": {
            "type": "string",
            "description": "密码输入框 CSS 选择器；'auto' 自动探测",
            "required": False,
        },
        "submit_selector": {
            "type": "string",
            "description": "提交按钮 CSS 选择器；'auto' 自动探测",
            "required": False,
        },
        "success_indicator": {
            "type": "string",
            "description": (
                "登录成功判定：URL 子串 / page selector / 页面文本任一模式。"
                "'auto' 时启发式判 URL 不再含 'login'。"
            ),
            "required": False,
        },
    },
)
@_retry_on_broken_pipe
async def auth_login(
    login_url: str,
    username: str,
    password: str,
    user_field: str = "auto",
    pass_field: str = "auto",
    submit_selector: str = "auto",
    success_indicator: str = "auto",
) -> str:
    login_url = sanitize_url(login_url)
    page = await get_page()

    # ① 访问登录页
    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        return f"登录失败：访问 {login_url} 异常 {type(e).__name__}: {e}"

    # ② 解析三个 selector
    user_sel = await _resolve_selector(page, user_field, _USER_FIELD_CANDIDATES, "用户名")
    if user_sel.startswith("登录失败"):
        return user_sel
    pass_sel = await _resolve_selector(page, pass_field, _PASS_FIELD_CANDIDATES, "密码")
    if pass_sel.startswith("登录失败"):
        return pass_sel
    submit_sel = await _resolve_selector(
        page, submit_selector, _SUBMIT_CANDIDATES, "提交按钮", required=False
    )

    # ③ 填表单
    try:
        await page.fill(user_sel, username)
        await page.fill(pass_sel, password)
    except Exception as e:
        return f"登录失败：填写表单异常 {type(e).__name__}: {e}"

    # ④ 提交
    try:
        if submit_sel and not submit_sel.startswith("登录失败"):
            await page.click(submit_sel)
        else:
            await page.press(pass_sel, "Enter")  # 兜底：直接 Enter 提交
    except Exception as e:
        return f"登录失败：提交异常 {type(e).__name__}: {e}"

    # ⑤ 等导航 idle（容错；部分站点 networkidle 永不到，忽略）
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=10000)

    # ⑥ 验证 success_indicator
    current_url = page.url
    indicator = (success_indicator or "auto").strip()
    if indicator and indicator.lower() != "auto":
        ok = await _check_indicator(page, indicator, current_url)
    else:
        # 启发式：URL 不再含 login/signin
        u = current_url.lower()
        ok = "login" not in u and "signin" not in u

    pool = get_pool()
    cookie_count = 0
    if pool._context is not None:
        try:
            cookies = await pool._context.cookies()
            cookie_count = len(cookies)
        except Exception:
            pass

    if ok:
        return (
            f"登录成功：URL = {current_url}（cookies = {cookie_count} 条已写入 BrowserPool）。"
            f"后续 browser_* / http_request(use_browser_session='true') 自动继承登录态。"
        )
    return (
        f"登录失败：当前 URL = {current_url}，未匹配到登录成功指示符。"
        f"可手动指定 success_indicator='dashboard' 等具体子串重试。"
    )


async def _resolve_selector(
    page,
    given: str,
    candidates: tuple[str, ...],
    label: str,
    required: bool = True,
) -> str:
    """LLM 显式传则用其值；否则按候选列表自动探测。失败返回失败串。"""
    given = (given or "").strip()
    if given and given.lower() != "auto":
        return given
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                return sel
        except Exception:
            continue
    if required:
        return f"登录失败：未找到 {label} 输入框（尝试 {len(candidates)} 个候选选择器均失败）"
    return ""


async def _check_indicator(page, indicator: str, current_url: str) -> bool:
    """登录成功判定：URL 子串 → selector → 页面文本 三选一命中即成功。"""
    if indicator in current_url:
        return True
    try:
        el = await page.query_selector(indicator)
        if el:
            return True
    except Exception:
        pass
    try:
        body = await page.content()
        return indicator in body
    except Exception:
        return False
