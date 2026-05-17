"""
REPL 交互循环 — simple-cli 的"脸面"

提供:
- 欢迎界面
- 多轮对话（保持 Agent 上下文）
- 特殊命令（/model, /tools, /mode, /help 等）
- 流式打印 Agent 输出
"""

import sys
import signal
from datetime import datetime
from typing import Optional, List
from .config import AppConfig, create_llm_from_config
from .agent import ReActAgent, FCAgent
from .tools import ToolRegistry
from .tools.builtin import (
    ReadFileTool, WriteFileTool, RunCommandTool,
    ListDirTool, WebSearchTool,
)
from .session import SessionStore

# Tab 补全命令列表（不含参数，纯命令名）
COMMANDS = [
    "/help", "/exit", "/quit",
    "/model", "/mode",
    "/resume", "/sessions",
    "/save", "/tools", "/clear", "/history",
    "/compress", "/single",
]

MODEL_NAMES = ["deepseek", "glm", "qwen", "openai", "ollama"]
MODE_NAMES = ["react", "fc"]


def _setup_completion(config: AppConfig):
    """
    设置 Tab 补全。

    原理:
        1. 注册一个 completer 函数到 readline
        2. 每次按 Tab 时，readline 调用 completer(text, state)
        3. completer 根据当前输入 text 返回匹配的候选项

    补全规则:
        /     → 显示所有命令
        /mod  → 补全 /model
        /model <Tab> → 显示提供商列表 (deepseek, glm, ...)
        /mode  <Tab> → 显示模式列表 (react, fc)
        /resume <Tab> → 显示已保存会话列表
    """
    try:
        import readline
    except ImportError:
        return  # 没有 readline 则静默禁用补全

    def completer(text: str, state: int) -> Optional[str]:
        """
        readline 补全回调。

        Args:
            text: 当前输入的文本（光标前的内容）
            state: 0 = 第一个匹配, 1 = 第二个匹配, ...（readline 会持续调用直到返回 None）

        Returns:
            匹配的补全文本，或 None（无更多匹配）
        """
        # 收集所有可能的补全项
        candidates: List[str] = []

        # 情况 1: /model Deep<Tab> → 补全提供商名
        if text.startswith("/model "):
            prefix = text[7:]
            candidates = [f"/model {m}" for m in MODEL_NAMES if m.startswith(prefix)]

        # 情况 2: /mode re<Tab> → 补全模式名
        elif text.startswith("/mode "):
            prefix = text[6:]
            candidates = [f"/mode {m}" for m in MODE_NAMES if m.startswith(prefix)]

        # 情况 3: /resume my<Tab> → 补全会话名
        elif text.startswith("/resume "):
            prefix = text[8:]
            store = SessionStore()
            candidates = [
                f"/resume {s['name']}"
                for s in store.list_sessions()
                if s["name"].startswith(prefix)
            ]

        # 情况 4: /save my<Tab> → 不补全（自由输入）
        elif text.startswith("/save"):
            pass  # save 的名字由用户自由输入

        # 情况 5: 补全命令本身 → /ex<Tab> → /exit
        else:
            candidates = [cmd for cmd in COMMANDS if cmd.startswith(text) and " " not in cmd]

        # 按 state 返回对应索引的候选
        if state < len(candidates):
            return candidates[state]
        return None

    # 注册补全函数
    readline.set_completer(completer)

    # 设置补全分隔符（默认会按空白分割，我们要整体匹配）
    readline.set_completer_delims(" \t\n")

    # 绑定 Tab 键到补全功能
    readline.parse_and_bind("tab: complete")

# 所有可用工具映射表
AVAILABLE_TOOLS = {
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "run_command": RunCommandTool,
    "list_directory": ListDirTool,
    "web_search": WebSearchTool,
}

BANNER = """
╔══════════════════════════════════════════╗
║          Simple-CLI Agent               ║
║   从零学习 Agent — 类似 Claude-CLI       ║
║                                          ║
║   输入 /help 查看可用命令                 ║
║   输入 /exit 或 Ctrl+C 退出              ║
╚══════════════════════════════════════════╝
"""

HELP_TEXT = """
命令列表:
  /help              显示此帮助
  /exit, /quit       退出程序
  /model <name>      切换模型 (deepseek/glm/qwen/openai/ollama)
  /mode <type>       切换 Agent 类型 (react/fc)
  /resume [name]     列出/恢复历史会话
  /sessions          列出所有已保存的会话
  /save [name]       保存会话（不指定名则自动命名）
  /tools             列出当前启用的工具
  /clear             清除当前会话历史
  /compress          手动压缩对话历史（生成摘要）
  /history           显示当前会话的历史消息
  /single <问题>     单轮模式（不进入 REPL，回答后退出）
"""


def _build_registry(config: AppConfig) -> ToolRegistry:
    """根据配置创建工具注册表"""
    registry = ToolRegistry()
    for name, tool_cls in AVAILABLE_TOOLS.items():
        if config.tools_enabled.get(name, True):
            registry.register(tool_cls())
    return registry


