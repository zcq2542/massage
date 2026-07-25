from pathlib import Path
from jxgrab.config import load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"

def test_load_example_config():
    cfg = load_config(EXAMPLE)
    assert cfg.base_url == "http://www.jingxin-jk.com:825"
    assert len(cfg.profiles) == 2
    p = cfg.profiles[0]
    assert p.name == "张三"
    assert p.openid == "1"
    assert p.phone == "13800138000"
    assert p.doc_id == "22"
    assert p.slot_priorities == ["20:30", "21:00", "21:30"]
    assert p.book_date == "tomorrow"

def test_profile_id_is_stable_key():
    cfg = load_config(EXAMPLE)
    p = cfg.profiles[0]
    assert p.id == "22:1:13800138000"

def test_defaults_applied():
    cfg = load_config(EXAMPLE)
    assert cfg.timing.poll_concurrency == 2
    assert cfg.rotation.weekly_quota == 1
    assert cfg.safety.auto_cancel_extras is True

def test_webhooks_parsed():
    cfg = load_config(EXAMPLE)
    types = [w.type for w in cfg.webhooks]
    assert types == ["bark", "dingtalk", "serverchan"]
    assert cfg.webhooks[1].params["secret"] == "SECXXXXXXXX"
