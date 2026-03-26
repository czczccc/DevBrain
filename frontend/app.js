const API_BASE = "http://127.0.0.1:8000";
const DEFAULT_REPO_CACHE_ROOT = "data/repos";
const INDEXABLE_EXTENSIONS = [".py", ".ts", ".js", ".md", ".json"];
const ANALYZE_POLL_INTERVAL_MS = 2000;
const ANALYZE_POLL_LIMIT = 300;

const state = {
  projectId: "",
  loadResponse: null,
  indexResponse: null,
  analyzeResponse: null,
  askResponse: null,
  lastSuggestedTargetDir: "",
  targetDirTouched: false,
};

const elements = {
  backendState: document.getElementById("backend-state"),
  backendDetail: document.getElementById("backend-detail"),
  refreshHealth: document.getElementById("refresh-health"),
  githubUrl: document.getElementById("github-url"),
  targetDir: document.getElementById("target-dir"),
  targetDirHint: document.getElementById("target-dir-hint"),
  githubToken: document.getElementById("github-token"),
  question: document.getElementById("question"),
  topK: document.getElementById("top-k"),
  messageBanner: document.getElementById("message-banner"),
  projectId: document.getElementById("project-id"),
  fileCount: document.getElementById("file-count"),
  chunkCount: document.getElementById("chunk-count"),
  indexableCount: document.getElementById("indexable-count"),
  analyzedCount: document.getElementById("analyzed-count"),
  failedCount: document.getElementById("failed-count"),
  sourceType: document.getElementById("source-type"),
  cacheStatus: document.getElementById("cache-status"),
  analysisReady: document.getElementById("analysis-ready"),
  rootPath: document.getElementById("root-path"),
  analysisStatus: document.getElementById("analysis-status"),
  analysisCurrentFile: document.getElementById("analysis-current-file"),
  repoSummaryState: document.getElementById("repo-summary-state"),
  repoSummaryOutput: document.getElementById("repo-summary-output"),
  askAnalysisBadge: document.getElementById("ask-analysis-badge"),
  answerOutput: document.getElementById("answer-output"),
  sourceCount: document.getElementById("source-count"),
  sourcesList: document.getElementById("sources-list"),
  loadJson: document.getElementById("load-json"),
  indexJson: document.getElementById("index-json"),
  analyzeJson: document.getElementById("analyze-json"),
  askJson: document.getElementById("ask-json"),
  runAll: document.getElementById("run-all"),
  runLoad: document.getElementById("run-load"),
  runIndex: document.getElementById("run-index"),
  runAnalyze: document.getElementById("run-analyze"),
  runAsk: document.getElementById("run-ask"),
};

const stepElements = {
  load: document.querySelector('[data-step="load"]'),
  index: document.querySelector('[data-step="index"]'),
  analyze: document.querySelector('[data-step="analyze"]'),
  ask: document.querySelector('[data-step="ask"]'),
};

const stepTexts = {
  load: document.getElementById("load-step-text"),
  index: document.getElementById("index-step-text"),
  analyze: document.getElementById("analyze-step-text"),
  ask: document.getElementById("ask-step-text"),
};

function init() {
  elements.refreshHealth.addEventListener("click", refreshHealth);
  elements.runAll.addEventListener("click", runFullFlow);
  elements.runLoad.addEventListener("click", runLoadOnly);
  elements.runIndex.addEventListener("click", runIndexOnly);
  elements.runAnalyze.addEventListener("click", runAnalyzeOnly);
  elements.runAsk.addEventListener("click", runAskOnly);
  elements.githubUrl.addEventListener("input", handleGithubUrlInput);
  elements.targetDir.addEventListener("input", handleTargetDirInput);
  refreshHealth();
  updateTargetDirHint();
  render();
}

async function refreshHealth() {
  elements.backendState.textContent = "检查中...";
  elements.backendDetail.textContent = API_BASE;
  try {
    const data = await apiRequest("/health", { method: "GET" });
    elements.backendState.textContent = data.status === "ok" ? "在线" : "异常";
    elements.backendDetail.textContent = `${API_BASE} | DeepSeek 已配置：${data.deepseek_configured ? "是" : "否"}`;
  } catch (error) {
    elements.backendState.textContent = "离线";
    elements.backendDetail.textContent = error.message;
  }
}

