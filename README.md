# 榆台剧场联奏服务

周末排练班登记交接清单、开排、联奏、现场改调，再停排核对实播。服务使用 Python 3.11 标准库、SQLite 和本地 JSON HTTP，输出可核对的整数音高与起停事件。

```sh
python3 -B -m session.http_api --database rehearsal.sqlite3 --port 8765
python3 -B check_project.py
python3 -B -m tests.test_day
```

服务监听 `127.0.0.1`。交付平台提供 `check_project.py`，它执行完整回归。直接使用源码时也可运行 `python3 -B -m unittest discover`。演示用独立临时库走实际 HTTP，逐项核对 `samples/weekend.json` 与 `samples/weekend-expected.json`，然后重开原库查领。启动和重开都只建立缺失表，样例通过 HTTP 显式提交。

## 请求

所有提交使用 JSON 对象。标识和声部为非空白字符串。路径和查询中的标识按 URL 规则编码。键位、键域和移调为 JSON 整数。每个键盘配置有 `keyboard_id`、`part`、`low`、`high`、`transposition`。

| 方法与路径 | 业务字段 | 成功响应 |
| --- | --- | --- |
| `POST /layouts` | `layout_id`, `keyboards` | 201，整份已登记布置 |
| `POST /sessions` | `layout_id` | 201，生成的 `session_id`、`active` 状态及逐键盘配置和生效移调 |
| `POST /keys/press` | `session_id`, `keyboard_id`, `request_id`, `key` | 200 实际结局，或 202 待查 |
| `POST /keys/release` | `session_id`, `keyboard_id`, `request_id`, `press_id` | 200 实际结局，或 202 待查 |
| `POST /transpositions` | `session_id`, `keyboard_id`, `transposition` | 200，已生效的移调 |
| `GET /operations/{id}?session_id=…` | 场次和原请求号 | 200，原操作状态和已知结局 |
| `GET /sessions/{id}/sound` | 场次 | 200，`status`、`pitches`、`operations`、`events` |
| `POST /sessions/{id}/close` | 空对象或空正文 | 200，`closed` 状态、封存的 `sound` 和终局 `operations` 列表 |

操作状态为 `pending`、`completed` 或 `rejected`。完成结果含实际 `pitch`，拒绝结果含 `error`。声音视图中的 `pitches` 是升序去重集合，`operations` 是已实际办理的原请求号到音高的映射，含未引起独立起停的合音操作。事件含从 1 开始的 `seq`、`action`（`start` 或 `stop`）、`pitch` 与 `request_id`。停排产生的停音用 `null` 请求号。同场的实际提交顺序决定 `seq`。单独查听不会推进演奏。

按键首次接纳时使用发声端已生效的移调。键位须落在配置的闭区间，移调后完整键域须落在 0–127。整数音高为原键位加移调。按键实际绑定一经提交即固定。松键引用同场同键盘的原按键，原按键尚未提交时可以待查。每个按键是独立来源，首份来源使音高起响，最后一份离开才停。已登记的待查操作用原参继续办理。同参复投已办操作领取原结局，包括先提交后失答以及重开服务的情况。控制侧未收结果时可见待查，查听仍可见声端已提交的起停。

错误正文包含 `error` 和 `message`。格式错误返回 400，未知布置、场次、键盘或操作返回 404。非法键域、移调、键位或松键引用返回 422。松键首次到达时若所引来源已经结束，拒绝结果可按原号查领。同场同号异参、重复登记布置或停排后的新演奏和移调返回 409。停排先收齐已经登记的操作，再按音高升序停止余音。最终停声、归档和停排状态一起提交，旧操作、停排结果和封存历史可重复领取。
