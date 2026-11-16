# DF Agent 0.5.0 验证

日期：2026-11-16。此版本落实五条协作准则，以及“原资料只读、指定目录按授权写入”的 B 方案。

| 验证 | 实际结果 |
|---|---|
| 完整本地回归 | 117 项：116 通过，1 项因当前账号缺少原生 symlink 权限跳过；Windows junction 测试通过 |
| 写入范围 | 无授权、错误操作、目录越界、资料根及其父目录作为写入根均被拒绝；包含硬链接、重解析点和 Windows 路径别名检查 |
| 读取无落盘 | 设置、检测、记忆和反馈读取不创建状态；记忆查询不创建锁文件；普通 Python 启动也不生成插件辅助模块字节码 |
| Windows 并发 | 子进程写者在读句柄释放后只提交一次；重试超时保留原快照并清理本次临时文件 |
| 记忆与反馈集成 | 6 项检查、12 次独立 CLI 调用通过，覆盖候选不可见、审核发布及项目/身份范围隔离 |
| 独立行为测试 | 5 个合成请求通过：模糊长方案先澄清、局部润色保留原文并提示疑点、资金流复算、仅在聊天记住偏好、无授权不调用落盘工具 |
| 独立代码复核 | 发现并修复记忆锁硬链接与 Windows 并发替换问题；复核后无未解决的实质发现 |
| 本机运行目录 | 已在当前用户的 LocalAppData 运行范围准备 indexes/cache/logs/tmp；验证商店版宿主的实际路径映射；没有启动资料库索引 |
| 发布包边界 | 运行目录、配置、记忆、反馈、日志和凭据不进入发布包；原有 LF 与指纹机制保留 |

行为测试的实际观察见 [结构化记录](../evals/results/v05-behavior-validation.json)。[场景目录](../evals/v05-cases.json) 另外定义了 8 个可重复验收场景，不代表这 8 项都已自动执行。历史业务集成结果仍见 [历史验证](VALIDATION.md)，没有改写为新版真实业务验收。

可复现命令：

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B tools/check_package.py
python -X utf8 -B tools/test_memory_integration.py --workdir '<仓库外的全新合成测试目录>'
```

GitHub Windows CI 以 [对应提交的实际运行结果](https://github.com/raymondhuang1994/DF-Agent/actions) 为准；安装后版本、原生发现与配置复用按 [安装说明](LOCAL_INSTALL.md) 单独核验。

本次没有读取或索引 `N:\digital finance`，没有迁移或改写真实配置、反馈和记忆。测试只使用合成数据。插件不改变系统 ACL，也不能替第三方工具提供操作系统隔离；公司连接、同事电脑和组织分发尚未验收。
