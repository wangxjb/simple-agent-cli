"""
配置管理 — TOML 文件加载 + 环境变量注入 + 多提供商管理

配置加载优先级:
    命令行参数 > 配置文件 > 环境变量 > 默认值
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


# ===== 寻找配置文件 =====

def _find_config() -> Path:
    """按优先级查找 config.toml"""
    candidates = [
        Path(os.getenv("SIMPLE_CLI_CONFIG", "")),
        Path.cwd() / "config.toml",
        Path.home() / ".simple_cli" / "config.toml",
        Path(__file__).parent / "config.toml",
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p.resolve()
        except OSError:
            continue
    # 不存在则返回默认位置
    return Path.cwd() / "config.toml"


# ===== TOML 加载 =====

def _load_toml(path: Path) -> Dict[str, Any]:
    """读取 TOML 文件，支持 tomllib (3.11+) 和 tomli 回退"""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            print("错误: 需要安装 tomli 库（pip install tomli）来支持 TOML 配置", file=sys.stderr)
            sys.exit(1)

    with open(path, "rb") as f:
        return tomllib.load(f)


# ===== 环境变量展开 =====

def _expand_env(value: str) -> str:
    """
    展开 ${VAR_NAME} 占位符。

    例: "${DEEPSEEK_API_KEY}" → os.environ["DEEPSEEK_API_KEY"]
        "https://api.openai.com/v1" → 原样返回
        "${HOME}/.config" → "C:/Users/xxx/.config"
    """
    if not isinstance(value, str):
        return value
    return os.path.expandvars(value)


def _expand_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """递归展开字典中的所有 ${ENV} 占位符"""
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = _expand_env(value)
        elif isinstance(value, dict):
            result[key] = _expand_dict(value)
        else:
            result[key] = value
    return result


# ===== 数据类 =====

@dataclass
class ProviderConfig:
    """单个 LLM 提供商的配置"""
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass
class AppConfig:
    """完整的应用配置"""
    default_provider: str = "deepseek"
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    agent_type: str = "auto"        # "auto" | "fc" | "react"
    max_steps: int = 5
    system_prompt: Optional[str] = None
    tools_enabled: Dict[str, bool] = field(default_factory=dict)


# ===== 主加载函数 =====

def load_config(path: Optional[str] = None) -> AppConfig:
    """
    加载并解析配置。

    加载流程:
        1. 找到 config.toml 文件
        2. 读取 TOML → 展开 ${ENV}
        3. 构建 ProviderConfig 列表
        4. 返回 AppConfig

    Args:
        path: 配置文件路径（可选，不传则自动查找）

    Returns:
        AppConfig 对象
    """
    if path:
        config_path = Path(path)
        if not config_path.is_file():
            print(f"错误: 配置文件不存在 — {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = _find_config()

    if not config_path.is_file():
        print(f"提示: 未找到配置文件，使用默认配置", file=sys.stderr)
        return AppConfig()

    raw = _load_toml(config_path)
    raw = _expand_dict(raw)

    config = AppConfig()

    # 解析 [general]
    general = raw.get("general", {})
    config.default_provider = general.get("default_provider", "deepseek")
    config.agent_type = general.get("agent_type", "fc")
    config.max_steps = int(general.get("max_steps", 5))
    config.system_prompt = general.get("system_prompt")

    # 解析 [providers]
    providers = raw.get("providers", {})
    for name, info in providers.items():
        config.providers[name] = ProviderConfig(
            name=name,
            base_url=info.get("base_url", ""),
            api_key=info.get("api_key", ""),
            model=info.get("model", ""),
        )

    # 解析 [tools]
    tools = raw.get("tools", {})
    for name, info in tools.items():
        if isinstance(info, dict):
            config.tools_enabled[name] = info.get("enabled", False)
        else:
            config.tools_enabled[name] = bool(info)

    return config


def get_provider(config: AppConfig, name: Optional[str] = None) -> ProviderConfig:
    """
    获取指定或默认提供商配置。

    Args:
        config: AppConfig
        name: 提供商名称（可选，不传则用默认）

    Returns:
        ProviderConfig
    """
    provider_name = name or config.default_provider
    provider = config.providers.get(provider_name)
    if not provider:
        available = list(config.providers.keys())
        raise ValueError(
            f"提供商 '{provider_name}' 未在配置中找到。可用: {', '.join(available)}"
        )
    return provider


def resolve_agent_type(config: AppConfig, llm: "HelloAgentsLLM") -> str:
    """
    解析最终的 agent_type。

    策略:
    - "auto" → 按厂商推断（已知支持 FC 的直接返回 fc）
    - "fc" / "react" → 直接使用

    为什么不做 API 检测？
    → 每次启动都发测试请求浪费额度，且触发速率限制。
      已知 DeepSeek/GLM/Qwen/OpenAI 都支持 FC，
      只有 Ollama/本地模型可能需要 ReAct。
    """
    if config.agent_type == "auto":
        # 按 base_url 推断：已知的云服务都支持 FC
        fc_indicators = [
            "api.deepseek.com",
            "open.bigmodel.cn",     # GLM
            "dashscope.aliyuncs.com", # Qwen
            "api.openai.com",
            "api.moonshot.cn",
        ]
        url = (llm.base_url or "").lower()
        for indicator in fc_indicators:
            if indicator in url:
                return "fc"
        # 未知提供商（如本地 Ollama）→ 默认 ReAct
        return "react"
    return config.agent_type


def create_llm_from_config(
    config: AppConfig,
    provider_name: Optional[str] = None,
) -> "HelloAgentsLLM":
    """
    从配置创建 LLM 客户端。

    这是配置系统和 LLM 模块之间的"胶水函数"——
    有了它，REPL 只需一行代码完成模型切换。

    Args:
        config: AppConfig
        provider_name: 提供商名称（可选）

    Returns:
        HelloAgentsLLM 实例
    """
    from .llm import HelloAgentsLLM

    provider = get_provider(config, provider_name)
    return HelloAgentsLLM(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=provider.model,
    )
