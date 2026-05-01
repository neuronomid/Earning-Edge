"""Onboarding FSM states (PRD §11.1)."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    account_size = State()
    risk_profile = State()
    timezone = State()
    broker = State()
    strategy_permission = State()
    openrouter_key = State()
    alpaca_key = State()
    alpaca_secret = State()
    alpha_vantage_key = State()
    confirm = State()


class SettingsEdit(StatesGroup):
    """States used when a user edits a single setting from the Settings menu."""

    account_size = State()
    risk_profile = State()
    timezone = State()
    broker = State()
    strategy_permission = State()
    max_contracts = State()
    openrouter_key = State()
    alpaca_key = State()
    alpaca_secret = State()
    alpha_vantage_key = State()
