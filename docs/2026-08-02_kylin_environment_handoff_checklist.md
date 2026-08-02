# 麒麟 OS 环境测试交接清单

**文档编号**：CHK-2026-08-02-001  
**日期**：2026-08-02  
**目标读者**：拥有真实麒麟 OS 环境、负责验证 MemoryHub 路线 B 的测试人员  
**前置条件**：已阅读 `docs/2026-08-02_kylin_embedding_vector_engine_integration_plan.md`

> 本文档假设测试人员有麒麟 OS 设备或容器，且具备基础 Linux 运维和 C++ 编译能力。

---

## 一、环境信息确认

在开始前，请确认以下信息并填写：

| 检查项 | 状态 | 备注 |
|---|---|---|
| 麒麟 OS 版本 | □ | 例：openkylin 2.0 / nile-sp2 |
| CPU 架构 | □ | 例：x86_64 / aarch64 |
| 是否有 root 权限 | □ | 编译安装 SDK 通常需要 |
| 网络可访问 Gitee | □ | 用于克隆 SDK 源码 |
| 是否可运行 Docker | □ | 用于 Milvus standalone |
| Python 版本 | □ | 建议 ≥ 3.10 |
| 已安装 cmake | □ | `cmake --version` ≥ 3.20 |
| 已安装 g++ | □ | `g++ --version` ≥ 11 |
| 已安装 git | □ | |
| 磁盘空间 | □ | 建议 ≥ 20GB |

---

## 二、SDK 源码准备

### 2.1 克隆 Embedding SDK

```bash
cd /path/to/workspaces
git clone https://gitee.com/openkylin/kylin-coreai-embedding.git
cd kylin-coreai-embedding
git checkout openkylin/nile-sp2
```

### 2.2 克隆 Vector Engine SDK

```bash
cd /path/to/workspaces
git clone https://gitee.com/openkylin/libkysdk-vector-engine-client.git
cd libkysdk-vector-engine-client
git checkout openkylin/nile-sp2
```

### 2.3 克隆 MemoryHub

```bash
cd /path/to/workspaces
git clone https://github.com/pyzw618/XA202612-2.git
cd XA202612-2
git checkout dev_improve
```

---

## 三、编译 Embedding SDK

### 3.1 安装依赖

```bash
sudo apt update
sudo apt install -y cmake g++ libgsettings-qt-dev libglib2.0-dev libdbus-1-dev
# 根据实际 README 补充其他依赖
```

### 3.2 编译

```bash
cd /path/to/workspaces/kylin-coreai-embedding
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### 3.3 安装或确认 .so 路径

```bash
sudo make install
# 或手动确认 .so 路径
find /path/to/workspaces/kylin-coreai-embedding -name "*.so" | grep embedding
```

典型路径：
- `/usr/lib/libkylin-coreai-embedding.so`
- `/usr/local/lib/libkylin-coreai-embedding.so`

### 3.4 验证 Embedding SDK 可运行

```bash
cd /path/to/workspaces/kylin-coreai-embedding/build
./test/TestTextEmbedding
```

预期：看到 `vector_length: 768` 等输出，无段错误。

---

## 四、编译 Vector Engine SDK（含 C API 桥接层）

### 4.1 安装依赖

```bash
sudo apt install -y cmake g++ libgrpc++-dev protobuf-compiler-grpc libprotobuf-dev
```

### 4.2 确认 C API 桥接层文件存在

如果 MemoryHub 的集成方案已经实施，应存在以下文件：

```bash
ls /path/to/workspaces/libkysdk-vector-engine-client/c_api_bridge.h
ls /path/to/workspaces/libkysdk-vector-engine-client/c_api_bridge.cpp
```

如果不存在，需要从 `docs/2026-08-02_milvus_c_api_minimal_interface.md` 中抄写最小接口实现，或联系当前执行者获取。

### 4.3 修改 CMakeLists.txt

确认 `CMakeLists.txt` 中已增加 `libkysdk-vector-engine-client-capi.so` 编译目标。例如：

```cmake
add_library(kysdk-vector-engine-client-capi SHARED
    c_api_bridge.cpp
)
target_link_libraries(kysdk-vector-engine-client-capi
    kysdk-vector-engine-client
)
```

### 4.4 编译

```bash
cd /path/to/workspaces/libkysdk-vector-engine-client
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)
```

### 4.5 确认 .so 输出

```bash
find /path/to/workspaces/libkysdk-vector-engine-client/build -name "*.so"
```

预期至少看到：
- `libkysdk-vector-engine-client.so`
- `libkysdk-vector-engine-client-capi.so`

### 4.6 设置动态库搜索路径

```bash
export LD_LIBRARY_PATH=/path/to/workspaces/libkysdk-vector-engine-client/build:$LD_LIBRARY_PATH
# 建议写入 ~/.bashrc 或测试脚本
```

---

## 五、部署 Milvus

### 方案 A：Docker Standalone（推荐）

```bash
cd /path/to/workspaces
curl -sfL https://raw.githubusercontent.com/milvus-io/milvus/master/scripts/standalone_embed.sh -o standalone_embed.sh
bash standalone_embed.sh start
```

默认监听：
- gRPC：`127.0.0.1:19530`
- webUI：`http://127.0.0.1:9091/webui`

