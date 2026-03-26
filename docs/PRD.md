📄 PRD：DevBrain（Local AI Codebase Intelligence System）
1. 📌 产品概述（Product Overview）
1.1 产品名称

DevBrain（暂定）

1.2 产品定位

DevBrain 是一个本地运行的 AI 代码理解系统，能够解析整个代码仓库，通过 RAG（Retrieval-Augmented Generation）实现：

代码级问答
项目结构理解
自动文档生成
1.3 产品愿景

让 AI 真正“理解代码”，成为开发者的本地智能助手，而不是仅仅聊天工具。

1.4 核心价值
📉 降低陌生项目理解成本
⚡ 提升开发效率
🔒 数据完全本地运行（隐私安全）
🧠 提供比通用 LLM 更精准的代码理解能力
2. 🎯 目标用户（Target Users）
2.1 核心用户
独立开发者
开源贡献者
初中级工程师
2.2 扩展用户
小型开发团队
技术负责人（快速理解项目）
2.3 使用场景
场景 1：快速理解项目

“这个 repo 是做什么的？”

场景 2：代码定位

“登录逻辑在哪里？”

场景 3：调用关系分析

“userService 被哪些模块调用？”

场景 4：自动生成文档

“帮我生成 README”

3. ❗问题定义（Problem Statement）

当前开发者在面对代码仓库时存在以下问题：

问题	描述
上手成本高	新项目理解耗时
文档缺失	README 不完整或不存在
代码复杂	调用链难追踪
AI 无上下文	通用 AI 无法理解整个 repo
4. 💡 解决方案（Solution）

DevBrain 提供：

4.1 代码解析引擎
自动扫描代码
提取结构（函数 / 类 / 模块）
4.2 RAG 知识库
将代码转为向量索引
支持语义检索
4.3 AI 问答系统
基于代码上下文回答问题
支持多文件推理
4.4 文档生成系统
自动生成 README
自动总结模块功能
4.5 本地运行能力
支持 DeepSeek / 本地模型
数据不出本地
5. 🧱 产品功能（Features）
5.1 MVP 功能（必须实现）
5.1.1 仓库导入
支持本地路径
支持 GitHub URL
5.1.2 文件扫描与过滤
忽略：
node_modules
.git
build
5.1.3 代码切分
按文件 + 函数切分
支持多语言
5.1.4 向量索引
embedding 生成
存储到 FAISS
5.1.5 语义检索
支持 top-k 相似搜索
5.1.6 AI 问答
支持代码级问题
返回答案 + 来源
5.2 增强功能（P1）
5.2.1 文档生成
README
模块说明
5.2.2 简单 UI
Chat 界面
文件树
5.3 高级功能（P2）
5.3.1 代码关系图
函数调用关系
模块依赖
5.3.2 Agent 能力
自动代码修改建议
自动补全功能模块
6. 🏗️ 系统架构（Architecture）
Frontend (Next.js)
        ↓
FastAPI Backend
        ↓
-------------------------
| Code Parser (tree-sitter)
-------------------------
        ↓
-------------------------
| RAG Engine
| - Embedding
| - FAISS
-------------------------
        ↓
-------------------------
| LLM (DeepSeek)
-------------------------
7. 🔄 核心流程（Core Flow）
7.1 索引流程
导入 repo
扫描文件
切分代码
生成 embedding
存储向量
7.2 问答流程
用户输入问题
检索相关代码 chunk
拼接上下文
调用 LLM
返回答案 + 来源
8. 📡 API 设计（简版）
导入仓库
POST /repo/load
构建索引
POST /repo/index
提问
POST /ask
{
  "question": "登录逻辑在哪里？"
}
9. 🧠 关键技术方案
9.1 RAG（Retrieval-Augmented Generation）
向量检索 + LLM 推理
9.2 代码解析
tree-sitter 提取结构
9.3 向量数据库
FAISS（本地）
9.4 模型
DeepSeek API（兼容 OpenAI）
10. 📊 成功指标（Success Metrics）
技术指标
查询响应时间 < 3s
检索准确率（人工评估）≥ 80%
产品指标
能正确回答：
项目结构问题
代码定位问题
开源指标
GitHub Star
Fork 数
Issue 活跃度
11. ⚠️ 非目标（Out of Scope）

当前阶段不做：

多用户系统
权限控制
云端部署
企业级协作
12. 🗺️ Roadmap
v0.1（MVP）
RAG + Q&A
Repo 导入
v0.2
文档生成
UI
v0.3
代码关系图
v0.4
Agent 能力
13. 🧾 技术选型
模块	技术
Backend	FastAPI
向量库	FAISS
Embedding	sentence-transformers
LLM	DeepSeek
解析	tree-sitter