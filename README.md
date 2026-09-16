# Gold Analyst · 黄金信息调查员

输入一条黄金新闻或说法 → AI 自主读资料、搜索与计算 → 独立审核 → 输出带证据的核验报告。

这是面向 Python/Agent 初学者的第一版原型。参考 [CoreCoder](https://github.com/he-yufeng/CoreCoder/) 的「模型 → 工具 → 模型」循环思想，独立实现黄金研究工具；没有复制它的源码，也不需要安装 CoreCoder。

## 先看到效果（不需要 API Key）

在本项目目录打开终端：

```bash
python3 main.py
```

浏览器打开 <http://127.0.0.1:8765>，点击 **运行教学演示**。

演示不联网、不调用模型、没有 API 费用。价格和参考表全部虚构，使用固定流程演示「三个说法 → 证据 → 计算 → 找出错误」。它不是一次真实市场调查，也不能证明模型能力。

只想直接生成一份示例报告：

```bash
python3 main.py --demo
```

结果保存在 `reports/` 的 JSON 和 Markdown 中。报告可在网页里下载，重启后也可查看最近记录。

## 连接 OpenAI，调查真实新闻

### 1. 安装依赖

推荐用已安装的 uv：

```bash
uv sync --locked
```

没有 uv，也可以用 Python 3.10+ 的虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

虚拟环境 `.venv` 就是这个项目自己的依赖文件夹，不会修改其他项目。

### 2. 填写本地配置

首次使用时复制 `.env.example` 为 `.env`；如果已经有 `.env`，直接编辑，不要覆盖已有 Key：

```bash
cp -n .env.example .env
```

用编辑器打开 `.env`：

```dotenv
OPENAI_API_KEY=填入你的实际Key
OPENAI_BASE_URL=https://api.openai.com/v1
GOLD_MODEL=gpt-4.1-mini
```

模型名可以改成账户可用、支持 Responses API 与工具调用的模型。模型默认值不保证你的账户具有访问权限。

`.env` 已加入 `.gitignore`。不要贴 Key 到聊天、截图、README 或代码。程序不会读取 CoreCoder 的配置。更改 `.env` 后请重启服务。

### 3. 启动

```bash
.venv/bin/python main.py
```

打开 <http://127.0.0.1:8765>，选择 **联网调查**，填入新闻 URL 或待核查说法，点击开始。

页面中的「填入同花顺真实新闻案例」只填写链接，不会自动产生模型调用费用。它是尚待核验的新闻，不是正确答案。也可以直接用命令：

```bash
.venv/bin/python main.py --investigate 'https://invest.10jqka.com.cn/20260824/c679225891.shtml'
```

停止服务：在终端按 `Ctrl+C`。端口被占用时用 `--port 8766`，浏览器相应打开新端口。

## 你会看到什么

- 教学演示 / 真实联网调查有清晰区分。
- 工具调用的行动记录（不是模型私密思维链）。
- 每条说法分别标注：支持 / 反驳 / 部分成立 / 证据不足。
- 可展开的证据卡：原文、来源、获取时间、表格、工具计算。
- 独立模型审核状态；审核失败时明确保留为未审核初稿。
- 输入/输出 tokens、工具次数、搜索次数、耗时。
- 最近调查与 Markdown 下载。

联网会把输入和已抓取的公开资料发送到配置的 OpenAI 服务，会产生模型与搜索费用。每次最多 6 轮正常调查、12 次研究工具调用；同一轮的独立工具最多用 4 个线程并行执行，其中联网搜索最多 5 次。另有一次收尾和一次审核请求。这些是调用限制，不是精确人民币预算。

## 第一版工具

| 工具 | 用途 |
|---|---|
| `read_url` | 读 HTML/PDF 并保存证据。PDF 最多 15 页，扫描图片不做 OCR |
| `list_news` | 找同花顺黄金列表中的文章链接，最多 20 条 |
| `get_sge_data` | 查指定日期上金所历史表格，不是实时行情 |
| `calculate_change` | 使用 Decimal 计算价差与涨跌幅，不执行任意代码 |
| `search_web` | 调用 OpenAI 内置网页搜索，只需同一个 OpenAI Key |
| `submit_report` | 提交结构化核验报告，检查证据编号 |

网页资料是数据，不能给 Agent 下指令。只读公开页面，不登录，不绕过 403/验证码，不访问本机与内网。单页最大 2 MB，正文截取 18,000 字符，超出部分有截断标记。

## 关于两个网站

- [同花顺黄金列表](https://invest.10jqka.com.cn/hj_list/)：新闻线索，不是原始事实保证。正文可能来自转载。
- [上金所行情走势](https://www.sge.com.cn/sjzx/mrhq)：不能直接当作已验证的实时 API。
- [上金所延时行情](https://www.sge.com.cn/sjzx/yshqbg)：栏目明确标为延时。
- [上海金基准价](https://www.sge.com.cn/sjzx/jzj)：核验上海金基准价格时参考。

初次开发时，程序直接访问上金所历史页面曾返回 HTTP 403。程序会如实显示来源受阻，不使用离线样例补充真实调查。搜索能提供其他线索，但不保证解决所有访问问题。网站改版也可能需要更新解析规则。

特别注意：上金所集中定价历史表可能包含多轮价格。不能取第一行或随意取最后一行就说是最终基准价。银行积存金、Au99.99、SHAU、伦敦金和 COMEX 也不能互相替代。

## 从哪里开始读代码

1. `main.py`：入口，选择网页 / 演示 / 联网。
2. `gold_analyst/demo.py`：最容易读，理解一条核验记录的结构。
3. `gold_analyst/tools/base.py`：所有工具的共同接口和注册表。
4. `gold_analyst/tools/__init__.py`：唯一的工具绑定入口。
5. `gold_analyst/tools/` 里的其他文件：每个文件负责一种工具。
6. `gold_analyst/llm.py`：把 OpenAI SDK 输出转换成项目自己的数据类。
7. `gold_analyst/agent.py`：只使用 `ModelResponse` 和 `ToolCall` 的核心循环。
8. `gold_analyst/prompts.py`：调查员、审核员及三个策略的提示词。

```text
GoldAnalyst/
├── main.py                 运行入口
├── gold_analyst/
│   ├── agent.py            OpenAI Responses 工具调用循环
│   ├── llm.py              SDK 适配层与稳定响应数据类
│   ├── models.py           项目运行状态类型
│   ├── tools/              可扩展工具包
│   │   ├── base.py         Tool 基类、共享上下文和注册表
│   │   ├── __init__.py     集中实例化并绑定全部工具
│   │   ├── web.py          网页 / PDF 读取
│   │   ├── news.py         同花顺新闻列表
│   │   ├── sge.py          上金所历史数据
│   │   ├── calculator.py   确定性价格计算
│   │   ├── search.py       OpenAI 联网搜索
│   │   └── report.py       结构化报告提交
│   ├── verification.py     计算与引用结构验证
│   ├── prompts.py          研究策略和角色
│   ├── demo.py             明确虚构的离线教学流程
│   ├── storage.py          保存 JSON 和 Markdown
│   ├── config.py           本地环境配置
│   └── server.py           仅监听 127.0.0.1 的开发服务
├── web/                    无需 npm 的本地页面
├── tests/                  不用 Key 的单元与代理协议测试
├── .env.example            可提交的空白配置模板
├── uv.lock                 锁定依赖版本
└── reports/                运行后生成，默认不提交
```

如果参考 CoreCoder，先看它的 `agent.py`、`llm.py` 和 `tools/base.py`：`llm.py` 隔离供应商 SDK，Agent 因此只处理项目自己的稳定结构。暂时不用学习权限、终端操作和上下文压缩等编码代理功能。

### 这种 Tool 类和 `@tool` 有什么区别？

底层没有本质区别：两者最终都要把工具名称、说明、参数 JSON Schema 交给模型，模型返回工具名和参数后，再由 Python 执行。

- `@tool` 是装饰器写法，框架通常根据函数签名和 docstring 自动生成 schema。短小项目写得快，但行为取决于所用框架。
- 本项目的 `Tool` 类显式保存 `name / description / parameters / execute()`，代码稍多，却容易加共享状态、预算、缓存、终止型工具和统一测试。

新增工具的步骤是：新建一个继承 `Tool` 的类，然后只在 `tools/__init__.py` 中实例化并加入 `ToolRegistry`。Agent 本身不需要修改。

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖计算、缺失/错误引用、新闻不能自证、页面解析、网络目标校验，以及用模拟模型验证的工具往返、独立审核、预算收尾。模拟测试不等于已经调用真实 OpenAI 成功；真实连通性需要你填 Key 后运行。

## Auto-research 与进化做到哪一步

- **已实现**：模型自主选择工具、继续调查、保留证据；独立审核；三种手动可选策略；记录每次运行的策略版本和用量。
- **未实现**：自动评测集、策略自动变异/交叉/选优。第一版不会声称自己已自动进化。
- 下一步先准备人工核验的案例，比较三种策略；划分开发案例与保留测试案例，再实现策略进化。不能用模型觉得「写得好」代替事实正确性。

这是开发原型，不是生产服务。引用编号检查只能验证引用存在，不能自动保证语义和独立来源正确；模型审核也会犯错，重要结论应人工复核。

## 推送到 GitHub

确认目标仓库后，在此目录初始化 Git、提交源代码并设置远程地址。提交前检查 `git status`，确保没有 `.env`、`.venv` 和 `reports/`。本项目不含任何 API Key，不应推送本地资料或其他 Learning 文件夹的内容。

## 参考

- [CoreCoder](https://github.com/he-yufeng/CoreCoder/)：小型 Agent 循环和工具设计思路。
- [OpenAI Function calling](https://developers.openai.com/api/docs/guides/function-calling)：Responses 工具协议。
- [OpenAI Web search](https://developers.openai.com/api/docs/guides/tools-web-search)：带来源的联网搜索。
