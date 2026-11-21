# 依赖许可证审计与提交检查（A 线采集，待 B 复核定稿）

2026-11-20。范围：参赛交付物的第三方依赖许可证 + 入库内容泄露检查。
方法：只读本地元数据（pip dist-info / conda-meta / `cargo metadata --offline` / node_modules package.json），
不联网、不安装、不触碰 live 应用。

重算方式（表格由脚本生成，勿手填）：

```bash
python -X utf8 tools/license_audit.py
```

原始记录落 `var/experiments/license_audit_<ts>.json`（gitignored），本文表格取自最近一次运行。
许可证解析顺序：`License-Expression` → `License` → trove classifier → conda-meta → 包内 LICENSE 文件首行；
每行都带 `source` 列说明依据，未安装/无法解析的显式标 `UNRESOLVED`，不猜。

## 1. 结论

- **57 个 Python 包（含传递依赖）、24 个 Rust crate、50 个 npm 包，全部为宽松许可证**
  （MIT / BSD / Apache-2.0 / ISC / PSF / Unlicense / MIT-CMU / Unicode-3.0），
  **没有 GPL / AGPL / LGPL 等强 copyleft**，因此依赖侧不强制本项目开源。
- 两处 **MPL-2.0（文件级弱 copyleft）**：`certifi`（经 httpx ← mcp/fastapi）、
  `tqdm`（`MPL-2.0 AND MIT`，经可选 extra `rapidocr-onnxruntime`）。
  义务限于「被修改的 MPL 文件须以 MPL 提供源码 + 保留声明」；我们未修改这两个包，随发行版附带其 LICENSE 即可。
- `unicode-ident` 为 `(MIT OR Apache-2.0) AND Unicode-3.0`：Unicode-3.0 是宽松数据许可证，保留声明即可。
- **本项目许可证已选定 MIT**（2026-11-20 用户裁决）：新增 `LICENSE`（MIT，Copyright (c) 2026 GUIBridge contributors）、
  `pyproject.toml` 加 `license = {text = "MIT"}`（本机 setuptools 75.1.0，SPDX 字符串形式需 ≥77，故用 table 形式）、
  `src/probe/gbmirror/Cargo.toml` 加 `license = "MIT"`。重跑审计后 `gbmirror` 行已解析为 MIT，不再 UNRESOLVED。
  与依赖侧兼容：MIT 与 Apache-2.0 单向兼容（Apache 声明保留即可），与 MPL-2.0 文件级义务不冲突。

## 2. 本次已修

| 问题 | 证据 | 处理 |
|---|---|---|
| 硬编码本机用户名 | `src/probe/trae_session_clone.py:33` 原为 `C:\Users\56407\AppData\Roaming\Trae` | 改 `Path(os.environ["APPDATA"]) / "Trae"` |
| Pillow 被入库代码使用但未声明 | `src/probe/gbdash.py:519`、`src/probe/hidden_mirror.py:28` | `pyproject.toml` dependencies 增 `pillow>=10.0` |
| 探针日志入库 | `src/probe/cli_chat.log`（7 字节 `EXIT=0`） | `git rm --cached`（本地文件保留）+ `.gitignore` 增 `*.log` |
| 本项目未声明许可证 | 无 LICENSE / pyproject 无 license / Cargo 无 license | 用户选定 MIT，三处均已声明 |
| 基准原始记录被 ignore 挡住 | `.gitignore` 的 `tests/bench/results/` 与 benchmark.md「每次运行生成新文件，均入库」矛盾 | 改 `tests/bench/results/*` + `!tests/bench/results/*.json` |

## 3. 未修，交付前需处理（如实标注）

- **机器特定默认路径**：`D:\QoderTest\guibridge-demo-workspace` 出现在
  `src/probe/hidden_trae_session.py:48`、`experiment_trae_hidden.py:93`、`verify_hidden_trae_chain.py:57`
  （三处均可 CLI 覆盖）以及 4 处文档证据记录。代码默认值建议改环境变量（属探针行为变更，留待复核后一起动）；
  文档中的路径属实测记录，**公开发布前需脱敏**。
