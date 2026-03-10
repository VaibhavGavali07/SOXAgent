from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.llm.chat_client import build_chat_provider
from backend.storage.models import ConfigRecord


def get_llm_provider(db: Session):
    config = db.scalar(
        select(ConfigRecord)
        .where(ConfigRecord.config_type == "llm")
        .order_by(
            desc(ConfigRecord.name == "llm-default"),
            desc(ConfigRecord.updated_at),
            desc(ConfigRecord.id),
        )
    )
    config_data = dict(config.data) if config else {}
    return build_chat_provider(config_data)
