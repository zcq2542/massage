# 按摩预约抢号程序 — 设计文档

- 日期：2026-07-25
- 目标站点：`http://www.jingxin-jk.com:825/#/schedule/22`
- 触发时间：每周一、周三 20:00（服务器时间）
- 运行环境：Linux 云服务器，cron 触发
- 语言：Python（异步 httpx）

## 1. 背景与目标

每周一、三 20:00 准点放号，热门时段秒空。需要一个定时程序在放号瞬间自动抢到指定优先级的时段，填写用户信息并提交。

**目标**：在放号那一刻以最小延迟提交预约，按用户给定的优先级列表选中第一个可用时段，并通过 webhook 通知结果。

**非目标**：不做多账号批量黄牛行为；仅服务于配置文件中登记的少数固定用户。

## 2. 站点机制（已逆向确认）

站点是 Vue 单页应用（`insure-register`），API 与页面同源：`http://www.jingxin-jk.com:825`。所有接口经同一个 axios 封装（`baseURL = location.origin`）。

### 2.1 相关接口

| 接口 | 方法 | 参数位置 | 作用 |
|---|---|---|---|
| `/InSurHome/GetServerTime` | GET | query | 返回服务器时间，用于对时 |
| `/InSurHome/getTimeConfig` | GET | query | 放号时间窗等配置（`setting_time`） |
| `/InSurHome/GetSchedule` | GET | query | 拉某天可预约时段列表，**只返回还有余位的时段** |
| `/InSurHome/SaveRecord` | POST | **query**（注意：JS 用 `params`，非 body） | 提交预约 |
| `/InSurHome/getUserInfo` | GET | query | 可选回填用户信息（不依赖） |
| `/InSurHome/cancelRecord` | POST | query | 取消预约（安全网用） |
| `/InSurHome/gethistory` | GET | query | 查询本人预约记录（误抢检测用） |

> 注意：`SaveRecord` 虽为 POST，但参数走 query string。请求需带浏览器风格 `User-Agent`、`Referer: http://www.jingxin-jk.com:825/`、`Origin` 头。

### 2.2 参数对象 `orderListQuery`

查询和提交共用：

```
doc_id        # = URL 中的 22（医生/项目 ID）
openid        # 默认 "1"，无需登录态
day           # 日期，如 2026-07-27
daytime       # 日期时间，如 "2026-07-27 00:00:00"
name          # 用户姓名
phone         # 手机号（正则 ^1[3456789]\d{9}$）
record_number # 预约人数（默认 1）—— 不是身份证号
sch_id        # 选中的时段 ID（来自 GetSchedule 返回）
```

### 2.3 GetSchedule 响应

返回数组，每个时段元素至少含：
- `sch_id`：时段 ID（提交时用）
- `work_begin` / `work_end`：时段起止时间（如 "20:30" / "21:00"）
- `work_remark`：备注/地址

空数组表示"医生未出诊"或"未放号"。

### 2.4 SaveRecord 返回码

| code | 含义 | 处理 |
|---|---|---|
| 正码（标定确认确切值） | 成功 | 置 `won`，停止 |
| `-1` | 预约间隔限制（多半今日已约过） | 通知并结束 |
| `-2` | 该时段已被预约（竞争点） | 立刻回退下一优先时段 |
| `-3` | 手机号格式错 | 配置错误，通知并中止该 profile |
| `-4` / 其他 | 未知 | 记录完整响应，按失败处理（标定后明确） |

### 2.5 放号机制

页面 `formatter` 根据 `setting_time` 配置 + 服务器时间判断哪天"可选"。20:00 前对目标日调 `GetSchedule` 返回空；20:00 放号后返回时段列表。`GetServerTime` 用于把页面行为与服务器时钟对齐——脚本同样依赖它做精确对时。

## 3. 抢号策略：C 混合

在 20:00:00 那一刻同时做两件事：

1. **高频并发轮询 `GetSchedule`**：T-1s 起，8 路并发，每 ~50ms 一批。第一个返回时段的响应立即进入发射。
2. **即时流水线发射**：解析响应 → `slots.rank_by_priority()` 排序 → 立即对最高优先时段 `SaveRecord`，不等结果继续处理后续响应。
3. **（标定后可选）T=0 盲打**：若标定确认 `sch_id` 跨周稳定，在 T=0 直接用缓存 sch_id 发射 SaveRecord，省一次 RTT。**标定确认前不开启**——此时 C 退化为"高频并发轮询 + 即时流水线发射"，已足够快。

**防重复预约**（C 的安全核心）：

