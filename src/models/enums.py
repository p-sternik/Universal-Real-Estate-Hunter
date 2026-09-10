from enum import Enum


class PropertyCategory(str, Enum):
    DOM = "dom"
    MIESZKANIE = "mieszkanie"
    DZIALKA = "dzialka"


class OwnerType(str, Enum):
    ALL = "all"
    PRIVATE = "private"
    AGENCY = "agency"
    DEVELOPER = "developer"


class BuildingType(str, Enum):
    SZEREGOWIEC = "szeregowiec"
    BLIZNIAK = "bliźniak"
    WOLNOSTOJACY = "wolnostojący"
    INNY = "inny"


class SegmentSubtype(str, Enum):
    SKRAJNY = "skrajny/narożny"
    SRODKOWY = "środkowy"
    NIEOKRESLONY = "nieokreślony"


class RoadType(str, Enum):
    ASFALT = "asfalt"
    KOSTKA = "kostka"
    UTWARDZONA = "utwardzona"
    POLNA = "polna"
    NIEZNANA = "nieznana"


class MarketType(str, Enum):
    PIERWOTNY = "pierwotny"
    WTORNY = "wtórny"
    NIEOKRESLONY = "nieokreślony"


class FinishCondition(str, Enum):
    DEWELOPERSKI = "deweloperski"
    DO_WYKONCZENIA = "do wykończenia"
    SUROWY_ZAMKNIETY = "surowy zamknięty"
    SUROWY_OTWARTY = "surowy otwarty"
    DO_ZAMIESZKANIA = "do zamieszkania"
    DO_REMONTU = "do remontu"
    NIEOKRESLONY = "nieokreślony"


class SewerageType(str, Enum):
    MIEJSKA = "miejska"
    SZAMBO = "szambo"
    OCZYSZCZALNIA = "oczyszczalnia"
    NIEZNANA = "nieznana"


class HeatingType(str, Enum):
    POMPA_CIEPLA = "pompa ciepła"
    GAZOWE = "gazowe"
    PELLET_WEGIEL = "piec/paliwo stałe"
    ELEKTRYCZNE = "elektryczne"
    MIEJSKIE = "miejskie"
    NIEZNANE = "nieznane"



class QualificationStatus(str, Enum):
    QUALIFIED_WHITELIST = "QUALIFIED_WHITELIST"
    QUALIFIED = "QUALIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED_STAGE1 = "REJECTED_STAGE1"
    REJECTED_STAGE2 = "REJECTED_STAGE2"


class UserCRMStatus(str, Enum):
    NEW = "NEW"
    FAVORITE = "FAVORITE"
    TO_VISIT = "TO_VISIT"
    REJECTED = "REJECTED"

