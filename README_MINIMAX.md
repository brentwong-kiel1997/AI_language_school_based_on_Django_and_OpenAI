# MiniMax CLI

独立的中国区 MiniMax Token Plan 客户端与命令行工具。默认地址为 `https://api.minimaxi.com`，不会依赖 Django Ark 应用。

## 配置

支持 `MINIMAX_API_KEY`、`MINIMAX_BASE_URL`、`MINIMAX_TEXT_MODEL`、`MINIMAX_CONTEXT_WINDOW_TOKENS`、`MINIMAX_MAX_TOKENS`、`MINIMAX_TIMEOUT_SECONDS` 环境变量，环境变量优先。默认文本模型为 `MiniMax-M3`，上下文窗口为 1,000,000 tokens（输入与输出合计），默认输出上限为 131,072 tokens；`MINIMAX_MAX_TOKENS` 可按 API 或应用需求覆盖，不能把上下文窗口直接当作输出上限。持久化配置位于 `~/.mmx/config.json`，可用 `MINIMAX_CONFIG_DIR` 覆盖目录。

```bash
export MINIMAX_API_KEY=你的密钥
python -m minimax_cli text chat --message "你好"
mmx auth login --api-key "$MINIMAX_API_KEY"
mmx config show
```

## 当前能力

支持非流式/基础 SSE 流式文本对话、coding plan search、可配置 quota endpoint，以及配置和认证管理。`json_mode` 通过 system 指令要求 JSON，不发送可能被接口拒绝的 `response_format`。search/quota 的官方字段可能随 Token Plan 版本变化，因此保留原始 JSON；默认 quota 路径为 `/v1/coding_plan/quota`，可通过配置覆盖。不会自动调用真实接口，测试使用 mock transport。

English: this package targets the China MiniMax Token Plan API, keeps raw search/quota responses, and intentionally excludes streaming tool orchestration, local agents, and Django integration from the first phase.