- `fired` 集合：同一 `sch_id` 只发一次 SaveRecord。
- `won` 标志：任一成功立即置位，取消所有在飞请求，不再发新的。
- 兜底：成功后查 `gethistory`，若今日该 profile 预约数 > `count`，用 `cancelRecord` 撤销多余预约（保留最早一个）。
- 残余风险（两发同时成功）由站点 `-1` 间隔限制 + 兜底撤销双重覆盖。

## 4. 模块划分

每个模块单一职责，可独立测试。

### 4.1 `config.yaml` + `config.py`
配置加载与校验。

```yaml
base_url: http://www.jingxin-jk.com:825
# 通知渠道：列表，可配 0~N 个；notify 会向所有配置的渠道都推送。
# bark / dingtalk / serverchan 三种适配器全部实现，按需在列表里列你想要的；
# 想只用一种就只列一个，想多端同时收到就列多个。
webhooks:
  - type: bark              # Bark（iOS 推送）
    url: https://api.day.app/XXXXXXXX    # 完整 url，含设备 token
    # 可选：group / icon / sound / level
  - type: dingtalk          # 钉钉群机器人
    webhook: https://oapi.dingtalk.com/robot/send?access_token=XXXXXXXX
    secret: SECXXXXXXXX      # 可选；启用加签时填，与 access_token 配套
  - type: serverchan        # Server酱（微信推送）
    sendkey: SCTXXXXXXXX
    # 可选：uid（Turbo 多通道时区分）
timing:
  start_lead_seconds: 60      # cron 提前量；脚本内再精确等到 T-1s
  pre_poll_seconds: 1         # T-1s 开始轮询
  poll_interval_ms: 50
  poll_concurrency: 8
  fire_concurrency: 3
  total_timeout_s: 30
safety:
  dedup: true
  auto_cancel_extras: true
  max_records_per_day: 1
profiles:
  - name: 张三
    phone: "13800138000"
    count: 1
    doc_id: "22"
    slot_priorities: ["20:30", "21:00", "21:30"]
  - name: 李四
    phone: "13900139000"
    count: 1
    doc_id: "22"
    slot_priorities: ["20:30"]
```

### 4.2 `client.py`
基于 `httpx.AsyncClient` 的薄 HTTP 层。方法：`get_server_time` / `get_time_config` / `get_schedule(q)` / `save_record(q)` / `get_user_info(q)` / `cancel_record(q)` / `get_history(q)`。统一带浏览器 UA、Referer、Origin 头；超时短（单请求 2-3s）；连接池复用。

### 4.3 `clocksync.py`
- 多次采样 `GetServerTime`（如 5 次），记录发送/接收时刻，估算偏移 `offset = server_time - (sent+recv)/2`，取中位。
- 提供 `server_now()` 与 `sleep_until(server_target)`：最后 100ms 用忙等保证精度。

### 4.4 `slots.py`
- `parse(raw) -> list[Slot]`：规范化时段 JSON。
- `rank_by_priority(slots, priorities) -> list[Slot]`：按 `work_begin` 匹配优先级字符串，命中的按优先级排前，未命中的按时间升序追加（可配置是否兜底抢任意）。

### 4.5 `grabber.py`
抢号引擎。`async run(profile) -> GrabResult`：编排 4.1–4.4，实现策略 C（并发轮询 + 流水线发射 + dedup + won + -2 回退）。返回 `{success, slot, code, attempts, duration_ms}`。

### 4.6 `notify.py`
通知层。三种适配器全部实现，按注册表（registry）模式组织，配置里列哪种就推哪种。

- `notify(title, body, level)`：遍历 `config.webhooks`，向每个渠道并发推送；单渠道失败重试 2 次、不影响其他渠道。
- **Bark 适配器**：POST `{url}` JSON `{title, body, group, level}`（level 由结果映射，如成功→active、失败→timeSensitive）。
- **DingTalk 适配器**：POST `{webhook}` JSON `{msgtype:"text", text:{content: title+"\n"+body}}`；若配了 `secret`，按钉钉规则计算加签（`timestamp = 毫秒时间戳`，`sign = base64(HMAC-SHA256(secret, timestamp+"\n"+secret))`，URL 编码后追加 `&timestamp=&sign=`）。
- **ServerChan 适配器**：POST `https://sctapi.ftqq.com/{sendkey}.send`，body `title` / `desp`（支持 Markdown）。
- 统一抽象：`Webhook` 基类 + `send(title, body, level)` 方法，新增渠道（如企业微信）只需加一个子类注册。

