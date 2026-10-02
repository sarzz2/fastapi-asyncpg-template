from typing import Any

from . import credentials as credentials
from . import messaging as messaging

class App:
    name: str

def get_app(name: str = ...) -> App: ...
def initialize_app(credential: Any = ..., options: dict[str, Any] | None = ..., name: str = ...) -> App: ...
