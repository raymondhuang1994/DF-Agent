# 安装 DF Agent 0.6.0

目标是用户当前使用的 Windows 桌面软件。DF Agent 0.6.0 明确 Router/Advisor 与专业技能的分工，增加 reader 包完整性及输入格式依赖检查，沿用现有专业技能与本地数据格式。此前 TeamAdvisor 0.3.1 的安装及发现记录保留在 [历史验证报告](VALIDATION.md)，新版本需按以下步骤核验。

## 从 GitHub 安装

仓库：[raymondhuang1994/DF-Agent](https://github.com/raymondhuang1994/DF-Agent) 已公开，可直接查看、下载和克隆，不需要单独授予仓库权限。共享插件不共享本机记忆与业务资料权限。

```powershell
codex plugin marketplace add https://github.com/raymondhuang1994/DF-Agent.git --ref '<实际已发布标签或审核过的提交>' --json
codex plugin add df-agent@df-agent --json
```

安装前在仓库发布页核实实际标签；源码版本号本身不代表该版本已发布。也可下载完整源码 ZIP，解压后把第一个命令的来源替换为包含 `.agents/plugins/marketplace.json` 的目录。插件 ZIP 只包含插件自身，不能当作完整 marketplace 根目录。CLI 未在 PATH 时，用当前客户端实际提供的 codex.exe。

安装后开启新会话，调用 `$df-agent`（目录可能显示 `df-agent:df-agent`），说“帮我完成首次设置”。顾问先给出可读的配置计划；你确认保存位置和设置操作后，再保存本机解释器与技能来源。只读回答不要求先落盘配置。

已有 `df-agent` 的电脑先检查 marketplace 当前来源，再按客户端实际支持的更新流程切换到实际选定版本并重新安装；不要重复注册同名 marketplace。新版入口不重建既有记忆。

## SkillHub 完整包

使用 `python tools/check_package.py --skill-package <仓库外路径>/DF-Agent-0.6.0.skill` 构建独立 Skill 包。它包含唯一的根级 `SKILL.md` 以及完整 `references/`、`scripts/`、`agents/`，与插件使用同一份源文件。选择 SkillHub 的 **ZIP / .skill** 上传入口；完整源码 ZIP 和插件 ZIP 各有自己的目录布局，不能替代此包。

下载并安装时保留目录结构，核对发布版本和 SHA-256。SkillHub 分发脚本，不代为执行。独立 Skill 安装和插件安装都会将设置、记忆、反馈及运行状态放到已授权的包外目录。DF MCP、DataLab、评论草稿技能和 Python 解释器仍是外部依赖，不在入口包重复分发。

## 从旧入口升级

先按上面的命令安装新 `df-agent` 来源与插件，保留旧入口供验证期间使用。核对 `codex plugin list --marketplace df-agent --json` 显示所选版本、已安装且启用，再在新会话确认 `$df-agent` 原生可见，并能读取本人原有的设置。只读检查不要重新初始化既有记忆库。

新入口确认正常后，按当前客户端已核实的 CLI 语法移除旧入口和旧 marketplace：

```powershell
codex plugin remove team-advisor-entry@team-advisor-pilot --json
codex plugin marketplace remove team-advisor-pilot --json
```

这两步针对旧插件缓存及注册信息，不删除本地设置、反馈或记忆目录。不要手动删除 `%LOCALAPPDATA%\TeamAdvisor`；新入口可能正在兼容使用它。迁移说明与旧名称保留原因见 [改名与兼容说明](RENAME_0.4.0.md)。

## 各电脑首次设置

新安装的 Windows 默认状态在 `%LOCALAPPDATA%\DF-Agent`。未找到新目录的配置、且 `%LOCALAPPDATA%\TeamAdvisor\setup.local.json` 已存在时，会沿用旧状态目录；两个目录都存在配置时优先使用新目录。显式 `-StateDir` 始终优先。这里只选择要使用的目录，不迁移或合并数据。配置只读取已批准技能根的公共文件；同名多份需要确定绑定。状态未变化不代表所有业务任务就绪。

DataLab、df-mcp、ETF 评论草稿 v2 由每位同事自己的安装提供。缺少某项可先用其他能力；插件不复制专业技能、私库或独立 Python 环境。公司资料连接由本人确定资料范围和权限后另行配置。不要把状态目录上传 GitHub。

索引、缓存、日志和临时文件使用本机 `%LOCALAPPDATA%\DF-Agent\runtime` 下的 `indexes`、`cache`、`logs`、`tmp` 子目录，首次先展示安排并确认。旧版 `N:\digital finance` 保持受保护，实际来源以 df-mcp 的已确认 profile/配置为准；不按默认路径选源或扩大扫描。创建运行目录不会自动配置 reader 或建立索引。详见 [规则与文件策略](POLICY_0.5.0.md)。

首次启用记忆时确定本人标识和项目标识。个人/项目记忆保存在明确指定的本地目录，未审核候选不用于普通任务，当前指令优先。调用入口的“记住”“更正”“忘记”由顾问按具体内容、目录和操作授权执行；插件安装和本机运行目录的授权不代表所有记忆都可自动保存。

## 更新与核验

```powershell
codex plugin list --marketplace df-agent --json
```

确认安装版本与启用状态，再在新会话检查原生入口。不同来源（本地目录和 Git）不要重复注册同名 marketplace；迁移来源时先查看当前 marketplace 列表，保留原配置并使用客户端支持的管理命令。

每台同事电脑各跑一次合成表格和三条评论任务；文件扫描、宿主发现、依赖、真实结果分别记证据。合成 reader 成功不等于真实公司资料连接通过。组织工作区导入及管理员分发需在实际账户验收。

可复制的测试提示词、示例文件和预期结果见 [试用与测试指南](TRY_IT.md)。
