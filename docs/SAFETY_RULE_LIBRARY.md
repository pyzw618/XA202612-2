# 安全规则库：版本与溯源设计

> **状态说明（核对日期：2026-07-24）**：`memoryhub.safety_rules` 已实现声明式
> 严格 JSON 规则集、`catalog.json` 默认/显式版本选择、规范化摘要校验、不可变数据模型、
> 结构化 `standard_ref` 溯源、固定且带版本的 validator/masker 注册表，以及
> `target_paths` 校验与编译。当前内置候选校验包括公民身份号码的出生日期、顺序码和
> MOD 11-2 校验、标准库 IP 地址解析、JWT 结构、Luhn、邮箱等。已注册的 masker
> 可被显式解析和调用；`redact_allow` 还要求注册表显式声明 `full_redaction`
> 能力并通过契约探针。递归事件扫描已接入同一快照的 validator、priority 和资源预算；
> 确定性策略聚合、作用域化有限期例外、全值类型标记脱敏、同规则快照复检、内存审计投影、
> 持久 HMAC 审计链、人工复核加密隔离和普通写入 Gate 已实现；运行时边界以
> [`INTERFACE.md`](INTERFACE.md) 为准。

## 1. 目标与非目标

规则库需要回答三个彼此独立的问题：

1. **为什么把某类信息纳入保护范围**：来自法律、国家标准或风险指南的分类依据。
2. **怎样识别一个格式候选并验证其语义**：来自强制性格式标准、协议 RFC、
   厂商格式文档或项目检测策略。
3. **命中后怎样处理**：由项目威胁模型和版本化安全策略决定，并参考相关处理、
   去标识化、效果评估和审计要求。

本文不把法律或标准直接翻译成正则，也不以“引用了某标准”代替符合性评估。
规则命中仅表示发现了一个候选风险；是否构成个人信息、敏感个人信息或有效凭据，
仍可能依赖语义校验、字段路径、上下文、信息聚合和人工复核。

## 2. 来源类型与效力边界

`RuleDefinition.standard_ref` 已实现为 `RuleSourceLink` 列表，不把不同效力的来源
压平为一个字符串。每个关联对象都应区分以下来源类型：

| `source_kind` | 含义 | 在规则库中的作用 | 不应作出的表述 |
|---|---|---|---|
| `law` | 现行法律 | 定义保护对象、处理原则和法定义务 | “法律规定了该正则” |
| `mandatory_gb` | 强制性国家标准 `GB` | 提供必须执行的技术要求或编码规则 | “该标准决定了 MemoryHub 的默认动作” |
| `recommended_gbt` | 推荐性国家标准 `GB/T` | 提供分类、工程、处理、评估和审计参考 | 未评估适用范围即声称“完全合规” |
| `tc260_guide` | TC260 网络安全标准实践指南 | 提供识别规则、类别示例和实践指引 | 将其称为国家标准或强制要求 |
| `ietf_rfc` | IETF/RFC Editor 发布的协议文件 | 提供互联网协议语法和语义 | 将 RFC 称为中国国家标准或个人信息分类依据 |
| `vendor_doc` | 凭据签发方的官方文档 | 提供特定产品凭据的名称、前缀、组合和轮换信息 | 从示例值反推未公开的稳定格式合同 |
| `security_guidance` | 权威安全组织的实践指南 | 支撑凭据风险、生命周期和审计设计 | 将指南称为法律或合规认证 |
| `project_policy` | Kylin-MemoryHub 自身策略 | 确定候选检测、置信度、风险等级和默认动作 | 将项目的保守策略归因于外部标准 |

根据国家市场监督管理总局公布的
[《中华人民共和国标准化法》第二条](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_d7040b9f1d0f4980a0e55089a57bf37d.html)，
强制性标准必须执行，国家鼓励采用推荐性标准。推荐性标准在被法律法规引用、
被企业自我声明采用或成为合同依据时，可能产生相应约束力，因此不能简单标记为
“永远不具约束力”。

## 3. 中国法律、国标与实践指南目录

以下状态均以 2026-07-24 为准。来源状态变化时应新增状态记录，不能覆盖历史快照。

