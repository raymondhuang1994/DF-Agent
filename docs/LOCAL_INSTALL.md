# 安装 TeamAdvisor 0.3.1

目标是用户当前使用的 Windows 桌面软件。已在应用 26.1106.51428（构建 26605）随附 CLI 中实际安装、启用，并由新临时会话原生发现入口。已有三项专业技能保持原安装。

## 从 GitHub 安装

仓库：[raymondhuang1994/TeamAdvisor](https://github.com/raymondhuang1994/TeamAdvisor) 已公开，可直接查看、下载和克隆，不需要单独授予仓库权限。共享插件不共享本机记忆与业务资料权限。

```powershell
codex plugin marketplace add https://github.com/raymondhuang1994/TeamAdvisor.git --ref v0.3.1 --json
codex plugin add team-advisor-entry@team-advisor-pilot --json
```

也可下载完整源码 ZIP，解压后把第一个命令的来源替换为包含 `.agents/plugins/marketplace.json` 的目录。插件 ZIP 只包含插件自身，不能当作完整 marketplace 根目录。CLI 未在 PATH 时，用当前客户端实际提供的 codex.exe。

安装后开启新会话，调用 `$team-advisor`（目录可能显示 `team-advisor-entry:team-advisor`），说“帮我完成首次设置”。顾问保存本机解释器和技能来源，正常提问即可使用。

## 各电脑首次设置

Windows 默认状态在 `%LOCALAPPDATA%\TeamAdvisor`，或用户明确选择的独立本地目录。配置只读取已批准技能根的公共文件；同名多份需要确定绑定。状态未变化不代表所有业务任务就绪。

DataLab、df-mcp、ETF 评论草稿 v2 由每位同事自己的安装提供。缺少某项可先用其他能力；插件不复制专业技能、私库或独立 Python 环境。公司资料连接由本人确定资料范围和权限后另行配置。不要把状态目录上传 GitHub。

首次启用记忆时确定本人标识和项目标识。个人/项目记忆保存在明确指定的本地目录，未审核候选不用于普通任务，当前指令优先。调用入口的“记住”“更正”“忘记”由顾问按实际授权与版本执行。

## 更新与核验

```powershell
codex plugin list --marketplace team-advisor-pilot --json
```

确认安装版本与启用状态，再在新会话检查原生入口。不同来源（本地目录和 Git）不要重复注册同名 marketplace；迁移来源时先查看当前 marketplace 列表，保留原配置并使用客户端支持的管理命令。

每台同事电脑各跑一次合成表格和三条评论任务；文件扫描、宿主发现、依赖、真实结果分别记证据。合成 reader 成功不等于真实公司资料连接通过。组织工作区导入及管理员分发需在实际账户验收。

可复制的测试提示词、示例文件和预期结果见 [试用与测试指南](TRY_IT.md)。
