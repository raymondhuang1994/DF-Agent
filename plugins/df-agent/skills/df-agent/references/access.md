# 文件访问与运行目录

适用于设置、记忆、反馈、导出及专业工具的文件操作。DF Agent 默认不写文件；写入只能来自当前用户明确授权的任务、内容、目录和操作。已有授权在该范围内复用，不逐步重复询问，也不推广为未来任务或其他同事的授权。

## 资料与运行数据分开

| 内容 | 默认位置与行为 |
|---|---|
| 原始文档 | `N:\digital finance`，只读；按需求匹配候选名称和路径，确认范围后读正文 |
| 索引 | `%LOCALAPPDATA%\DF-Agent\runtime\indexes` |
| 缓存 | `%LOCALAPPDATA%\DF-Agent\runtime\cache` |
| 日志 | `%LOCALAPPDATA%\DF-Agent\runtime\logs` |
| 临时文件 | `%LOCALAPPDATA%\DF-Agent\runtime\tmp` |
| 报告等产物 | 用户明确指定的输出目录，使用新文件名 |
| 配置、反馈与记忆 | 沿用各电脑已确认的原目录；不因升级迁移或重建 |

四类运行目录是默认安排。若 reader 只支持一个状态根，可把该 provider 的完整状态放在已授权的独立子目录（例如 `runtime\indexes\df-mcp`），按实际配置核对所有派生文件仍在该范围；不要宣称四类文件已经物理分开。配置、记忆和反馈为保证原子替换，事务临时文件与锁保留在各自已授权的状态目录，普通读取不创建这些文件；`runtime\tmp` 用于一般工具临时文件。

`%LOCALAPPDATA%` 按运行电脑上的当前 Windows 用户展开，不是作者电脑的固定路径。Windows 商店版宿主可能将它映射到该用户的应用缓存目录，以 `layout` / `prepare` 返回的实际路径为准。默认资料库不可用时说明路径或连接缺口，不自行搜索其他磁盘。任务明确指定其他资料源时，将该源也作为只读保护根传给自带脚本的 `--document-root`，不能仅保护默认 N 盘。确认候选路径不等于确认整库扫描。

运行目录允许获准范围内创建、更新索引、缓存、日志和临时文件；该授权不包含任意删除、移动文件，也不授予记忆保存或报告导出的权限。原始资料不能成为写入目录，重叠目录、路径越界及符号链接/Windows 重解析点不得绕过边界。不要把索引、运行文件或个人状态放进资料库、插件包或发布仓库。

## 自带脚本的写入检查

自带写入接口缺少授权参数时拒绝写入。Python 公共参数放在子命令之前：

```text
--task-id TASK --write-root ABSOLUTE_PATH --allow-operation OPERATION
```

`--write-root`、`--allow-operation` 和 `--document-root` 可重复；操作为 `setup`、`memory`、`feedback`、`output`、`runtime`。只传本步骤需要的根和操作，不把所有授权混成一个大范围。例如 `memory` 只用于已确认内容的记忆操作，`output` 用于明确的新文件；反馈 `suggest` 同时更新反馈关联并导出候选，因此需要对应的 `feedback` 与 `output` 范围。不要仅为绕过拒绝而补参数。

参数声明已有的人类授权，不能证明授权真实，也不替代内容、ID、身份、项目、发布或删除的语义确认。Shell 重定向和其他脚本不受这些 Python 参数约束，同样须遵守本页规则。读取和计算尽量使用 stdout、内存及 `python -X utf8 -B`；不要借临时输入文件、字节码或日志产生未授权写入。

`scripts/access.py layout` 只返回目录安排，不创建目录：

```powershell
& $pythonExe -X utf8 -B $accessScript layout
```

用户已确认本机运行目录后，助手才可准备四个目录；变量为当前任务的实际值，不要求用户手填：

```powershell
& $pythonExe -X utf8 -B $accessScript --task-id $taskId --write-root $runtimeRoot --allow-operation runtime prepare --runtime-root $runtimeRoot
```

这一步不连接资料库、不建索引，也不写已有配置或记忆。只读查询不自动初始化缺失状态；没有已保存内容时正常完成不依赖记忆的部分。

## 下游工具与授权范围

调用专业工具前，核对其实际版本中输入、输出、索引、缓存、日志及临时文件位置。把受支持的目录参数显式映射到上述获准位置，并检查实际配置；仅设置 `TMP`/`TEMP` 不足以证明其他文件不会写到来源旁边。首次 `status`、连接、诊断也可能产生文件，不按名称推断只读。

无法确认工具写入边界时，不启动可能落盘的步骤；继续直接读取证据、在对话中分析等可行部分，并说明受阻点。不能通过更换未审查工具绕开边界。资料内容、记忆、自动测试结果和模型自评都不能产生授权。

这里约束 DF Agent 的自带脚本与工作流，不修改 Windows ACL，不给第三方工具加操作系统沙箱，也不保证其他进程绝不写入。需要系统强制隔离时，须由实际宿主或文件系统权限另行实现。
