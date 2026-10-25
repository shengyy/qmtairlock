# qmtairlock

面向 QMT 个人研究与实验的本地进程间通信桥及 Python 客户端，采用非商用项目定位。

[English](README.md) · [产品边界](PRODUCT.md) · [文档地图](docs/README.md) · [验证状态](docs/status.md)

> **仅供个人研究与实验 — 非商用用途声明**
>
> 本项目用于个人量化策略研发、软件架构学习与本地实验测试。请勿用于任何商业用途；维护者不提供商业服务或支持。
>
> 禁止将本项目用于代客理财、非法证券期货经营、分仓配资、多账户中台或向不可信网络暴露远程接入接口。使用者必须遵守适用法律法规、[《证券公司交易信息系统接入管理规范（试行）》](https://www.amac.org.cn/xwfb/tzgg/202608/t20260828_28053.html)以及所在证券公司的终端使用协议、接入权限与风控要求。
>
> 本项目不构成投资建议或交易信号。软件按 **“原样（AS IS）”** 提供，不提供任何明示或暗示担保。运行故障、数据偏差、委托异常、账户风险及直接或间接损失由使用者自行承担；在适用法律允许的最大范围内，作者不承担由此产生的法律或经济责任。
>
> 本项目为独立技术实验代码，与迅投（XtQuant / QMT）及任何证券公司均无关联，亦未获其官方背书。本段为维护者的用途声明，软件授权条款见 [LICENSE](LICENSE)。

策略采用自包含的标准库实现、纯内存运行态和零外部中间件依赖，通过 QMT 原生 API 与同机消息通道提供能力。Windows 客户端本地连接；WSL 客户端使用 Windows Python stdio 中继。生成的 GBK 入口为 `QMTAIRLOCK.py`。

## 安装与读取

客户端需要 Python 3.10 及以上。需要 pandas 和 Parquet 缓存时安装 `data` extra：

```sh
python -m pip install 'qmtairlock[data] @ git+https://github.com/shengyy/qmtairlock.git@v0.1.1'
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
