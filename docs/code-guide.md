# jxgrab 代码说明与运行手册

> 代码层面已完成（11 模块，44/44 测试通过，三道评审干净）。本文档讲：代码怎么读、运行时发生了什么、**实际跑起来可能踩的坑 + 怎么排查/修改**。

---

## 1. 核心思路（先建立心智模型）

抢号程序没驱动浏览器，而是**直接调用站点后端 API**。原因：浏览器要加载渲染（几百毫秒到秒级），直接发 HTTP 请求是毫秒级——抢号这种"谁快谁赢"的场景，差几百毫秒就没了。

整条链路的本质是：

```
准点(20:00:00) → 拉时段(GetSchedule) → 选时段(按优先级) → 提交(SaveRecord) → 通知(webhook)
```

难点在两处：
- **准点**：你的服务器时钟和站点服务器时钟有偏差 → 用 `GetServerTime` 接口对时。
- **选时段**：放号前接口返回空，放号后才有数据 → 高频轮询直到非空。

---

## 2. 运行时时间线（一次抢号实际发生了什么）

cron 在 **19:59** 启动 `main.py`（留 ~60 秒余量）：

| 时刻（服务器时间） | 干什么 | 对应代码 |
|---|---|---|
| 19:59:0x | 加载 config，`rotation.pick_profile` 选今天该用哪个 profile | `main.py:run_grab` |
| 19:59:1x | `clocksync.calibrate`：调 5 次 `GetServerTime`，算出本地时钟↔站点时钟的偏移（取中位数） | `clocksync.py` |
| 19:59:1x~59 | 算出 `fire_at = 今天 20:00:00`（用 `timing.release_time`） | `main.py:_today_at` |
| 19:59:59 | `sleep_until(fire_at - 1s)`：粗睡到 19:59:59，最后 50ms 忙等精确卡点 | `clocksync.py:sleep_until` |
| **20:00:00** | 开始轮询：2 路并发每 50ms 一批 `GetSchedule`，直到返回非空 | `grabber.py:_first_nonempty_schedule` |
| 20:00:0x | 拿到时段 → 按优先级排序 → 对最高优先发 `SaveRecord` | `grabber.py:run` |
| 若 `-2`（被抢） | 立刻回退下一个优先时段再发 | `grabber.py:run` 循环 |
| 成功 | `rotation.mark_booked`（记录本周已用）+ `safety.reconcile`（查历史，删多余预约） | `main.py:run_grab` |
| 最后 | 拼 title/body，`notify_all` 推送 bark/钉钉/Server酱 | `main.py:_notify` |

**防重复预约的关键**：发射阶段是**顺序的**（await 一个再发下一个），不是并发。所以一次运行最多只可能抢到一个时段——从根上避免了重复预约。`safety.reconcile` 只是兜底（处理极罕见的站点端竞态或历史残留）。

---

## 3. 代码结构（每个文件干什么）

```
jxgrab/
├── config.py      配置：dataclass + YAML 加载
├── client.py      HTTP 层：7 个站点接口（只这一层碰网络）
├── clocksync.py   对时 + 精确 sleep_until
├── slots.py       时段解析 + 按优先级排序
├── rotation.py    profile 轮换 + 每周额度（state.json）
├── notify.py      webhook：Bark/DingTalk/ServerChan
├── grabber.py     抢号引擎（核心）
├── safety.py      误抢兜底：删多余预约
├── calibrate.py   只读标定工具（上线前必跑）
└── main.py        入口：把上面所有拼起来
```

**怎么读代码**：建议顺序 `config → client → slots → grabber → main`，这是主链路；`clocksync / rotation / notify / safety` 是辅助，可后看。

### 关键契约（改代码前必知）

- **`SaveRecord` 是 POST 但参数走 query string**（不是 body）——站点 JS 就这么写的，`client.py:save_record` 用 `params=`。
- **成功判定 = `code > "0"`（字符串比较）**，镜像站点 JS 的 `t.code>"0"`。错误码 `-1/-2/-3/-4` 都 < "0"，自动排除。见 `grabber.py:is_success_code`。
- **`day`/`daytime` 格式都是 `YYYY-MM-DD`**（从 JS 的 `formatDate2` 逆向确认）。
- **无需登录**：`openid` 默认 `"1"` 即可；但多 profile 要各自不同（见问题 D）。

