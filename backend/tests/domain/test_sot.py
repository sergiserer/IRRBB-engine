from pathlib import Path

from app.domain.sot import SOTConfig, load_sot_config

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "sot.yaml"


def test_load_sot_config_reads_threshold_pct():
    config = load_sot_config(CONFIG_PATH)
    assert config == SOTConfig(threshold_pct=0.15)
