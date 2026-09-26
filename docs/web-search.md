# 联网搜索与事实来源

## 为什么 DeepSeek 不会自动联网

DeepSeek 模型 API 接收消息，也可以按 AstrBot 提供的函数定义请求调用工具；但函数调用只是让模型请求工具，实际搜索和天气数据必须由 AstrBot 搜索提供方或本项目的查询接口完成。AstrBot 内置 Web Search 依赖模型函数调用能力，需要先启用并配置搜索提供方。DeepSeek 官方接口也把工具调用设计为“模型发起调用、应用执行函数并把结果交回模型”的流程。

## 启用 AstrBot 通用网页搜索

1. 打开本机 AstrBot WebUI：`http://127.0.0.1:6185`。
2. 进入“配置”，选择机器人正在使用的人格配置；在“AI → 能力 → 网页搜索”启用搜索。
3. 搜索服务先选 `AnySearch`。可先不填 API Key 试用匿名额度；若遇到限流或服务不可用，再按需配置该提供方的 Key。
4. 保存配置，然后在“插件 → 管理行为 → 函数工具”确认网页搜索工具已启用，并在当前人格允许该工具。
5. 模型提供商应选择支持函数调用的模型。AstrBot 文档列出 DeepSeek v3.2（`deepseek-chat`）为支持模型；不支持工具调用的旧模型可能不会触发搜索。若刚刚修改了提供方或人格配置，重新开始一轮对话再试。
6. 用明确请求验收，例如“联网搜索今天的天气，并列出来源”。天气查询不依赖该搜索开关，直接问“今天的天气”会走项目的 `weather_today` 工具；具体地点从项目私有 `.env` 读取。

## 回复来源约定

已更新建议加入 AstrBot 人格的[助手规则](assistant-persona.md)：

- 使用 Web Search 或外部查询结果时，在相关事实旁写“【联网查询】”，并给出真实来源名称和链接。
- 天气工具的最终回复保留“天气预报查询”标记及 Open-Meteo 来源链接。
- 搜索没有成功时要明确说未查到；不能把模型记忆说成实时查询，也不能虚构引用。

网页搜索与模型生成的最终表达由 AstrBot 的人格提示词约束；工具结果本身会携带来源信息。模型若仍省略来源，请将 `docs/assistant-persona.md` 的规则完整复制到当前人格提示词。

## 官方文档

- [AstrBot 网页搜索配置](https://docs.astrbot.app/en/use/websearch.html)
- [AstrBot 函数调用与模型兼容性](https://docs.astrbot.app/use/function-calling.html)
- [DeepSeek 工具调用流程](https://api-docs.deepseek.com/guides/tool_calls/)