- **无 Python 锁文件，本机是混合环境**：conda + 用户 site-packages 并存，同名多版本 dist-info
  （numpy 1.26.4 与 2.0.1 并存、实际导入 2.0.1；cv2 实际 4.10.0 来自用户 site，
  而 anaconda 内是 `opencv_python_headless` 4.13.0.90）。审计以「实际可导入版本 + 本地元数据」为准，
  但**干净环境复跑需要 pin**：交付前建议生成锁文件并在干净 venv 复跑一次非 live 套件。
- **OCR extra 的 `opencv-python` 未以该名字安装**（表内 UNRESOLVED / not-installed）：
  rapidocr 声明 opencv-python，本机由 headless / 用户 site 的 cv2 满足。
  若交付声明支持 OCR 通道，需在干净环境按 extra 安装后重跑本审计。
- **调试端口** 9222 / 9333 / 8710 在 32 个文件出现 66 次，均为 loopback 默认值或文档记录，非凭据；
  但公开站点不得包含本机执行器、端口转发或 `var/experiments` 证据目录（handoff §5 的 G5 前置）。
- `tests/test_mcp.py:73/82` 用 `D:\GitHub\Agui` 作字符串断言（不依赖真实路径，仅观感问题）。

## 4. 泄露检查（tracked 文件全量扫描）

- 非源码产物：仅 `cli_chat.log`（已移出索引）；无 png/jpg/mp4/db/exe/dll/zip/pem/key 入库。
- 凭据模式：私钥块 / `api_key|secret|token|password` 赋值 / `AKIA…` / `git@gitee.com` 均 **0 命中**。
- 本机标识：`56407` 全库仅 1 处（已修）；`Urgar|biolian` **0 处**。
- `.gitignore` 覆盖 `var/`、`node_modules/`、`*.db`、`*.sqlite3`、`src/probe/*.png`、`uia_dump.json`、`*.log`。
- 扫描后未跟踪文件仅 `debug.log`（现被 `*.log` 覆盖）与新增的基准原始 JSON（按纪律应入库）。

## 5. 明细表（脚本生成）

原始记录：`var/experiments/license_audit_20261120T132201Z.json`

### Python

| name | version | license | source | via |
|---|---|---|---|---|
| annotated-doc | 0.0.4 | MIT | License-Expression | fastapi |
| annotated-types | 0.6.0 | MIT License | classifier | pydantic |
| anyio | 4.11.0 | MIT | License-Expression | mcp |
| attrs | 23.1.0 | MIT | License-Expression | jsonschema |
| certifi | 2026.5.20 | MPL-2.0 | License | httpx |
| click | 8.1.7 | BSD-3-Clause | License | uvicorn |
| colorama | 0.4.6 | BSD-3-Clause | License-Expression | pytest |
| coloredlogs | 15.0.1 | MIT | License | onnxruntime |
| comtypes | 1.4.10 | MIT License | classifier | uiautomation |
| fastapi | 0.138.0 | MIT | License-Expression | declared |
| flatbuffers | 25.2.10 | Apache 2.0 | License | onnxruntime |
| h11 | 0.14.0 | MIT | License | uvicorn |
| httpcore | 1.0.2 | BSD-3-Clause | License-Expression | httpx |
| httpx | 0.27.0 | BSD-3-Clause | License-Expression | mcp |
| httpx-sse | 0.4.3 | MIT | License | mcp |
| humanfriendly | 10.0 | MIT | License | coloredlogs |
| idna | 3.7 | BSD License | classifier | anyio |
| iniconfig | 1.1.1 | MIT License | License | pytest |
| jsonschema | 4.23.0 | MIT | License | mcp |
| jsonschema-specifications | 2023.7.1 | MIT | License | jsonschema |
| mcp | 1.22.0 | MIT | License | declared |
| mpmath | 1.3.0 | BSD | License | sympy |
| mss | 10.2.0 | MIT License | License | declared |
| numpy | None | BSD-3-Clause | conda-meta/numpy-2.0.1-py312hfd52020_1.json | rapidocr-onnxruntime |
| onnxruntime | 1.21.0 | MIT License | License | rapidocr-onnxruntime |
| opencv-python | None | UNRESOLVED | not-installed | rapidocr-onnxruntime |
| packaging | 24.1 | Apache Software License | classifier | pytest |
| pillow | 11.1.0 | MIT-CMU | License | declared |
| pluggy | 1.6.0 | MIT | License | pytest |
| protobuf | 5.29.3 | 3-Clause BSD License | License | onnxruntime |
| pyclipper | 1.4.0 | MIT | License | rapidocr-onnxruntime |
| pydantic | 2.13.4 | MIT | License-Expression | fastapi |
| pydantic-core | 2.46.4 | MIT | License-Expression | pydantic |
| pydantic-settings | 2.14.2 | MIT | License-Expression | mcp |
| pygments | 2.15.1 | BSD-2-Clause | License | pytest |
| pyjwt | 2.10.1 | MIT | License | mcp |
| pyreadline3 | 3.5.4 | BSD | License | humanfriendly |
| pytest | 9.1.1 | MIT | License-Expression | declared |
| python-dotenv | 1.0.1 | BSD-3-Clause | License | pydantic-settings |
| python-multipart | 0.0.6 | Apache-2.0 | License-Expression | mcp |
| pywin32 | 311 | PSF | License | mcp |
| pyyaml | 6.0.2 | MIT | License | declared |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 | License | declared |
| referencing | 0.30.2 | MIT | License | jsonschema |
| rpds-py | 0.10.6 | MIT | License | jsonschema |
| shapely | 2.1.2 | BSD 3-Clause | License | rapidocr-onnxruntime |
| six | 1.16.0 | MIT | License | rapidocr-onnxruntime |
| sniffio | 1.3.0 | MIT OR Apache-2.0 | License | anyio |
| sse-starlette | 3.0.3 | BSD-3-Clause | License-Expression | mcp |
| starlette | 1.3.1 | BSD-3-Clause | License-Expression | fastapi |
| sympy | 1.14.0 | BSD | License | onnxruntime |
| tqdm | 4.66.5 | MPL-2.0 AND MIT | License | rapidocr-onnxruntime |
| typing-extensions | 4.15.0 | PSF-2.0 | License-Expression | fastapi |
| typing-inspection | 0.4.2 | MIT | License-Expression | fastapi |
| uiautomation | 2.0.29 | Apache 2.0 | License | declared |
| uvicorn | 0.49.0 | BSD-3-Clause | License-Expression | declared |
| websockets | 15.0.1 | BSD-3-Clause | License | declared |

