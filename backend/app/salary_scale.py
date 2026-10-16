import re
from collections.abc import Iterable

# 2026 salary schedule supplied for Cathedra. SG 22 step 8 was corrected to
# PHP 90,295 from the supplied academic-rank monetary-equivalent table.
SALARY_STEPS: dict[int, tuple[int, ...]] = {
    1: (14634, 14730, 14849, 14968, 15089, 15211, 15333, 15456),
    2: (15522, 15636, 15752, 15869, 15986, 16103, 16223, 16342),
    3: (16486, 16610, 16732, 16856, 16982, 17106, 17234, 17360),
    4: (17506, 17636, 17767, 17898, 18031, 18163, 18298, 18433),
    5: (18581, 18720, 18858, 18998, 19137, 19280, 19423, 19565),
    6: (19716, 19862, 20009, 20158, 20307, 20456, 20609, 20761),
    7: (20914, 21069, 21224, 21382, 21539, 21699, 21859, 22022),
    8: (22423, 22627, 22832, 23038, 23246, 23456, 23668, 23883),
    9: (24329, 24523, 24720, 24917, 25117, 25318, 25521, 25725),
    10: (26917, 27131, 27347, 27565, 27786, 28007, 28230, 28456),
    11: (31705, 31820, 32109, 32401, 32697, 32998, 33302, 33611),
    12: (33947, 34069, 34357, 34648, 34943, 35242, 35544, 35850),
    13: (36125, 36283, 36599, 36919, 37244, 37572, 37904, 38241),
    14: (38764, 39141, 39523, 39910, 40300, 40696, 41097, 41503),
    15: (42178, 42594, 43015, 43442, 43874, 44310, 44753, 45202),
    16: (45694, 46152, 46615, 47084, 47559, 48040, 48528, 49020),
    17: (49562, 50066, 50576, 51092, 51614, 52144, 52678, 53221),
    18: (53818, 54371, 54933, 55499, 56075, 56657, 57246, 57842),
    19: (59153, 59966, 60793, 61632, 62486, 63353, 64236, 65132),
    20: (66052, 66970, 67904, 68853, 69818, 70772, 71727, 72671),
    21: (73303, 74337, 75388, 76456, 77542, 78645, 79692, 80831),
    22: (81796, 82963, 84151, 85356, 86582, 87746, 89011, 90295),
    23: (91306, 92622, 93962, 95330, 96823, 98341, 99883, 101318),
    24: (102603, 104209, 105841, 107500, 109185, 110898, 112533, 114301),
    25: (116643, 118469, 120326, 122212, 124131, 126079, 128061, 130073),
    26: (131807, 133870, 135968, 138100, 140268, 142469, 144707, 146983),
    27: (148940, 151273, 153644, 155906, 158353, 160235, 162752, 165310),
    28: (167129, 169752, 172418, 174797, 177545, 180339, 182660, 185537),
    29: (187531, 190482, 193480, 196528, 199624, 202005, 205191, 208430),
    30: (210718, 214038, 217207, 220425, 223691, 227224, 230595, 234240),
    31: (300961, 306691, 312532, 318182, 323938, 329989, 336092, 342310),
    32: (356237, 363257, 370418, 377359, 384805, 392400, 400150, 408055),
    33: (449157, 462329),
}

RANK_TO_GRADE = {
    "Instructor I": 12,
    "Instructor II": 13,
    "Instructor III": 14,
    "Assistant Professor I": 15,
    "Assistant Professor II": 16,
    "Assistant Professor III": 17,
    "Assistant Professor IV": 18,
    "Associate Professor I": 19,
    "Associate Professor II": 20,
    "Associate Professor III": 21,
    "Associate Professor IV": 22,
    "Associate Professor V": 23,
    "Professor I": 24,
    "Professor II": 25,
    "Professor III": 26,
    "Professor IV": 27,
    "Professor V": 28,
    "Professor VI": 29,
    "College / University Professor": 30,
}

_RANK_TO_GRADE_CASEFOLD = {rank.casefold(): grade for rank, grade in RANK_TO_GRADE.items()}
_GRADE_PATTERN = re.compile(r"(?:SG\s*)?(\d{1,2})", re.IGNORECASE)


def format_grade(grade_number: int) -> str:
    return f"SG {grade_number}"


def normalize_grade(value: str | None) -> str | None:
    match = _GRADE_PATTERN.fullmatch((value or "").strip())
    if match is None:
        return None
    grade_number = int(match.group(1))
    return format_grade(grade_number) if grade_number in SALARY_STEPS else None


def grade_for_rank(rank: str | None) -> str | None:
    grade_number = _RANK_TO_GRADE_CASEFOLD.get((rank or "").strip().casefold())
    return format_grade(grade_number) if grade_number else None


def salary_for(grade: str, step: int) -> int | None:
    normalized = normalize_grade(grade)
    if normalized is None:
        return None
    salaries = SALARY_STEPS[int(normalized.removeprefix("SG "))]
    return salaries[step - 1] if 1 <= step <= len(salaries) else None


def allowed_steps(grade: str) -> Iterable[int]:
    normalized = normalize_grade(grade)
    if normalized is None:
        return ()
    return range(1, len(SALARY_STEPS[int(normalized.removeprefix("SG "))]) + 1)


def salary_scale_payload() -> dict[str, object]:
    return {
        "grades": [
            {
                "salary_grade": format_grade(grade_number),
                "steps": [
                    {"step": step, "monthly_salary": monthly_salary}
                    for step, monthly_salary in enumerate(salaries, start=1)
                ],
            }
            for grade_number, salaries in SALARY_STEPS.items()
        ],
        "rank_mappings": [
            {"rank": rank, "salary_grade": format_grade(grade_number)}
            for rank, grade_number in RANK_TO_GRADE.items()
        ],
    }
