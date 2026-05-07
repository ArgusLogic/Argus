// 合成 fixture：模拟超星类 SPA 的端点分布特征
// 覆盖 crawl_js_endpoints 全部 7 个正则模式

const config = {
    apiBase: "https://api.chaoxing.com",
    version: "v2",
};

// 1) 完整 URL（_FULL_URL_RE）
const ssoUrl = "https://passport.chaoxing.com/login";
const cdnUrl = "https://cdn.example.com/static/main.js";

// 2) 高确信前缀路径（_API_PATH_RE）
const ENDPOINTS = {
    init: "/mooc2-ans/ai-evaluate/v2/answer/init",
    loadData: "/mooc2-ans/ai-evaluate/v2/answer/load-data",
    submit: "/mooc2-ans/ai-evaluate/v2/answer/submit",
    review: "/api/v2/review/modify-eva",
    auth: "/auth/login",
};

// 3) 宽路径（_BROAD_PATH_RE）— 不含已知前缀但是合法
const otherPath = "/student/course/detail";
const reportPath = "/business/report/export";

// 4) 模板字符串 URL（_TEMPLATE_URL_RE）
function buildUrl(id) {
    return `/think/topic/${id}/detail`;
}
const sseEndpoint = `/ai-ans/ai-evaluate/think/main-talk`;

// 5) AJAX 调用（_AJAX_CALL_RE）
fetch("/topic-map-data");
axios.get("/answer-topic-stat");
new EventSource("/think/tip-question");
$.ajax("/think/end-report");

// 6) AJAX 选项里的 url（_AJAX_OPTS_URL_RE）
$.ajax({
    url: "/think/change-question",
    method: "POST",
});
axios.request({
    url: "/exam/result/save",
    data: { id: 1 },
});

// 7) 敏感信息（_SENSITIVE_RE）
const SECRETS = {
    apiKey: "abc123def456ghi789",
    secret: "supersecretvalue123",
    token: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
};

// 不应被误抓（尾部为 css/png 等资源）
const styles = "/static/main.css";
const logo = "/img/logo.png";
const font = "/fonts/icon.woff2";

// 不应被误抓（短路径 + 单 /）
const root = "/";
const dot = "/.";
