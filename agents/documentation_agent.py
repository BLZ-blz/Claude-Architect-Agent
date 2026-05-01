"""
agents/documentation_agent.py
==============================
文档同步 Agent — 基于架构分析结论自动更新项目文档。

接收推理 Agent 的输出作为上下文，生成：
- README.md 的更新片段
- OpenAPI 风格的 API 文档描述
- CHANGELOG 条目
"""

import logging
from core.config import AgentResult, GitDiffEvent, AGENT_ROLES
from prompts.templates import DOC_SYSTEM_PROMPT, DOC_USER_TEMPLATE
from utils.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class DocumentationAgent:
    """
    文档同步 Agent。

    采用"分析-生成"两阶段模式：
    1. 理解架构影响报告中的关键变更点
    2. 以技术写作的视角生成结构化文档更新
    """

    ROLE = "documentation"

    def __init__(self, client: ClaudeClient):
        self.client = client
        self.role_config = AGENT_ROLES[self.ROLE]

    async def generate_docs(
        self,
        event: GitDiffEvent,
        reasoning_result: AgentResult,
    ) -> AgentResult:
        """
        根据架构分析结果生成文档更新内容。

        Args:
            event:            原始 Git Diff 事件
            reasoning_result: 推理 Agent 的执行结果（作为上下文输入）

        Returns:
            包含文档更新内容的 AgentResult
        """
        logger.info(f"📝 文档 Agent 启动 | 基于推理结果生成文档")

        # 如果推理 Agent 失败，文档 Agent 使用降级策略
        reasoning_context = (
            reasoning_result.final_output
            if reasoning_result.success
            else f"推理 Agent 未能提供分析（错误: {reasoning_result.error_message}）"
        )

        user_message = DOC_USER_TEMPLATE.format(
            changed_files="\n".join(f"  - {f}" for f in event.changed_files),
            commit_message=event.commit_message,
            reasoning_output=reasoning_context,
        )

        try:
            raw_output, tokens = await self.client.invoke(
                system_prompt=DOC_SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=self.role_config["max_tokens"],
                temperature=0.5,  # 中等温度，保持文档准确性的同时允许一定灵活性
                agent_role=self.ROLE,
            )

            # 提取各文档部分（Part A / B / C）作为推理链节点
            reasoning_chain = self._extract_doc_sections(raw_output)

            logger.info(f"📝 文档 Agent 完成 | tokens={tokens}")

            return AgentResult(
                agent_role=self.ROLE,
                success=True,
                reasoning_chain=reasoning_chain,
                final_output=raw_output,
                tokens_used=tokens,
            )

        except Exception as exc:
            logger.error(f"📝 文档 Agent 异常: {exc}")
            return AgentResult(
                agent_role=self.ROLE,
                success=False,
                reasoning_chain=[],
                final_output="",
                error_message=str(exc),
            )

    def _extract_doc_sections(self, raw_text: str) -> list[str]:
        """将文档输出按 Part A/B/C 分段，作为推理链节点记录。"""
        import re
        sections = re.split(r"###\s*Part\s+[ABC]", raw_text, flags=re.IGNORECASE)
        headers = re.findall(r"###\s*Part\s+[ABC][^\n]*", raw_text, flags=re.IGNORECASE)

        result = []
        for i, content in enumerate(sections[1:], 0):
            header = headers[i].strip() if i < len(headers) else f"Part {i + 1}"
            result.append(f"{header}\n{content.strip()[:300]}...")

        return result or [raw_text[:400] + "..."]
