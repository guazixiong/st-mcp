# vendor/ —— 数据库介质投递位（本仓库**不含**介质）

神通（ShenTong / Oscar）是商业数据库，安装介质、Python 驱动、ACI 客户端库和 license
都由厂商分发，**不在本仓库里，也不能由本仓库转发**。要跑通"由本包装库"这条路径，需要自备：

| 需要的东西 | 厂商介质里的位置 | 放到哪 |
|---|---|---|
| 服务端安装包（aarch64，V7.0.8 系列） | 官网下载中心（需注册/授权账号），形如 `ShenTong7.0.8_342.185_arm64.zip` | `vendor/` 原名放入即可 |
| Python 驱动 `STPython-*-cp311-cp311-linux_aarch64.whl` | 介质内 `drivers/STPython/Python311/` | `wheels/` |
| ACI 客户端库 `libaci.so` | 介质内 `drivers/aci/arm64/`，或已装好的库上 `$SZ_OSCAR_HOME/drivers/aci/arm64/` | `aci/`（见 `aci/README.md`） |
| license | 介质自带**试用授权**（版本串显示 `license invalid after 90 days`） | 正式授权找厂商换 |

放好后直接：

```sh
sh install-all.sh
```

`INSTALL_SHENTONG=yes`（默认）时脚本会在 `vendor/` 找 `*.zip`；找到就解压安装，
`$ST_INSTALL_PREFIX/bin/oscar` 已存在则跳过 setup，只补建库、初始化和驱动收割
（把介质里的 `libaci.so` 覆盖到 `aci/`，版本自动匹配）。

## 不想让本包装库

连一台**已经装好的**库（本仓库的推荐用法，也是"场景 B"）：

```sh
sed -i 's|^INSTALL_SHENTONG=.*|INSTALL_SHENTONG=no|' deploy.conf
sed -i 's|^ST_HOST=.*|ST_HOST=<库机IP>|' deploy.conf
sh install-all.sh
```

这条路完全不需要 `vendor/` 里放任何东西，只需要 `wheels/` + `aci/` 齐（镜像里要有驱动才能执行 SQL）。

## 换架构 / 换 Python 版本

驱动只覆盖厂商发布过的组合（当前已知 **cp311 + linux_aarch64**）。
x86_64 要取该架构介质里的 `drivers/STPython/Python311/*linux64.whl` 与对应 `libaci.so`，
基础镜像不变，其余脚本通用。厂商没发过的 Python 版本就别指望驱动。

## 授权提醒

试用许可到期后数据库会拒绝启动，届时 MCP 侧表现为连不上，不是本项目的故障。
另外：把厂商介质、驱动或 `libaci.so` 提交进本仓库或任何公开分发渠道，属再分发第三方商业软件，
本项目的 MIT 许可**不覆盖**这些文件。
