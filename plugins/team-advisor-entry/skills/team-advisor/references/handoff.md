# 跨技能交接

沿用专业技能原生产物，不要求重写成统一框架。顾问在上下文中保留下列最少信息，最终回答只呈现用户核验需要的部分：

```yaml
task:
  objective: 用户交付目标
  confirmed: 数量、范围、期间、单位、产品角色、指标定义
stage:
  skill_id: 实际逻辑 ID
  source_ref: 当前选定来源
  source_fingerprint: 已读取公共文件的 SHA-256；未算则 null
  access_mode: native_skill 或 explicit_file_playbook
  task_profile: 本次具体任务能力
  execution_environment: 实际执行环境
  state: completed | partial_result | needs_input | dependency_unavailable
inputs:
  - id: 稳定引用
    source: 实际来源
    locator: 页码、单元格、段落或真实工具返回位置
    version: 实际版本或哈希；未知写未知
    observed_at: 实际读取时间
    coverage: 已定义全集或局部范围，以及遗漏
artifacts:
  - path_or_handle: 当前执行者可访问的数据或产物
    readable: 根据实际读取结果填写
facts_and_metrics:
  - statement: 有据事实或计算值
    evidence: 输入或计算产物引用
    definition: 单位、周期、分母、过滤、缺失值规则
native_validation: 保留原工具的原值
limitations: 影响下游的缺口
pending: 剩余必要输入或能力
```

项目阶段状态不是平台 API 状态，不能覆盖原工具返回值。

**df-mcp → DataLab：**交接数据本体、定位、版本、筛选与覆盖。先验证当前计算环境能读取导出；服务端 `artifact_path` 字符串不能代替数据。全集排名先枚举应纳入范围；Top-K 搜索只支持局部结论。跨文件读取是观察窗口，不声称原子快照。

**DataLab → ETF：**交接已验证指标、口径、比较基准、表格/claim 引用及局限。保留 `validation.checks_status` 和 `validation.status`；`needs_review` 不代表程序还在运行。无法验证的数字不写进草稿，仍可完成不依赖该断言的部分。

**df-mcp → ETF：**交接本轮产品身份、角色和事实依据；原帖、产品事实、风格例分开。旧案例的费率、日期和经历不是当前事实。

继续任务时复用已确认决定和未变化输入。来源、期间或口径变化，只重做受影响部分；不要每个阶段重问整项需求。