def _run_single(config: AppConfig, question: str):
    """单轮模式：一个问题 → 回答 → 退出"""
    llm = create_llm_from_config(config)
    registry = _build_registry(config)

    if config.agent_type == "react":
        agent = ReActAgent(llm, registry, config.system_prompt, config.max_steps)
    else:
        agent = FCAgent(llm, registry, config.system_prompt, config.max_steps)

    print(f"\n使用模型: {llm.model}\n")
    result = agent.run(question)
    print(f"\n{'=' * 50}")
    print(result)


def _do_save(store: SessionStore, agent, provider: str, agent_type: str, name: str = "") -> str:
    """保存会话，返回提示信息"""
    try:
        if name:
            store.save(name, agent.history, provider, agent_type)
            return f"会话已保存为 '{name}' ({len(agent.history)} 条消息)"
        else:
            path = store.auto_save(agent.history, provider, agent_type)
            return f"会话已保存 ({len(agent.history)} 条消息)"
    except Exception as e:
        return f"保存失败: {e}"


def _cmd_resume(store: SessionStore, agent, config: AppConfig,
                 current_provider: str, current_mode: str,
                 llm, _create_agent) -> tuple:
    """
    /resume [name] 命令处理。

    不带参数: 列出所有会话，让用户选择
    带参数: 直接加载指定会话

    Returns: (agent, llm, current_provider, current_mode) — 可能因恢复而更新
    """
    sessions = store.list_sessions()

    if not sessions:
        print("没有已保存的会话")
        return agent, llm, current_provider, current_mode

    target = None
    args = ""  # 暂时省略参数解析，简化逻辑

    # 直接检查是否有参数传入 — 但这里我们要重构，暂时只做列表选择
    print(f"\n已保存的会话 ({len(sessions)}):")
    print(f"{'#':<4} {'名称':<30} {'时间':<18} {'消息':<6} {'预览'}")
    print("-" * 80)
    for i, s in enumerate(sessions, 1):
        try:
            updated = datetime.fromisoformat(s.get("updated_at", ""))
            time_str = updated.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            time_str = "???"
        print(f"{i:<4} {s['name']:<30} {time_str:<18} {s['message_count']:<6} {s['preview']}")

    try:
        choice = input("\n输入序号或名称来恢复 (回车取消): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return agent, llm, current_provider, current_mode

    if not choice:
        return agent, llm, current_provider, current_mode

    # 尝试按序号匹配
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(sessions):
            target = sessions[idx]["name"]
    except ValueError:
        pass

    # 尝试按名称匹配
    if not target:
        # 精确匹配
        if store.exists(choice):
            target = choice
        # 模糊匹配
        else:
            matches = [s["name"] for s in sessions if choice.lower() in s["name"].lower()]
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) > 1:
                print(f"多个匹配: {', '.join(matches)}")
                return agent, llm, current_provider, current_mode
            else:
                print(f"未找到会话: {choice}")
                return agent, llm, current_provider, current_mode

    # 加载会话
    data = store.load(target)
    if not data:
        print(f"无法加载会话: {target}")
        return agent, llm, current_provider, current_mode

    saved_history = store.restore_history(target)

    # 恢复 provider
    saved_provider = data.get("provider", "")
    if saved_provider and saved_provider in config.providers:
        try:
            llm = create_llm_from_config(config, saved_provider)
            current_provider = saved_provider
        except Exception:
            pass

    # 恢复 agent_type
    saved_mode = data.get("agent_type", "")
    if saved_mode in ("react", "fc"):
        current_mode = saved_mode

    agent = _create_agent()
    for msg in saved_history:
        agent.history.append(msg)

    print(f"已恢复会话 '{target}' ({len(saved_history)} 条消息)")
    return agent, llm, current_provider, current_mode


def _cmd_sessions(store: SessionStore):
    """列出所有已保存的会话"""
    sessions = store.list_sessions()
    if not sessions:
        print("没有已保存的会话")
        return

    print(f"\n已保存的会话 ({len(sessions)}):")
    print(f"{'名称':<32} {'更新时间':<20} {'消息':<6} {'提供商':<12} {'Agent':<6}")
    print("-" * 80)
    for s in sessions:
        try:
            updated = datetime.fromisoformat(s.get("updated_at", ""))
            time_str = updated.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            time_str = "???"
        print(f"{s['name']:<32} {time_str:<20} {s['message_count']:<6} "
              f"{s.get('provider',''):<12} {s.get('agent_type',''):<6}")


