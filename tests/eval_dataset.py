"""
评测数据集构造模块

按文档 §5.3 设计:
- 100 条覆盖多域的记忆
- 20 个带 ground truth 标注的 query
- 难度分层: 精确匹配、语义相近、干扰型、跨域型
"""

from __future__ import annotations
import json
import os
from typing import Optional


# ============================================================
# 1. 100 条多域记忆数据
# ============================================================

DATASET_100_MEMORIES = [
    # ── 域 1: 系统凭证 (System Credentials, mem_001 ~ mem_015) ──
    {"id": "mem_001", "content": "我的系统登录密码是 Admin@123456", "domain": "credentials"},
    {"id": "mem_002", "content": "公司 VPN 密码是 Kylin_VPN_2025_Secure", "domain": "credentials"},
    {"id": "mem_003", "content": "数据库 root 账号密码是 RootDB!Pass#2024", "domain": "credentials"},
    {"id": "mem_004", "content": "GitHub 个人访问令牌 ghp_xxxxxxxxxxxxxxxxxxxx", "domain": "credentials"},
    {"id": "mem_005", "content": "API 密钥 sk-abc123def456ghi789jkl 用于调用大模型服务", "domain": "credentials"},
    {"id": "mem_006", "content": "企业微信管理后台密码 WeCom@Admin2025", "domain": "credentials"},
    {"id": "mem_007", "content": "内部 npm 仓库认证令牌 npm_auth_token_xxxxx", "domain": "credentials"},
    {"id": "mem_008", "content": "AWS IAM 访问密钥 AKIAIOSFODNN7EXAMPLE", "domain": "credentials"},
    {"id": "mem_009", "content": "Jenkins 管理员密码 Jenkins#Deploy#2025", "domain": "credentials"},
    {"id": "mem_010", "content": "Docker Registry 登录密码 docker_reg_pass_xxxx", "domain": "credentials"},
    {"id": "mem_011", "content": "Redis 服务器连接密码 redis_secure_pass_2025", "domain": "credentials"},
    {"id": "mem_012", "content": "Kubernetes 集群 admin.conf 中的证书已过期需要更新", "domain": "credentials"},
    {"id": "mem_013", "content": "公司邮箱密码 Exchange_Mail_2025_Q3", "domain": "credentials"},
    {"id": "mem_014", "content": "Linux 服务器 root 密码已改为 R00t#Server#2025", "domain": "credentials"},
    {"id": "mem_015", "content": "所有密码统一使用 LastPass 管理，主密码在保险柜", "domain": "credentials"},

    # ── 域 2: 网络与服务器 (Network & Servers, mem_016 ~ mem_030) ──
    {"id": "mem_016", "content": "开发服务器 IP 是 10.0.1.100，SSH 端口 2222", "domain": "network"},
    {"id": "mem_017", "content": "生产环境负载均衡地址: https://lb.prod.kylin.com", "domain": "network"},
    {"id": "mem_018", "content": "测试环境部署在 192.168.1.50:8080", "domain": "network"},
    {"id": "mem_019", "content": "公司 Wi-Fi SSID: Kylin-Office，密码: Kylin_WiFi_2024", "domain": "network"},
    {"id": "mem_020", "content": "公司内部 DNS 服务器地址 10.0.0.53", "domain": "network"},
    {"id": "mem_021", "content": "数据库服务器 IP 10.0.2.30，端口 3306", "domain": "network"},
    {"id": "mem_022", "content": "CDN 加速域名 static-cdn.kylin.com，需要配置 CNAME", "domain": "network"},
    {"id": "mem_023", "content": "VPN 服务器地址 vpn.kylin.com:8443，使用 OpenConnect 协议", "domain": "network"},
    {"id": "mem_024", "content": "监控系统 Prometheus 运行在 monitor.kylin.com:9090", "domain": "network"},
    {"id": "mem_025", "content": "日志收集 ELK 面板地址 logs.kylin.internal:5601", "domain": "network"},
    {"id": "mem_026", "content": "前端项目部署在 Nginx 上，路径 /var/www/frontend", "domain": "network"},
    {"id": "mem_027", "content": "反向代理配置在 nginx-proxy.kylin.com", "domain": "network"},
    {"id": "mem_028", "content": "后端微服务注册中心 Eureka: eureka.kylin.internal:8761", "domain": "network"},
    {"id": "mem_029", "content": "消息队列 RabbitMQ 地址 mq.kylin.internal:5672", "domain": "network"},
    {"id": "mem_030", "content": "所有服务器需通过堡垒机 jump.kylin.internal 跳转访问", "domain": "network"},

    # ── 域 3: 工作日程 (Schedule & Meetings, mem_031 ~ mem_045) ──
    {"id": "mem_031", "content": "每周一上午 9:30 团队站会，地点 3 楼会议室 A", "domain": "schedule"},
    {"id": "mem_032", "content": "每月 15 号提交月度工作总结报告", "domain": "schedule"},
    {"id": "mem_033", "content": "下周五 7 月 30 日是团队团建日，地点青龙峡，早上 8 点集合", "domain": "schedule"},
    {"id": "mem_034", "content": "今天下午 3 点产品评审会议，记得带笔记本和原型图", "domain": "schedule"},
    {"id": "mem_035", "content": "每周三下午 2 点到 4 点是代码 Review 时间", "domain": "schedule"},
    {"id": "mem_036", "content": "Q3 季度 OKR 评审定在 8 月 5 日上午", "domain": "schedule"},
    {"id": "mem_037", "content": "技术分享会每月最后一个周五举办", "domain": "schedule"},
    {"id": "mem_038", "content": "与甲方项目汇报每周四下午 4 点，使用腾讯会议", "domain": "schedule"},
    {"id": "mem_039", "content": "本周五晚上 6 点部门聚餐，地点海底捞朝阳大悦城店", "domain": "schedule"},
    {"id": "mem_040", "content": "2025 年 8 月 15-17 日参加 AI 开发者大会，已请假", "domain": "schedule"},
    {"id": "mem_041", "content": "每天早上 9:00 前填写日报，总结昨日工作和今日计划", "domain": "schedule"},
    {"id": "mem_042", "content": "10 月国庆节放假安排：10.1-10.7 共 7 天", "domain": "schedule"},
    {"id": "mem_043", "content": "产品需求评审每周二下午 2 点召开", "domain": "schedule"},
    {"id": "mem_044", "content": "项目里程碑：8 月底完成 Beta 版本，9 月中旬上线", "domain": "schedule"},
    {"id": "mem_045", "content": "周五下午 5 点是自由学习时间，可以看书或做 side project", "domain": "schedule"},

    # ── 域 4: 开发与工具 (Dev Tools & Repos, mem_046 ~ mem_060) ──
    {"id": "mem_046", "content": "项目前端代码仓库 https://git.kylin.com/frontend/os-agent-ui", "domain": "dev"},
    {"id": "mem_047", "content": "后端主仓库 https://git.kylin.com/backend/os-agent-core，使用 Go 语言", "domain": "dev"},
    {"id": "mem_048", "content": "推荐使用 VS Code 开发，已配置好 settings.json 共享", "domain": "dev"},
    {"id": "mem_049", "content": "代码提交前必须通过 ESLint 和 Prettier 检查", "domain": "dev"},
    {"id": "mem_050", "content": "Git 分支规范: feature/xxx, bugfix/xxx, hotfix/xxx", "domain": "dev"},
    {"id": "mem_051", "content": "CI/CD 使用 Jenkins Pipeline，配置文件在 Jenkinsfile", "domain": "dev"},
    {"id": "mem_052", "content": "单元测试覆盖率要求 > 80%，使用 Jest 框架", "domain": "dev"},
    {"id": "mem_053", "content": "Docker 镜像统一推送到 harbor.kylin.internal/os-agent", "domain": "dev"},
    {"id": "mem_054", "content": "Node.js 版本统一使用 v18 LTS，通过 nvm 管理", "domain": "dev"},
    {"id": "mem_055", "content": "Python 项目使用 Poetry 管理依赖，不使用 requirements.txt", "domain": "dev"},
    {"id": "mem_056", "content": "前端组件库使用 Element Plus，版本 2.x", "domain": "dev"},
    {"id": "mem_057", "content": "后端 API 文档使用 Swagger，地址 /api/docs", "domain": "dev"},
    {"id": "mem_058", "content": "数据库迁移使用 Flyway，迁移脚本在 db/migration 目录", "domain": "dev"},
    {"id": "mem_059", "content": "微服务间通信使用 gRPC + Protobuf 3", "domain": "dev"},
    {"id": "mem_060", "content": "项目遵循 Clean Architecture 分层设计，不要跨层调用", "domain": "dev"},

    # ── 域 5: 文档与格式偏好 (Doc Preferences, mem_061 ~ mem_070) ──
    {"id": "mem_061", "content": "项目周报统一使用 Markdown 格式撰写", "domain": "preferences"},
    {"id": "mem_062", "content": "技术文档放在项目 wiki 中，不要用 Word 文档", "domain": "preferences"},
    {"id": "mem_063", "content": "代码注释统一使用中文，JSDoc 格式", "domain": "preferences"},
    {"id": "mem_064", "content": "会议纪要模板：时间、参会人、议题、决议、待办", "domain": "preferences"},
    {"id": "mem_065", "content": "API 接口文档使用 OpenAPI 3.0 规范", "domain": "preferences"},
    {"id": "mem_066", "content": "所有对外邮件抄送给部门主管和项目经理", "domain": "preferences"},
    {"id": "mem_067", "content": "汇报 PPT 使用公司统一模板，蓝色主题", "domain": "preferences"},
    {"id": "mem_068", "content": "代码提交信息使用中文，格式: <类型>: <描述>", "domain": "preferences"},
    {"id": "mem_069", "content": "数据库表命名使用蛇形命名法 snake_case", "domain": "preferences"},
    {"id": "mem_070", "content": "测试用例命名规范: should_<预期行为>_when_<条件>", "domain": "preferences"},

    # ── 域 6: 安全策略 (Security, mem_071 ~ mem_080) ──
    {"id": "mem_071", "content": "所有敏感信息（密码、密钥、令牌）禁止提交到 Git 仓库", "domain": "security"},
    {"id": "mem_072", "content": "生产环境密钥必须使用 Vault 管理，不得硬编码", "domain": "security"},
    {"id": "mem_073", "content": "接入第三方 API 需要安全评审并由 CISO 审批", "domain": "security"},
    {"id": "mem_074", "content": "数据库备份每天凌晨 2 点自动执行，保留 30 天", "domain": "security"},
    {"id": "mem_075", "content": "用户密码必须使用 bcrypt 加密存储，不得明文保存", "domain": "security"},
    {"id": "mem_076", "content": "日志中禁止记录用户密码和完整身份证号", "domain": "security"},
    {"id": "mem_077", "content": "离职员工账号需在最后工作日前 1 天冻结", "domain": "security"},
    {"id": "mem_078", "content": "外部系统对接需要通过 API 网关，不允许直接访问内网服务", "domain": "security"},
    {"id": "mem_079", "content": "发现安全漏洞后 2 小时内上报安全团队", "domain": "security"},
    {"id": "mem_080", "content": "每季度进行一次全量安全审计和渗透测试", "domain": "security"},

    # ── 域 7: 学习与知识 (Learning & Knowledge, mem_081 ~ mem_090) ──
    {"id": "mem_081", "content": "Transformer 模型核心是自注意力机制 (Self-Attention)，计算 Q、K、V 三个矩阵", "domain": "learning"},
    {"id": "mem_082", "content": "BERT 预训练使用 MLM (Masked Language Model) 和 NSP (Next Sentence Prediction) 两个任务", "domain": "learning"},
    {"id": "mem_083", "content": "Kubernetes Pod 是 K8s 最小调度单元，包含一个或多个容器", "domain": "learning"},
    {"id": "mem_084", "content": "Redis 支持 5 种数据类型: String、Hash、List、Set、Sorted Set", "domain": "learning"},
    {"id": "mem_085", "content": "设计模式中的工厂模式用于解耦对象的创建和使用", "domain": "learning"},
    {"id": "mem_086", "content": "SQL 优化核心：合理使用索引、避免 SELECT *、减少 JOIN 层级", "domain": "learning"},
    {"id": "mem_087", "content": "Docker 镜像分层构建可以显著减小最终镜像体积", "domain": "learning"},
    {"id": "mem_088", "content": "微服务拆分的核心原则：高内聚低耦合，按业务边界划分", "domain": "learning"},
    {"id": "mem_089", "content": "消息队列 (MQ) 的核心作用是削峰填谷、异步解耦", "domain": "learning"},
    {"id": "mem_090", "content": "单元测试的最佳实践: AAA 模式 (Arrange-Act-Assert)", "domain": "learning"},

    # ── 域 8: 日常备忘 (Daily Notes, mem_091 ~ mem_100) ──
    {"id": "mem_091", "content": "周末需要去超市购买牛奶、鸡蛋、面包、水果和纸巾", "domain": "daily"},
    {"id": "mem_092", "content": "下周三是老婆生日，记得买礼物和订蛋糕", "domain": "daily"},
    {"id": "mem_093", "content": "体检预约在 8 月 3 日上午 9 点，地点协和医院体检中心", "domain": "daily"},
    {"id": "mem_094", "content": "物业费截止日期 8 月 10 日，需通过支付宝缴纳", "domain": "daily"},
    {"id": "mem_095", "content": "车险 9 月到期，记得提前一个月续保", "domain": "daily"},
    {"id": "mem_096", "content": "图书馆借的书《深入理解计算机系统》8 月 20 日到期", "domain": "daily"},
    {"id": "mem_097", "content": "健身房年卡明年 3 月到期，最近三个月只去了 5 次", "domain": "daily"},
    {"id": "mem_098", "content": "家里的 Wi-Fi 密码是 Home_WiFi_88888888", "domain": "daily"},
    {"id": "mem_099", "content": "常去的餐厅：海底捞（火锅）、绿茶（江浙菜）、太二（酸菜鱼）", "domain": "daily"},
    {"id": "mem_100", "content": "每周末打扫卫生，拖地擦窗洗衣服", "domain": "daily"},
]


