#!/usr/bin/env python3

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List


class ConfigAuditor:
    def __init__(self, workspace: str = None):
        if workspace is None:
            workspace = os.environ.get("OPENCLAW_WORKSPACE", "~/.openclaw/workspace")
        self.workspace = Path(workspace).expanduser()
        self.expected_python = os.environ.get("CONFIG_ARCH_EXPECTED_PYTHON", "python3.13")
        self.files = {
            "USER": self.workspace / "USER.md",
            "SOUL": self.workspace / "SOUL.md",
            "TOOLS": self.workspace / "TOOLS.md",
            "AGENTS": self.workspace / "AGENTS.md",
            "MEMORY": self.workspace / "MEMORY.md",
            "HEARTBEAT": self.workspace / "HEARTBEAT.md",
            "IDENTITY": self.workspace / "IDENTITY.md",
        }
        self.skip_dirs = {
            "node_modules",
            ".git",
            ".ruff_cache",
            "__pycache__",
            "logs",
        }
        self.path_patterns = [
            re.compile(r'(?<!https:)(?<!http:)(?<!ws:)(?<!wss:)(/[^ \n"`]+)'),
            re.compile(r'(~(?:/[^ \n"`]+)+)'),
        ]

    def read_text(self, key: str) -> str:
        path = self.files[key]
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")

    def iter_workspace_files(self) -> Iterable[Path]:
        for root, dirs, files in os.walk(self.workspace):
            dirs[:] = [d for d in dirs if d not in self.skip_dirs]
            for filename in files:
                path = Path(root) / filename
                if path.suffix.lower() in {".md", ".py", ".json", ".txt"}:
                    yield path

    def find_mentions(self, terms: List[str], file_keys: List[str]) -> List[str]:
        found = []
        for key in file_keys:
            content = self.read_text(key)
            if content and all(term in content for term in terms):
                found.append(key)
        return found

    def check_missing_files(self) -> List[Dict]:
        missing = []
        for name in ["USER", "SOUL", "TOOLS", "AGENTS", "MEMORY"]:
            if not self.files[name].exists():
                missing.append(
                    {
                        "type": "file_missing",
                        "file": f"{name}.md",
                        "priority": "high" if name in {"USER", "SOUL"} else "medium",
                    }
                )
        return missing

    def check_hierarchy_violations(self) -> List[Dict]:
        violations = []

        soul = self.read_text("SOUL")
        for pattern in ["9222", "agent-browser", "start-chrome-debug.sh", "web_search_pro"]:
            if pattern in soul:
                violations.append(
                    {
                        "file": "SOUL.md",
                        "issue": f'包含技术细节 "{pattern}"（应移至 TOOLS.md 或 USER.md）',
                        "severity": "warning",
                    }
                )

        user = self.read_text("USER")
        for pattern in ["ReAct", "执行审计声明", "惩罚机制", "失败报告格式"]:
            if pattern in user:
                violations.append(
                    {
                        "file": "USER.md",
                        "issue": f'包含冗长执行模板 "{pattern}"（建议精简为短规则）',
                        "severity": "warning",
                    }
                )
        if "Vibe" in user or "Character" in user or "性格" in user:
            violations.append(
                {
                    "file": "USER.md",
                    "issue": "包含人格描述（应移至 SOUL.md）",
                    "severity": "warning",
                }
            )

        memory = self.read_text("MEMORY")
        for pattern in ["## 项目配置", "## 工作流 SOP", "触发规则"]:
            if pattern in memory:
                violations.append(
                    {
                        "file": "MEMORY.md",
                        "issue": f'包含活配置或 SOP "{pattern}"（应迁出到 TOOLS.md / 独立工作流文档）',
                        "severity": "warning",
                    }
                )

        tools = self.read_text("TOOLS")
        for pattern in ["强制默认", "任何搜索任务必须首先使用", "禁止使用 SearXNG"]:
            if pattern in tools:
                violations.append(
                    {
                        "file": "TOOLS.md",
                        "issue": f'包含策略性规则 "{pattern}"（应保留环境事实，把硬约束放到 USER.md）',
                        "severity": "warning",
                    }
                )

        return violations

    def check_internal_conflicts(self) -> List[Dict]:
        conflicts = []

        heartbeat = self.read_text("HEARTBEAT")
        if "Keep this file empty" in heartbeat and "每日会话记录整理任务" in heartbeat:
            conflicts.append(
                {
                    "file": "HEARTBEAT.md",
                    "issue": "文件头声明禁用 heartbeat，但正文定义了 heartbeat 任务",
                    "severity": "high",
                }
            )

        return conflicts

    def check_duplicates(self) -> List[Dict]:
        duplicates = []

        rules = [
            (
                "skill-first 约束",
                ["优先阅读对应 `SKILL.md`", "等效 skill"],
                ["USER", "AGENTS"],
                "保留在 USER.md，AGENTS.md 只描述启动顺序与引用关系",
            ),
            (
                "浏览器远程调试规则",
                ["start-chrome-debug.sh", "Google Chrome for Testing"],
                ["USER", "AGENTS", "MEMORY", "SOUL"],
                "权威规则保留在 USER.md，其他文件仅保留引用或经验",
            ),
            (
                "搜索默认入口规则",
                ["web_search_pro", "默认搜索入口"],
                ["USER", "AGENTS", "SOUL"],
                "权威规则保留在 USER.md，SOUL/AGENTS 不重复定义",
            ),
        ]

        for rule, terms, file_keys, recommendation in rules:
            found_in = self.find_mentions(terms, file_keys)
            if len(found_in) > 1:
                duplicates.append(
                    {
                        "rule": rule,
                        "found_in": found_in,
                        "recommendation": recommendation,
                    }
                )

        return duplicates

    def check_dead_references(self) -> List[Dict]:
        missing = []
        seen = set()
        for path in self.iter_workspace_files():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for pattern in self.path_patterns:
                for raw_match in pattern.findall(content):
                    candidate = raw_match.rstrip("),.;'\"")
                    if candidate.startswith("//"):
                        continue
                    if candidate.startswith("/System/") or candidate.startswith("/usr/"):
                        continue
                    candidate_path = Path(candidate).expanduser()
                    if str(candidate_path) in seen:
                        continue
                    seen.add(str(candidate_path))
                    if not candidate_path.exists():
                        missing.append(
                            {
                                "type": "path_missing",
                                "rule": str(candidate_path),
                                "file": path.name,
                            }
                        )
        return missing

    def check_unused_state_references(self) -> List[Dict]:
        issues = []
        target = "heartbeat-state.json"
        mentions = []

        for path in self.iter_workspace_files():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if target in content:
                mentions.append(path)

        if len(mentions) == 1:
            issues.append(
                {
                    "file": mentions[0].name,
                    "issue": f'引用了 "{target}"，但工作区没有其他文件消费它',
                    "severity": "warning",
                }
            )

        return issues

    def check_completeness(self) -> List[Dict]:
        missing = []
        user = self.read_text("USER")
        agents = self.read_text("AGENTS")
        heartbeat = self.read_text("HEARTBEAT")

        required_rules = [
            (
                f"Python 版本声明（{self.expected_python}）",
                self.expected_python in user,
                "USER.md",
            ),
            (
                "浏览器条件流",
                all(
                    token in user
                    for token in [
                        "agent-browser connect http://127.0.0.1:9222",
                        "connect 失败",
                        "start-chrome-debug.sh",
                        "验证当前 URL",
                    ]
                ),
                "USER.md",
            ),
            (
                "搜索默认入口 web_search_pro",
                "默认搜索入口是" in user and "web_search_pro" in user,
                "USER.md",
            ),
            (
                "时间标准化规则",
                "今日/今天" in user and "after:YYYY-MM-DD" in user,
                "USER.md",
            ),
            (
                "TOOLS 启动加载",
                "Read `TOOLS.md`" in agents,
                "AGENTS.md",
            ),
            (
                "Silent Replies 规则",
                "NO_REPLY" in agents,
                "AGENTS.md",
            ),
            (
                "Heartbeat 响应规则",
                "HEARTBEAT_OK" in agents,
                "AGENTS.md",
            ),
            (
                "Heartbeat 幂等说明",
                "prompt 文件" in heartbeat and "输出文件" in heartbeat,
                "HEARTBEAT.md",
            ),
        ]

        for rule_name, check, owner in required_rules:
            if not check:
                missing.append(
                    {
                        "type": "rule_missing",
                        "rule": rule_name,
                        "file": owner,
                    }
                )

        return missing

    def generate_report(self) -> str:
        report = ["# OpenClaw 配置审计报告", ""]

        missing_files = self.check_missing_files()
        hierarchy = self.check_hierarchy_violations()
        conflicts = self.check_internal_conflicts()
        duplicates = self.check_duplicates()
        dead_refs = self.check_dead_references()
        stale_state = self.check_unused_state_references()
        completeness = self.check_completeness()

        if conflicts:
            report.append("## 🔴 自相矛盾")
            for item in conflicts:
                report.append(f"- [{item['severity']}] {item['file']}: {item['issue']}")
            report.append("")

        if hierarchy:
            report.append("## 🟡 层级错位")
            for item in hierarchy:
                report.append(f"- [{item['severity']}] {item['file']}: {item['issue']}")
            report.append("")

        if duplicates:
            report.append("## 🟠 重复定义")
            for item in duplicates:
                report.append(f"- **{item['rule']}** 出现在: {', '.join(item['found_in'])}")
                report.append(f"  建议: {item['recommendation']}")
            report.append("")

        all_missing = missing_files + dead_refs + completeness
        if all_missing:
            report.append("## 🔴 缺失项")
            for item in all_missing:
                if item["type"] == "file_missing":
                    report.append(f"- 缺失文件: {item['file']} (优先级: {item['priority']})")
                elif item["type"] == "path_missing":
                    report.append(f"- 路径不存在: {item['rule']} (引用位置: {item['file']})")
                else:
                    report.append(f"- 缺失规则: {item['rule']} (应在 {item['file']})")
            report.append("")

        if stale_state:
            report.append("## 🟡 伪状态引用")
            for item in stale_state:
                report.append(f"- [{item['severity']}] {item['file']}: {item['issue']}")
            report.append("")

        if not (conflicts or hierarchy or duplicates or all_missing or stale_state):
            report.append("✅ 所有检查通过，配置健康！")

        return "\n".join(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw 配置审计")
    parser.add_argument(
        "--workspace",
        default=os.environ.get("OPENCLAW_WORKSPACE", "~/.openclaw/workspace"),
        help="待审计工作区路径（默认读取 OPENCLAW_WORKSPACE，否则使用 ~/.openclaw/workspace）",
    )
    args = parser.parse_args()

    auditor = ConfigAuditor(workspace=args.workspace)
    print(auditor.generate_report())
