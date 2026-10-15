"""通知渠道与投递的输入结构：不接受客户端指定租户、投递人或渠道凭据。"""

from pydantic import BaseModel, ConfigDict, Field


class NotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DispatchRequest(NotificationInput):
    """人工确认后的一次投递请求。

    默认不指定渠道则按 ``NOTIFICATION_ROUTES`` 路由；显式指定只影响本次请求，
    不会写回配置。
    """

    event: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    recipient_id: str | None = Field(default=None, max_length=36)
    dedup_key: str | None = Field(default=None, max_length=128)
    channels: list[str] | None = Field(default=None, max_length=5)
