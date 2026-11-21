# 依赖许可证审计

状态：2026-11-21 离线审计 · 项目许可选定 **MIT**（见根目录 `LICENSE`）

## 1. 范围与方法

- 审计对象：`pyproject.toml` 声明的直接依赖、本机 `.venv` 实际安装的完整 Python 依赖集、`apps/dashboard` 的 npm 依赖树。
- 方法：`pip list` 取版本；`importlib.metadata` 读取每个发行版的 `License-Expression` / `License` / `License ::` 分类器；npm 侧读各 `node_modules/*/package.json` 的 `license` 字段。
- 性质：离线元数据核对，未逐包比对上游 LICENSE 原文，也未联网解析 SPDX。发布前若需要更严格结论，应对仓库内 `LICENSE` 原文再做一次抽检。

## 2. 结论

- 已安装的 Python 与 npm 依赖**全部为宽松许可**：MIT、MIT-0、BSD-2-Clause、BSD-3-Clause、Apache-2.0、ISC、PSF-2.0，以及 `Apache-2.0 OR BSD-3-Clause` / `Apache-2.0 OR BSD-2-Clause` 二选一。
- 未发现 GPL / AGPL / LGPL / SSPL / MPL 等需要源代码开放或文件级回馈的许可（`ocr` 额外依赖未安装，未在审计范围内，见第 5 节）。
- 因此以 **MIT** 发布本项目与全部已安装依赖兼容；分发时保留本仓库 `LICENSE` 及各依赖自身版权声明即可。

## 3. Python 直接依赖

| 包 | 版本（本机） | 许可 | 备注 |
|---|---|---|---|
| uiautomation | 2.0.29 | Apache-2.0 | UIA 绑定 |
| mss | 10.2.0 | MIT | 截屏 |
| PyYAML | 6.0.3 | MIT | locators / 配置 |
| websockets | 17.4 | BSD-3-Clause | SSE / WS |
| fastapi | 0.163.1 | MIT | 控制平面 REST |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI 服务器 |
| mcp | 2.3.0（声明 `>=1.0,<2`） | MIT | 版本偏差见第 5 节 |
| pytest（dev） | 9.2.0 | MIT | 测试 |
| httpx（dev，声明） | 未安装 | — | 代码与测试均未引用，见第 5 节 |
| rapidocr-onnxruntime（ocr，可选） | 未安装 | — | 未审计，见第 5 节 |

## 4. 完整 Python 依赖表（本机 `.venv`，42 个第三方发行版 + pip）

| 包 | 版本 | 许可 |
|---|---|---|
| annotated-doc | 0.0.6 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| click | 8.5.1 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| comtypes | 1.5.0 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| fastapi | 0.163.1 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore2 | 2.16.2 | BSD-3-Clause |
| httpx2 | 2.16.2 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| mcp | 2.3.0 | MIT |
| mcp-types | 2.3.0 | MIT |
| mss | 10.2.0 | MIT |
| opentelemetry-api | 1.45.2 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pip | 26.3 | MIT |
| pluggy | 1.7.0 | MIT |
| pycparser | 3.12 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| pydantic_core | 2.50.4 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| PyJWT | 2.15.1 | MIT |
| pytest | 9.2.0 | MIT |
| python-multipart | 0.0.34 | Apache-2.0 |
| pywin32 | 312 | PSF-2.0 |
| PyYAML | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |
| sse-starlette | 3.7.0 | BSD-3-Clause |
| starlette | 1.10.0 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typing-inspection | 0.4.5 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| uiautomation | 2.0.29 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| websockets | 17.4 | BSD-3-Clause |

（`pip` 与 `guibridge` 自身不计入第三方审计；`guibridge` 采用本仓库 MIT。）

## 5. 缺口与注意事项

1. **OCR 可选依赖未审计。** `ocr` extra（`rapidocr-onnxruntime>=1.3`）在本机未安装，其传递闭包（onnxruntime、opencv-python、numpy 等）不在上表内。交付物若启用 OCR 通道，须在安装后补一次同样方法的审计并按结果更新本文件；当前所有交付证据与测试都不依赖 OCR。
2. **mcp 版本偏差。** `pyproject.toml` 声明 `mcp>=1.0,<2`（网关按 1.x FastMCP API 编写），本机 `.venv` 实际为 `mcp==2.3.0`，因此 `tests/test_mcp.py`、`tests/test_live_mcp.py`、`tests/test_handoff_mcp_demo.py` 三条用例按设计 skip（528 passed / 3 skipped / 8 deselected）。发布复核应在声明范围内重建环境（`pip install -e '.[dev]'`）重跑全套。
3. **`httpx` 声明但未使用。** `dev` extra 含 `httpx>=0.27`，本机未安装该发行版，且仓库代码与测试均未 import（控制平面测试走自建 ASGI 驱动，不用 `fastapi.testclient`）。环境里的 `httpx2` / `httpcore2` 是独立发行版，未被项目引用。保留声明不影响许可结论，后续可精简。
4. **`src/probe/PROBE_REPORT.md` 里的探针截图**不入库；本次收尾同时把 `src/probe/cli_chat.log` 移出版本库并新增 `*.log` 忽略。
5. Node 侧 `apps/dashboard` 依赖树共 50 个包，许可分布为 MIT（绝大多数）、ISC（minimatch、picocolors）、BSD-2-Clause（entities）、BSD-3-Clause（source-map-js）、Apache-2.0（typescript）；`examples/demo-app` 无第三方运行依赖（`node --test` 为内置）。均为宽松许可。
