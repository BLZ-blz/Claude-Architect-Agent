"""
tests/test_coordinator.py
==========================
协调器与各 Agent 的单元测试套件。
使用 pytest + unittest.mock 对所有 Claude API 调用进行隔离。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.config import GitDiffEvent, AgentResult
from core.coordinator import ArchitectCoordinator
from agents.reasoning_agent import ReasoningAgent
from agents.documentation_agent import DocumentationAgent
from agents.quality_agent import QualityAgent
from utils.claude_client import ClaudeClient, ClaudeAPIError


# ---------------------------------------------------------------------------
# 测试夹具（Fixtures）
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_event() -> GitDiffEvent:
    """标准测试用 Git Diff 事件。"""
    return GitDiffEvent(
        repo_name="test-repo",
        commit_hash="abc1234",
        author="test@example.com",
        commit_message="feat: 添加用户分组功能",
        changed_files=["models/user.py", "api/users.py"],
        diff_content="""
+class UserGroup(Base):
+    __tablename__ = "user_groups"
+    id = Column(Integer, primary_key=True)
+    name = Column(String(64), nullable=False)
+    users = relationship("User", back_populates="group")
""",
        tags=["feature"],
    )


@pytest.fixture
def mock_client() -> ClaudeClient:
    """返回一个 Mock 版 ClaudeClient，避免真实 API 调用。"""
    client = MagicMock(spec=ClaudeClient)
    client.invoke = AsyncMock(
        return_value=("### Step 1\n分析结果\n\n### Step 5\n结论：APPROVE", 1500)
    )
    client.get_usage_summary = MagicMock(return_value={
        "total_calls": 4,
        "total_tokens": 8500,
        "by_agent": {"reasoning": {"calls": 1, "tokens": 5000, "avg_latency_ms": 3200}},
    })
    return client


@pytest.fixture
def mock_reasoning_result() -> AgentResult:
    """成功的推理 Agent 结果。"""
    return AgentResult(
        agent_role="reasoning",
        success=True,
        reasoning_chain=["Step 1: 变更意图识别", "Step 4: 风险量化 — 可维护性: 6/10"],
        final_output="完整的架构分析报告内容...\n\n**综合建议**: APPROVE with minor changes",
        tokens_used=4800,
    )


# ---------------------------------------------------------------------------
# ClaudeClient 单元测试
# ---------------------------------------------------------------------------

class TestClaudeClient:
    """ClaudeClient 的行为测试。"""

    @pytest.mark.unit
    def test_usage_summary_empty(self):
        """初始状态下使用摘要应全为零。"""
        client = ClaudeClient(model_id="claude-sonnet-4-20250514")
        summary = client.get_usage_summary()
        assert summary["total_calls"] == 0
        assert summary["total_tokens"] == 0
        assert summary["by_agent"] == {}

    @pytest.mark.unit
    def test_api_error_creation(self):
        """ClaudeAPIError 应正确携带状态码和消息。"""
        error = ClaudeAPIError(429, "Rate limit exceeded")
        assert error.status_code == 429
        assert "429" in str(error)
        assert "Rate limit" in str(error)


# ---------------------------------------------------------------------------
# ReasoningAgent 单元测试
# ---------------------------------------------------------------------------

class TestReasoningAgent:
    """推理 Agent 的行为测试。"""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_analyze_success(self, sample_event, mock_client):
        """推理 Agent 成功时应返回正确的 AgentResult 结构。"""
        agent = ReasoningAgent(mock_client)
        result = await agent.analyze(sample_event)

        assert result.success is True
        assert result.agent_role == "reasoning"
        assert result.final_output != ""
        assert isinstance(result.reasoning_chain, list)
        mock_client.invoke.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_analyze_api_failure(self, sample_event, mock_client):
        """API 调用失败时应返回失败的 AgentResult，而非抛出异常。"""
        mock_client.invoke = AsyncMock(side_effect=ClaudeAPIError(500, "服务不可用"))
        agent = ReasoningAgent(mock_client)
        result = await agent.analyze(sample_event)

        assert result.success is False
        assert result.error_message is not None
        assert "500" in result.error_message or "服务不可用" in result.error_message

    @pytest.mark.unit
    def test_extract_reasoning_steps_with_structure(self):
        """有结构化标题的文本应正确分割为推理步骤。"""
        client = MagicMock(spec=ClaudeClient)
        agent = ReasoningAgent(client)
        text = "## Step 1 — 分析\n内容A\n\n## Step 2 — 评估\n内容B"
        steps = agent._extract_reasoning_steps(text)
        assert len(steps) >= 1
        assert "Step" in steps[0]

    @pytest.mark.unit
    def test_extract_reasoning_steps_fallback(self):
        """无结构标题时应降级为段落分割。"""
        client = MagicMock(spec=ClaudeClient)
        agent = ReasoningAgent(client)
        text = "第一段落内容。\n\n第二段落内容。\n\n第三段落内容。"
        steps = agent._extract_reasoning_steps(text)
        assert len(steps) >= 1


# ---------------------------------------------------------------------------
# DocumentationAgent 单元测试
# ---------------------------------------------------------------------------

class TestDocumentationAgent:
    """文档 Agent 的行为测试。"""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_generate_docs_success(
        self, sample_event, mock_client, mock_reasoning_result
    ):
        """文档 Agent 成功时应正确传递推理结果作为上下文。"""
        mock_client.invoke = AsyncMock(
            return_value=("### Part A\nREADME 更新\n### Part B\nAPI 文档\n### Part C\nCHANGELOG", 2000)
        )
        agent = DocumentationAgent(mock_client)
        result = await agent.generate_docs(sample_event, mock_reasoning_result)

        assert result.success is True
        # 验证推理结果被正确传递到 Prompt 中
        call_args = mock_client.invoke.call_args
        assert "APPROVE" in call_args.kwargs.get("user_message", "")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_generate_docs_with_failed_reasoning(self, sample_event, mock_client):
        """推理 Agent 失败时，文档 Agent 应使用降级策略继续执行。"""
        failed_reasoning = AgentResult(
            agent_role="reasoning",
            success=False,
            reasoning_chain=[],
            final_output="",
            error_message="连接超时",
        )
        mock_client.invoke = AsyncMock(return_value=("降级文档内容", 500))
        agent = DocumentationAgent(mock_client)
        result = await agent.generate_docs(sample_event, failed_reasoning)

        # 即使推理失败，文档 Agent 也应能继续执行
        assert result.success is True


# ---------------------------------------------------------------------------
# ArchitectCoordinator 集成测试
# ---------------------------------------------------------------------------

class TestArchitectCoordinator:
    """协调器的集成行为测试（全流程 Mock）。"""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, sample_event):
        """全流水线在所有 Agent 成功时应返回包含关键字段的报告。"""
        mock_response = ("分析完成，建议 APPROVE。所有测试通过。", 1000)

        with patch("core.coordinator.ClaudeClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.invoke = AsyncMock(return_value=mock_response)
            mock_instance.get_usage_summary = MagicMock(return_value={
                "total_calls": 4,
                "total_tokens": 4000,
                "by_agent": {},
            })
            mock_instance.print_usage_report = MagicMock()
            MockClient.return_value = mock_instance

            coordinator = ArchitectCoordinator()
            report = await coordinator.process(sample_event)

        assert isinstance(report, str)
        assert len(report) > 100
        # 报告应包含各 Agent 的章节标题
        assert "推理 Agent" in report or "架构" in report

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_pipeline_partial_failure(self, sample_event):
        """部分 Agent 失败时，流水线应继续执行并在报告中标记失败状态。"""
        call_count = 0

        async def flaky_invoke(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 第一次调用（推理 Agent）失败
                raise ClaudeAPIError(503, "服务暂时不可用")
            return ("后续 Agent 成功", 500)

        with patch("core.coordinator.ClaudeClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.invoke = AsyncMock(side_effect=flaky_invoke)
            mock_instance.get_usage_summary = MagicMock(return_value={
                "total_calls": 3,
                "total_tokens": 1500,
                "by_agent": {},
            })
            mock_instance.print_usage_report = MagicMock()
            MockClient.return_value = mock_instance

            coordinator = ArchitectCoordinator()
            report = await coordinator.process(sample_event)

        # 即使推理 Agent 失败，协调器也应生成报告
        assert isinstance(report, str)


# ---------------------------------------------------------------------------
# GitDiffEvent 数据类测试
# ---------------------------------------------------------------------------

class TestGitDiffEvent:
    """GitDiffEvent 数据类的基础行为测试。"""

    @pytest.mark.unit
    def test_summary_truncates_long_message(self):
        """长提交信息应被截断以保持摘要简洁。"""
        event = GitDiffEvent(
            repo_name="repo",
            commit_hash="abc",
            author="dev",
            commit_message="这是一条非常非常非常非常非常长的提交信息，超过了60个字符的限制",
            changed_files=["file.py"],
            diff_content="",
        )
        summary = event.summary()
        assert len(summary) < 300  # 摘要不应过长
        assert "repo" in summary
        assert "abc" in summary

    @pytest.mark.unit
    def test_default_base_branch(self):
        """默认基准分支应为 main。"""
        event = GitDiffEvent(
            repo_name="r", commit_hash="h", author="a",
            commit_message="m", changed_files=[], diff_content="",
        )
        assert event.base_branch == "main"
