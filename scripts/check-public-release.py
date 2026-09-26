#!/usr/bin/env python3
"""Validate the Git index before a public release; never prints file contents."""

from __future__ import annotations

import re
import subprocess
import sys

ROOT_FILES = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "compose.yaml",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
}
PLUGIN_DIRS = {
    "astrbot_plugin_pa_common",
    "astrbot_plugin_personal_assistant_planner",
    "astrbot_plugin_personal_assistant_push",
    "astrbot_plugin_personal_assistant_timetable",
    "astrbot_plugin_personal_assistant_todo",
}
SECRET_PATTERNS = (
    ("home directory path", re.compile(rb"/home/[A-Za-z0-9_.-]+/")),
    ("WeChat account identifier", re.compile(rb"[A-Za-z0-9_-]{20,}@im\.wechat", re.I)),
    ("API key-like value", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "credential assignment",
        re.compile(
            rb"(?:API[_-]?KEY|ACCESS[_-]?TOKEN|SERVICE_API_TOKEN|SESSION_SECRET|WEB_PASSWORD)"
            rb"[\"']?\s*[:=]\s*[\"']([A-Za-z0-9/+=_-]{32,})[\"']",
            re.I,
        ),
    ),
    ("coordinate pair", re.compile(rb"\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b")),
)


def allowed(path: str) -> bool:
    parts = path.split("/")
    if path in ROOT_FILES:
        return True
    if len(parts) < 2:
        return False
    root, name = parts[0], parts[-1]
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if root == "docs":
        return suffix == "md"
    if root == "personal_assistant":
        return suffix == "py"
    if root == "tests":
        return suffix == "py"
    if root == "web":
        return suffix in {"js", "html", "css"}
    if root == "scripts":
        return suffix == "sh" or name == "check-public-release.py"
    if root in PLUGIN_DIRS:
        return suffix in {"py", "yaml", "yml", "json", "txt", "md"}
    return False


def main() -> int:
    try:
        output = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("发布检查失败：当前目录尚未初始化 Git。", file=sys.stderr)
        return 2

    revision = None
    paths = [item.decode("utf-8", errors="strict") for item in output.split(b"\0") if item]
    if not paths:
        try:
            output = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
        except subprocess.CalledProcessError:
            print("发布检查失败：暂存区为空，且当前没有可检查的提交。", file=sys.stderr)
            return 2
        paths = [item.decode("utf-8", errors="strict") for item in output.split(b"\0") if item]
        revision = "HEAD"
        if not paths:
            print("发布检查失败：没有可检查的暂存文件或提交文件。", file=sys.stderr)
            return 2

    failures: list[str] = []
    for path in paths:
        if not allowed(path):
            failures.append(f"不在发布白名单：{path}")
            continue
        try:
            object_name = f"{revision}:{path}" if revision else f":{path}"
            content = subprocess.run(
                ["git", "show", object_name],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
        except subprocess.CalledProcessError:
            failures.append(f"无法读取暂存文件：{path}")
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                failures.append(f"疑似包含 {label}：{path}")

    if failures:
        print("发布检查未通过：")
        for failure in failures:
            print(f"- {failure}")
        return 1
    source = "已提交版本" if revision else "暂存文件"
    print(f"发布检查通过：已检查 {len(paths)} 个{source}，位于白名单内且未发现已知隐私模式。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
