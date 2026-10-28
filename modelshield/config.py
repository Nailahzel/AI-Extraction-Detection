"""Explicit demo credentials and deployment settings."""

from dataclasses import dataclass, field
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parent.parent
DEMO_KEYS = {
    "normal-01": "Customer insights",
    "normal-02": "Review analytics",
    "batch-01": "Batch processor",
    "attacker-01": "Research client",
    "probe-01": "Evaluation client",
    "swarm-01": "Partner alpha",
    "swarm-02": "Partner beta",
    "swarm-03": "Partner gamma",
}


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("MODELSHIELD_DATA_DIR", ROOT / "data"))
    )
    demo: bool = field(
        default_factory=lambda: os.getenv("MODELSHIELD_DEMO", "1") == "1"
    )
    admin_token: str = field(
        default_factory=lambda: os.getenv("MODELSHIELD_ADMIN_TOKEN", "")
    )
    keys: dict[str, str] = field(
        default_factory=lambda: json.loads(os.getenv("MODELSHIELD_API_KEYS", "{}"))
    )

    def __post_init__(self):
        if not self.keys:
            if not self.demo:
                raise ValueError(
                    "Set MODELSHIELD_API_KEYS to a JSON object of secret keys and client names."
                )
            self.keys = DEMO_KEYS.copy()
        if not isinstance(self.keys, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and k and v
            for k, v in self.keys.items()
        ):
            raise ValueError(
                "MODELSHIELD_API_KEYS must map nonempty string secrets to client names."
            )
        if not self.demo and len(self.admin_token) < 32:
            raise ValueError(
                "Set a MODELSHIELD_ADMIN_TOKEN of at least 32 characters outside demo mode."
            )