def repl(config: AppConfig):
    """
    REPL 主循环 — 多会话持久化版。

    启动 → 新会话（不自动恢复，用 /resume 手动恢复）
    退出 → 自动保存
    """
    print(BANNER)

    store = SessionStore()

    # ── 初始化 Agent ──
    llm = create_llm_from_config(config)
    registry = _build_registry(config)
    current_provider = config.default_provider
    current_mode = config.agent_type
    current_session_name = ""  # 当前已保存的会话名（空 = 新会话）

    def _create_agent():
        if current_mode == "react":
            return ReActAgent(llm, registry, config.system_prompt, config.max_steps)
        else:
            return FCAgent(llm, registry, config.system_prompt, config.max_steps)

    agent = _create_agent()

    # ── Ctrl+C 安全退出 ──
    def _handle_interrupt(signum, frame):
        print("\n\n正在保存会话...")
        msg = _do_save(store, agent, current_provider, current_mode, current_session_name)
        print(msg)
        print("再见!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_interrupt)

    # ── Tab 补全 ──
    _setup_completion(config)

    # ── 启动提示 ──
    saved_count = len(store.list_sessions())
    print(f"  模型: {llm.model}")
    print(f"  Agent: {current_mode}")
    print(f"  工具: {len(registry)} ({', '.join(registry.list_names())})")
    if saved_count > 0:
        print(f"  已保存 {saved_count} 个会话 (输入 /resume 恢复)")
    else:
        print(f"  输入 /help 查看所有命令")
    print()

    # ── 主循环 ──
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n正在保存会话...")
            msg = _do_save(store, agent, current_provider, current_mode, current_session_name)
            print(msg)
            print("再见!")
            break

        if not user_input:
            continue

        # ── 特殊命令 ──

        if user_input.startswith("/exit") or user_input.startswith("/quit"):
            print("正在保存会话...")
            msg = _do_save(store, agent, current_provider, current_mode, current_session_name)
            print(msg)
            print("再见!")
            break

        if user_input == "/help":
            print(HELP_TEXT)
            continue

        if user_input == "/tools":
            print(f"已启用 ({len(registry)}): {', '.join(registry.list_names())}")
            continue

        if user_input == "/clear":
            agent.clear_history()
            current_session_name = ""
            print("会话历史已清除")
            continue

        if user_input == "/compress":
            result = agent.compress_history()
            if result["status"] == "skip":
                print(result["reason"])
            else:
                print(f"压缩完成: {result['before_tokens']} → {result['after_tokens']} token "
                      f"(减少 {result['reduced']}, 共压缩 {result['compressions']} 次)")
            continue

        if user_input == "/history":
            h = agent.get_history_text()
            print(h if h else "(无历史)")
            continue

        if user_input == "/sessions":
            _cmd_sessions(store)
            continue

        if user_input.startswith("/save"):
            parts = user_input.split(maxsplit=1)
            name = parts[1].strip() if len(parts) > 1 else ""
            if name:
                current_session_name = name
            msg = _do_save(store, agent, current_provider, current_mode, name)
            print(msg)
            continue

        if user_input.startswith("/resume"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1:
                # /resume myname — 直接加载
                name = parts[1].strip()
                if store.exists(name):
                    data = store.load(name)
                    saved_history = store.restore_history(name)
                    saved_provider = data.get("provider", "")
                    saved_mode = data.get("agent_type", "")
                    if saved_provider and saved_provider in config.providers:
                        try:
                            llm = create_llm_from_config(config, saved_provider)
                            current_provider = saved_provider
                        except Exception:
                            pass
                    if saved_mode in ("react", "fc"):
                        current_mode = saved_mode
                    agent = _create_agent()
                    for msg in saved_history:
                        agent.history.append(msg)
                    current_session_name = name
                    print(f"已恢复会话 '{name}' ({len(saved_history)} 条消息)")
                else:
                    print(f"未找到会话: {name}")
            else:
                # /resume — 交互式选择
                agent, llm, current_provider, current_mode = _cmd_resume(
                    store, agent, config, current_provider, current_mode,
                    llm, _create_agent
                )
                if agent.history:
                    current_session_name = store.list_sessions()[0]["name"] if store.list_sessions() else ""
            continue

        if user_input.startswith("/model "):
            name = user_input[7:].strip()
            try:
                llm = create_llm_from_config(config, name)
                current_provider = name
                agent = _create_agent()
                print(f"已切换到: {llm.model}")
            except ValueError as e:
                print(f"错误: {e}")
            continue

        if user_input.startswith("/mode "):
            mode = user_input[6:].strip()
            if mode not in ("react", "fc"):
                print("错误: mode 只能是 react 或 fc")
                continue
            current_mode = mode
            agent = _create_agent()
            print(f"已切换到: {mode}")
            continue

        if user_input.startswith("/single "):
            question = user_input[8:].strip()
            _run_single(config, question)
            continue

        # ── 普通对话 ──
        try:
            result = agent.run(user_input)
            print(f"\n{'=' * 50}")
            print(result)
            print()

            # 每次对话后自动保存（防崩溃丢数据）
            _do_save(store, agent, current_provider, current_mode, current_session_name)

        except RuntimeError as e:
            print(f"\n错误: {e}")
        except Exception as e:
            print(f"\n未知错误: {e}")