| `source_id` | 来源、效力和当前状态 | 项目用途 | 关键 caveat |
|---|---|---|---|
| `pipl-2021-art28` | [《中华人民共和国个人信息保护法》](https://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html)，`law`；2021-08-20 通过，依据[主席令第九十一号](https://www.npc.gov.cn/c2/c30834/202108/t20210820_313045.html)自 2021-11-01 施行 | 内置规则当前以第 28 条作为敏感个人信息的 `classification` 依据；更广泛的法律适用分析应另建精确来源关联 | 第 28 条是风险导向且使用“等信息”，不是穷尽词表；不提供任何检测正则 |
| `gbt-35273-2020` | [GB/T 35273-2020《信息安全技术 个人信息安全规范》](https://std.samr.gov.cn/gb/search/gbDetailed?id=A0280129495AEBB4E05397BE0A0AB6FE)，`recommended_gbt`；2020-03-06 发布，2020-10-01 实施，现行 | 个人信息类别、示例和通用处理安全要求 | 2026-01-28 复审结论为“修订”；[修订计划 20260700-T-469 正在征求意见](https://www.tc260.org.cn/portal/suggestion-detail/ef5518f3213b4ec5bc5f3f2ce5ce1bee)。现行规则必须锁定 `2020` 版，征求意见稿不得替代现行依据 |
| `tc260-pg-20244a` | [《网络安全标准实践指南——敏感个人信息识别指南》](https://www.tc260.org.cn/portal/article/2/20240918084858)，`tc260_guide`；2024-09 发布 | 敏感个人信息识别规则、常见类别和示例；单项及多项一般个人信息汇聚/融合风险 | 不是国家标准；聚合风险不能只靠单字段正则表达 |
| `gbt-45574-2025` | [GB/T 45574-2025《数据安全技术 敏感个人信息处理安全要求》](https://std.samr.gov.cn/gb/search/gbDetailed?id=33D40F1161155D92E06397BE0A0A5B93)，`recommended_gbt`；2025-04-25 发布，2025-11-01 实施，现行 | 敏感个人信息处理活动的安全要求，可用于策略和保护措施映射 | 不是邮箱、证件号码或凭据格式规范，不能作为正则来源 |
| `gb-11643-1999` | [GB 11643-1999《公民身份号码》](https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D75D5FD3A7E05397BE0A0AB82A)，`mandatory_gb`；1999-01-19 发布，1999-07-01 实施，现行 | 公民身份号码的结构、表现形式和校验依据 | 只覆盖公民身份号码，不覆盖护照等其他证件；18 位正则只能生成候选，后续还需日期、顺序码和 MOD 11-2 校验码等语义验证 |
| `gbt-37964-2019` | [GB/T 37964-2019《信息安全技术 个人信息去标识化指南》](https://std.samr.gov.cn/gb/search/gbDetailed?id=91890A0DA4AB80C6E05397BE0A0A065D)，`recommended_gbt`；2019-08-30 发布，2020-03-01 实施，现行；2025-12-08 复审结论为“继续有效” | 设计替换、泛化、扰动、假名化等去标识化方式 | 去标识化不等于匿名化；仍可借助额外信息关联自然人的数据仍是个人信息 |
| `gbt-42460-2023` | [GB/T 42460-2023《信息安全技术 个人信息去标识化效果评估指南》](https://std.samr.gov.cn/gb/search/gbDetailed?id=F789206610ADB223E05397BE0A0AE533)，`recommended_gbt`；2023-03-17 发布，2023-10-01 实施，现行 | 设计脱敏后复检、重标识风险和效果评估 | 用于评估结果，不定义检测正则或固定掩码文本 |
| `gbt-41817-2022` | [GB/T 41817-2022《信息安全技术 个人信息安全工程指南》](https://std.samr.gov.cn/gb/search/gbDetailed?id=EB58F4DA9267B2A2E05397BE0A0A7D33)，`recommended_gbt`；2022-10-12 发布，2023-05-01 实施，现行 | 规则需求、设计、开发、测试、发布、监测和退役的生命周期参考 | 不直接决定单条规则的 `pattern`、风险等级或动作 |
| `gbt-46903-2025` | [GB/T 46903-2025《数据安全技术 个人信息保护合规审计要求》](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=EC64C138A5B6A52AA5DC5A60188FC07E&refer=outter)，`recommended_gbt`；2025-12-31 发布，2026-07-01 实施，现行 | 个人信息保护合规审计流程、证据和报告的映射依据 | 不能声称其规定了本项目的具体运行时字段；其主题是个人信息合规审计，不当然覆盖所有非个人信息类凭据秘密 |

## 4. “标准—用途—规则”溯源矩阵

内置 `builtin-1.0.json` 已包含具体声明式规则；其 `pattern`、`target_paths` 和
validator 可用于单个候选的校验。一条规则可以有多个来源，但每个来源只能承担其明确的
`role`。递归扫描、单事件原子处置、REVIEW 隔离、审计持久化和强制 Gate 已实现；
普通存储与 Embedding 的业务算法仍是脚手架，只能作为受保护 sink 接入。跨字段/
跨事件聚合与表中标为“规划”的规则族不属于当前内置快照。

| 规则族或候选规则 | 分类依据 | 格式或验证依据 | 处理、评估或审计依据 | 项目策略边界 |
|---|---|---|---|---|
| `id_card` | `pipl-2021-art28` | `gb-11643-1999` | `gbt-37964-2019`、`kmh-policy-1.0` | 当前 `builtin.cn_resident_id@1.0` 已校验日期、非零顺序码和 MOD 11-2 校验位；尚未接入行政区划历史码表 |
| `phone` | `gbt-35273-2020` | `kmh-policy-1.0`；号码政策背景可查[工信部《电信网编号计划（2017年版）》](https://www.miit.gov.cn/jgsj/xgj/wjfb/art/2020/art_eb0adf5b6e7148cbb70802b264878b1e.html)，国际号码可参考 [ITU-T E.164](https://www.itu.int/itu-t/recommendations/rec.aspx?rec=E.164) | `kmh-policy-1.0` | 当前 `1[3-9]\d{9}` 及 `builtin.cn_mobile@1.0` 只是项目级中国大陆移动号码候选；号段会调整，不能声称该正则来自 GB/T 35273 |
| `email` | `gbt-35273-2020`，且需判断是否与可识别自然人有关 | `rfc-5322`（[§3.4.1](https://www.rfc-editor.org/rfc/rfc5322.html#section-3.4.1)）；支持国际化邮箱时需另行引入 [RFC 6531](https://www.rfc-editor.org/rfc/rfc6531.html) | `kmh-policy-1.0` | 当前 `builtin.email_ascii@1.0` 只验证常见 ASCII addr-spec 子集，不是完整 RFC 解析器；角色邮箱和系统邮箱未必是个人信息 |
| `ip_address` | `gbt-35273-2020`，需结合主体可识别性和使用场景 | `rfc-3986`（IPv4 文本候选，[§3.2.2](https://www.rfc-editor.org/rfc/rfc3986.html#section-3.2.2)）、`rfc-4291`（IPv6 边界，[§2.2](https://www.rfc-editor.org/rfc/rfc4291.html#section-2.2)） | `kmh-policy-1.0` | 当前规则只产生 IPv4 候选，再由 `builtin.ip_address@1.0` 调用标准库解析器排除越界地址；尚未启用 IPv6 候选正则，且 IP 地址不当然对应自然人 |
| 规划：`personal_info_aggregate` | `pipl-2021-art28`、`tc260-pg-20244a` | 场景化关联和聚合评估，不存在单一格式标准 | `gbt-45574-2025`、`gbt-41817-2022` | 需要跨字段或跨事件策略；当前内置快照及扫描管线均未实现该判定 |
| `credential_field`、`api_key` | 凭据秘密与个人信息应分开分类 | 字段名和赋值语法来自 `kmh-policy-1.0`；`owasp-secrets` 对应 [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html) 的威胁模型建议 | `kmh-policy-1.0`、`owasp-secrets` | `api_key|secret|password|token` 是保守启发式，不是国标、RFC 或厂商格式；密码、私钥和 Token 未必属于个人信息，但通常具有更高系统风险 |
| `credential.bearer_token` | 凭据类别，不应自动归入个人信息 | `rfc-6750`（[§2.1](https://www.rfc-editor.org/rfc/rfc6750.html#section-2.1)）定义 `Authorization: Bearer` 上下文和语法 | `kmh-policy-1.0` | RFC 只提供协议语法，不决定是否 `reject`；脱离 `Bearer` 上下文的相似字符串置信度应降低 |
| `credential.jwt` | 取决于 Token 的用途和载荷 | `rfc-7519`（[§3](https://www.rfc-editor.org/rfc/rfc7519.html#section-3)）定义 JWT 表示结构 | `kmh-policy-1.0` | 当前 validator 只解析三段 compact serialization 的 JSON 头与载荷，不验证签名、有效期或授权能力 |
| `credential.private_key` | 凭据或密钥材料类别 | `rfc-7468`（[§10—11](https://www.rfc-editor.org/rfc/rfc7468.html#section-10)）定义 `PRIVATE KEY` 和 `ENCRYPTED PRIVATE KEY` 文本边界 | `kmh-policy-1.0` | 当前 validator 覆盖部分 PEM 私钥标签，不覆盖所有厂商或 OpenSSH 私有格式；已加密私钥仍按高风险密钥材料处理 |
| 规划：`vendor_access_key`、`vendor_security_token` | 厂商凭据类别 | 必须引用签发方官方格式或凭据文档，例如 [AWS IAM 标识符](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html)、[阿里云 AccessKey](https://help.aliyun.com/zh/ram/user-guide/create-an-accesskey-pair)、[腾讯云 SecretId/SecretKey](https://cloud.tencent.com/document/product/436/44352) | 厂商轮换/吊销指南及项目策略 | 当前内置快照没有厂商专用规则；文档示例不是稳定正则合同，缺少官方格式保证时应使用字段路径、上下文和熵等组合启发式并明确标为项目策略 |

当前内置快照还包含 `sensitive_personal.bank_card`、
`sensitive_personal.biometric_field`、`sensitive_personal.health_field`、
`sensitive_personal.location_trace_field` 和 `sensitive_personal.minor_age`。这些规则分别
使用 Luhn、字段路径或年龄 validator 生成候选，并按 `redact_allow`、`reject` 或
`review` 建模；这些动作现已由递归策略执行器聚合，其中 `redact_allow` 只有在
全值脱敏、同规则快照复检无残留且幂等后才能继续普通写入链。

[GitHub 的受支持秘密扫描模式说明](https://docs.github.com/en/code-security/reference/secret-security/supported-secret-scanning-patterns)
明确提醒服务提供商会定期更新 Token 格式，并可能同时支持多个版本。项目可以借鉴其
“通用模式、AI 模式、厂商模式”分层，但不能把 GitHub 的扫描能力或未公开正则视为
本项目已经实现的能力。

## 5. 最小溯源数据模型

实现已将“来源目录”和“规则对来源的引用”分开。这样同一来源只维护一次状态，
历史规则快照也可以稳定复现。

### 5.1 来源目录

```yaml
source_id: "gb-11643-1999"
source_kind: "mandatory_gb"
identifier: "GB 11643-1999"
title: "公民身份号码"
edition: "1999"
issuer: "国家质量技术监督局"
normative_force: "强制性国家标准"
published_on: "1999-01-19"
effective_on: "1999-07-01"
status: "现行"
status_as_of: "2026-07-24"
official_url: "https://std.samr.gov.cn/gb/search/gbDetailed?id=71F772D75D5FD3A7E05397BE0A0AB82A"
supersession_candidate: ""
caveat: "用于公民身份号码结构和校验；不定义个人信息分类、处置动作或其他证件格式。"
```

当前 `RuleSource` 模型字段如下；`edition`、`supersession_candidate` 默认为空字符串，
`published_on`、`effective_on` 可为空，其余字段由模型校验：

```text
source_id
source_kind
identifier
title
edition
issuer
normative_force
published_on
effective_on
status
status_as_of
official_url
supersession_candidate
caveat
```

若项目保存了官方全文副本，可另外记录 `retrieved_at` 和文件 `sha256`。动态网页本身
不宜直接作为稳定内容摘要；摘要应针对实际归档的官方文件计算。

### 5.2 规则中的来源引用

```yaml
standard_ref:
  - source_id: "pipl-2021-art28"
    role: "classification"
    locator: "第二十八条"
    derivation_note: "公民身份号码候选按特定身份信息进行高风险评估"
    caveat: "法律提供分类依据，不提供号码正则"
  - source_id: "gb-11643-1999"
    role: "semantic_validation"
    locator: "出生日期码、顺序码、校验码"
    derivation_note: "正则仅找候选，validator 检查日期、顺序码与 MOD 11-2 校验位"
    caveat: "当前未接入行政区划历史码表"
  - source_id: "kmh-policy-1.0"
    role: "risk_policy"
    locator: "identity number default action"
    derivation_note: "选择 redact_allow、review 或 reject"
    caveat: "默认动作来自项目策略，不来自 GB 11643"
```

每个 `RuleSourceLink` 使用以下字段；`locator` 可为空，其他字段由当前模型校验：

```text
source_id
role
locator
derivation_note
caveat
```

声明式资产以 `RuleDefinition.standard_ref` 作为机器可解析的权威溯源。加载器编译到旧
`SensitiveRule` 时，会把 `source_id`、`role` 和 `locator` 展平到字符串
`standard_source`，该字段仅用于运行时兼容和展示，不能反向替代结构化目录与关联记录。
协议、厂商文档、OWASP 和项目策略也不能伪装成 `GB/T`。

## 6. 规则版本与来源状态

当前版本链由 catalog、规则集文档和单条规则三层组成：

```text
catalog.json:
  schema_version, rule_set_id, default_version
  versions[].version, versions[].resource, versions[].snapshot_digest

RuleSetDocument:
  schema_version, rule_set_id, version, released_on, status_as_of
  sources, governance_ref, rules

RuleDefinition:
  rule_id, rule_version, enabled, category, risk_level, default_action
  pattern, validator, masker, target_paths, target_path_case_sensitive
  priority, standard_ref
  reason_code, reason, replacement, match_group
```

当前 catalog 的默认且唯一内置版本是 `1.0`。加载器按 UTF-8 严格解析 JSON、拒绝重复键和
非有限数、过深结构和未知字段，日期只接受 `YYYY-MM-DD`，并原子校验整个规则集；
内置资源还必须与 catalog 中的规范化 SHA-256 `snapshot_digest` 一致。catalog
资源名同时按 POSIX 和 Windows 纯文件名规则校验，不能越出包资源目录。

规则集、单规则、catalog 和组件引用共用严格的两段/三段版本语法，并按规范化版本
（例如 `1.0` 与 `1.0.0` 等价）检查冲突。快照摘要同时覆盖声明式文档、编译器 schema、
完整 `compiled_rules`，以及当前规则实际引用组件的实现指纹和 masker capability；
新增未引用组件不会改写旧快照摘要。相同 `source_id` 的来源内容也会跨 catalog 快照锁定，
来源新版必须使用新 ID。

自动组件指纹只接受可检查源码的 Python 函数，递归覆盖项目 helper、正则/常量及所用
模块符号身份，并拒绝 closure 和可变全局依赖；调用方给出的指纹只能作为预期值校验，
不能跳过实际计算。该机制用于规则发布和受信进程内的漂移检查，不是抵御任意进程内篡改的
沙箱。当前扫描器在一次扫描开始时校验注册表一次，不在每个候选上反复读取源码。

外部规则文件仍属于受信任配置输入；正则回溯门禁会拒绝嵌套重复、重复组内分支、
有重叠候选的相邻重复和过大有界重复，但它不是对任意表达式运行时间的形式化证明。
当前扫描器同时限制单字段、总字节、结构节点、候选和 Finding 数；结构预算在
Pydantic 序列化和事件摘要之前以显式栈检查并建立有界快照，失败时抛出不含输入的
稳定 `SafetyScanError`。快照后的候选/Finding 超限则产生不完整报告。这些预算
不等同于正则引擎的硬超时。

版本管理遵循以下原则：

1. 法律、标准、RFC 或厂商文档出现新版时，先新增来源记录和
   `supersession_candidate`，不得原地修改旧来源的版次、日期或 URL。
2. “已发布”与“已实施”分开记录；尚未实施的新国标不能提前覆盖现行规则。
3. 征求意见稿只允许作为 `draft_watch` 或替代候选，不能进入生产规则的规范性引用。
4. 来源变化不会自动改变 `default_action`。必须重新完成适用范围、误报/漏报、
   脱敏效果和策略影响评估，再发布新的规则集 `version`。
5. 关闭规则应通过新快照把 `enabled` 设为 `false`，并保留旧资源及其摘要。当前模型没有
   单规则 `effective_to` 字段，历史时点恢复依赖归档规则集版本和 digest，不能只覆盖原文件。
6. 当前模型 `extra="forbid"`，尚无 `vendor`、`product`、`format_version` 和
   `verified_on` 字段。引入厂商专用规则时，应先以新版 schema 或专门来源记录承载这些
   元数据；官方未承诺稳定格式时，不能把样例前缀或长度标为完整验证规则。
7. `redact_allow` 的 replacement 只能使用固定的 `[REDACTED...]` 标记；自定义
   masker 必须由创建 `ComponentRegistry` 的受信任代码显式证明
   `full_redaction` capability。注册表除加载时探针外，还在每次调用时要求返回值严格
   等于 replacement；唯一例外是输入本身已为安全 `[REDACTED...]` 标记时允许原样返回，
   以保持幂等。错误实现会失败关闭，不能把候选原文返回给调用方。该返回值约束仍不能
   替代对第三方 masker 的代码审计和可用性测试。

## 7. 关键 caveat

### 7.1 分类依据不等于格式依据

GB/T 35273-2020 可用于说明电话号码、电子邮箱或网络标识在特定场景中可能属于
个人信息，但不能证明某个正则符合该标准。身份证号码规则也应把“敏感分类”
和“号码结构”分别映射到个人信息保护依据与 GB 11643-1999。

### 7.2 格式有效不等于风险成立

一个通过 RFC 或国标格式校验的字符串可能是测试值、示例值、系统账号或未分配号码。
相反，格式不完整的凭据片段仍可能造成安全风险。Finding 应保留 `confidence`、
路径、上下文原因码和验证结果，不能只保留一个布尔命中值。

### 7.3 去标识化不等于匿名化

掩码、假名、可关联 HMAC 指纹和保存于其他位置的映射表，通常仍允许数据与个人重新
关联。此类结果仍应按个人信息管理。只有无法识别或关联自然人且不能复原的匿名化结果，
才不再属于《个人信息保护法》第 4 条所称个人信息。

HMAC 指纹不保存原始命中值，但它仍可能是可链接标识。实现时还需管理密钥版本、
访问控制、轮换和保留期限，且不得把指纹写成“已匿名化”的证明。

### 7.4 凭据秘密与个人信息必须分域

密码、私钥、API Key、AccessKey Secret 和 Bearer Token 未必与自然人有关，
因此不能统一标为 `personal` 或 `sensitive_personal`。它们应进入独立的
`credential` 类别；高风险和默认拒绝来自端侧记忆系统的威胁模型与项目安全策略。

### 7.5 单项安全不代表聚合安全

TC260 指南要求考虑多项一般个人信息汇聚或融合后的整体属性。规则库因此需要给未来的
跨字段、跨事件或主体级关联策略预留来源和规则类型，但本文不声称该聚合分析已经实现。

### 7.6 审计本身也需要最小化

GB/T 46903-2025 可用于映射个人信息合规审计流程、证据和报告，但不能据此保存命中
原文。审计记录应引用规则、来源、策略、Finding 摘要和不可逆或受控指纹，并避免复制
原事件正文、payload、工具结果、Token 或完整个人信息。非个人信息类凭据的审计依据
还需项目安全策略或专门安全指南。

本项目的 `SafetyAuditLogRecord` 因此只保存版本/摘要、动作、稳定原因码、最高风险、
类别计数、二次脱敏后的字段路径、脱敏数量、设备密钥 HMAC 输入指纹、安全输出摘要、
耗时和认证链字段。它不会直接序列化内存 `SafetyAuditRecord`；动态事件 ID 和路径段
若命中同一规则快照，会改为域分离 HMAC 引用。该记录是“安全处置审计记录”，用途是
证明一次 MemoryEvent 的安全门禁如何执行，不是正式合规审计报告。

### 7.7 引用不等于符合

文档、报告和演示中优先使用以下措辞：

- “依据……定义分类”
- “参考……设计”
- “映射至……要求”
- “格式验证基于……”
- “项目策略选择……动作”

除非已完成适用范围分析、逐条符合性检查和证据留存，不使用“已符合某国标”
或“国标认证正则”等表述。

### 7.8 目标路径是受控的 RFC 6901 glob 扩展

实际 Finding 路径仍是严格 RFC 6901 JSON Pointer。规则的 `target_paths` 在此基础上
保留整段 `*` 和 `**` 作为 glob；为避免无法精确指向名为 `*` 的 JSON 键，规则模板
额外使用 `~2` 表示一个字面星号，例如 `/payload/~2` 精确指向 `/payload/*`，
`/payload/~2~2` 精确指向 `/payload/**`。`~2` 只属于规则模板，不允许出现在
Finding 的实际 JSON Pointer 中。

## 8. 后续升级与运行时接入的资料门槛

在新增、升级或把声明式规则接入递归扫描/处置流水线前，应完成以下资料检查：

- 从官方全文锁定实际引用位置，不能仅凭标准标题或搜索摘要填写 `locator`。
- 对每项官方文件记录版次、发布日期、实施日期、状态核对日期和官方 URL。
- 为征求意见稿、即将实施、现行、被代替和废止分别建模。
- 保持邮箱、IP、电话和证件号码的“候选检测—语义验证”分层；新增或修改规则不能只使用正则。
- 对每个厂商凭据核实官方文档是否真的承诺前缀、长度或校验方式。
- 使用无真实个人信息和无有效凭据的合成样本测试误报、漏报、掩码边界和复检。
- 在规则发布记录中说明默认动作来自哪一版项目策略，而不是把动作归因于分类标准。
