# TeamAdvisor · 团队顾问 0.3.1

在当前 Windows 桌面软件的本地会话中，选择并衔接已安装的 DataLab、df-mcp 和 ETF 评论草稿 v2。本插件提供顾问入口、本机配置、任务质量反馈及有来源的个人/项目记忆；专业技能继续使用每台电脑现有的安装。

## 使用

安装后在新会话调用 `$team-advisor`，直接描述任务：

- “帮我完成首次设置，记住本机可用的技能和运行环境。”
- “按这份产品资料写三条中文社区评论，给我内部审阅。”
- “按附件计算各基金净流入，核对日期、币种和汇总口径，解释主要变化。”
- “记住：项目 A 的净流入口径是申购减赎回，赎回金额按正数输入。”
- “采用第二版，修改原因是要先交代适用场景；保存为这个项目的经验。”
- “查看项目 A 的记忆，把已经过时的这条删除。”

已有输入足够就省略检索，不需要计算就省略 DataLab。缺少某项技能时说明缺项，继续可独立完成的步骤。首次设置与后续自检由顾问处理；本地配置变化会重新检查。

## 0.3.1 新增能力

| 能力 | 行为 |
|---|---|
| 一次设置、后续复用 | 保存允许读取的技能根、明确来源和解释器；后续进程检测来源及环境变化 |
| 两种任务的质量核对 | 产品材料转评论、资金流数据转解释，各自核对事实、口径、数量和缺口 |
| 明确反馈记录 | 记录采纳/修改/拒绝及用户原因，关联任务、产物和来源版本 |
| 个人/项目记忆 | 候选与发布分离，按身份及项目读取，带来源、有效期和明确替代关系 |
| 更正与遗忘 | 更新、范围内回退及删除；已删除内容不因回退复活 |

记忆只保存选中的经验，不自动抓取聊天记录。记忆不授予访问或发布权限，历史数字仍需核对最新来源。团队共享、同事电脑和真实公司连接的验收状态见 [验证报告](docs/VALIDATION.md)。

## 安装与开发

完整仓库包含 `.agents/plugins/marketplace.json` 和 `plugins/team-advisor-entry/`。下载完整源码后，在当前客户端支持的 CLI 中运行：

```powershell
codex plugin marketplace add '<完整源码目录>' --json
codex plugin add team-advisor-entry@team-advisor-pilot --json
```

具体安装、更新和新会话检查见 [安装说明](docs/LOCAL_INSTALL.md)。

开发检查只需 Python 3.11+ 标准库：

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B tools/check_package.py
python -X utf8 -B tools/check_package.py --zip '<项目外目录>\TeamAdvisor-Entry-Source-0.3.1.zip' --plugin-zip '<项目外目录>\TeamAdvisor-Entry-0.3.1.zip'
```

GitHub Actions 已配置相同的 Windows 回归和发布检查。工作流文件存在不代表远端 CI 已运行。

## 文件与数据边界

入口插件独立分发；专业技能代码、Python 环境、个人路径、反馈记录、记忆库、认证和公司资料均不进入发布包。本地状态默认在 `%LOCALAPPDATA%\TeamAdvisor`，也可指定其他独立目录。个人/项目范围由程序筛选，不是操作系统权限隔离；不要把自己的状态目录作为团队共享盘。

`sources.json` 固定本插件文件哈希与已观察的专业资源版本。`evals/` 的素材为合成数据，场景定义与实际执行证据分开保存。[设计说明](docs/MEMORY_DESIGN.md) 说明记忆方案及验证边界。
