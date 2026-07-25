# jxgrab — 按摩预约抢号

每周一、三 20:00 自动抢 jingxin 预约。

## 安装
```bash
git clone <repo> /opt/jxgrab && cd /opt/jxgrab
python3 -m venv venv && . venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml   # 填真实信息（gitignore，不入库）
```

## 标定（上线前必跑一次）
在真实的周一/三 19:55–20:05 之间运行，**只读，不会预约**：
```bash
python -m jxgrab.calibrate --config config.yaml
```
确认报告中的 `server_time` 解析、`slot_fields`、`schedule_count` 与设计一致；结果记入 `docs/calibration-YYYY-MM-DD.md`。

## 试运行（只读，不抢号）
```bash
python -m jxgrab.calibrate --config config.yaml
```

## 手动抢一次（跳过 cron）
```bash
python -m jxgrab --config config.yaml --target 张三
```

## 定时
```bash
crontab deploy/jxgrab.cron
```
确保服务器时区正确（`timedatectl`）。每周一、三 20:00 自动抢。

## 测试
```bash
pytest -v
```
