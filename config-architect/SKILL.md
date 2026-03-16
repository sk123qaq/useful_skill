---
name: config-architect
description: 审计、优化和维护 OpenClaw 配置文件体系（USER.md, SOUL.md, TOOLS.md, AGENTS.md, MEMORY.md, HEARTBEAT.md），确保层级清晰、无冲突、符合最佳实践
tools:
  - read
  - write
  - python
  - memory_search
auto_activate: false
---

# Config Architect - 配置架构师

管理你的 OpenClaw 配置文件生态系统，确保核心五层（USER/SOUL/TOOLS/AGENTS/MEMORY）以及可选辅助文件（HEARTBEAT/IDENTITY）职责清晰、无重复、强制规则生效。

## 核心功能

### 1. 配置审计 (Audit)
检查现有配置的健康状况：
- **冲突检测**：同一规则出现在多个文件（如浏览器规则同时在 MEMORY.md 和 AGENTS.md）
- **层级错位**：人格描述出现在 TOOLS.md，强制规则出现在 SOUL.md 等
- **缺失检查**：必需文件（USER.md, SOUL.md）是否存在
- **自相矛盾检查**：同一文件的头部说明与正文执行逻辑冲突（如 HEARTBEAT.md）
- **语言一致性**：中英混杂检测
- **死链检查**：引用的脚本路径是否存在（如 `/absolute/path/to/start-chrome-debug.sh`）
- **伪状态检查**：声明了状态文件，但仓库里没有任何脚本或工具真实消费它

### 2. 优化建议 (Optimize)
基于你的使用模式提供重构建议：
- **迁移建议**：哪些内容应该从 MEMORY.md 移到 USER.md（强制规则）
- **精简建议**：哪些内容是冗余的（如 IDENTITY.md 与 SOUL.md 重复）
- **减载建议**：USER.md 是否塞入了过多执行模板、惩罚机制或冗长 SOP
- **结构化建议**：TOOLS.md 是否包含所有必要的环境信息

### 3. 迁移辅助 (Migrate)
安全地将内容从一个文件转移到另一个：
- 自动提取 MEMORY.md 中的 `[强制规则]` 块，生成 USER.md 草案
- 将 AGENTS.md 中的技术细节移到 TOOLS.md
- 合并 IDENTITY.md 到 SOUL.md
- 将 HEARTBEAT.md 中的去重逻辑收敛到真实幂等信号（输出文件、prompt 文件）

### 4. 模板生成 (Template)
为缺失的文件生成符合最佳实践的模板：
- 根据你的身份（金融 + 硬件）生成个性化的 SOUL.md
- 基于现有 MEMORY.md 内容推断 TOOLS.md 应有的配置
- 生成 USER.md 的强制规则框架

### 5. 配置验证 (Validate)
验证配置是否符合 OpenClaw 最佳实践：
- 检查浏览器规则是否已改为条件流（先 connect，失败后再启动）
- 验证时间敏感查询处理规则是否存在（“今日”→具体日期转换）
- 确认 Python 3.13 强制使用声明
- 确认 Heartbeat 使用真实幂等信号，而不是空转的状态文件

## 使用方式

### 命令格式
```bash
use config-architect [action] [options]
```

### 自动化审计脚本

内置 `scripts/audit.py` 提供自动化审计能力：

**运行完整审计**
```bash
cd /path/to/config-architect
python3 scripts/audit.py --workspace /path/to/openclaw/workspace
```

也可以通过环境变量指定工作区：

```bash
export OPENCLAW_WORKSPACE=/path/to/openclaw/workspace
cd /path/to/config-architect
python3 scripts/audit.py
```

说明：
- `audit.py` 仅依赖 Python 标准库，无需额外安装依赖
- 默认工作区是 `~/.openclaw/workspace`，但更推荐显式传入 `--workspace`
- 脚本现在会扫描配置中出现的绝对路径和 `~/...` 路径，检查是否存在，而不是依赖作者本机路径
- 默认会检查 `USER.md` 是否声明 `python3.13`；如果你的团队标准不是这个版本，可通过 `CONFIG_ARCH_EXPECTED_PYTHON` 覆盖

```bash
export CONFIG_ARCH_EXPECTED_PYTHON=python3
```

