# MemoryHub DEB 打包与安装

该目录生成面向银河麒麟桌面 V11（当前验证架构为 `amd64`）的独立安装包。DEB 包含：

- MemoryHub Python 后端及离线 wheel 依赖；
- Qt 桌面控制台；
- `memoryhub` CLI 与 `memoryhub-mcp`；
- 桌面会话自启动服务（兼容银河麒麟 KARE）；
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
sudo apt install ./packaging/linux/dist/kylin-memoryhub_<version>-<revision>_amd64.deb
memoryhub-configure-opencode --current-user
memoryhub status
```

也可以在文件管理器中双击 DEB，使用系统“安装器”完成安装。银河麒麟自带的
`dpkg-deb` 可能在本机构建时自动附加发行版内部的 `_compat` 成员；构建脚本会
在签名之前移除该内部成员。银河麒麟 V11 的图形安装器仍可能通过 KARE `shadow`
环境安装原生第三方应用。本包使用 XDG 桌面会话自启动，避免 KARE 把用户级
systemd 服务改写为不安全的 `forking + /tmp PIDFile` 后误判启动失败。

双击安装必须在系统的正常模式下进行。维护模式会额外叠加 `/usr` 和 `/etc`，此时
KARE 再创建安装环境可能触发 `overlayfs: maximum fs stacking depth exceeded`，表现为
安装器立即显示“安装失败”。如果桌面右下角显示红色“维护模式”，请先在系统中选择
保存更改并退出维护模式，重启回到正常模式后再双击安装；不要用关闭来源检查来掩盖
该错误。

银河麒麟 V11 的“应用程序来源检查”有“阻止 / 警告 / 关闭”三种策略。未签名
Release 通过命令行安装时可在“警告”策略下继续，但部分 V11 KARE 图形安装器会在
“警告”策略下仍然拒绝安装软件主体、却错误显示安装成功。因此，双击安装未签名
Release 前必须暂时选择“关闭”；安装完成后可恢复为“警告”。随 Release 提供的
`.sha256` 仅用于下载完整性校验，不替代发行证书。使用麒麟开发证书签名的正式包
不需要关闭来源检查。

面向默认启用“阻止”策略的组织分发时，必须使用麒麟开发证书签名。构建脚本支持官方 `kylinsigntool`：

```bash
KYLIN_SIGN_PRIVATE_KEY=/secure/path/developer.key \
KYLIN_SIGN_CERTIFICATE=/secure/path/developer.pem \
KYLIN_REQUIRE_SIGNATURE=true \
bash packaging/linux/build-deb.sh
```

私钥和证书不得提交到仓库。签名成功后，DEB 会包含麒麟签名成员，并在生成 SHA256 之前执行 `kylinsigntool -v` 验证。

桌面重新登录后，MemoryHub 会话服务会自动启动；MemoryHub 会从应用菜单出现，
OpenCode 会从 `~/.config/opencode/plugins/` 自动发现插件，同时加载同目录下的命令、
技能和工具。“一键配置”还会将 `memoryhub` MCP 合并写入 OpenCode 的全局配置；已有
配置会保留，改写前的原文件保存为同目录下的 `.memoryhub-backup` 备份。配置完成后
需要完全退出并重新打开 OpenCode，随后可用 `/mcps` 查看 `memoryhub` 连接状态。

## 升级与卸载

升级不会删除 `~/.local/share/MemoryHub` 中的数据库、向量索引或安全密钥。

```bash
sudo apt remove kylin-memoryhub
```

用户数据需要由用户自行明确删除，卸载脚本不会自动清理。