async function runFullFlow() {
  if (!validateLoadInputs() || !validateQuestion()) {
    return;
  }

  withBusyState(async () => {
    const loadData = await callLoadRepo();
    if (getIndexableFileCount(loadData) === 0) {
      return;
    }
    await callIndexRepo(loadData.metadata.project_id);
    await callAnalyzeRepo(loadData.metadata.project_id);
    await callAsk(loadData.metadata.project_id);
    showMessage("一键流程已完成。", "success");
  });
}

async function runLoadOnly() {
  if (!validateLoadInputs()) {
    return;
  }

  withBusyState(async () => {
    const loadData = await callLoadRepo();
    if (getIndexableFileCount(loadData) === 0) {
      return;
    }
    showMessage(
      loadData.metadata.cache_reused
        ? "已复用本地缓存，仓库无需重复下载。"
        : "仓库导入成功。",
      "success"
    );
  });
}

async function runIndexOnly() {
  withBusyState(async () => {
    await callIndexRepo(requireProjectId());
    showMessage("索引构建完成。", "success");
  });
}

async function runAnalyzeOnly() {
  withBusyState(async () => {
    await callAnalyzeRepo(requireProjectId());
    showMessage("仓库分析完成。", "success");
  });
}

async function runAskOnly() {
  if (!validateQuestion()) {
    return;
  }

  withBusyState(async () => {
    await callAsk(requireProjectId());
    showMessage("DeepSeek 已返回回答。", "success");
  });
}

async function callLoadRepo() {
  setStepState("load", "running", "正在从 GitHub 导入仓库...");
  setStepState("index", "idle", "等待仓库导入");
  setStepState("analyze", "idle", "等待索引完成");
  setStepState("ask", "idle", "等待提问");

  const payload = {
    github_url: elements.githubUrl.value.trim(),
    target_dir: elements.targetDir.value.trim(),
  };
  const token = elements.githubToken.value.trim();
  let response;
  try {
    response = await apiRequest("/repo/load", {
      method: "POST",
      body: payload,
      headers: token ? { "X-GitHub-Token": token } : {},
    });
  } catch (error) {
    throw new Error(rewriteLoadError(error, payload.github_url, Boolean(token)));
  }

  state.projectId = response.metadata.project_id;
  state.loadResponse = response;
  state.indexResponse = null;
  state.analyzeResponse = null;
  state.askResponse = null;

  const modeText = response.metadata.cache_reused ? "已复用本地缓存" : "已完成首次克隆";
  setStepState("load", "success", `已导入 ${response.files.length} 个文件 | ${modeText}`);
  updateTargetDirHint(response.metadata.cache_reused);
  maybeShowIndexabilityHint(response);
  render();
  return response;
}

async function callIndexRepo(projectId) {
  setStepState("index", "running", "正在构建逐行覆盖索引...");
  setStepState("analyze", "idle", "等待索引完成");
  setStepState("ask", "idle", "等待分析完成或直接提问");
  let response;
  try {
    response = await apiRequest("/repo/index", {
      method: "POST",
      body: { project_id: projectId },
    });
  } catch (error) {
    throw new Error(rewriteIndexError(error));
  }
  state.indexResponse = response;
  state.analyzeResponse = null;
  state.askResponse = null;
  setStepState("index", "success", `已生成 ${response.chunk_count} 个索引块`);
  render();
  return response;
}

async function callAnalyzeRepo(projectId) {
  setStepState("analyze", "running", "正在逐文件分析仓库...");
  let startResponse;
  try {
    startResponse = await apiRequest("/repo/analyze", {
      method: "POST",
      body: { project_id: projectId },
    });
  } catch (error) {
    throw new Error(rewriteAnalyzeError(error));
  }
  state.analyzeResponse = startResponse;
  render();
  return await pollAnalyzeStatus(startResponse.job_id);
}

async function pollAnalyzeStatus(jobId) {
  for (let attempt = 0; attempt < ANALYZE_POLL_LIMIT; attempt += 1) {
    const status = await apiRequest(`/repo/analyze/${jobId}`, { method: "GET" });
    state.analyzeResponse = status;
    setAnalyzeStepState(status);
    render();
    if (isAnalyzeTerminal(status.status)) {
      if (status.status === "failed" || status.status === "interrupted") {
        throw new Error(`仓库分析${formatAnalyzeTerminalError(status.status)}。`);
      }
      return status;
    }
    await delay(ANALYZE_POLL_INTERVAL_MS);
  }
  throw new Error("仓库分析超时，尚未在预期时间内完成。");
}