**建议使用场景：**
- 定期健康检查（每周）
- 修改配置前
- 发现冲突时手动排查

输出示例：
```text
# OpenClaw 配置审计报告

## 🔴 自相矛盾
- [high] HEARTBEAT.md: 文件头声明禁用 heartbeat，但正文定义了 heartbeat 任务

## 🟠 重复定义
- **skill-first 约束** 出现在: USER, AGENTS
  建议: 保留在 USER.md，AGENTS.md 只引用 USER.md

## 🟡 伪状态引用
- [warning] AGENTS.md: 引用了 "heartbeat-state.json"，但工作区没有其他文件消费它
```

### 具体用法

**完整审计当前配置**
```bash
use config-architect audit
```
输出：冲突报告、错位列表、缺失文件、优化优先级

**生成优化方案**
```bash
use config-architect optimize
```
输出：具体的迁移步骤（如“将 MEMORY.md 的工作流 SOP 改写为已验证经验”）

**执行迁移（dry-run 模式）**
```bash
use config-architect migrate --from MEMORY.md --to USER.md --tag "强制规则" --dry-run
```

**生成缺失文件模板**
```bash
use config-architect template --file USER.md --persona "金融分析师+硬件爱好者"
```

**验证特定规则**
```bash
use config-architect validate --rule "browser-conditional-flow"
```

## 审计检查清单

执行 `audit` 时，按以下维度检查：

### 层级合规性
- [ ] USER.md 只包含用户硬约束，不承载长篇 ReAct 模板、惩罚机制、失败报告样板
- [ ] SOUL.md 只包含身份 / 价值观，无技术操作细节
- [ ] TOOLS.md 包含具体路径、端口、API Keys，无抽象业务规则
- [ ] AGENTS.md 只包含会话流程与响应约定，无具体业务规则
- [ ] MEMORY.md 只包含经验 / 历史，无系统级约束和 SOP
- [ ] HEARTBEAT.md 不存在“禁用说明”和“启用流程”同时出现的冲突

### 内容冲突
- [ ] skill-first 规则是否只保留一份权威定义
- [ ] 浏览器规则是否同时出现在 MEMORY.md 和 AGENTS.md / USER.md
- [ ] 搜索默认入口是否统一为 `web_search_pro`
- [ ] Python 版本要求是否一致（3.13）
- [ ] 时间敏感词处理规则是否存在且统一
- [ ] 是否引用了未被实现的状态文件

### 完整性
- [ ] 浏览器规则是否包含条件流（connect → fallback start → reconnect → verify）
- [ ] AGENTS.md 是否在启动流程中读取 TOOLS.md
- [ ] 是否定义了 Silent Replies 和 Heartbeats 规则
- [ ] HEARTBEAT.md 是否说明 prompt 文件 / 输出文件的幂等关系
- [ ] 是否包含时间标准化规则（“今日”→绝对日期）

## 最佳实践规则

执行此 skill 时遵循：

1. **备份优先**：任何写入操作前优先考虑创建 `.bak` 备份
2. **dry-run 默认**：迁移操作默认预览，确认后才执行
3. **增量更新**：不一次性重构全部文件，按优先级分批次（先 USER.md，后 TOOLS.md）
4. **验证闭环**：每次修改后重新运行 audit 确认冲突已解决
5. **保留意图**：迁移时保留原文里的意图，只移动到更合适的层

## 工作流程建议

针对典型配置问题，建议按此顺序执行：

**Phase 1: 修权威源**
```bash
use config-architect audit
```
先找出重复规则、自相矛盾和伪状态引用。

**Phase 2: 收口配置层**
```bash
use config-architect optimize
```
把 USER/SOUL/TOOLS/AGENTS/MEMORY/HEARTBEAT 的职责重新对齐。

**Phase 3: 验证可执行性**
```bash
use config-architect validate --rule "heartbeat-idempotency"
```
确保 heartbeat 去重依赖的是脚本真正会消费的文件或状态。

## 与其他 Skill 的协作

- **执行前**：先调用 `config-architect validate --rule browser-conditional-flow` 确保浏览器规则最新
- **执行后**：更新完成后，建议将关键变化记录到 memory 文件

---

**注意**：此 skill 默认处于分析和建议模式；只有显式执行写入时才修改配置。