### Rust

| name | version | license |
|---|---|---|
| gbmirror | 0.1.0 | MIT |
| itoa | 1.0.18 | MIT OR Apache-2.0 |
| memchr | 2.8.1 | Unlicense OR MIT |
| proc-macro2 | 1.0.106 | MIT OR Apache-2.0 |
| quote | 1.0.45 | MIT OR Apache-2.0 |
| serde_core | 1.0.228 | MIT OR Apache-2.0 |
| serde_json | 1.0.150 | MIT OR Apache-2.0 |
| syn | 2.0.117 | MIT OR Apache-2.0 |
| unicode-ident | 1.0.24 | (MIT OR Apache-2.0) AND Unicode-3.0 |
| windows | 0.61.3 | MIT OR Apache-2.0 |
| windows-collections | 0.2.0 | MIT OR Apache-2.0 |
| windows-core | 0.61.2 | MIT OR Apache-2.0 |
| windows-future | 0.2.1 | MIT OR Apache-2.0 |
| windows-implement | 0.60.2 | MIT OR Apache-2.0 |
| windows-interface | 0.59.3 | MIT OR Apache-2.0 |
| windows-link | 0.1.3 | MIT OR Apache-2.0 |
| windows-numerics | 0.2.0 | MIT OR Apache-2.0 |
| windows-result | 0.3.4 | MIT OR Apache-2.0 |
| windows-strings | 0.4.2 | MIT OR Apache-2.0 |
| windows-sys | 0.59.0 | MIT OR Apache-2.0 |
| windows-targets | 0.52.6 | MIT OR Apache-2.0 |
| windows-threading | 0.1.0 | MIT OR Apache-2.0 |
| windows_x86_64_msvc | 0.52.6 | MIT OR Apache-2.0 |
| zmij | 1.0.21 | MIT |

### npm

