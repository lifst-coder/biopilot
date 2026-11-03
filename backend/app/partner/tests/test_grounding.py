"""PAR-6: grounding validator edge cases (units, separators, Korean numerals, rounding)."""

from __future__ import annotations

import pytest

from app.partner.grounding import GroundingIndex, base_index, extract_numbers, free_numbers


@pytest.fixture
def index() -> GroundingIndex:
    idx = base_index()
    idx.add_value(61.97633940639864, "%")  # recovery mean
    idx.add_value(-27.09724818949708, "%p")  # delta
    idx.add_value(3.0)  # flagged injections
    idx.add_value(10.0)  # total injections
    idx.add_value(1234.5)
    idx.add_value(4.9596184748193704e-21)  # p-value
    idx.add_text("추출 시간 (min): #018 10 → #024 5")
    idx.add_free([70.0, 120.0])
    return idx


def ungrounded(index: GroundingIndex, text: str) -> list[str]:
    return index.ungrounded([text])


@pytest.mark.parametrize(
    "text",
    [
        "평균 회수율 62.0%",  # rounding to 1 decimal
        "평균 회수율 62%",  # rounding to integer
        "평균 회수율 61.98%",  # more decimals
        "변화 -27.1%p",  # percentage points with sign
        "27.1 퍼센트포인트 감소",  # spelled-out unit
        "27.1 pp 감소",
        "주입 3/10회",  # ratio of two evidence values
        "세 번 이탈",  # Korean numeral (3)
        "열 번 주입",  # Korean numeral (10)
        "1,234.5 면적",  # thousands separator
        "p = 4.96e-21",  # scientific notation
        "p = 4.96×10^-21",
        "허용 범위 70–120%",  # free numbers (criteria)
        "70,120 범위",  # comma list, both free
        "추출 10분 → 5분",  # numbers from evidence text
        "#024와 #018 비교, E3·P12 참조",  # identifiers are not quantities
        "가중 1/x2, R² 비교, 2×2 요인",  # name tokens
        "주입 S-03 (시료 R10-3), 2026-10-20 수행",  # injection ids and dates
        "PSA·C18·MgSO4 사용",  # chemical names
        "한 번 더 확인",  # 'one' idiom is not a quantity
        "p<0.05 기준",  # fixed statistical thresholds
    ],
)
def test_grounded_texts(index: GroundingIndex, text: str) -> None:
    assert ungrounded(index, text) == []


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("평균 회수율 62.1%", "62.1%"),  # outside rounding tolerance
        ("변화 -27.1%", "-27.1%"),  # %p value cited as %
        ("평균 회수율 62.0%p", "62.0%p"),  # % value cited as %p
        ("여섯 번 이탈", "여섯 번"),  # Korean numeral not in evidence
        ("2,345 면적", "2,345"),  # thousands-separated invented number
        ("p = 5.2e-21", "5.2e-21"),  # sci-notation mismatch
        ("회수율 73.3%로 하락", "73.3%"),
        ("주입 3/11회", "11"),
        # C5 regression: the stored change is −27.1 %p; a flipped explicit sign is ungrounded.
        ("회수율이 +27.1%p 증가했다", "+27.1%p"),
        ("변화 +27.1 퍼센트포인트", "+27.1 퍼센트포인트"),
        ("회수율 -62.0%", "-62.0%"),  # positive level cited with a minus sign
        ("p = -4.96e-21", "-4.96e-21"),
    ],
)
def test_ungrounded_texts(index: GroundingIndex, text: str, bad: str) -> None:
    assert bad in ungrounded(index, text)


def test_token_details() -> None:
    (tok,) = extract_numbers("-27.1%p")
    assert tok.value == 27.1 and tok.decimals == 1 and tok.unit == "%p"
    (tok,) = extract_numbers("1,234")
    assert tok.value == 1234 and tok.alternatives == (1.0, 234.0)
    (tok,) = extract_numbers("4.96e-21")
    assert tok.exponent == -21
    assert free_numbers("PSA 50 mg, −29.2") == {50.0, -29.2}  # sign kept as written
    assert [t.sign for t in extract_numbers("+27.1%p, −27.1%p, 27.1%p")] == [1, -1, 0]


def test_sign_is_part_of_the_comparison(index: GroundingIndex) -> None:
    """Regression (REVIEW C5): ``abs()`` let "+27.1%p 증가" pass for a −27.1 %p change."""
    assert ungrounded(index, "회수율 -27.1%p 변화") == []  # same sign
    assert ungrounded(index, "회수율 −27.1%p 변화") == []  # unicode minus
    assert ungrounded(index, "회수율 27.1%p 감소") == []  # unsigned magnitude
    assert ungrounded(index, "회수율 +27.1%p 증가") == ["+27.1%p"]
    assert ungrounded(index, "평균 회수율 +62.0%") == []  # explicit + on a positive value
    free = base_index()
    free.add_text("매트릭스 효과 −29.2%")
    assert free.ungrounded(["ME 29.2%", "ME -29.2%"]) == []
    assert free.ungrounded(["ME +29.2%"]) == ["+29.2%"]
    assert index.grounds(-27.09724818949708, "%p")
    assert not index.grounds(27.09724818949708, "%p")


def test_structured_value_grounding(index: GroundingIndex) -> None:
    assert index.grounds(3)
    assert index.grounds(61.97633940639864, "%")
    assert not index.grounds(61.98, "%")
    assert not index.grounds(7)
    index.add_value(None)
    index.add_value(float("nan"))
    index.add_text(None)
    assert not index.grounds(99)
