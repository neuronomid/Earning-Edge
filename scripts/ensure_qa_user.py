from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.qa_runtime import ensure_qa_user, get_qa_runtime_config


async def _main() -> None:
    settings = get_settings()
    runtime = get_qa_runtime_config(settings)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await ensure_qa_user(session, settings=settings)
        await session.commit()
    print(f"qa_user_id={user.id}")
    print(f"qa_user_chat_id={runtime.user_chat_id}")
    print(f"qa_account_size={runtime.account_size}")
    print(f"qa_risk_profile={runtime.risk_profile}")
    print(f"qa_timezone={runtime.timezone_label}/{runtime.timezone_iana}")
    print(f"qa_broker={runtime.broker}")
    print(f"qa_strategy_permission={runtime.strategy_permission}")
    print(f"qa_max_contracts={runtime.max_contracts}")


if __name__ == "__main__":
    asyncio.run(_main())
