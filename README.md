#  MaiBot 智能提醒插件

自然语言驱动的定时提醒插件，为 MaiBot 添加**备忘、定时通知、人设化提醒**能力。用户无需记忆命令，只需像日常聊天一样说出需求，机器人即可自动理解并设置提醒。

## 功能特色

- **自然语言交互**：说“明天下午3点提醒我开会”就能自动设置，无需 `/remind` 等命令
- **人设化提醒**：到时间后，机器人会用你配置的人格语气发送提醒，而非生硬的系统通知
- **持久化存储**：提醒数据保存到本地文件，重启机器人不丢失
- **数量限制保护**：每个用户可设置提醒上限，防止滥用
- **自动降级**：人格化生成失败时，自动降级为普通提醒，保证消息送达

## 安装

1. 确保你的 MaiBot 版本支持 `manifest_version: 2`，且已安装 `maibot-plugin-sdk`（版本 ≥ 2.0.0）。
2. 将本仓库克隆或下载到 MaiBot 的 `plugins/` 目录下：

```bash
cd MaiBot/plugins
git clone https://github.com/Kinsely/maibot-reminder-plugin.git reminder-bot

⚙️ 配置说明
插件加载后，MaiBot 会自动在 plugins/reminder-bot/ 目录下生成 config.toml。你也可以通过 WebUI 的插件管理界面直接修改配置。

配置项
配置项	类型	默认值	说明
plugin.enabled	bool	true	是否启用插件
plugin.config_version	string	"1.0.0"	配置版本号，请勿手动修改
reminder.check_interval	int	60	后台检查提醒的间隔（秒），越小越精确但越耗资源
reminder.use_personality	bool	true	是否用人设语气发送提醒
reminder.personality_prompt	string	见下方	人格化提醒的提示词模板
reminder.max_reminders_per_user	int	20	每个用户最多可存储的提醒数量

人格化提示词模板
personality_prompt 支持以下变量：

{bot_name}：自动读取 bot_config.toml 中的 [bot].nickname

{personality}：自动读取 bot_config.toml 中的 [personality].personality

{reminder_content}：提醒的具体内容

默认模板：

text
你是{bot_name}。你的人设是：{personality}。现在请用人设中描述的语气和风格，自然地提醒用户一件事：{reminder_content}。不要用系统提示式的语气，要像平时聊天一样。

这是作者初次尝试编写一份插件，希望它是实用而有效的，只是一个初步的版本，也许有很多不足，后续有新的想法会持续更新，感谢下载。