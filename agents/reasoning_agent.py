"""
agents/reasoning_agent.py
=========================
架构推理 Agent — 系统中 Token 消耗最密集的核心模块。

通过多步 Chain-of-Thought 推理，对代码变更进行深度架构影响分析。
设计上支持"思维链分步提取"，以便审计每个推理节点的中间结论。
"""

import re
import logging
from core.config import AgentResult, GitDiffEvent, AGENT_ROLES
from prompts.templates import REASONING_SYSTEM_PROMPT, REASONING_USER_TEMPLATE
from utils.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

# 推理步骤的标题模式（与 Prompt 模板中的 Step N 对应）
_STEP_PATTERN = re.compile(r"#{2,3}\s*Step\s*\d+[^#\n]*", re.IGNORECASE)


class ReasoningAgent:
    """
    架构推理 Agent。

    核心职责：
    1. 将 Git Diff 转化为结构化的上下文
    2. 驱动 Claude 执行 5 步架构分析链
    3. 解析并返回每个推理步骤的中间结论
    """

    ROLE = "reasoning"

    def __init__(self, client: ClaudeClient):
        self.client = client
        self.role_config = AGENT_ROLES[self.ROLE]

    async def analyze(self, event: GitDiffEvent) -> AgentResult:
        """
        执行架构影响分析。

        Args:
            event: Git Diff 事件对象

        Returns:
            包含完整推理链的 AgentResult
        """
        logger.info(f"🧠 推理 Agent 启动 | 分析提交: {event.commit_hash}")

        # 构造用户消息（填充 Prompt 模板）
        user_message = REASONING_USER_TEMPLATE.format(
            repo_name=event.repo_name,
            commit_hash=event.commit_hash,
            author=event.author,
            commit_message=event.commit_message,
            changed_files="\n".join(f"  - {f}" for f in event.changed_files),
            diff_content=event.diff_content,
        )

        try:
            raw_output, tokens = await self.client.invoke(
                system_prompt=REASONING_SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=self.role_config["max_tokens"],
                temperature=0.3,  # 低温度保证推理的确定性
                agent_role=self.ROLE,
            )

            # 从完整输出中提取各推理步骤
            reasoning_chain = self._extract_reasoning_steps(raw_output)

            logger.info(
                f"🧠 推理 Agent 完成 | "
                f"提取到 {len(reasoning_chain)} 个推理节点 | "
                f"tokens={tokens}"
            )

            return AgentResult(
                agent_role=self.ROLE,
                success=True,
                reasoning_chain=reasoning_chain,
                final_output=raw_output,
                tokens_used=tokens,
            )

        except Exception as exc:
            logger.error(f"🧠 推理 Agent 异常: {exc}")
            return AgentResult(
                agent_role=self.ROLE,
                success=False,
                reasoning_chain=[],
                final_output="",
                error_message=str(exc),
            )

    def _extract_reasoning_steps(self, raw_text: str) -> list[str]:
        """
        从完整的 LLM 输出中提取分步推理节点。

        通过匹配 Prompt 模板中定义的 Step N 标题，
        将长文本切分为独立的推理片段。
        """
        # 按 Step 标题分割文本
        sections = _STEP_PATTERN.split(raw_text)
        headers = _STEP_PATTERN.findall(raw_text)

        steps = []
        for i, content in enumerate(sections[1:], 0):  # sections[0] 是前言
            header = headers[i].strip() if i < len(headers) else f"Step {i + 1}"
            snippet = content.strip()[:500]  # 限制每步摘要长度
            steps.append(f"{header}\n{snippet}")

        # 如果正则未匹配到结构（模型自由发挥），则按段落分割
        if not steps:
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            steps = paragraphs[:5]  # 最多取前 5 段

        return steps
