from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    answering = State()


class AdminStates(StatesGroup):
    subscription_user_id = State()
    subscription_expires_at = State()
    link_user_id = State()
