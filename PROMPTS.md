# PROMPTS

本文件集中存放管线所用 LLM 提示词(既定约定)。

**M1 默认零 LLM 调用** —— 本文件存在仅作占位与契约声明:仅当 `config/settings.toml` 的
`[toggles] l2_enabled = true` 时,S4 元数据 L2(业务域/摘要辅助)才会启用并使用以下提示词。
关闭时业务域取 manifest 声明值,代码路径不变(生产期切网关 endpoint,见 SPEC §决策)。

## L2 业务域辅助(l2_enabled 时启用)

> 待 L2 回迁时填充。
