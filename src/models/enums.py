from enum import StrEnum


class PropertyCategory(StrEnum):
    DOM = "dom"
    MIESZKANIE = "mieszkanie"
    DZIALKA = "dzialka"


class OwnerType(StrEnum):
    ALL = "all"
    PRIVATE = "private"
    AGENCY = "agency"
    DEVELOPER = "developer"


class BuildingType(StrEnum):
    SZEREGOWIEC = "szeregowiec"
    BLIZNIAK = "bliźniak"
    WOLNOSTOJACY = "wolnostojący"
    INNY = "inny"


class SegmentSubtype(StrEnum):
    SKRAJNY = "skrajny/narożny"
    SRODKOWY = "środkowy"
    NIEOKRESLONY = "nieokreślony"


class RoadType(StrEnum):
    ASFALT = "asfalt"
    KOSTKA = "kostka"
    UTWARDZONA = "utwardzona"
    POLNA = "polna"
    NIEZNANA = "nieznana"


class MarketType(StrEnum):
    PIERWOTNY = "pierwotny"
    WTORNY = "wtórny"
    NIEOKRESLONY = "nieokreślony"


class FinishCondition(StrEnum):
    DEWELOPERSKI = "deweloperski"
    DO_WYKONCZENIA = "do wykończenia"
    SUROWY_ZAMKNIETY = "surowy zamknięty"
    SUROWY_OTWARTY = "surowy otwarty"
    DO_ZAMIESZKANIA = "do zamieszkania"
    DO_REMONTU = "do remontu"
    NIEOKRESLONY = "nieokreślony"


class SewerageType(StrEnum):
    MIEJSKA = "miejska"
    SZAMBO = "szambo"
    OCZYSZCZALNIA = "oczyszczalnia"
    NIEZNANA = "nieznana"


class HeatingType(StrEnum):
    POMPA_CIEPLA = "pompa ciepła"
    GAZOWE = "gazowe"
    PELLET_WEGIEL = "piec/paliwo stałe"
    ELEKTRYCZNE = "elektryczne"
    MIEJSKIE = "miejskie"
    NIEZNANE = "nieznane"


class QualificationStatus(StrEnum):
    QUALIFIED_WHITELIST = "QUALIFIED_WHITELIST"
    QUALIFIED = "QUALIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NEEDS_REVIEW_BORDERLINE = "NEEDS_REVIEW_BORDERLINE"
    REJECTED_STAGE1 = "REJECTED_STAGE1"
    REJECTED_STAGE2 = "REJECTED_STAGE2"


class UserCRMStatus(StrEnum):
    NEW = "NEW"
    FAVORITE = "FAVORITE"
    TO_VISIT = "TO_VISIT"
    REJECTED = "REJECTED"