### 4.7 `safety.py`
`reconcile(profile, expected_count)`：查 `gethistory`，若今日预约数超预期，对多余的调 `cancelRecord`（保留最早）。返回操作记录供通知。

### 4.8 `calibrate.py`
一次性只读标定工具（见第 6 节）。

### 4.9 `main.py`
入口：解析 `--target`/`--dry-run`/`--calibrate` → 加载配置 → 校时 → 精确等到放号前 → 逐 profile（或并发）跑 grabber → safety 兜底 → notify → 退出码反映结果。

## 5. 数据流

```
cron(周一/三 19:59) → main.py
  → clocksync.calibrate()              # 对齐服务器时钟
  → sleep_until(T - pre_poll_seconds)  # 精确等到 19:59:59
  → for profile in targets:
       grabber.run(profile)
         ├─ asyncio.gather(*[poll_get_schedule()])   # 8 路并发轮询
         ├─ on first slots → slots.rank_by_priority
         ├─ pipeline fire SaveRecord (fired-set, won-flag)
         │     └─ on code -2 → next priority slot
         └─ won or timeout
       safety.reconcile(profile, count)              # 撤多余
       notify(result)
```

## 6. 标定步骤（calibrate.py，上线前必跑一次）

真实 8PM 手动执行 `python calibrate.py --doc-id 22`，**只读不改**，捕获并打印：

- 成功 code 的确切值与响应体
- `-4` 等未知码的确切含义
- 时段 JSON 确切字段——**确认是否存在"余位数字"字段**（若有，可只抢真正有余位的时段，进一步提速避让）
- 20:00 前后 `GetSchedule` 返回变化（验证放号假设）
- `sch_id` 跨周稳定性（决定盲打开关能否开启）

标定产出写入 `docs/calibration-YYYY-MM-DD.md`，并据此回填本设计的未知项。

## 7. 调度

云服务器 crontab：

```
59 19 * * 1,3  /opt/jxgrab/venv/bin/python /opt/jxgrab/main.py --target all >> /var/log/jxgrab.log 2>&1
```

19:59 启动 → 校时（约耗数秒）→ 精确等到 19:59:59（服务器时间）开始轮询。`--target all` 跑全部 profile，或指定单 profile。

## 8. 错误处理

- **网络异常 / 超时**：单请求 2-3s 超时；轮询窗口内重试；窗口结束仍无果则通知。
- **`-2`**：回退下一优先时段。
- **`-3`**：配置错误 → 通知并中止该 profile（不中止其他 profile）。
- **`-1`**：多半今日已约 → 通知提示。
- **未知码**：记录完整响应体 → 通知 → 按失败处理。
- **超时无时段**：通知"未放号/放号时间判断有误"，提示人工检查。
- **时钟漂移**：每次运行重新校时；不缓存偏移。

## 9. 测试策略

- **单测**：`slots.rank_by_priority`（含优先级命中/未命中/空列表）、`clocksync` 偏移计算（mock 采样）、各 webhook 格式化、返回码分支解析、dedup/won 逻辑。
- **Mock HTTP**：录制/回放 fixture（`pytest` + `respx` 或自建 record/replay）。
- **`--dry-run`**：只调 `GetServerTime`/`GetSchedule`（只读），不调 `SaveRecord`，平时验证不误抢。
- **集成测试**：本地起一个 mock 服务器，可配置"到点放号 + 控制余位 + 模拟竞争"，验证整条抢号链路与 -2 回退。
- **安全网测试**：模拟"误抢 2 个"，验证 `safety.reconcile` 正确撤销多余。

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 站点改版导致接口/字段变化 | 标定脚本可重复运行；`client.py` 集中一层易于修改 |
| sch_id 跨周不稳定，盲打失效 | 默认不开盲打；标定确认后再启用 |
| 重复预约 | dedup + won + `cancelRecord` 兜底三层防护 |
| 时钟不准错过放号 | 每次运行 `GetServerTime` 实时校时 + 忙等 |
| 被站点风控/限流 | 请求带正常浏览器头；轮询并发与频率可调；bounded |
| 放号时间临时调整 | `getTimeConfig` 可读取配置；超时无果及时通知人工 |

## 11. 待标定确认的未知项

- [ ] 成功 code 的确切值
- [ ] `-4` 码含义
- [ ] 时段 JSON 是否含"余位数字"字段
- [ ] `sch_id` 跨周是否稳定（决定盲打开关）
- [ ] 20:00 前对目标日 `GetSchedule` 是否返回空（验证放号边界）
