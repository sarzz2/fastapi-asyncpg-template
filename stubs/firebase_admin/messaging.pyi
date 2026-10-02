from typing import Any

from firebase_admin import App

class Notification:
    title: str | None
    body: str | None
    image: str | None
    def __init__(self, title: str | None = ..., body: str | None = ..., image: str | None = ...) -> None: ...

class MulticastMessage:
    tokens: list[str]
    data: dict[str, str] | None
    notification: Notification | None
    def __init__(
        self,
        tokens: list[str],
        data: dict[str, str] | None = ...,
        notification: Notification | None = ...,
        android: Any = ...,
        webpush: Any = ...,
        apns: Any = ...,
        fcm_options: Any = ...,
    ) -> None: ...

class SendResponse:
    success: bool
    message_id: str | None
    exception: Exception | None

class BatchResponse:
    responses: list[SendResponse]
    success_count: int
    failure_count: int

def send_each_for_multicast(
    multicast_message: MulticastMessage,
    dry_run: bool = ...,
    app: App | None = ...,
) -> BatchResponse: ...
