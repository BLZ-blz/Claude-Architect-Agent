"""
agents/quality_agent.py
========================
质量保障 Agent — 基于变更逻辑和架构风险自动生成单元测试。

三阶段执行模式：
  Phase 1: 测试策略规划（识别需要覆盖的场景矩阵）
  Phase 2: 测试代码生成（生成可执行的 pytest 套件）
  Phase 3: 覆盖率分析（估算覆盖率并指出盲区）
"""

import re
import logging
from core.config import AgentResult, GitDiffEvent, AGENT_ROLES
from prompts.templates import TEST_SYSTEM_PROMPT, TEST_USER_TEMPLATE
from utils.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


class QualityAgent:
    """
    质量保障 Agent。

    关键设计：
    - 从推理 Agent 的风险评分中提取高风险模块
    - 优先为高风险区域生成测试用例
    - 支持 pytest + mock 框架的测试代码生成
    """

    ROLE = "quality"

    def __init__(self, client: ClaudeClient):
        self.client = client
        self.role_config = AGENT_ROLES[self.ROLE]

    async def generate_tests(
        self,
        event: GitDiffEvent,
        reasoning_result: AgentResult,
    ) -> AgentResult:
        """
        生成单元测试套件。

        Args:
            event:            原始 Git Diff 事件
            reasoning_result: 推理 Agent 的结果（提取风险摘要）

        Returns:
            包含测试代码的 AgentResult
        """
        logger.info(f"🧪 质量 Agent 启动 | 基于架构风险生成测试")

        # 从推理结果中提取风险摘要（如果可用）
        risk_summary = self._extract_risk_summary(reasoning_result)

        user_message = TEST_USER_TEMPLATE.format(
            diff_content=event.diff_content,
            risk_summary=risk_summary,
        )

        try:
            raw_output, tokens = await self.client.invoke(
                system_prompt=TEST_SYSTEM_PROMPT,
                user_message=user_message,
                max_tokens=self.role_config["max_tokens"],
                temperature=0.2,  # 极低温度确保生成可执行的确定性代码
                agent_role=self.ROLE,
            )

            # 提取三个阶段作为推理链节点
            reasoning_chain = self._extract_phases(raw_output)

            logger.info(f"🧪 质量 Agent 完成 | tokens={tokens}")

            return AgentResult(
                agent_role=self.ROLE,
                success=True,
                reasoning_chain=reasoning_chain,
                final_output=raw_output,
                tokens_used=tokens,
            )

        except Exception as exc:
            logger.error(f"🧪 质量 Agent 异常: {exc}")
            return AgentResult(
                agent_role=self.ROLE,
                success=False,
                reasoning_chain=[],
                final_output="",
                error_message=str(exc),
            )

    def _extract_risk_summary(self, reasoning_result: AgentResult) -> str:
        """
        从推理 Agent 的输出中提取风险评分部分。
        用于引导质量 Agent 优先覆盖高风险区域。
        """
        if not reasoning_result.success or not reasoning_result.final_output:
            return "推理 Agent 未提供风险数据，请覆盖所有变更模块的基础场景。"

        text = reasoning_result.final_output
        # 尝试提取 Step 4（架构风险量化）部分
        match = re.search(
            r"Step\s*4[^\n]*\n(.*?)(?=Step\s*5|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()[:1000]

        # 降级：取全文前 800 字符作为风险摘要
        return text[:800] + "..."

    def _extract_phases(self, raw_text: str) -> list[str]:
        """将测试输出按 Phase 1/2/3 分段。"""
        phases = re.split(r"###\s*Phase\s+\d+", raw_text, flags=re.IGNORECASE)
        headers = re.findall(r"###\s*Phase\s+\d+[^\n]*", raw_text, flags=re.IGNORECASE)

        result = []
        for i, content in enumerate(phases[1:], 0):
            header = headers[i].strip() if i < len(headers) else f"Phase {i + 1}"
            result.append(f"{header}\n{content.strip()[:400]}...")

        return result or [raw_text[:400] + "..."]
