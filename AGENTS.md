# DevBrain Project Rules

## 🎯 Project Goal
Build a local-first AI system that understands codebases using RAG.

---

## 🧱 Architecture Rules

- Use modular architecture:
  - api/
  - core/
  - services/
  - models/

- Keep business logic inside `core/` and `services/`
- API layer should be thin (only request/response handling)

---

## ⚙️ Tech Stack Rules

- Backend: FastAPI
- Vector DB: FAISS
- Embedding: sentence-transformers
- LLM: DeepSeek (OpenAI-compatible API)
- Code parsing: tree-sitter

DO NOT introduce new frameworks unless necessary.

---

## 🧠 RAG Rules

- Always use retrieval before calling LLM
- Never answer without context from codebase
- Limit context size to avoid token overflow
- Prefer function-level chunks over raw text chunks

---

## 📂 Repo Handling Rules

- Ignore directories:
  - node_modules
  - .git
  - build
  - dist

- Only index relevant files:
  - .py .ts .js .md .json

---

## 🧾 Code Style

- Write clean, readable, modular code
- Use type hints (Python typing)
- Avoid large functions (>50 lines)
- Use clear naming (no abbreviations)

---

## 🚫 What NOT to do

- Do NOT over-engineer
- Do NOT add unnecessary abstractions
- Do NOT rewrite existing working logic
- Do NOT introduce complex frameworks

---

## 🔁 Workflow Rules

- Always:
  1. Understand existing code before editing
  2. Make minimal changes
  3. Keep consistency with current style

---

## 🧪 Testing Rules

- Ensure core logic is testable
- Avoid side effects in core modules

---

## 🧩 Future Extensions (Keep in mind)

- Code graph (NetworkX)
- Agent-based code modification
- Multi-repo support

## 🧠 Skill: Progress Summary

When user asks about progress or current status:

Always output in the following format:

1. 已完成模块
2. 新增/修改的文件
3. 当前还缺什么才能达到 MVP
4. 最推荐的下一步（只选一个）
5. 如果继续开发，建议我发给你的下一条指令

Constraints:
- 只基于当前线程和实际代码状态回答
- 不要扩展新需求
- 不要同时给多个下一步
- 优先保证项目尽快跑通