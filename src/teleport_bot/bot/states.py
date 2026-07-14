from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    answering = State()
