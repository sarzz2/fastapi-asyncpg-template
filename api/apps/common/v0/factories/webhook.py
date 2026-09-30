from api.apps.common.v0.adapters.base import BaseWebhookAdapter
from api.apps.common.v0.adapters.generic import GenericWebhookAdapter


class WebhookAdapterFactory:
    """
    Factory responsible for instantiating and retrieving vendor webhook adapters.
    """

    _registry: dict[str, type[BaseWebhookAdapter]] = {
        "generic": GenericWebhookAdapter,
    }

    @classmethod
    def get_adapter(cls, source: str) -> BaseWebhookAdapter:
        """
        Retrieve an instance of the adapter corresponding to the source.
        Falls back to GenericWebhookAdapter if the source is not recognized.

        Args:
            source (str): The vendor name / source.

        Returns:
            BaseWebhookAdapter: Instantiated adapter for the given source.
        """
        adapter_cls = cls._registry.get(source.lower(), GenericWebhookAdapter)
        return adapter_cls()
