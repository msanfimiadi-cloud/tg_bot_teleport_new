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


class PartnerStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AttributionSource(StrEnum):
    DEEP_LINK = "deep_link"
    MANUAL = "manual"


class EventType(StrEnum):
    USER_STARTED = "user_started"
    QUESTIONNAIRE_STARTED = "questionnaire_started"
    QUESTIONNAIRE_STEP_COMPLETED = "questionnaire_step_completed"
    QUESTIONNAIRE_COMPLETED = "questionnaire_completed"
    QUESTIONNAIRE_RESTARTED = "questionnaire_restarted"
    PAYMENT_STAGE_REACHED = "payment_stage_reached"
    ADMIN_NOTIFICATION_FAILED = "admin_notification_failed"
    PAYMENT_CREATED = "payment_created"
    PAYMENT_REUSED = "payment_reused"
    PAYMENT_STATUS_CHECKED = "payment_status_checked"
    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_CANCELED = "payment_canceled"
    PAYMENT_VALIDATION_FAILED = "payment_validation_failed"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    SUBSCRIPTION_EXTENDED = "subscription_extended"
    PAYMENT_METHOD_SAVED = "payment_method_saved"
    INVITE_LINK_CREATED = "invite_link_created"
    ACCESS_ALREADY_PRESENT = "access_already_present"
    ACCESS_DELIVERY_FAILED = "access_delivery_failed"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    SUBSCRIPTION_REMINDER_SENT = "subscription_reminder_sent"
    SUBSCRIPTION_MIGRATED = "subscription_migrated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_EXTENDED_MANUAL = "subscription_extended_manual"
    SETTINGS_CHANGED = "settings_changed"
    QUESTIONNAIRE_PUBLICATION_FAILED = "questionnaire_publication_failed"
    PUBLIC_WELCOME_SENT = "public_welcome_sent"
    PUBLIC_WELCOME_FAILED = "public_welcome_failed"
    PARTNER_CREATED = "partner_created"
    PARTNER_ACTIVATED = "partner_activated"
    PARTNER_DEACTIVATED = "partner_deactivated"
    REFERRAL_ATTRIBUTED = "referral_attributed"
    REFERRAL_ATTRIBUTION_SKIPPED = "referral_attribution_skipped"
    REFERRAL_QUESTIONNAIRE_COMPLETED = "referral_questionnaire_completed"
    REFERRAL_PAYMENT_LINK_CREATED = "referral_payment_link_created"
    REFERRAL_FIRST_PAYMENT_SUCCEEDED = "referral_first_payment_succeeded"
    REFERRAL_MANUALLY_ASSIGNED = "referral_manually_assigned"
    REFERRAL_MANUALLY_REASSIGNED = "referral_manually_reassigned"


class SubscriptionStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    EXPIRED = "expired"
    MANUAL = "manual"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ActivationSource(StrEnum):
    MANUAL = "manual"
    YOOKASSA = "yookassa"
    MIGRATION = "migration"


class AdminAction(StrEnum):
    QUESTIONNAIRE_VIEWED = "questionnaire_viewed"
    MANUAL_SUBSCRIPTION_ACTIVATED = "manual_subscription_activated"
    MANUAL_LINK_SENT = "manual_link_sent"
    TELEGRAM_API_ERROR = "telegram_api_error"
    ACCESS_DENIED = "access_denied"
    SUBSCRIPTION_MIGRATED = "subscription_migrated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_EXTENDED_MANUAL = "subscription_extended_manual"
    SETTINGS_CHANGED = "settings_changed"
    PARTNER_CREATED = "partner_created"
    PARTNER_ACTIVATED = "partner_activated"
    PARTNER_DEACTIVATED = "partner_deactivated"
    REFERRAL_MANUALLY_ASSIGNED = "referral_manually_assigned"
    REFERRAL_MANUALLY_REASSIGNED = "referral_manually_reassigned"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    WAITING_FOR_CAPTURE = "waiting_for_capture"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FAILED = "failed"


class PaymentMethodStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    UNAVAILABLE = "unavailable"