# ============================================================
# 2. 20 个标注 Query（含 ground truth）
# ============================================================

DATASET_20_QUERIES = [
    # ── 精确匹配型 (Exact Match): 6 个 ──
    {
        "query_id": "q_exact_01",
        "query_text": "数据库密码是什么",
        "relevant_ids": ["mem_003"],  # "数据库 root 账号密码是 RootDB!Pass#2024"
        "difficulty": "exact_match",
        "domain": "credentials",
    },
    {
        "query_id": "q_exact_02",
        "query_text": "公司 Wi-Fi 密码",
        "relevant_ids": ["mem_019"],  # "公司 Wi-Fi SSID: Kylin-Office，密码: Kylin_WiFi_2024"
        "difficulty": "exact_match",
        "domain": "network",
    },
    {
        "query_id": "q_exact_03",
        "query_text": "团队团建",
        "relevant_ids": ["mem_033"],  # 团建日
        "difficulty": "exact_match",
        "domain": "schedule",
    },
    {
        "query_id": "q_exact_04",
        "query_text": "Git 分支命名规范",
        "relevant_ids": ["mem_050"],  # "Git 分支规范: feature/xxx..."
        "difficulty": "exact_match",
        "domain": "dev",
    },
    {
        "query_id": "q_exact_05",
        "query_text": "敏感信息禁止提交",
        "relevant_ids": ["mem_071"],  # "所有敏感信息禁止提交到 Git 仓库"
        "difficulty": "exact_match",
        "domain": "security",
    },
    {
        "query_id": "q_exact_06",
        "query_text": "Transformer 注意力机制",
        "relevant_ids": ["mem_081"],  # Transformer 自注意力
        "difficulty": "exact_match",
        "domain": "learning",
    },

    # ── 语义相近型 (Semantic): 6 个 ──
    {
        "query_id": "q_semantic_01",
        "query_text": "如何登录开发环境的机器",
        "relevant_ids": ["mem_016"],  # SSH 端口 2222, IP 10.0.1.100
        "difficulty": "semantic",
        "domain": "network",
    },
    {
        "query_id": "q_semantic_02",
        "query_text": "公司代码仓库在哪里",
        "relevant_ids": ["mem_046", "mem_047"],
        "difficulty": "semantic",
        "domain": "dev",
    },
    {
        "query_id": "q_semantic_03",
        "query_text": "我的密码应该怎么保管",
        "relevant_ids": ["mem_015", "mem_071"],
        "difficulty": "semantic",
        "domain": "credentials",
    },
    {
        "query_id": "q_semantic_04",
        "query_text": "什么时候开周会",
        "relevant_ids": ["mem_031"],  # 每周一上午
        "difficulty": "semantic",
        "domain": "schedule",
    },
    {
        "query_id": "q_semantic_05",
        "query_text": "K8s 的基本调度单位是什么",
        "relevant_ids": ["mem_083"],  # Pod
        "difficulty": "semantic",
        "domain": "learning",
    },
    {
        "query_id": "q_semantic_06",
        "query_text": "代码提交流程要求",
        "relevant_ids": ["mem_049", "mem_068"],
        "difficulty": "semantic",
        "domain": "dev",
    },

    # ── 干扰型 (Distractor): 5 个 ──
    # 查询可能匹配多条记忆，但正确答案需要精确区分
    {
        "query_id": "q_distractor_01",
        "query_text": "Redis 密码",
        "relevant_ids": ["mem_011"],  # Redis 连接密码，而非 Redis 数据类型(mem_084)
        "difficulty": "distractor",
        "domain": "credentials",
    },
    {
        "query_id": "q_distractor_02",
        "query_text": "家里的 Wi-Fi",
        "relevant_ids": ["mem_098"],  # 家里 Wi-Fi，而非公司 Wi-Fi (mem_019)
        "difficulty": "distractor",
        "domain": "daily",
    },
    {
        "query_id": "q_distractor_03",
        "query_text": "周报格式",
        "relevant_ids": ["mem_061"],  # Markdown 周报，而非汇报 PPT (mem_067)
        "difficulty": "distractor",
        "domain": "preferences",
    },
    {
        "query_id": "q_distractor_04",
        "query_text": "数据库服务器地址",
        "relevant_ids": ["mem_021"],  # 特定服务器信息，而非密码相关
        "difficulty": "distractor",
        "domain": "network",
    },
    {
        "query_id": "q_distractor_05",
        "query_text": "晚上聚餐",
        "relevant_ids": ["mem_039"],  # 周五部门聚餐，而非常去餐厅(mem_099)
        "difficulty": "distractor",
        "domain": "schedule",
    },

    # ── 跨域型 (Cross-domain): 3 个 ──
    {
        "query_id": "q_cross_01",
        "query_text": "开发环境的部署和访问安全策略",
        "relevant_ids": ["mem_016", "mem_018", "mem_030", "mem_078"],
        "difficulty": "cross_domain",
        "domain": "multi",
    },
    {
        "query_id": "q_cross_02",
        "query_text": "项目管理和技术文档的规范",
        "relevant_ids": ["mem_050", "mem_061", "mem_062", "mem_063", "mem_065", "mem_068"],
        "difficulty": "cross_domain",
        "domain": "multi",
    },
    {
        "query_id": "q_cross_03",
        "query_text": "重要日期和日程提醒",
        "relevant_ids": ["mem_032", "mem_033", "mem_036", "mem_040", "mem_092", "mem_094", "mem_096"],
        "difficulty": "cross_domain",
        "domain": "multi",
    },
]


