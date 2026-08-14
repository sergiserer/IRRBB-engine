from datetime import date, timedelta
from pathlib import Path

import pytest

from app.domain.time_buckets import bucket_for, load_time_buckets

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "time_buckets.yaml"
AS_OF = date(2026, 8, 14)


def _buckets():
    return load_time_buckets(CONFIG_PATH)


def test_load_time_buckets_reads_all_19():
    buckets = _buckets()
    assert len(buckets) == 19
    assert buckets[0].name == "overnight"
    assert buckets[0].lower_days == 0
    assert buckets[0].upper_days == 1
    assert buckets[-1].name == "over_20y"
    assert buckets[-1].upper_days is None


def test_bucket_for_day_zero_is_overnight():
    buckets = _buckets()
    assert bucket_for(AS_OF, AS_OF, buckets) == "overnight"


def test_bucket_for_day_one_is_1d_1m():
    buckets = _buckets()
    assert bucket_for(AS_OF + timedelta(days=1), AS_OF, buckets) == "1d_1m"


def test_bucket_for_day_29_vs_day_30_boundary():
    buckets = _buckets()
    assert bucket_for(AS_OF + timedelta(days=29), AS_OF, buckets) == "1d_1m"
    assert bucket_for(AS_OF + timedelta(days=30), AS_OF, buckets) == "1m_3m"


def test_bucket_for_day_7299_vs_7300_boundary():
    buckets = _buckets()
    assert bucket_for(AS_OF + timedelta(days=7299), AS_OF, buckets) == "15y_20y"
    assert bucket_for(AS_OF + timedelta(days=7300), AS_OF, buckets) == "over_20y"


def test_bucket_for_far_future_is_over_20y():
    buckets = _buckets()
    assert bucket_for(AS_OF + timedelta(days=20000), AS_OF, buckets) == "over_20y"


def test_bucket_for_negative_horizon_raises():
    buckets = _buckets()
    with pytest.raises(ValueError):
        bucket_for(AS_OF - timedelta(days=1), AS_OF, buckets)
