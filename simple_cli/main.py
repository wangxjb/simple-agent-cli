"""simple-cli 入口 — CLI 参数解析 + 模式分发"""

import argparse
import sys
import os

# Windows 终端 UTF-8 兼容
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .config import load_config, AppConfig
from .repl import repl, _run_single


def main():
    parser = argparse.ArgumentParser(
        prog="simple-cli",
        description="从零学习 Agent — 一个类似 Claude-CLI 的终端 AI 助手",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="单轮模式: 直接提问（不带参数则进入 REPL 交互模式）",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="配置文件路径（默认自动查找 config.toml）",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="指定 LLM 提供商（覆盖配置文件中的 default_provider）",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=["react", "fc"],
        help="指定 Agent 类型（覆盖配置文件中的 agent_type）",
    )

    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 命令行参数覆盖配置
    if args.model:
        config.default_provider = args.model
    if args.mode:
        config.agent_type = args.mode

    # 模式分发
    if args.question:
        # 单轮模式
        _run_single(config, args.question)
    else:
        # REPL 模式
        repl(config)


if __name__ == "__main__":
    main()
