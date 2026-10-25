# qmtairlock · Agent 指引

公开 MIT 仓库。为大 QMT 提供本地 IPC RPC、WSL 中继与 Python 客户端。领域支持面由 `PRODUCT.md` 持有；先核对实现和声明文件，再更新文档，未验证的宿主行为明确标注。

## 按需加载

| 范围 | 先读 |
|---|---|
| 产品边界、支持范围与非目标 | [`PRODUCT.md`](PRODUCT.md) |
| 文档与目录的职责、写入规则与上下文分层 | [`docs/README.md`](docs/README.md) |
| 当前已验证的 QMT 终端版本与运行环境 | [`docs/status.md`](docs/status.md) |
| 模块地图、数据流、单文件构建与中继链路 | [`docs/architecture.md`](docs/architecture.md) |
| 大 QMT 内置 Python 3.6 宿主事实、GIL/线程模型与运行态边界限制 | [`docs/qmt-runtime.md`](docs/qmt-runtime.md) |
| 本地 IPC 帧协议、RPC 方法合同与错误语义 | [`docs/rpc-contract.md`](docs/rpc-contract.md) |
| 版本、构建产物校验与发版流程 | [`docs/release.md`](docs/release.md) |
| 信任边界、通道权限与凭据安全 | [`SECURITY.md`](SECURITY.md) |
| 开发环境、门禁检查与提交流程 | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## 边界

- QMT 是资金、持仓、委托与成交的唯一来源；本库不维护账户账本。
- 已发送请求的未知结果不得透明重发；真实下撤单默认关闭，开启或扩大真实写入须由用户明确授权。
- 交易与账户查询必须由策略回调主线程执行；重行情读与文件缓存的边界见各 owner。
- 宿主产物兼容 Python 3.6，采用自包含标准库运行态与纯内存状态；模块图只包含服务端和共享领域代码，客户端、中继及桌面启动器独立维护。
- 公开内容不得包含真实账号、凭据、私有日志或个人绝对路径；测试使用隔离夹具。
- 一个事实一个 owner；替代实现落地时同时删除旧路径、旧测试与旧文档。
- `src/`、`scripts/`、`tests/` 的 Python 文件控制在 800 行内；按职责拆分，不用 mixin、拼接或薄 wrapper 凑行数。
- 不把本机测试写成真实终端验收；不改生产调度或部署，除非用户明确授权。

## 协作

- 中文交流，标识符与命令保留英文；公共文档默认英文，两份 README 同步。
- 工作开始确认 cwd、分支和已有 diff，保留无关改动。
- 后续改动走主题分支和 PR；用户可见变化记入 `CHANGELOG.md`。
- 门禁命令由 `CONTRIBUTING.md` 持有；交付前由子代理做一轮对抗审并修复阻塞项。
