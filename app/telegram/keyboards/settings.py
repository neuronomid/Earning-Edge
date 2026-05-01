"""Settings & API-keys inline keyboards (PRD §10.5)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class SettingsCB(CallbackData, prefix="set"):
    field: str  # account_size, risk_profile, timezone, broker, strategy, max_contracts


class ApiKeyCB(CallbackData, prefix="key"):
    action: str  # set_openrouter, set_alpaca, set_av, remove_alpaca, remove_av


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Account Size",
                    callback_data=SettingsCB(field="account_size").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎚 Risk Profile",
                    callback_data=SettingsCB(field="risk_profile").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌎 Timezone",
                    callback_data=SettingsCB(field="timezone").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏦 Broker",
                    callback_data=SettingsCB(field="broker").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📜 Strategy Permission",
                    callback_data=SettingsCB(field="strategy").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔢 Max Contracts",
                    callback_data=SettingsCB(field="max_contracts").pack(),
                )
            ],
        ]
    )


def api_keys_keyboard(
    *,
    has_alpaca: bool,
    has_alpha_vantage: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔑 OpenRouter API Key",
                callback_data=ApiKeyCB(action="set_openrouter").pack(),
            )
        ],
        [
            InlineKeyboardButton(
                text="🔑 Alpaca Key + Secret",
                callback_data=ApiKeyCB(action="set_alpaca").pack(),
            )
        ],
    ]
    if has_alpaca:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Remove Alpaca",
                    callback_data=ApiKeyCB(action="remove_alpaca").pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔑 Alpha Vantage API Key",
                callback_data=ApiKeyCB(action="set_av").pack(),
            )
        ]
    )
    if has_alpha_vantage:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Remove Alpha Vantage",
                    callback_data=ApiKeyCB(action="remove_av").pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- Recommendation inline buttons (PRD §10.3) ----------


class RecCB(CallbackData, prefix="rec"):
    action: str  # why, risk, alts, save_note, bought, skipped
    rec_id: str


def recommendation_keyboard(rec_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Why this?",
                    callback_data=RecCB(action="why", rec_id=rec_id).pack(),
                ),
                InlineKeyboardButton(
                    text="⚖️ Risk / Sizing",
                    callback_data=RecCB(action="risk", rec_id=rec_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📈 Alternatives",
                    callback_data=RecCB(action="alts", rec_id=rec_id).pack(),
                ),
                InlineKeyboardButton(
                    text="📘 Save Note",
                    callback_data=RecCB(action="save_note", rec_id=rec_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ I bought it",
                    callback_data=RecCB(action="bought", rec_id=rec_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ I skipped it",
                    callback_data=RecCB(action="skipped", rec_id=rec_id).pack(),
                ),
            ],
        ]
    )
