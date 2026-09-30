from maibot_sdk import MaiBotPlugin, PluginConfigBase, Field, Tool, CONFIG_RELOAD_SCOPE_SELF
from maibot_sdk.types import ToolParameterInfo, ToolParamType
import asyncio
import json
import os
from datetime import datetime
from typing import Optional


# ========== 配置模型 ==========

class PluginSectionConfig(PluginConfigBase):
    """插件基础配置，必须包含 config_version。"""
    __ui_label__ = "插件"
    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class ReminderConfig(PluginConfigBase):
    """插件配置模型。Runner 会自动生成 config.toml。"""

    __ui_label__ = "提醒设置"

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)

    check_interval: int = Field(default=60, description="后台检查提醒的间隔（秒）")
    use_personality: bool = Field(default=True, description="是否用人设语气发送提醒")
    personality_prompt: str = Field(
        default="你是{bot_name}。你的人设是：{personality}。现在请用人设中描述的语气和风格，自然地提醒用户一件事：{reminder_content}。不要用系统提示式的语气，要像平时聊天一样。",
        description="人格化提醒的提示词模板，可用变量：{bot_name}、{personality}、{reminder_content}",
    )
    max_reminders_per_user: int = Field(default=20, description="每个用户最多可存储的提醒数量")


# ========== 数据存储 ==========

class ReminderStore:
    """提醒数据的持久化存储，用 JSON 文件保存。只负责读写，不含 Bot 逻辑。"""

    def __init__(self, data_dir: str):
        self.file_path = os.path.join(data_dir, "reminders.json")
        self.reminders = self._load()

    def _load(self) -> list:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return []
        return []

    def _save(self):
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.reminders, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.file_path)

    def add(self, stream_id: str, user_id: str, content: str, remind_at: str):
        self.reminders.append({
            "stream_id": stream_id,
            "user_id": user_id,
            "content": content,
            "remind_at": remind_at,
            "created_at": datetime.now().isoformat(),
        })
        self._save()

    def get_due(self) -> list:
        now = datetime.now()
        due = []
        for r in self.reminders:
            try:
                remind_time = datetime.fromisoformat(r["remind_at"])
                if remind_time <= now:
                    due.append(r)
            except (ValueError, KeyError):
                continue
        return due

    def remove(self, reminder: dict):
        self.reminders.remove(reminder)
        self._save()

    def count_by_user(self, user_id: str) -> int:
        return sum(1 for r in self.reminders if r.get("user_id") == user_id)


# ========== 插件主类 ==========

