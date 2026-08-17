from pathlib import Path

from app.domain.nmd_decay import NmdDecayConfig, load_nmd_decay_config

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "nmd_decay.yaml"


def test_load_nmd_decay_config_reads_values():
    config = load_nmd_decay_config(CONFIG_PATH)
    assert config == NmdDecayConfig(core_fraction=0.50, core_max_life_years=5.0, decay_frequency_months=1)