---

## 4. 配置文件详解（`config.yaml`，从 `config.example.yaml` 复制）

```yaml
base_url: http://www.jingxin-jk.com:825
timing:
  release_time: "20:00"     # 放号时刻（服务器本地时间）。改这里调整准点
  pre_poll_seconds: 1.0      # 提前几秒开始轮询
  poll_interval_ms: 50       # 轮询间隔
  poll_concurrency: 2        # 并发轮询数（2 是为避免给站点太大压力；想要更激进可调大）
  total_timeout_s: 30.0      # 总超时：30 秒内没轮到时段就放弃
rotation:
  weekly_quota: 1            # 每个员工每周最多几次（站点业务规则）
  state_file: state.json     # 轮换状态文件
safety:
  auto_cancel_extras: true   # 自动删除多余预约（见问题 C 的风险）
webhooks: [...]              # 通知渠道，列表，可多个
profiles:
  - name: 张三
    openid: "1"              # 不同 profile 必须不同（见问题 D）
    phone: "138..."
    count: 1                 # 单次预约人数
    doc_id: "22"             # 项目/医生 ID（URL 里的 22）
    slot_priorities: ["20:30","21:00"]  # 想要的时段，按优先级
    book_date: tomorrow      # today | tomorrow | 2026-07-28
```

---

## 5. 上线前必做：标定（只读，不会真预约）

在真实的**周一或周三 19:55–20:05** 跑一次：

```bash
python -m jxgrab.calibrate --config config.yaml
```

它会调 `GetServerTime/GetSchedule/getTimeConfig`（**绝不调 SaveRecord**），打印真实响应。看报告确认这 5 个未知项（代码里都做了防御性兜底，但实测才放心）：

1. `GetServerTime` 的确切返回格式（字符串？epoch？）——`client.py:parse_server_time` 已支持多种。
2. 时段 JSON 的字段名（`sch_id/work_begin/work_end` 确认）+ **有没有"余位数字"字段**（有的话能只抢真有余位的）。
3. **`work_begin` 的真实格式**（"20:30" 还是 "20:30:00"）——直接影响优先级匹配（见问题 B）。
4. **20:00 前后 `GetSchedule` 是否从空变非空**（验证放号假设）+ **哪天的号**（today/tomorrow/具体日期 → 设 `book_date`）。
5. **`gethistory` 返回结构和排序**（见问题 C，这关系到 safety 会不会误删）。

---

## 6. 实际运行潜在问题 & 排查 & 修改（重点）

### 问题 A：抢不到号（最常见）

**排查**：看 `/var/log/jxgrab.log`，重点看 `fire_at`、`duration_ms`、结果的 `code/message`。

| 子原因 | 怎么看 | 怎么改 |
|---|---|---|
| 时钟偏移大 | 日志里 `fire_at` 对不对 | `clocksync` 已对时；若云服务器到站点 RTT 大，换**离站点近的服务器**（最有效） |
| cron 触发晚于 20:00 | 日志有 `started after release time ... firing immediately` | 确保 cron 行是 `59 19 * * 1,3`；服务器别在高负载时段 |
| 放号不是精确 20:00:00 | 轮询窗口内没拿到 | 调大 `timing.total_timeout_s`（如 60） |
| RTT 太慢抢不过 | `duration_ms` 很大 | 换近的服务器；调大 `poll_concurrency`（如 4） |

### 问题 B：时段选得不对（优先级没命中）

**现象**：抢到的是随便一个时段，不是你想要的。

**根因**：`slots.rank_by_priority` 是按 `work_begin` **精确字符串匹配**。如果站点返回 `"20:30:00"` 而你配 `"20:30"`，匹配失败 → 全部走"未命中按时间排序"。

**排查**：标定报告里看 `work_begin` 真实值。

**修改**：两个办法二选一——
- 改 `config.yaml` 的 `slot_priorities` 匹配真实格式（推荐，零代码）；
- 或改 `jxgrab/slots.py:rank_by_priority`，匹配时去掉秒、统一格式（容错）。

### 问题 C：⚠️ safety 误删预约（最需要警惕）

**背景**：抢号成功后 `safety.reconcile` 会查你的历史，如果发现超过 `count` 个预约，删掉多余的。**已修成"按 sch_id 保住刚抢的那个"**（不会删你刚抢的），但有个残留前提：**`gethistory` 返回里必须有 `sch_id` 字段**，否则 `keep_sch_id` 匹配不到 → 退化为按位置删 → **可能删错**。