class ReminderPlugin(MaiBotPlugin):
    """智能提醒插件主类。"""
    capabilities = ["config.get_all", "llm.chat", "send.text"]
    config_model = ReminderConfig

    def __init__(self):
        super().__init__()
        self.store: Optional[ReminderStore] = None
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    # ---------- Tool：让 LLM 调用 ----------

    @Tool(
        "set_reminder",
        brief_description="当用户要求设置提醒、备忘、定时通知时调用此工具",
        detailed_description="""用于记录用户的提醒事项。参数说明：
        - content：string，必填。提醒的具体内容，比如"开会"、"吃药"、"交作业"。
        - remind_at：string，必填。ISO 8601 格式的提醒时间，例如 "2026-10-01T15:00:00"。
        - stream_id：string，必填。当前聊天流 ID，用于确定回复和发送提醒的目标。""",
        parameters=[
            ToolParameterInfo(
                name="content",
                param_type=ToolParamType.STRING,
                description="提醒的内容",
                required=True,
            ),
            ToolParameterInfo(
                name="remind_at",
                param_type=ToolParamType.STRING,
                description="提醒时间，ISO 8601 格式，如 2026-10-01T15:00:00",
                required=True,
            ),
            ToolParameterInfo(
                name="stream_id",
                param_type=ToolParamType.STRING,
                description="当前聊天流 ID",
                required=True,
            ),
        ],
    )
    async def handle_set_reminder(
        self, content: str, remind_at: str, stream_id: str, **kwargs
    ):
        """处理 LLM 调用，设置一条提醒。"""
        try:
            remind_time = datetime.fromisoformat(remind_at)
        except ValueError:
            return {"success": False, "message": "时间格式不正确，请使用 ISO 格式"}

        if remind_time <= datetime.now():
            return {"success": False, "message": "提醒时间必须在未来"}

        user_id = kwargs.get("user_id", "unknown")

        if self.store.count_by_user(user_id) >= self.config.max_reminders_per_user:
            return {
                "success": False,
                "message": f"提醒数量已达上限（{self.config.max_reminders_per_user}条），请先删除一些旧提醒",
            }

        self.store.add(stream_id, user_id, content, remind_at)

        time_str = remind_time.strftime("%m月%d日 %H:%M")
        return {
            "success": True,
            "message": f"已记录提醒：{time_str} — {content}",
        }

    # ---------- 后台循环 ----------

    async def _reminder_loop(self):
        """后台循环：定期检查是否有到期的提醒需要发送。"""
        while self._running:
            try:
                due_reminders = self.store.get_due()
                for reminder in due_reminders:
                    await self._fire_reminder(reminder)
                    self.store.remove(reminder)
            except Exception as e:
                self.ctx.logger.error("提醒循环出错: %s", e)

            await asyncio.sleep(self.config.check_interval)

    async def _fire_reminder(self, reminder: dict):
        """触发一条提醒：先尝试人格化包装，再发送。"""
        stream_id = reminder["stream_id"]
        content = reminder["content"]

        if self.config.use_personality:
            try:
                final_text = await self._personalize_reminder(content)
            except Exception:
                final_text = f"提醒时间到！{content}"
        else:
            final_text = f"提醒时间到！{content}"

        await self.ctx.send.text(final_text, stream_id)
        self.ctx.logger.info("已发送提醒: %s -> %s", content, stream_id)

    # ---------- 人格化 ----------

    async def _personalize_reminder(self, content: str) -> str:
        """用人设语气包装提醒内容，人格信息从 bot_config.toml 动态读取。"""

        try:
            all_config = await self.ctx.config.get_all()
        except Exception as e:
            self.ctx.logger.warning("读取全局配置失败，降级为默认提醒: %s", e)
            return f"提醒时间到！{content}"

        bot_section = all_config.get("bot", {})
        personality_section = all_config.get("personality", {})

        bot_name = bot_section.get("nickname", "麦麦")
        personality = personality_section.get("personality", "一个普通的聊天机器人")
        reply_style = personality_section.get("reply_style", "")

        prompt = self.config.personality_prompt.format(
            bot_name=bot_name,
            personality=personality,
            reminder_content=content,
        )

        if reply_style:
            prompt += f"\n\n你的说话风格：{reply_style}"

        try:
            result = await self.ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                task="reply",
            )
            if isinstance(result, dict):
                return result.get("content", str(result))
            return str(result)
        except Exception as e:
            self.ctx.logger.error("人格化 LLM 调用失败，降级为普通提醒: %s", e)
            return f"提醒时间到！{content}"

    # ---------- 生命周期 ----------

    async def on_load(self) -> None:
        data_dir = self.ctx.paths.data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.store = ReminderStore(data_dir)

        self._running = True
        self._loop_task = asyncio.create_task(self._reminder_loop())

        self.ctx.logger.info(
            "智能提醒插件已加载，当前有 %d 条待提醒",
            len(self.store.reminders),
        )

    async def on_unload(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self.ctx.logger.info("智能提醒插件已卸载")

    async def on_config_update(
        self, scope: str, config_data: dict, version: str
    ) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self.ctx.logger.info("提醒插件配置已更新: version=%s", version)


# ========== 工厂函数 ==========

def create_plugin():
    return ReminderPlugin()