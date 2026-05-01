"""
main.py
=======
Claude Architect Agent — 命令行主入口。

支持两种运行模式：
  1. demo  — 运行内置的演示场景（JWT → OAuth2 重构）
  2. watch — 监听指定目录的 Git 变更（生产模式占位）

用法：
  python main.py demo
  python main.py --help
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# 配置根日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="claude-architect-agent",
        description="多 Agent 协作的自动化代码架构分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py demo           # 运行演示场景
  python main.py demo --verbose # 详细日志模式
        """,
    )
    parser.add_argument(
        "mode",
        choices=["demo"],
        help="运行模式：demo=内置演示场景",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用调试日志",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("analysis_report.md"),
        help="输出报告路径（默认: analysis_report.md）",
    )
    return parser.parse_args()


async def run_demo_mode(output_path: Path) -> None:
    """运行内置演示场景。"""
    from examples.demo_scenario import DEMO_EVENT
    from core.coordinator import ArchitectCoordinator

    coordinator = ArchitectCoordinator()
    report = await coordinator.process(DEMO_EVENT)

    output_path.write_text(report, encoding="utf-8")
    logger.info(f"报告已写入: {output_path.resolve()}")


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"启动模式: {args.mode}")

    if args.mode == "demo":
        asyncio.run(run_demo_mode(args.output))
    else:
        logger.error(f"未知模式: {args.mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
