VEGA v1.0.0 Stable Local Agent Release

VEGA is a local CLI coding agent for project work, code assistance, document reading, document analysis, local RAG search, and Ollama model profile management.

Highlights

Stable CLI runtime.
Local document reader.
Local document index.
Document analysis.
Document summaries.
Document Q and A with sources.
Model profiles for fast, code, docs, and deep workflows.
Runtime diagnostics with /doctor.
Safer behavior when the selected model is missing.
Smoke test for basic project validation.

Recommended model

Main model:
ollama pull qwen2.5-coder:14b

Optional deep mode:
ollama pull qwen2.5-coder:32b

Main commands

/about
/help
/status
/doctor
/model
/model status
/model install-help
/docs
/docs list
/docs index
/docs search <query>
/docs read <filename>
/docs analyze <filename>
/docs summarize <filename>
/docs ask <question>
/exit

Notes

Internet mode is OFF.
PDF and DOCX support requires optional Python libraries.
The 32B model may be slow or heavy on machines with 32 GB RAM.
qwen2.5-coder:14b is the recommended default model.