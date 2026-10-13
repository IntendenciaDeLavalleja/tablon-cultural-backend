import enum

class EventStatus(str, enum.Enum):
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"

    @property
    def label(self):
        return EVENT_STATUS_TRANSLATIONS.get(self.value, self.value)

class SubmissionStatus(str, enum.Enum):
    NEW = "NEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"

    @property
    def label(self):
        return SUBMISSION_STATUS_TRANSLATIONS.get(self.value, self.value)

class MessageStatus(str, enum.Enum):
    NEW = "NEW"
    REPLIED = "REPLIED"
    ARCHIVED = "ARCHIVED"

    @property
    def label(self):
        return MESSAGE_STATUS_TRANSLATIONS.get(self.value, self.value)

EVENT_STATUS_TRANSLATIONS = {
    "PUBLISHED": "Publicado",
    "ARCHIVED": "Archivado"
}

SUBMISSION_STATUS_TRANSLATIONS = {
    "NEW": "Nuevo",
    "APPROVED": "Aprobado",
    "REJECTED": "Rechazado",
    "ARCHIVED": "Archivado"
}

MESSAGE_STATUS_TRANSLATIONS = {
    "NEW": "Nuevo",
    "REPLIED": "Respondido",
    "ARCHIVED": "Archivado"
}
