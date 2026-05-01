"""
core/coordinator.py
===================
多 Agent 协调器 — 整个系统的调度中枢。

Coordinator 负责：
1. 接收 GitDiffEvent，编排各 Agent 的执行顺序
2. 管理 Agent 间的上下文传递（推理结果 → 文档/测试 Agent）
3. 执行元推理，生成最终汇总报告
4. 收集并展示所有 Agent 的 Token 消耗指标

执行拓扑（有向无环图）：
    GitDiffEvent
         │
         ▼
  ReasoningAgent          ← 首先执行，消耗最多 Token
    (CoT Analysis)
         │
    ┌────┴─────┐
    ▼          ▼
DocAgent   QualityAgent  ← 并行执行（依赖推理结果）
    │          │
    └────┬─────┘
         ▼
   Coordinator            ← 元推理，生成最终报告
  (Meta-Reasoning)
"""

import asyncio
import logging
import time
from datetime import datetime

from core.config import (
    AgentResult,
    GitDiffEvent,
    AGENT_ROLES,
    MODEL_ID,
    COORDINATOR_MAX_TOKENS,
)
from agents.reasoning_agent import ReasoningAgent
from agents.documentation_agent import DocumentationAgent
from agents.quality_agent import QualityAgent
from prompts.templates import COORDINATOR_SYSTEM_PROMPT, COORDINATOR_SUMMARY_TEMPLATE
from utils.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class ArchitectCoordinator:
    """
    多 Agent 架构分析协调器。

    使用示例：
        coordinator = ArchitectCoordinator()
        report = await coordinator.process(event)
        print(report)
    """

    def __init__(self):
        # 所有 Agent 共享同一个 Claude 客户端实例（共享 Token 统计）
        self.client = ClaudeClient(model_id=MODEL_ID)

        # 初始化三个专职 Agent
        self.reasoning_agent = ReasoningAgent(self.client)
        self.doc_agent = DocumentationAgent(self.client)
        self.quality_agent = QualityAgent(self.client)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def process(self, event: GitDiffEvent) -> str:
        """
        处理一个 Git Diff 事件，驱动完整的多 Agent 分析流水线。

        Args:
            event: 代码变更事件

        Returns:
            最终汇总报告（Markdown 格式字符串）
        """
        pipeline_start = time.monotonic()

        self._print_pipeline_header(event)

        # ── Phase 1: 推理 Agent（串行，是后续 Agent 的依赖） ──────────
        print(f"\n{'─' * 60}")
        print(f"  Phase 1/3 | {AGENT_ROLES['reasoning']['emoji']} 架构推理分析")
        print(f"{'─' * 60}")

        reasoning_result = await self.reasoning_agent.analyze(event)
        self._print_agent_result(reasoning_result)

        # ── Phase 2: 文档 & 质量 Agent（并行执行） ────────────────────
        print(f"\n{'─' * 60}")
        print(f"  Phase 2/3 | 📝 文档生成 & 🧪 测试生成（并行）")
        print(f"{'─' * 60}")

        doc_result, test_result = await asyncio.gather(
            self.doc_agent.generate_docs(event, reasoning_result),
            self.quality_agent.generate_tests(event, reasoning_result),
        )
        self._print_agent_result(doc_result)
        self._print_agent_result(test_result)

        # ── Phase 3: Coordinator 元推理（汇总） ───────────────────────
        print(f"\n{'─' * 60}")
        print(f"  Phase 3/3 | 🎯 元推理 & 最终报告生成")
        print(f"{'─' * 60}")

        final_report = await self._meta_reasoning(
            event, reasoning_result, doc_result, test_result
        )

        # ── 输出 Token 使用报告 ────────────────────────────────────────
        total_elapsed = time.monotonic() - pipeline_start
        self.client.print_usage_report()
        print(f"⏱️  总耗时: {total_elapsed:.2f}s\n")

        return final_report

    # ------------------------------------------------------------------
    # 元推理
    # ------------------------------------------------------------------

    async def _meta_reasoning(
        self,
        event: GitDiffEvent,
        reasoning_result: AgentResult,
        doc_result: AgentResult,
        test_result: AgentResult,
    ) -> str:
        """
        协调器自身的推理步骤：汇总三个 Agent 的结论，生成最终报告。
        这是整个流水线的最后一次 Claude API 调用。
        """
        # 提取各 Agent 的关键结论摘要
        reasoning_conclusion = (
            reasoning_result.final_output[-800:]  # 取结论部分
            if reasoning_result.success
            else f"❌ 推理 Agent 失败: {reasoning_result.error_message}"
        )
        doc_summary = (
            f"成功生成 {len(doc_result.reasoning_chain)} 个文档部分"
            if doc_result.success
            else f"❌ 文档 Agent 失败: {doc_result.error_message}"
        )
        test_summary = (
            f"成功生成 {len(test_result.reasoning_chain)} 个测试阶段报告"
            if test_result.success
            else f"❌ 质量 Agent 失败: {test_result.error_message}"
        )

        user_message = COORDINATOR_SUMMARY_TEMPLATE.format(
            event_summary=event.summary(),
            reasoning_conclusion=reasoning_conclusion,
            doc_summary=doc_summary,
            test_summary=test_summary,
        )

        try:
            meta_output, tokens = await self.client.invoke(
                system_prompt=COORDINATOR_SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=COORDINATOR_MAX_TOKENS,
                temperature=0.4,
                agent_role="coordinator",
            )
            logger.info(f"🎯 协调器元推理完成 | tokens={tokens}")
            return self._format_final_report(event, reasoning_result, doc_result, test_result, meta_output)

        except Exception as exc:
            logger.error(f"🎯 协调器异常: {exc}")
            return f"# ⚠️ 协调器元推理失败\n\n错误: {exc}"

    # ------------------------------------------------------------------
    # 报告格式化
    # ------------------------------------------------------------------

    def _format_final_report(
        self,
        event: GitDiffEvent,
        reasoning_result: AgentResult,
        doc_result: AgentResult,
        test_result: AgentResult,
        meta_output: str,
    ) -> str:
        """将所有 Agent 的输出整合为最终的 Markdown 报告。"""
        usage = self.client.get_usage_summary()
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %Human:%M:%S UTC")

        sections = [
            f"# 🏗️ Claude Architect Agent — 分析报告",
            f"",
            f"> **事件**: `{event.summary()}`  ",
            f"> **生成时间**: {timestamp}  ",
            f"> **总 Token 消耗**: {usage['total_tokens']:,}",
            f"",
            f"---",
            f"",
            f"## 🎯 协调器总结",
            f"",
            meta_output,
            f"",
            f"---",
            f"",
            f"## 🧠 推理 Agent — 架构影响分析",
            f"",
            reasoning_result.final_output if reasoning_result.success
            else f"> ⚠️ 执行失败: {reasoning_result.error_message}",
            f"",
            f"---",
            f"",
            f"## 📝 文档 Agent — 生成内容",
            f"",
            doc_result.final_output if doc_result.success
            else f"> ⚠️ 执行失败: {doc_result.error_message}",
            f"",
            f"---",
            f"",
            f"## 🧪 质量 Agent — 测试套件",
            f"",
            test_result.final_output if test_result.success
            else f"> ⚠️ 执行失败: {test_result.error_message}",
            f"",
            f"---",
            f"",
            f"## 📊 Pipeline 执行统计",
            f"",
            f"| Agent | 状态 | Token 消耗 |",
            f"|-------|------|-----------|",
        ]

        for role, stats in usage["by_agent"].items():
            emoji = AGENT_ROLES.get(role, {}).get("emoji", "🤖")
            name = AGENT_ROLES.get(role, {}).get("name", role)
            sections.append(f"| {emoji} {name} | ✅ | {stats['tokens']:,} |")

        sections += [
            f"| **合计** | — | **{usage['total_tokens']:,}** |",
            f"",
        ]

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # 辅助输出方法
    # ------------------------------------------------------------------

    def _print_pipeline_header(self, event: GitDiffEvent) -> None:
        print("\n" + "═" * 60)
        print("  🏗️  Claude Architect Agent — 多 Agent 分析流水线")
        print("═" * 60)
        print(f"  📦 仓库:  {event.repo_name}")
        print(f"  📝 提交:  {event.commit_hash} — {event.commit_message[:50]}")
        print(f"  👤 作者:  {event.author}")
        print(f"  📁 文件:  {', '.join(event.changed_files[:3])}{'...' if len(event.changed_files) > 3 else ''}")
        print("═" * 60)

    def _print_agent_result(self, result: AgentResult) -> None:
        status = "✅" if result.success else "❌"
        tokens = f"{result.tokens_used:,}" if result.tokens_used else "N/A"
        print(f"  {status} {result.display_name()} | tokens={tokens}")
        if result.reasoning_chain:
            for i, step in enumerate(result.reasoning_chain[:2], 1):
                preview = step.replace("\n", " ")[:80]
                print(f"     └─ [{i}] {preview}...")
