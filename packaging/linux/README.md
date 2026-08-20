# MemoryHub DEB 打包与安装

该目录生成面向银河麒麟桌面 V11（当前验证架构为 `amd64`）的独立安装包。DEB 包含：

- MemoryHub Python 后端及离线 wheel 依赖；
- Qt 桌面控制台；
- `memoryhub` CLI 与 `memoryhub-mcp`；
- systemd 用户服务；
- OpenCode 插件、工具、命令与 `memory-awareness` 技能；
- 首次登录时的按用户自动配置脚本。

## 构建依赖

```bash
sudo apt install -y python3 python3-venv python3-pip build-essential cmake \
  dpkg-dev qtbase5-dev qtbase5-dev-tools libqt5charts5-dev
```

## 构建

在仓库根目录执行：

```bash
bash packaging/linux/build-deb.sh
```

产物位于：

```text
packaging/linux/dist/kylin-memoryhub_<version>-1_<arch>.deb
packaging/linux/dist/kylin-memoryhub_<version>-1_<arch>.deb.sha256
```

构建脚本会先生成 Python wheelhouse、编译并测试 Qt 客户端，再生成 DEB。wheelhouse 会随包安装，因此目标机配置阶段不需要访问 PyPI。

## 安装与验证

```bash
sudo apt install ./packaging/linux/dist/kylin-memoryhub_0.1.0-1_amd64.deb
memoryhub-configure-opencode --current-user
systemctl --user status memoryhub --no-pager
memoryhub status
```

银河麒麟 V11 启用“应用程序来源检查”时，本地未接入企业签名链的 DEB 会弹出来源确认；请从文件管理器双击 DEB，并在图形安装器中确认本地来源。面向组织分发时，应使用组织的麒麟开发证书签名，或通过已签名的软件仓库发布。随 Release 提供的 `.sha256` 用于下载完整性校验，不替代发行证书。

桌面重新登录后，MemoryHub 会从应用菜单出现；OpenCode 会从 `~/.config/opencode/plugins/` 自动发现插件，同时加载同目录下的命令、技能和工具。

## 升级与卸载

升级不会删除 `~/.local/share/MemoryHub` 中的数据库、向量索引或安全密钥。

```bash
sudo apt remove kylin-memoryhub
```

用户数据需要由用户自行明确删除，卸载脚本不会自动清理。
