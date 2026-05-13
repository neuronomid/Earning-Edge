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
            [
                InlineKeyboardButton(
                    text="🔔 Alert Mute Duration",
                    callback_data=SettingsCB(field="alert_mute_duration").pack(),
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
    action: str  # why, risk, save_note, bought, skipped
    rec_id: str


class AltRecCB(CallbackData, prefix="alt"):
    cursor_rec_id: str


class PosCB(CallbackData, prefix="pos"):
    action: str  # sold, holding, delete, adjust, mute_tp, mute_sl, okay_tp, okay_sl
    position_id: str


class ValCB(CallbackData, prefix="val"):
    action: str  # validate, history
    position_id: str


class ValApplyCB(CallbackData, prefix="vap"):
    action: str  # apply_target, apply_stop, apply_both
    validation_id: str


class PositionAdjustCB(CallbackData, prefix="padj"):
    action: str  # target, stop, both
    position_id: str


def recommendation_keyboard(
    rec_id: str,
    *,
    alternative_cursor_id: str | None = None,
    include_alternative: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔍 Why this?",
                callback_data=RecCB(action="why", rec_id=rec_id).pack(),
            ),
            InlineKeyboardButton(
                text="⚖️ Risk / Sizing",
                callback_data=RecCB(action="risk", rec_id=rec_id).pack(),
            ),
        ]
    ]
    action_row: list[InlineKeyboardButton] = []
    if include_alternative:
        action_row.append(
            InlineKeyboardButton(
                text="📈 Alternatives",
                callback_data=AltRecCB(cursor_rec_id=alternative_cursor_id or rec_id).pack(),
            )
        )
    action_row.append(
        InlineKeyboardButton(
            text="📘 Save Note",
            callback_data=RecCB(action="save_note", rec_id=rec_id).pack(),
        )
    )
    rows.append(action_row)
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ I bought it",
                callback_data=RecCB(action="bought", rec_id=rec_id).pack(),
            ),
            InlineKeyboardButton(
                text="❌ I skipped it",
                callback_data=RecCB(action="skipped", rec_id=rec_id).pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def position_alert_keyboard(
    position_id: str,
    alert_type: str | None = None,
) -> InlineKeyboardMarkup:
    if alert_type in ("tp", "sl"):
        # Price-level alert: show Sold, Mute, Okay buttons
        mute_action = f"mute_{alert_type}"
        okay_action = f"okay_{alert_type}"
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Sold",
                        callback_data=PosCB(action="sold", position_id=position_id).pack(),
                    ),
                    InlineKeyboardButton(
                        text="Mute",
                        callback_data=PosCB(action=mute_action, position_id=position_id).pack(),
                    ),
                    InlineKeyboardButton(
                        text="Okay",
                        callback_data=PosCB(action=okay_action, position_id=position_id).pack(),
                    ),
                ]
            ]
        )
    else:
        # Date-based alert: show original Sold and Still holding buttons
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Sold",
                        callback_data=PosCB(action="sold", position_id=position_id).pack(),
                    ),
                    InlineKeyboardButton(
                        text="Still holding",
                        callback_data=PosCB(action="holding", position_id=position_id).pack(),
                    ),
                ]
            ]
        )


def position_list_keyboard(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Validate now",
                    callback_data=ValCB(action="validate", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="Validation history",
                    callback_data=ValCB(action="history", position_id=position_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Adjust",
                    callback_data=PosCB(action="adjust", position_id=position_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔒 Close",
                    callback_data=PosCB(action="sold", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="🗑 Delete",
                    callback_data=PosCB(action="delete", position_id=position_id).pack(),
                ),
            ],
        ]
    )


def validation_result_keyboard(revalidation) -> InlineKeyboardMarkup | None:
    proposed = getattr(revalidation, "proposed_adjustment_json", None)
    if not isinstance(proposed, dict):
        return None

    has_target = proposed.get("target_option_price") is not None
    has_stop = proposed.get("stop_loss_option_price") is not None
    rows: list[list[InlineKeyboardButton]] = []
    validation_id = str(revalidation.id)
    if has_target and has_stop:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Apply TP and SL",
                    callback_data=ValApplyCB(
                        action="apply_both",
                        validation_id=validation_id,
                    ).pack(),
                )
            ]
        )
    else:
        row: list[InlineKeyboardButton] = []
        if has_target:
            row.append(
                InlineKeyboardButton(
                    text="Apply target",
                    callback_data=ValApplyCB(
                        action="apply_target",
                        validation_id=validation_id,
                    ).pack(),
                )
            )
        if has_stop:
            row.append(
                InlineKeyboardButton(
                    text="Apply stop",
                    callback_data=ValApplyCB(
                        action="apply_stop",
                        validation_id=validation_id,
                    ).pack(),
                )
            )
        if row:
            rows.append(row)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def position_adjust_keyboard(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Target Price",
                    callback_data=PositionAdjustCB(
                        action="target",
                        position_id=position_id,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🛑 Stop Loss",
                    callback_data=PositionAdjustCB(
                        action="stop",
                        position_id=position_id,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚪️ TP and SL",
                    callback_data=PositionAdjustCB(
                        action="both",
                        position_id=position_id,
                    ).pack(),
                )
            ],
        ]
    )
