"""
core/config.py
==============
全局配置中心 — 管理模型参数、Agent 角色定义及系统级常量。
所有可调参数均集中于此，方便评审人员快速了解系统规格。
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 模型配置
# ---------------------------------------------------------------------------

MODEL_ID = "claude-sonnet-4-20250514"

# 推理 Agent 允许消耗更多 Token 以完成深度架构分析
REASONING_MAX_TOKENS = 16000

# 文档 & 测试 Agent 的输出 Token 上限
DOC_MAX_TOKENS = 8000
TEST_MAX_TOKENS = 8000

# Coordinator 元推理（汇总各 Agent 结论）
COORDINATOR_MAX_TOKENS = 4000


# ---------------------------------------------------------------------------
# Agent 角色枚举
# ---------------------------------------------------------------------------

AGENT_ROLES = {
    "reasoning": {
        "name": "架构推理 Agent",
        "emoji": "🧠",
        "description": "基于长链 Chain-of-Thought 评估代码变更对系统架构的深度影响",
        "max_tokens": REASONING_MAX_TOKENS,
    },
    "documentation": {
        "name": "文档同步 Agent",
        "emoji": "📝",
        "description": "根据架构分析结论自动更新 README 和 API 文档",
        "max_tokens": DOC_MAX_TOKENS,
    },
    "quality": {
        "name": "质量保障 Agent",
        "emoji": "🧪",
        "description": "基于变更逻辑自动生成单元测试，覆盖边界条件与回归场景",
        "max_tokens": TEST_MAX_TOKENS,
    },
    "coordinator": {
        "name": "协调器 Agent",
        "emoji": "🎯",
        "description": "调度各 Agent、聚合结论并生成最终执行报告",
        "max_tokens": COORDINATOR_MAX_TOKENS,
    },
}


# ---------------------------------------------------------------------------
# 数据类：代码变更事件
# ---------------------------------------------------------------------------

@dataclass
class GitDiffEvent:
    """
    模拟 Git Diff 事件的结构化载体。
    在真实场景中，可通过 GitHub Webhooks / GitLab CI 触发。
    """
    repo_name: str                          # 仓库名称
    commit_hash: str                        # 提交哈希（短）
    author: str                             # 提交作者
    commit_message: str                     # 提交信息
    changed_files: list[str]               # 变更文件列表
    diff_content: str                       # 原始 diff 文本
    base_branch: str = "main"              # 基准分支
    tags: list[str] = field(default_factory=list)  # 自定义标签（如 breaking-change）

    def summary(self) -> str:
        """返回事件的简洁摘要，用于日志输出。"""
        return (
            f"[{self.repo_name}] {self.commit_hash} by {self.author} | "
            f"{len(self.changed_files)} files changed | {self.commit_message[:60]}"
        )


# ---------------------------------------------------------------------------
# 数据类：Agent 执行结果
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """单个 Agent 的执行结果，包含推理链与最终输出。"""
    agent_role: str                         # Agent 角色键
    success: bool                           # 是否执行成功
    reasoning_chain: list[str]             # 中间推理步骤（Chain-of-Thought）
    final_output: str                       # 最终结构化输出
    tokens_used: Optional[int] = None      # 消耗的 Token 数（估算）
    error_message: Optional[str] = None    # 错误信息（失败时填充）

    def display_name(self) -> str:
        role_info = AGENT_ROLES.get(self.agent_role, {})
        emoji = role_info.get("emoji", "🤖")
        name = role_info.get("name", self.agent_role)
        return f"{emoji} {name}"