# ============================================================
# 3. 加载/保存工具
# ============================================================

def get_dataset_path() -> str:
    """获取数据集 JSON 文件路径"""
    return os.path.join(os.path.dirname(__file__), "eval_dataset.json")


def save_dataset(path: Optional[str] = None) -> str:
    """保存数据集到 JSON 文件"""
    filepath = path or get_dataset_path()
    dataset = {
        "memories": DATASET_100_MEMORIES,
        "queries": DATASET_20_QUERIES,
        "metadata": {
            "total_memories": len(DATASET_100_MEMORIES),
            "total_queries": len(DATASET_20_QUERIES),
            "domains": list(set(m["domain"] for m in DATASET_100_MEMORIES)),
            "difficulty_distribution": {
                "exact_match": sum(1 for q in DATASET_20_QUERIES if q["difficulty"] == "exact_match"),
                "semantic": sum(1 for q in DATASET_20_QUERIES if q["difficulty"] == "semantic"),
                "distractor": sum(1 for q in DATASET_20_QUERIES if q["difficulty"] == "distractor"),
                "cross_domain": sum(1 for q in DATASET_20_QUERIES if q["difficulty"] == "cross_domain"),
            },
        },
    }
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    return filepath


def load_dataset(path: Optional[str] = None) -> dict:
    """从 JSON 文件加载数据集"""
    filepath = path or get_dataset_path()
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"数据集文件不存在: {filepath}，请先运行 save_dataset()")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    path = save_dataset()
    print(f"数据集已生成: {path}")
    d = load_dataset(path)
    print(f"  记忆数量: {d['metadata']['total_memories']}")
    print(f"  查询数量: {d['metadata']['total_queries']}")
    print(f"  覆盖领域: {d['metadata']['domains']}")
    print(f"  难度分布: {d['metadata']['difficulty_distribution']}")
