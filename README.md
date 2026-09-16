# WhalePet —— 把小鲸鱼挂件搬到桌面

把开源 DSH 插件 [dsh-whale-widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT）
的**本体**跑在桌面上：透明覆盖层里就是插件自己的界面，所以角色、音效、模块化泡泡、吸附翻转、
多厂商余额/额度、Codex 统计这些功能与插件版本**完全一致**，插件更新时只需换插件文件重新打包，
不需要移植任何功能。

> **第三方与免责**：挂件本体（`lib/`、`assets/`）与其中的角色图、音效等素材来自上述上游项目，
> 版权归原作者及各自权利人所有，本项目只是按上游的 MIT 许可在构建时获取并打包。
> 本项目是非官方工具，与 DeepSeek、DSH、Codex 官方无关；余额与用量数据只来自你自己填写的接口，
> 所有配置与密钥都保存在本机。

## 架构

```
WhalePet.exe (PyInstaller 单文件, Python + PySide6)
├─ 外壳（src/whalepet/）
│   ├─ overlay.py  透明置顶覆盖层：QtWebEngine 加载假 DSH 页面，按挂件可见区域打遮罩实现鼠标穿透
│   ├─ host.py     Node 宿主子进程管理 + 运行时解包 + 宿主 HTTP 客户端
│   ├─ proxy.py    本地 OpenAI 兼容中转：抓 usage 合成 DSH 会话事件（每轮消耗/模型明细/额度）
│   ├─ migrate.py  旧版 Qt 桌宠数据迁移（配置/账本/密钥 → 插件状态文件）
│   ├─ wizard.py   首次运行向导（API Key / 中转开关与端口 / 连通性自检）
│   └─ app.py      单实例、托盘、看门狗、生命周期
├─ 宿主垫片（host/host.mjs）
│   └─ 提供插件所需的 ctx 服务：webServer.register/tapIndex、credentials、connection、
│      on('session/event')、effect、get；并对外提供假 DSH 页面与 /__host/* 接口
└─ payload.zip：node.exe + 插件本体（lib/index.js、assets/whale-widget.js、素材）
```

`vendor/dsh-whale-widget/`（插件本体）**不入库**，构建前用 `scripts\sync-plugin.ps1` 从上游拉取。

关键设计（都来自阶段 0 的可行性验证）：

- 插件入口自检要求 `#root` 里有 `textarea`，宿主页面用一个 1px 隐形输入框满足它；
- 挂件用角色图的 **alpha 通道**判定点击命中，透明处故意穿透，所以遮罩只圈"挂件本体 + 展开的面板"，
  其余屏幕区域点击照常落到桌面；
- QtWebEngine 回传 JS 对象不可靠，统一 `JSON.stringify` 成字符串再解析；
- 每轮消耗没有 DSH 会话事件，靠本地中转在响应 `usage` 上合成事件喂给插件。

## 构建

```powershell
.\scripts\sync-plugin.ps1     # 从上游拉取插件本体到 vendor\dsh-whale-widget（插件不入库）
.\scripts\fetch_node.ps1      # 首次：下载 Node LTS 到 runtime\node\node.exe（国内镜像）
.\build.ps1                   # 生成 build\payload.zip + 图标 + dist\WhalePet.exe
.\build-dist.ps1              # 构建 + 分发校验 + dist\WhalePet-<版本>.zip
```

调试与测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q      # 单元 + 宿主集成测试（需要 node）
.\.venv\Scripts\python.exe scripts\smoke_app.py    # 源码态端到端冒烟
$env:WHALE_PET_SELFCHECK=1
.\.venv\Scripts\python.exe scripts\smoke_exe.py    # 打包产物冒烟（含"挂件是否真的渲染"自检）
```

阶段 0 的验证脚本保留在 `scripts\spike_widget.py`（插件脱离 DSH 能否运行）与
`scripts\spike_overlay.py`（透明覆盖层 + 鼠标穿透是否可用）。

## 插件升级（以后只做这一步）

```powershell
.\scripts\sync-plugin.ps1                 # 拉取上游最新插件覆盖 vendor\dsh-whale-widget
# 同步 src\whalepet\__init__.py 里的 PLUGIN_VERSION
.\build-dist.ps1
```

`payload.zip` 里带的是插件本体，外壳只按"壳层契约"（ctx 服务 + `assistant/message` 事件 +
`/dsh-whale/*` 路由）与它对接；插件新增路由/字段通常无需改外壳代码。

## 数据目录

| 模式 | 触发条件 | 位置 |
| --- | --- | --- |
| 默认 | —— | `%APPDATA%\WhalePet\` |
| 便携 | exe 同目录存在 `portable.flag` 或 `config.json` | `exe同级\WhalePetData\` |
| 调试 | 环境变量 `WHALE_PET_DATA` | 指定目录 |

目录内容：`config.json`（外壳配置）、`dsh-home\`（插件自己的状态：`.dshw-size.json`、
`.dshw-usage.json`、`credentials.json`、`whale-roles\`、`whale-audio\`…）、`runtime\<版本戳>\`
（解包后的 node + 插件）、`webengine\`（QtWebEngine 持久化配置，挂件位置等）、`logs\`。

## 从旧版桌宠（pet 包）升级

旧版的 `config.json` / `ledger.json` / `phrases.json` 与新版同目录。首次启动时：

1. 三个文件各备份一份 `*.pre-v030.bak`；
2. 旧配置键（api_key、proxy_*、scale、volume、sound_set、peak_mode、usage_mode、预警阈值…）
   合并进新配置，并写成插件的 `.dshw-size.json`；
3. 旧账本（`history` 是 `{day: {usage, models}}`）转换成插件的 `.dshw-usage.json`
   （`{day: number}` + `dayStart` / `lastBalance`），保证"今日已用 / 近 7 天"不归零；
4. api_key 写入插件密钥库 `DEEPSEEK_API_KEY`。

迁移只跑一次、只增不删；旧版 exe 保留备份，随时可回退。

## 分发

`build-dist.ps1` 产出的 zip 里是 `WhalePet.exe` + 使用说明 + README + 插件 MIT 许可。
打包前后会做校验（`scripts/verify_dist.py`）：

- 产物中不含 `sk-` 形式的密钥、不含你本机正在用的 API Key、不含本机用户名；
- `payload.zip` 只含 `node/node.exe`、`host.mjs`、插件本体，不含任何个人数据/密钥文件。

对方拿到 exe 双击即可运行（64 位 Windows 10 1809+ / 11），不需要 Python/Node/Qt；
API Key、账本等数据都由对方自己产生，不随包分发。

## 已知限制

- 单文件打包每次启动要解压运行时，首次约 5~10 秒、之后约 5 秒；想更快可自己用
  `pyinstaller --onedir` 打包成文件夹版。
- 只用主显示器作为覆盖层（多屏未做）。
- 个别杀软会对"PyInstaller + 内嵌 Node"误报，加白名单即可。
- 任务结束音等由轮询触发的声音依赖 WebEngine 的自动播放策略，程序已用
  `--autoplay-policy=no-user-gesture-required` 放开。

## 许可

- 本仓库的外壳代码（`src/`、`host/`、`scripts/`、构建脚本）：MIT，见 `LICENSE`。
- 挂件本体与素材：来自 [MeteorNOX/DeepSeek-Balance-Whale-Widget](https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget)（MIT），
  构建时通过 `scripts\sync-plugin.ps1` 获取，不随本仓库分发；角色图、音效等素材的版权归原作者及各自权利人所有。
