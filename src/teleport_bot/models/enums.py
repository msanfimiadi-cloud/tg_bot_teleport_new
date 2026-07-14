from enum import StrEnum


class QuestionnaireStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class OnboardingStatus(StrEnum):
    NEW = "new"
    INFO_STARTED = "info_started"
    QUESTIONNAIRE = "questionnaire"
    QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
    PAYMENT_STAGE = "payment_stage"


class FunnelStatus(StrEnum):
    ONBOARDING = "onboarding"
    QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
    PAYMENT_STAGE_REACHED = "payment_stage_reached"


class EventType(StrEnum):
    USER_STARTED = "user_started"
    QUESTIONNAIRE_STARTED = "questionnaire_started"
    QUESTIONNAIRE_STEP_COMPLETED = "questionnaire_step_completed"
    QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
    QUESTIONNAIRE_RESTARTED = "questionnaire_restarted"
    PAYMENT_STAGE_REACHED = "payment_stage_reached"
    ADMIN_NOTIFICATION_FAILED = "admin_notification_failed"