**排查**：标定时看 `gethistory` 返回字段里有没有 `sch_id`。

**修改**（三选一）：
- **最稳**：如果 `gethistory` 没有 `sch_id` 或你不确定，把 `safety.auto_cancel_extras` 设成 `false`（关掉自动删除，万一重复预约你手动处理）。顺序发射本来就几乎不会重复。
- 如果有 `sch_id`：保持 `true`，没事。
- 想更稳：改 `safety.py:reconcile`，除了 `sch_id` 再加按 `work_begin`（时间）匹配刚抢的时段作为二级保据。

### 问题 D：openid 与每周额度（多人时关键）

**背景**：站点规定"每位员工每周最多 1 次"（`-4` 码）。**这个额度是按手机号算还是按 openid 算，是逆向不出来的未知项**。设计上每个 profile 配了独立 `openid`（张三="1"、李四="2"…）。

**风险**：如果额度按 openid 算、而所有 profile 都用默认 `"1"`，它们会**共用一个员工的额度**，互相挤占、很快触发 `-4`。

**排查**：标定时用「同手机号不同 openid」和「同 openid 不同手机号」各跑一次 `getUserInfo/gethistory`，看记录归到谁名下。

**修改**：按标定结果，在 `config.yaml` 给每个真实员工配正确的 `openid`（如果是按 openid 计，必须各不相同；如果按手机号计，openid 保持 `"1"` 即可）。

### 问题 E：站点改版（接口/字段/返回码变了）

**现象**：一直抢不到、或 `SaveRecord` 返回不认识的 code、或 HTTP 报错。

**排查**：重跑 `calibrate` 看响应；看日志里完整的 `code/message`。

**修改**：好消息是**网络只集中在 `client.py` 一层**。改 URL/参数改 `client.py`；改返回码处理改 `grabber.py:run` 里的 `_TERMINAL_FAIL` 集合和 `is_success_code`。

### 问题 F：收不到通知

**排查**：日志里 `webhook ... failed`。

| 渠道 | 常见错 | 改 |
|---|---|---|
| Bark | url/token 错 | 核对 `config.yaml` 的 `url` |
| DingTalk | 加签错（401/签名不符） | 核对 `secret` 与 `access_token` 配对；`notify.py:dingtalk_sign` 已按官方算法 |
| ServerChan | sendkey 错 | 核对 `sendkey` |

`notify_all` 有 2 次重试 + 渠道间隔离（一个挂不影响其他）。

### 问题 G：网络代理（生产服务器常见）

**现象**：日志里 `site unreachable (all polls errored)`（I4 已专门区分"站点不可达"和"没号"）。

**根因**：云服务器在代理后，httpx 默认读 `HTTP_PROXY/HTTPS_PROXY`，可能走错代理被拦（Task 1 装依赖时就撞到过代理 mirror 不通）。

**修改**：在 cron 环境或 systemd unit 里显式设置/清除代理：
```bash
export HTTP_PROXY="" HTTPS_PROXY=""   # 直连
# 或 export HTTPS_PROXY=http://你的代理:端口
```

### 问题 H：state.json 错乱 / 轮换不对

**现象**：轮换顺序乱了，或某 profile 一直不被选。

**排查**：看 `state.json` 内容（`week/rotation_index/used`）。

**修改**：
- 文件损坏/手动改坏了 → **直接删掉 `state.json`**，下次运行自动重建（相当于本周重新开始轮换）。
- **跨周判断偏**：`rotation.py` 用 ISO week。如果服务器时区是 UTC 而非北京时间，跨周边界会偏一天 → 用 `timedatectl set-timezone Asia/Shanghai`。

### 问题 I：book_date 选错（抢了不是目标日的号）

**背景**：默认 `book_date: tomorrow`。但站点 20:00 放的可能是后天、或今天的余位——逆向不出来。

**排查**：标定时对 today/tomorrow/+2 都看 `GetSchedule`，哪天有数据。

**修改**：`config.yaml` 里把 `book_date` 改成正确的（`today` / `tomorrow` / 具体 `2026-07-28`）。

### 问题 J：cron 没触发 / 触发了但报错