| name | version | license |
|---|---|---|
| alien-signals | 1.0.13 | MIT |
| balanced-match | 1.0.2 | MIT |
| brace-expansion | 2.1.8 | MIT |
| csstype | 3.2.3 | MIT |
| de-indent | 1.0.2 | MIT |
| entities | 7.0.1 | BSD-2-Clause |
| esbuild | 0.25.12 | MIT |
| estree-walker | 2.0.2 | MIT |
| fdir | 6.5.0 | MIT |
| he | 1.2.0 | MIT |
| magic-string | 0.30.21 | MIT |
| minimatch | 9.0.9 | ISC |
| muggle-string | 0.4.1 | MIT |
| nanoid | 3.3.20 | MIT |
| path-browserify | 1.0.1 | MIT |
| picocolors | 1.1.1 | ISC |
| picomatch | 4.0.7 | MIT |
| postcss | 8.5.33 | MIT |
| rollup | 4.68.4 | MIT |
| source-map-js | 1.2.2 | BSD-3-Clause |
| tinyglobby | 0.2.17 | MIT |
| typescript | 5.6.3 | Apache-2.0 |
| vite | 6.4.6 | MIT |
| vscode-uri | 3.2.0 | MIT |
| vue | 3.5.45 | MIT |
| vue-tsc | 2.2.12 | MIT |
| @babel/helper-string-parser | 7.29.14 | MIT |
| @babel/helper-validator-identifier | 7.29.7 | MIT |
| @babel/parser | 7.29.14 | MIT |
| @babel/types | 7.29.14 | MIT |
| @esbuild/win32-x64 | 0.25.12 | MIT |
| @jridgewell/sourcemap-codec | 1.6.0 | MIT |
| @rollup/rollup-win32-x64-gnu | 4.68.4 | MIT |
| @rollup/rollup-win32-x64-msvc | 4.68.4 | MIT |
| @types/estree | 1.0.10 | MIT |
| @vitejs/plugin-vue | 5.2.4 | MIT |
| @volar/language-core | 2.4.15 | MIT |
| @volar/source-map | 2.4.15 | MIT |
| @volar/typescript | 2.4.15 | MIT |
| @vue/compiler-core | 3.5.45 | MIT |
| @vue/compiler-dom | 3.5.45 | MIT |
| @vue/compiler-sfc | 3.5.45 | MIT |
| @vue/compiler-ssr | 3.5.45 | MIT |
| @vue/compiler-vue2 | 2.7.16 | MIT |
| @vue/language-core | 2.2.12 | MIT |
| @vue/reactivity | 3.5.45 | MIT |
| @vue/runtime-core | 3.5.45 | MIT |
| @vue/runtime-dom | 3.5.45 | MIT |
| @vue/server-renderer | 3.5.45 | MIT |
| @vue/shared | 3.5.45 | MIT |

### tallies

python {'Apache 2.0': 2, 'MIT License': 5, 'MIT': 23, 'BSD-3-Clause': 10, 'MIT-CMU': 1, 'Apache-2.0': 2, 'PSF-2.0': 1, 'PSF': 1, 'UNRESOLVED': 1, 'BSD 3-Clause': 1, 'MPL-2.0 AND MIT': 1, 'Apache Software License': 1, 'BSD-2-Clause': 1, 'BSD License': 1, 'MIT OR Apache-2.0': 1, 'MPL-2.0': 1, '3-Clause BSD License': 1, 'BSD': 3}
cargo {'MIT': 2, 'MIT OR Apache-2.0': 20, 'Unlicense OR MIT': 1, '(MIT OR Apache-2.0) AND Unicode-3.0': 1}
npm {'MIT': 45, 'BSD-2-Clause': 1, 'ISC': 2, 'BSD-3-Clause': 1, 'Apache-2.0': 1}

### flagged (unresolved / not installed / non-permissive prefix)

| name | version | license | source |
|---|---|---|---|
| opencv-python | None | UNRESOLVED | not-installed |
| tqdm | 4.66.5 | MPL-2.0 AND MIT | License |
| certifi | 2026.5.20 | MPL-2.0 | License |
| unicode-ident | 1.0.24 | (MIT OR Apache-2.0) AND Unicode-3.0 | cargo metadata |

## 6. 边界

本文是 A 线采集的原始数据与可核实结论。team-plan §5 把「依赖许可证审计、交付材料」判给 B，
**定稿与许可证选择由 B / 用户确认**。本次未改任何冻结契约文件，未发布，未执行 live 写。