验证：
```bash
docker ps | grep milvus
```

### 方案 B：Milvus Lite（仅测试，不推荐生产）

```bash
pip install milvus-lite
```

然后在 Python 中启动：
```python
from milvus import default_server
default_server.start()
```

### 方案 C：Milvus Standalone 手动部署

参考官方文档：https://milvus.io/docs/zh/install_standalone-docker.md

---

## 六、配置 MemoryHub

### 6.1 安装 Python 依赖

```bash
cd /path/to/workspaces/XA202612-2
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 6.2 修改配置文件

复制 `config.example.yaml` 为 `config.yaml`（或 `.env`），修改如下：

```yaml
embedding:
  provider: kylin
  kylin:
    so_path: /path/to/libkylin-coreai-embedding.so
    model_name: ensemble-embd_gte-base_uint8-text
    dim: 768

vector_engine:
  provider: milvus
  milvus:
    so_path: /path/to/libkysdk-vector-engine-client-capi.so
    host: 127.0.0.1
    port: 19530
    collection: memoryhub
    dimension: 768
    metric: cosine
```

如使用默认搜索路径，可省略 `so_path`。

### 6.3 设置环境变量

```bash
export LD_LIBRARY_PATH=/path/to/libkysdk-vector-engine-client-capi.so所在目录:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/path/to/libkylin-coreai-embedding.so所在目录:$LD_LIBRARY_PATH
```

---

## 七、验证步骤

### 7.1 验证 Embedding SDK 可被 Python 调用

```bash
cd /path/to/workspaces/XA202612-2
source .venv/bin/activate
python - <<'PY'
from memoryhub.embedding import create_embedding_client
client = create_embedding_client(provider="kylin")
print("available:", client.is_available())
vec = client.embed("测试文本")
print("dim:", len(vec))
print("first 5:", vec[:5])
PY
```

预期：
- `available: True`
- `dim: 768`
- 输出 5 个浮点数

### 7.2 验证 Vector Engine SDK 可连接

```bash
python - <<'PY'
from memoryhub.storage.vector_engine import create_vector_engine
engine = create_vector_engine(provider="milvus")
print("created")
engine.connect()
print("connected")
PY
```

预期：无异常，连接成功。

### 7.3 运行冒烟测试脚本

```bash
python scripts/run_milvus_real_smoke_test.py
```

预期：
- 创建 collection
- 插入测试数据
- 执行 hybrid search
- 返回 Top-K 结果

### 7.4 运行端到端 API 测试

```bash
uvicorn memoryhub.app:app --reload
```

另一个终端：
```bash
curl -X POST "http://127.0.0.1:8000/api/memory/search" \
     -H "Content-Type: application/json" \
     -H "X-MemoryHub-User: test-user" \
     -d '{"query":"测试查询","top_k":5}'
```

预期：返回 JSON，包含 `results` 列表。

---

## 八、性能测试

### 8.1 准备数据集

```bash
python -c "from tests.eval_dataset import generate_dataset; generate_dataset(count=10000, output='tests/eval_dataset_10k.json')"
```

> 如果 `generate_dataset` 不支持缩放，需要联系当前执行者确认数据集生成脚本。

### 8.2 运行真实环境性能基准

```bash
python evaluation/run_milvus_kylin_benchmark.py \
    --dataset tests/eval_dataset_10k.json \
    --memory_count 10000 \
    --iterations 100