**排查**：`/var/log/jxgrab.log` 有没有 20:00 前后的日志。

**常见**：cron 的 PATH/环境跟交互 shell 不同，`python`/`httpx` 找不到。**修复**：cron 行用**绝对路径**（已在 `deploy/jxgrab.cron` 里写好 `/opt/jxgrab/venv/bin/python`），且在 main 里 `logging` 有基本输出。

### 问题 K：未来优化——盲打（现在别开）

现在不开盲打（标定前 sch_id 跨周稳定性未知）。**如果**上线后连两周都"差一点"抢到、**且**标定确认同一时段的 `sch_id` 跨周不变，可在 20:00:00 直接用缓存的 sch_id 发 SaveRecord（省一次 GetSchedule 往返）。这是策略 C 的可选加速，需要时再加一个小任务实现，不必现在做。

### 问题 L：对站点的访问压力 / 会不会把站搞挂

**不会宕机。** 程序只在周一/三 19:59 跑一次（cron 触发），平时完全不动（非常驻后台）。跑起来时请求集中在 20:00:00 那一小段：

| 阶段 | 频率 | 持续 | 总量 |
|---|---|---|---|
| 轮询找放号 | `poll_concurrency / (poll_interval_ms/1000)` ≈ 默认 **40 请求/秒** | 通常 1–2 秒拿到就停 | 实际 ~40–80 个 |
| 极端（一直没号） | 同上 | 最多 `total_timeout_s`（默认 30s）封顶 | 最多 ~1200 个 |
| 抢号提交 | 顺序 1 个 | <1 秒 | 1–3 个 |

对比：真实 DDoS 是几万到几十万请求/秒、来自海量 IP。这是**单 IP、~40 请求/秒、最多 30 秒**——量级差好几个数量级，压不垮一台能正常服务用户的网站。

**真正要注意的**（不是宕机，是针对你）：
- 站点的 WAF/限流可能觉得"这一个 IP 在 20:00 突然每秒 40 次"很可疑 → **临时封你 IP 或限流**。这才是更可能踩的坑。
- 抢号本身是竞争行为；如果同时有很多人在抢，集体压力大，但那是大家加起来的事，不是这个程序单独的问题。

**想更温和**（推荐第一轮先这样跑，确认没被限流、能稳定抢到，再决定要不要调激进）：在 `config.yaml` 的 `timing` 里放慢节奏——
```yaml
timing:
  poll_concurrency: 1        # 默认 2 → 降到 1
  poll_interval_ms: 100      # 默认 50 → 提到 100
  total_timeout_s: 30        # 上限不变
```
变成 **~10 请求/秒**，对站点几乎无感，但抢号依然够快（100ms 内就能感知到放号，远比人工快）。

---

## 7. 常见修改速查

| 想改什么 | 改哪里 |
|---|---|
| 放号准点（不是 20:00） | `config.yaml: timing.release_time` |
| 想要的时段/优先级 | `config.yaml: profiles[].slot_priorities` |
| 加一个抢号的人 | `config.yaml: profiles` 加一条（给独立 openid） |
| 每周每人几次 | `config.yaml: rotation.weekly_quota` |
| 换/加通知渠道 | `config.yaml: webhooks` 列表 |
| 抢哪天的号 | `config.yaml: profiles[].book_date` |
| 站点改了接口 | `jxgrab/client.py` |
| 站点改了返回码 | `jxgrab/grabber.py` 的 `_TERMINAL_FAIL` / `is_success_code` |
| 关掉自动删预约 | `config.yaml: safety.auto_cancel_extras: false` |

---

## 8. 本地测试 & 试运行

```bash
# 跑全部测试（44 个）
pytest -v

# 只读试运行（不会真预约）——平时随时可跑，验证脚本没坏、对时正常
python -m jxgrab.calibrate --config config.yaml

# 手动抢一次（跳过 cron，指定 profile；会真预约！仅在放号窗口期用）
python -m jxgrab --config config.yaml --target 张三
```

---

## 9. 一句话总结

代码已经能跑、测试齐全、评审干净。**真正上线只剩三步**：① 标定（一次，确认 5 个未知项）→ ② 按标定回填 `config.yaml`（尤其 `book_date`、`openid`、`slot_priorities` 格式）→ ③ 部署到云服务器挂 cron。第一次真跑后看日志微调即可。
