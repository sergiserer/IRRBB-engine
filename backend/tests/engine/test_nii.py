from datetime import date

from app.engine.nii import month_boundaries, month_index


def test_month_boundaries_returns_25_calendar_month_starts():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert len(boundaries) == 25
    assert boundaries[0] == date(2025, 1, 1)
    assert boundaries[1] == date(2025, 2, 1)
    assert boundaries[12] == date(2026, 1, 1)
    assert boundaries[24] == date(2027, 1, 1)


def test_month_index_buckets_dates_into_the_correct_month():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert month_index(date(2025, 1, 1), boundaries) == 0
    assert month_index(date(2025, 1, 31), boundaries) == 0
    assert month_index(date(2025, 2, 1), boundaries) == 1
    assert month_index(date(2026, 1, 1), boundaries) == 12
    assert month_index(date(2026, 12, 31), boundaries) == 23


def test_month_index_returns_none_outside_the_24_month_window():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert month_index(date(2024, 12, 31), boundaries) is None  # antes de as_of_date
    assert month_index(date(2027, 1, 1), boundaries) is None  # exactamente en el borde de 24m, excluido
    assert month_index(date(2030, 1, 1), boundaries) is None  # muy más allá
