# qmtairlock

面向 Windows 大 QMT 策略宿主的命名管道桥，提供行情、账户查询和交易 Python 客户端。

[English](README.md) · [产品边界](PRODUCT.md) · [文档地图](docs/README.md) · [验证状态](docs/status.md)

策略通过 `ContextInfo` 和宿主注入函数调用 QMT。构建产物是一份 GBK Python 文件，只使用标准库与命名管道，不主动读写文件或创建 Socket。Windows 客户端直接连接；WSL 客户端通过 Windows Python 进程的 stdio 帧中继连接。

## 安装与读取

客户端需要 Python 3.10 及以上。需要 pandas 和 Parquet 缓存时安装 `data` extra：

```sh
python -m pip install 'qmtairlock[data] @ git+https://github.com/shengyy/qmtairlock.git@v0.1.0'
```

在同一 Windows 机器上配置并启动策略后：

```python
from qmtairlock.client import BigQmtRpcClient
from qmtairlock.data_client import BigQmtXtData
from qmtairlock.trader_client import BigQmtXtTrader

client = BigQmtRpcClient("YOUR_ACCOUNT")
try:
    print(client.call("ping"))
    data = BigQmtXtData(client)
    print(data.get_full_tick(["600000.SH", "000001.SZ"]))
    bars = data.get_market_data_ex(stock_list=["600000.SH"], period="1d", count=20)
finally:
    client.close()

trader = BigQmtXtTrader("YOUR_ACCOUNT")
try:
    print(trader.query_stock_asset("YOUR_ACCOUNT"))
finally:
    trader.stop()
```

连接前先读[宿主安装与 WSL 配置](docs/qmt-runtime.md)。交易 RPC 默认关闭；查询能否返回数据取决于券商终端原生 API 和数据权限。

## 能力

- STOCK 行情、全市场盘口、K 线、除权因子、合约、板块、日历与账户快照。
- 单笔和批量下撤单、原生 `passorder`，以及客户端轮询合成执行回调。
- 两融账户与合约查询、柜台快照限流与陈旧保护、两融委托类型。
- 期权链、期权持仓与委托类型；客户端 BSM 定价、IV 反解与 Greeks。
- 宿主内置公式、ETF 申赎清单、新股额度、港股通汇率和财务查询。
- 显式启用的客户端 Parquet 缓存；本地读取不会触发 RPC 下载。

[RPC 合同](docs/rpc-contract.md)说明超时、未知写入结果和领域入口。[开发指南](CONTRIBUTING.md)持有本地门禁与构建命令。GitHub Actions 只允许手动触发。

使用 [MIT 许可证](LICENSE)。
