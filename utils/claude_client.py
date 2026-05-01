"""
utils/claude_client.py
======================
Claude API 的轻量封装层。
负责统一的请求构建、错误处理、Token 统计与调用日志记录。
"""

import json
import time
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ClaudeAPIError(Exception):
    """Claude API 调用异常的统一封装。"""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[HTTP {status_code}] {message}")


class ClaudeClient:
    """
    Claude API 客户端。

    封装了：
    - 单轮调用（invoke）
    - 流式调用占位（stream_invoke，可扩展）
    - 调用指标统计
    """

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, model_id: str):
        self.model_id = model_id
        self._call_log: list[dict] = []           # 历史调用记录

    # ------------------------------------------------------------------
    # 核心调用方法
    # ------------------------------------------------------------------

    async def invoke(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
        temperature: float = 0.7,
        agent_role: str = "unknown",
    ) -> tuple[str, int]:
        """
        向 Claude API 发送单次请求。

        Args:
            system_prompt:  系统角色提示词
            user_message:   用户侧内容（包含任务指令）
            max_tokens:     最大输出 Token 数
            temperature:    采样温度（0.0 = 确定性，1.0 = 创造性）
            agent_role:     调用方 Agent 角色（用于日志）

        Returns:
            (response_text, estimated_tokens) 二元组
        """
        import aiohttp  # 延迟导入，减少启动开销

        payload = {
            "model": self.model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ],
        }

        start_time = time.monotonic()
        logger.info(
            f"[{agent_role}] 发起 API 请求 | max_tokens={max_tokens} | "
            f"system_len={len(system_prompt)} | user_len={len(user_message)}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.API_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "anthropic-version": self.API_VERSION,
                    },
                ) as resp:
                    elapsed = time.monotonic() - start_time

                    if resp.status != 200:
                        error_body = await resp.text()
                        raise ClaudeAPIError(resp.status, error_body)

                    data = await resp.json()
                    response_text = data["content"][0]["text"]

                    # 从响应中提取 Token 用量
                    usage = data.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    total_tokens = input_tokens + output_tokens

                    # 记录调用日志
                    self._call_log.append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "agent_role": agent_role,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "latency_ms": round(elapsed * 1000, 1),
                    })

                    logger.info(
                        f"[{agent_role}] 请求完成 | "
                        f"tokens={input_tokens}+{output_tokens}={total_tokens} | "
                        f"latency={elapsed:.2f}s"
                    )

                    return response_text, total_tokens

        except ClaudeAPIError:
            raise
        except Exception as exc:
            raise ClaudeAPIError(0, f"网络或解析错误: {exc}") from exc

    # ------------------------------------------------------------------
    # 指标统计
    # ------------------------------------------------------------------

    def get_usage_summary(self) -> dict:
        """汇总所有 Agent 的 Token 消耗情况。"""
        if not self._call_log:
            return {"total_calls": 0, "total_tokens": 0, "by_agent": {}}

        by_agent: dict[str, dict] = {}
        for entry in self._call_log:
            role = entry["agent_role"]
            if role not in by_agent:
                by_agent[role] = {"calls": 0, "tokens": 0, "avg_latency_ms": 0}
            by_agent[role]["calls"] += 1
            by_agent[role]["tokens"] += entry["total_tokens"]
            by_agent[role]["avg_latency_ms"] = round(
                (by_agent[role]["avg_latency_ms"] * (by_agent[role]["calls"] - 1)
                 + entry["latency_ms"]) / by_agent[role]["calls"],
                1,
            )

        total_tokens = sum(e["total_tokens"] for e in self._call_log)
        return {
            "total_calls": len(self._call_log),
            "total_tokens": total_tokens,
            "by_agent": by_agent,
        }

    def print_usage_report(self) -> None:
        """在控制台打印 Token 使用报告。"""
        summary = self.get_usage_summary()
        print("\n" + "=" * 60)
        print("📊 Token 使用报告")
        print("=" * 60)
        print(f"  总调用次数: {summary['total_calls']}")
        print(f"  总 Token 消耗: {summary['total_tokens']:,}")
        print("\n  按 Agent 分类:")
        for role, stats in summary["by_agent"].items():
            print(
                f"    • {role:<20} "
                f"调用={stats['calls']} | "
                f"tokens={stats['tokens']:,} | "
                f"avg_latency={stats['avg_latency_ms']}ms"
            )
        print("=" * 60 + "\n")
