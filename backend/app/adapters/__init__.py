from ..config import Config
from .base import Adapter


def make_adapter(cfg: Config) -> Adapter:
    if cfg.adapter == "mock":
        from .mock import MockAdapter
        return MockAdapter()
    if cfg.adapter == "wikimasters":
        from .wikimasters import WikiMastersAdapter
        return WikiMastersAdapter(cfg)
    raise ValueError(f"Adaptateur inconnu : {cfg.adapter}")
