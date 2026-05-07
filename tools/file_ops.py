"""文件操作工具：保存结果、读取文件。支持绝对路径和相对路径。"""

import os

from agent.tool_registry import registry


def _resolve_path(filepath: str) -> str:
    """解析文件路径。支持绝对路径（如 C:/Users/.../file.md）和相对路径（默认存到 output/reports/）。"""
    # 展开 ~ 为用户主目录
    filepath = os.path.expanduser(filepath)

    # 判断是否为绝对路径（如 C:\..., D:\..., /home/...）
    if os.path.isabs(filepath):
        return filepath

    # 相对路径：存到 ~/.argus/output/reports/ 下
    from utils.paths import REPORTS_DIR
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return os.path.join(REPORTS_DIR, os.path.basename(filepath))


@registry.tool(
    name="save_file",
    description="将文本内容保存到指定文件路径。支持绝对路径（如 C:/Users/用户/Desktop/report.md）或仅文件名（默认保存到 output/reports/）。可通过 ~/Desktop/file.md 保存到用户桌面。",
    params={
        "filename": {"type": "string", "description": "文件路径。支持：1) 绝对路径如 'C:/Users/23725/Desktop/report.md'；2) 相对路径如 '~/Desktop/report.md'；3) 仅文件名如 'report.md'（默认存到 output/reports/）"},
        "content": {"type": "string", "description": "要保存的文本内容"},
    },
)
async def save_file(filename: str, content: str) -> str:
    filepath = _resolve_path(filename)

    # 确保目录存在
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        abs_path = os.path.abspath(filepath)
        return f"文件已保存: {abs_path} ({len(content)} 字符)"
    except Exception as e:
        return f"保存失败: {e}"


@registry.tool(
    name="read_file",
    description="读取指定文件的内容。支持绝对路径或 output/ 目录下的文件名。",
    params={
        "filename": {"type": "string", "description": "文件路径（绝对路径或文件名）"},
    },
)
async def read_file(filename: str) -> str:
    filepath = os.path.expanduser(filename)

    # 如果是绝对路径，直接读取
    if os.path.isabs(filepath) and os.path.isfile(filepath):
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            return f"文件内容 ({filepath}):\n{content}"
        except Exception as e:
            return f"读取失败: {e}"

    # 否则在 ~/.argus/output 目录下搜索
    from utils.paths import OUTPUT_DIR
    output_dir = OUTPUT_DIR
    safe_name = os.path.basename(filename)
    for root, _dirs, files in os.walk(output_dir):
        if safe_name in files:
            found_path = os.path.join(root, safe_name)
            try:
                with open(found_path, encoding="utf-8") as f:
                    content = f.read()
                return f"文件内容 ({found_path}):\n{content}"
            except Exception as e:
                return f"读取失败: {e}"

    return f"文件未找到: {filename}"