```

### 8.3 收集指标

脚本应输出：
- P50/P95/P99 检索延迟
- QPS
- Recall@K / Precision@K / MRR / NDCG
- 索引构建时间
- 内存占用

---

## 九、常见问题排查

### 9.1 `libkylin-coreai-embedding.so` 找不到

```bash
sudo find / -name "libkylin-coreai-embedding.so*" 2>/dev/null
# 确认在 config.yaml 中指定 so_path
# 或 export LD_LIBRARY_PATH
```

### 9.2 ctypes 加载 .so 报 `OSError: undefined symbol`

原因：C++ 桥接层依赖了未链接的库。  
解决：确认 `LD_LIBRARY_PATH` 包含 `libkysdk-vector-engine-client.so` 和 `libkylin-coreai-embedding.so` 所在目录。

### 9.3 `kylin-coreai-embedding` 初始化失败

可能原因：
- DBus 服务未启动：`systemctl status dbus`
- embedding 后端服务未启动：需确认 `kylin-coreai-embedding` 依赖的系统服务
- 非 root 用户权限不足：尝试用 `sudo` 运行测试

### 9.4 Milvus 连接失败

```bash
# 检查 Milvus 是否运行
docker ps | grep milvus

# 检查端口
nc -zv 127.0.0.1 19530

# 检查日志
docker logs milvus-standalone
```

### 9.5 向量维度不一致

- 确保 `kylin-coreai-embedding` 输出维度与 `config.yaml` 中 `dim` 一致（当前为 768）
- 确保 Milvus collection 的 dimension 与配置一致

### 9.6 HybridSearch 返回空结果

- 检查 collection 是否已 `load`
- 检查稀疏向量索引是否正确创建
- 检查 query 是否经过 `jieba` 分词且生成了有效 sparse_terms
- 检查 embedding 是否返回非零向量

### 9.7 内存泄漏或段错误

- 确认每次 `vector_engine_create` 都对应 `vector_engine_destroy`
- 确认 `embedding_result_destroy` 被调用
- 使用 `valgrind` 或 `asan` 运行 C++ demo 定位问题

---

## 十、反馈给当前执行者

测试完成后，请向当前执行者提供以下信息：

1. 麒麟 OS 版本和 CPU 架构
2. SDK 编译是否成功（附关键命令输出）
3. Milvus 部署方式
4. 验证脚本输出（成功或失败）
5. 性能基准结果（JSON 文件路径或截图）
6. 遇到的问题及已尝试的解决方案
7. 建议的代码修改点（如有）

---

## 十一、快速命令速查表

```bash
# 启动 Milvus
bash standalone_embed.sh start

# 停止 Milvus
bash standalone_embed.sh stop

# 设置库路径
export LD_LIBRARY_PATH=/path/to/so/dir:$LD_LIBRARY_PATH

# 验证 Embedding
python -c "from memoryhub.embedding import create_embedding_client; c=create_embedding_client('kylin'); print(c.embed('测试')[:5])"

# 验证 Vector Engine
python -c "from memoryhub.storage.vector_engine import create_vector_engine; e=create_vector_engine('milvus'); e.connect(); print('ok')"

# 跑端到端测试
python scripts/run_milvus_real_smoke_test.py

# 跑性能基准
python evaluation/run_milvus_kylin_benchmark.py --memory_count 10000

# 跑 API
uvicorn memoryhub.app:app
```

---

## 参考文档

- 集成方案：`docs/2026-08-02_kylin_embedding_vector_engine_integration_plan.md`
- Embedding SDK 接口签名：`docs/2026-08-02_kylin_embedding_sdk_api_signatures.md`
- Vector Engine SDK 接口签名：`docs/2026-08-02_kylin_vector_engine_sdk_api_signatures.md`
- 最小 C API 接口：`docs/2026-08-02_milvus_c_api_minimal_interface.md`
- Embedding SDK 测试示例：[TestTextEmbedding.cpp](https://gitee.com/openkylin/kylin-coreai-embedding/blob/openkylin/nile-sp2/test/TestTextEmbedding.cpp)
- Vector Engine SDK 混合检索示例：[exampleHybridSearch.cpp](https://gitee.com/openkylin/libkysdk-vector-engine-client/blob/openkylin/nile-sp2/demo/client/exampleHybridSearch.cpp)
- Milvus 文档：https://milvus.io/docs/zh/index.md
