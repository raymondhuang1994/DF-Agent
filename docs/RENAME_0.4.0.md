# DF Agent 0.4.0：改名与兼容

从 0.4.0 起，项目和插件统一使用 **DF Agent**。本次调整名称、安装标识和文件路径；业务流程、专业技能来源、用户资料范围及记忆的授权规则沿用原有实现。

| 项目 | 新名称或位置 |
|---|---|
| 用户界面显示名 | DF Agent |
| GitHub 仓库 | [raymondhuang1994/DF-Agent](https://github.com/raymondhuang1994/DF-Agent) |
| 插件与 marketplace 标识 | `df-agent` |
| 安装选择器 | `df-agent@df-agent` |
| Skill 调用 | `$df-agent`；宿主目录可能显示 `df-agent:df-agent` |
| 插件目录 | `plugins/df-agent/` |
| Skill 目录 | `plugins/df-agent/skills/df-agent/` |
| 完整源码包 | `DF-Agent-Source-0.4.0.zip` |
| 插件本体包 | `DF-Agent-0.4.0.zip` |

## 本地数据继续可用

Windows 新安装默认使用 `%LOCALAPPDATA%\DF-Agent`。默认目录选择规则为：

1. 用户显式给出 `-StateDir` 时，始终使用该目录。
2. 新目录中存在 `setup.local.json` 时，使用新目录。
3. 新目录没有配置，而旧 `%LOCALAPPDATA%\TeamAdvisor\setup.local.json` 存在时，继续使用旧目录和已保存的解释器、技能绑定。
4. 两边都没有配置时，为新安装选择 `%LOCALAPPDATA%\DF-Agent`。

这不是数据迁移：不移动、复制或合并设置、反馈及记忆。原来明确指定的记忆库路径继续使用原路径；不能仅凭项目改名猜测或创建另一个空库。两个目录同时有配置时，如需使用旧目录，应显式传入它。

为保证已有状态和检测报告仍可读取，内部持久化 schema 标识保留 `team-advisor-setup/1`、`team-advisor-setup-plan/1` 与 `team-advisor-capabilities/1`。这些是文件格式版本，不是用户界面名称。

## 升级顺序

按 [安装说明](LOCAL_INSTALL.md) 安装新的 `df-agent@df-agent`，检查安装版本、启用状态以及新会话原生发现，然后验证本人原配置可读取。确认新入口正常后再移除旧 `team-advisor-entry@team-advisor-pilot` 和旧 marketplace `team-advisor-pilot`。仅清理旧插件注册与缓存，保留状态和记忆目录。

## 历史记录与验证

旧版报告、已有合成任务答复、原始交接文件名及旧版发布标签保留当时名称和版本，避免把历史测试改写成新版本测试。查看 [历史验证报告](VALIDATION.md) 时应按其中实际版本理解；旧记录中的 TeamAdvisor、team-advisor-entry 或旧路径并不表示新入口仍使用旧名称。

0.4.0 的本地回归、实际安装、新会话发现和旧配置复用结果见 [本版验收](VALIDATION_0.4.0.md)。发布与远端 CI 以对应标签和提交的实际状态为准。
