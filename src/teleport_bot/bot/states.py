from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    answering = State()


class AdminStates(StatesGroup):
    subscription_user_id = State()
    subscription_expires_at = State()
    link_user_id = State()
    import_user_id = State()
    import_expires_at = State()
    import_comment = State()
    extend_user_id = State()
    extend_days = State()
    cancel_user_id = State()
    history_user_id = State()
    setting_key = State()
    setting_value = State()