async function callAsk(projectId) {
  setStepState("ask", "running", "正在把检索结果发送给 DeepSeek...");
  const response = await apiRequest("/ask", {
    method: "POST",
    body: {
      project_id: projectId,
      question: elements.question.value.trim(),
      top_k: Number(elements.topK.value),
    },
  });
  state.askResponse = response;
  setStepState("ask", "success", `已返回 ${response.sources.length} 条引用来源`);
  render();
  return response;
}

async function apiRequest(path, options = {}) {
  const method = options.method || "POST";
  const headers = { ...(options.headers || {}) };
  const fetchOptions = { method, headers };

  if (options.body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${path}`, fetchOptions);
  const text = await response.text();
  const data = text ? tryParseJson(text) : {};
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : text || `Request failed with ${response.status}`;
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }
  return data;
}

function validateLoadInputs() {
  if (!elements.githubUrl.value.trim()) {
    showMessage("请先输入 GitHub 仓库地址。", "error");
    return false;
  }
  if (!elements.targetDir.value.trim()) {
    const suggestedTargetDir = buildTargetDirFromGithubUrl(elements.githubUrl.value);
    if (suggestedTargetDir) {
      applySuggestedTargetDir(suggestedTargetDir);
    }
  }
  if (!elements.targetDir.value.trim()) {
    showMessage("请填写目标目录。", "error");
    return false;
  }
  return true;
}

function validateQuestion() {
  if (!elements.question.value.trim()) {
    showMessage("向 DeepSeek 提问前，请先填写问题。", "error");
    return false;
  }
  const topK = Number(elements.topK.value);
  if (!Number.isInteger(topK) || topK < 1 || topK > 20) {
    showMessage("检索数量必须是 1 到 20 之间的整数。", "error");
    return false;
  }
  return true;
}

function requireProjectId() {
  if (!state.projectId) {
    throw new Error("当前还没有 project_id，请先执行“仅导入仓库”或“一键运行”。");
  }
  return state.projectId;
}

async function withBusyState(task) {
  toggleButtons(true);
  showMessage("正在执行流程，请稍候...", "");
  try {
    await task();
  } catch (error) {
    showMessage(error.message, "error");
    syncErrorState(error.message);
  } finally {
    toggleButtons(false);
    render();
  }
}

function syncErrorState(message) {
  const runningStep = ["load", "index", "analyze", "ask"].find((step) =>
    stepElements[step].classList.contains("is-running")
  );
  if (runningStep) {
    setStepState(runningStep, "error", message);
  }
}

function setStepState(step, mode, text) {
  const element = stepElements[step];
  element.classList.remove("is-running", "is-success", "is-error");
  if (mode === "running") {
    element.classList.add("is-running");
  }
  if (mode === "success") {
    element.classList.add("is-success");
  }
  if (mode === "error") {
    element.classList.add("is-error");
  }
  stepTexts[step].textContent = text;
}

function setAnalyzeStepState(status) {
  if (status.status === "completed" || status.status === "completed_with_errors") {
    const suffix = status.failed_files > 0 ? ` | 失败 ${status.failed_files} 个` : "";
    setStepState(
      "analyze",
      "success",
      `已分析 ${status.completed_files}/${status.total_files} 个文件${suffix}`
    );
    return;
  }
  if (status.status === "failed" || status.status === "interrupted") {
    setStepState("analyze", "error", `分析${formatAnalyzeTerminalError(status.status)}。`);
    return;
  }
  const currentFile = status.current_file ? ` | ${status.current_file}` : "";
  setStepState("analyze", "running", `已分析 ${status.completed_files}/${status.total_files}${currentFile}`);
}

function showMessage(message, tone) {
  elements.messageBanner.textContent = message;
  elements.messageBanner.classList.remove("hidden", "success", "error");
  if (!message) {
    elements.messageBanner.classList.add("hidden");
    return;
  }
  if (tone === "success") {
    elements.messageBanner.classList.add("success");
  } else if (tone === "error") {
    elements.messageBanner.classList.add("error");
  }
}

function toggleButtons(isBusy) {
  [elements.runAll, elements.runLoad, elements.runIndex, elements.runAnalyze, elements.runAsk].forEach(
    (button) => {
      button.disabled = isBusy;
      button.classList.toggle("is-disabled", isBusy);
    }
  );
}

function render() {
  elements.projectId.textContent = state.projectId || "尚未创建";
  elements.fileCount.textContent = state.loadResponse?.files?.length ?? 0;
  elements.chunkCount.textContent = state.indexResponse?.chunk_count ?? 0;
  elements.indexableCount.textContent = getIndexableFileCount(state.loadResponse);
  elements.analyzedCount.textContent = `${state.analyzeResponse?.completed_files ?? 0} / ${state.analyzeResponse?.total_files ?? 0}`;
  elements.failedCount.textContent = state.analyzeResponse?.failed_files ?? 0;
  elements.sourceType.textContent = formatSourceType(state.loadResponse?.metadata?.source_type);
  elements.cacheStatus.textContent = formatCacheStatus(state.loadResponse?.metadata?.cache_reused);
  elements.analysisReady.textContent = isAnalysisReady() ? "是" : "否";
  elements.rootPath.textContent = state.loadResponse?.metadata?.root_path ?? "暂无";
  elements.analysisStatus.textContent = formatAnalyzeStatus();
  elements.analysisCurrentFile.textContent =
    state.analyzeResponse?.current_file || "当前没有正在分析的文件。";
  elements.repoSummaryState.textContent = isAnalysisReady() ? "已生成" : "未生成";
  elements.repoSummaryOutput.textContent =
    state.analyzeResponse?.repo_summary ||
    state.askResponse?.repo_summary ||
    "完成“开始分析”后，这里会展示仓库级总结，帮助你快速理解项目用途、核心模块和入口。";
  elements.askAnalysisBadge.textContent = `分析就绪：${state.askResponse?.analysis_ready ? "是" : "否"}`;
  elements.answerOutput.textContent =
    state.askResponse?.answer ||
    "导入并分析仓库后，在左侧输入问题，这里会展示基于代码上下文生成的中文回答。";

  renderSources();
  renderJson();
}

function renderSources() {
  const sources = state.askResponse?.sources ?? [];
  elements.sourceCount.textContent = `共 ${sources.length} 条`;
  if (!sources.length) {
    elements.sourcesList.innerHTML = '<p class="empty-state">相关代码片段会显示在这里，方便你核对回答依据。</p>';
    return;
  }

  elements.sourcesList.innerHTML = sources
    .map(
      (source) => `
        <article class="source-item">
          <strong>${escapeHtml(source.file_path)}</strong>
          <div class="source-meta">
            <span>行号 ${escapeHtml(source.line_range)}</span>
            <span>相关度 ${Number(source.score).toFixed(3)}</span>
          </div>
        </article>
      `
    )
    .join("");
}

function renderJson() {
  elements.loadJson.textContent = formatJson(state.loadResponse);
  elements.indexJson.textContent = formatJson(state.indexResponse);
  elements.analyzeJson.textContent = formatJson(state.analyzeResponse);
  elements.askJson.textContent = formatJson(state.askResponse);
}

function handleGithubUrlInput() {
  const suggestedTargetDir = buildTargetDirFromGithubUrl(elements.githubUrl.value);
  if (!suggestedTargetDir) {
    state.lastSuggestedTargetDir = "";
    updateTargetDirHint();
    return;
  }

  const currentValue = elements.targetDir.value.trim();
  const shouldAutofill =
    !state.targetDirTouched || !currentValue || currentValue === state.lastSuggestedTargetDir;

  state.lastSuggestedTargetDir = suggestedTargetDir;
  if (shouldAutofill) {
    applySuggestedTargetDir(suggestedTargetDir);
    state.targetDirTouched = false;
  } else {
    updateTargetDirHint();
  }
}

function handleTargetDirInput() {
  const currentValue = elements.targetDir.value.trim();
  state.targetDirTouched = Boolean(currentValue && currentValue !== state.lastSuggestedTargetDir);
  updateTargetDirHint();
}

function applySuggestedTargetDir(targetDir) {
  elements.targetDir.value = targetDir;
  state.lastSuggestedTargetDir = targetDir;
  updateTargetDirHint();
}

function buildTargetDirFromGithubUrl(rawUrl) {
  const parsed = parseGithubUrl(rawUrl);
  if (!parsed) {
    return "";
  }
  return `${DEFAULT_REPO_CACHE_ROOT}/${parsed.owner}__${parsed.repo}`;
}

function parseGithubUrl(rawUrl) {
  const match = rawUrl
    .trim()
    .match(/^https:\/\/github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/);

  if (!match) {
    return null;
  }

  return { owner: match[1], repo: match[2] };
}

function updateTargetDirHint(cacheReused = false) {
  const suggestedTargetDir = state.lastSuggestedTargetDir;
  const currentValue = elements.targetDir.value.trim();
  elements.targetDirHint.classList.remove("is-ready", "is-cache");

  if (cacheReused) {
    elements.targetDirHint.textContent = "已复用本地缓存，本次未重复下载仓库。";
    elements.targetDirHint.classList.add("is-cache");
    return;
  }
  if (suggestedTargetDir && currentValue === suggestedTargetDir) {
    elements.targetDirHint.textContent = `已根据仓库地址自动生成目录：${suggestedTargetDir}`;
    elements.targetDirHint.classList.add("is-ready");
    return;
  }
  if (suggestedTargetDir && currentValue && currentValue !== suggestedTargetDir) {
    elements.targetDirHint.textContent =
      "当前使用你自定义的目录；如果该目录已经是同一仓库缓存，系统仍会自动复用。";
    return;
  }
  elements.targetDirHint.textContent = "输入合法的 GitHub 地址后，会自动生成缓存目录，你也可以手动调整。";
}

function formatSourceType(sourceType) {
  if (!sourceType) {
    return "暂无";
  }
  return sourceType === "github" ? "GitHub 仓库" : "本地路径";
}

function formatCacheStatus(cacheReused) {
  if (cacheReused === true) {
    return "已复用本地缓存";
  }
  if (cacheReused === false && state.loadResponse) {
    return "首次克隆";
  }
  return "未确定";
}

function formatAnalyzeStatus() {
  if (!state.analyzeResponse) {
    return "未开始";
  }
  return mapAnalyzeStatus(state.analyzeResponse.status);
}

function isAnalysisReady() {
  return Boolean(state.askResponse?.analysis_ready || state.analyzeResponse?.repo_summary_ready);
}

function getIndexableFileCount(loadResponse) {
  if (!loadResponse?.files?.length) {
    return 0;
  }
  return loadResponse.files.filter((item) => hasIndexableExtension(item.path)).length;
}

function hasIndexableExtension(path) {
  const normalized = String(path || "").toLowerCase();
  return INDEXABLE_EXTENSIONS.some((extension) => normalized.endsWith(extension));
}

function maybeShowIndexabilityHint(loadResponse) {
  const indexableCount = getIndexableFileCount(loadResponse);
  if (indexableCount > 0) {
    return;
  }
  showMessage(
    `仓库已导入，但没有发现可索引文件。当前支持的文件类型：${INDEXABLE_EXTENSIONS.join(", ")}。`,
    "error"
  );
}

function rewriteLoadError(error, githubUrl, hasToken) {
  const message = error instanceof Error ? error.message : String(error);
  if (!message.startsWith("HTTP 404:")) {
    return message;
  }
  return hasToken
    ? `无法访问仓库：${githubUrl}。请确认地址正确，并检查 Token 是否具备该仓库的读取权限。`
    : `无法访问仓库：${githubUrl}。请确认地址是否正确；如果是私有仓库，请补充可用的 GitHub Token。`;
}

function rewriteIndexError(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (!message.includes("No chunks available to index")) {
    return message;
  }
  const indexableCount = getIndexableFileCount(state.loadResponse);
  if (indexableCount === 0) {
    return `当前规则下，这个仓库没有可索引文件。支持的文件类型：${INDEXABLE_EXTENSIONS.join(", ")}。`;
  }
  return `发现了 ${indexableCount} 个可索引文件，但没有成功生成索引块。请检查这些文件是否为空，或是否超出了当前解析能力。`;
}

function rewriteAnalyzeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (message.includes("DEEPSEEK_API_KEY")) {
    return "DeepSeek 尚未配置，暂时无法启动仓库分析。";
  }
  return message;
}

function isAnalyzeTerminal(status) {
  return ["completed", "completed_with_errors", "failed", "interrupted"].includes(status);
}

function tryParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function formatJson(value) {
  return value ? JSON.stringify(value, null, 2) : "暂无返回数据。";
}

function mapAnalyzeStatus(status) {
  switch (status) {
    case "pending":
      return "排队中";
    case "running":
      return "分析中";
    case "completed":
      return "已完成";
    case "completed_with_errors":
      return "完成（有错误）";
    case "failed":
      return "失败";
    case "interrupted":
      return "已中断";
    default:
      return status || "未开始";
  }
}

function formatAnalyzeTerminalError(status) {
  if (status === "failed") {
    return "失败";
  }
  if (status === "interrupted") {
    return "被中断";
  }
  return status;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

init();
