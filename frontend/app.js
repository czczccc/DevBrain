
const API_BASE = "http://127.0.0.1:8000";
const DEFAULT_REPO_CACHE_ROOT = "data/repos";
const INDEXABLE_EXTENSIONS = [".py", ".ts", ".js", ".md", ".json"];
const ANALYZE_POLL_INTERVAL_MS = 2000;
const ANALYZE_POLL_LIMIT = 300;

const state = {
  busy: false,
  aiConfig: null,
  aiPanelExpanded: true,
  selectedTemplateType: "deepseek",
  editingProviderId: "",
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
  aiOnboardingPanel: document.getElementById("ai-onboarding-panel"),
  aiPanelTitle: document.getElementById("ai-panel-title"),
  aiPanelDescription: document.getElementById("ai-panel-description"),
  aiActiveProviderSummary: document.getElementById("ai-active-provider-summary"),
  aiPanelToggle: document.getElementById("ai-panel-toggle"),
  aiPanelBody: document.getElementById("ai-panel-body"),
  aiSetupTitle: document.getElementById("ai-setup-title"),
  aiSetupText: document.getElementById("ai-setup-text"),
  aiTemplates: document.getElementById("ai-templates"),
  providerForm: document.getElementById("ai-provider-form"),
  providerFormTitle: document.getElementById("provider-form-title"),
  providerFormMode: document.getElementById("provider-form-mode"),
  providerName: document.getElementById("provider-name"),
  providerBaseUrl: document.getElementById("provider-base-url"),
  providerModel: document.getElementById("provider-model"),
  providerApiKey: document.getElementById("provider-api-key"),
  providerApiKeyHint: document.getElementById("provider-api-key-hint"),
  resetProviderForm: document.getElementById("reset-provider-form"),
  providerCount: document.getElementById("provider-count"),
  providerList: document.getElementById("provider-list"),
  githubUrl: document.getElementById("github-url"),
  targetDir: document.getElementById("target-dir"),
  targetDirHint: document.getElementById("target-dir-hint"),
  githubToken: document.getElementById("github-token"),
  question: document.getElementById("question"),
  topK: document.getElementById("top-k"),
  workspaceLockHint: document.getElementById("workspace-lock-hint"),
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

const actionButtons = [elements.runAll, elements.runLoad, elements.runIndex, elements.runAnalyze, elements.runAsk];
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

async function init() {
  elements.refreshHealth.addEventListener("click", handleRefreshHealth);
  elements.aiPanelToggle.addEventListener("click", toggleAiPanel);
  elements.providerForm.addEventListener("submit", handleSaveProvider);
  elements.resetProviderForm.addEventListener("click", () => resetProviderForm());
  elements.runAll.addEventListener("click", runFullFlow);
  elements.runLoad.addEventListener("click", runLoadOnly);
  elements.runIndex.addEventListener("click", runIndexOnly);
  elements.runAnalyze.addEventListener("click", runAnalyzeOnly);
  elements.runAsk.addEventListener("click", runAskOnly);
  elements.githubUrl.addEventListener("input", handleGithubUrlInput);
  elements.targetDir.addEventListener("input", handleTargetDirInput);
  await loadAiConfig();
  await refreshHealth();
  updateTargetDirHint();
  render();
}

async function handleRefreshHealth() {
  await withBusyState(async () => {
    await loadAiConfig();
    await refreshHealth();
  }, { showBusyMessage: false });
}

async function loadAiConfig() {
  const data = await apiRequest("/config/ai", { method: "GET" });
  state.aiConfig = data;
  if (!data.llm_configured) {
    state.aiPanelExpanded = true;
  } else if (!state.editingProviderId) {
    state.aiPanelExpanded = false;
  }
  ensureTemplateSelection();
  renderAiPanel();
  syncActionButtons();
}

async function refreshHealth() {
  elements.backendState.textContent = "检查中...";
  elements.backendDetail.textContent = API_BASE;
  try {
    const data = await apiRequest("/health", { method: "GET" });
    const providerText = data.active_provider_name ? ` | 当前 Provider：${data.active_provider_name}` : "";
    elements.backendState.textContent = data.status === "ok" ? "在线" : "异常";
    elements.backendDetail.textContent = `${API_BASE} | AI 已配置：${data.llm_configured ? "是" : "否"}${providerText}`;
  } catch (error) {
    elements.backendState.textContent = "离线";
    elements.backendDetail.textContent = error.message;
  }
}

function render() {
  renderAiPanel();
  syncActionButtons();
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
  elements.analysisCurrentFile.textContent = state.analyzeResponse?.current_file || "当前没有正在分析的文件。";
  elements.repoSummaryState.textContent = formatRepoSummaryState();
  elements.repoSummaryOutput.textContent = state.analyzeResponse?.repo_summary || state.askResponse?.repo_summary || "完成“开始分析”后，这里会展示仓库级总结，帮助你快速理解项目用途、核心模块和入口。";
  elements.askAnalysisBadge.textContent = `分析就绪：${state.askResponse?.analysis_ready ? "是" : "否"}`;
  elements.answerOutput.textContent = state.askResponse?.answer || "导入并分析仓库后，在左侧输入问题，这里会展示基于代码上下文生成的中文回答。";
  renderSources();
  renderJson();
}
function renderAiPanel() {
  const config = state.aiConfig;
  const configured = Boolean(config?.llm_configured);
  const activeProvider = config?.active_provider;
  const providerCount = config?.providers?.length ?? 0;
  const isEditing = Boolean(state.editingProviderId);
  const shouldCompact = configured && !state.aiPanelExpanded;
  elements.aiOnboardingPanel.classList.toggle("is-compact", configured && !state.aiPanelExpanded);
  elements.aiPanelToggle.classList.toggle("hidden", !configured);
  elements.aiPanelToggle.textContent = state.aiPanelExpanded ? "收起配置" : "管理配置";
  elements.aiPanelBody.classList.toggle("hidden", configured && !state.aiPanelExpanded);
  elements.aiActiveProviderSummary.textContent = activeProvider?.name || "尚未配置";
  elements.aiPanelTitle.textContent = configured ? "AI 已配置" : "先配置一个可用的 AI Provider";
  elements.aiPanelDescription.textContent = configured
    ? shouldCompact
      ? `当前使用 ${activeProvider?.name || "未命名 Provider"}，密钥保存在系统凭据库。`
      : "你可以继续新增、切换或编辑 Provider。API Key 仍然只保存在本机系统凭据库里。"
    : "你的 API Key 只会写入本机系统凭据库，不会保存在项目文件、浏览器存储或调试面板里。";
  elements.aiSetupTitle.textContent = configured ? `当前使用：${activeProvider?.name || "未命名 Provider"}` : "首次进入时，先完成 AI 配置";
  elements.aiSetupText.textContent = configured
    ? `已保存 ${providerCount} 个 Provider。你可以切换模型服务，当前工作台会立即使用新的激活项。`
    : "选择一个主流 Provider 模板，填写模型信息和 API Key。保存后，当前工作台会直接切换到你选中的 Provider。";
  elements.providerFormTitle.textContent = isEditing ? "编辑 Provider" : "新增 Provider";
  elements.providerFormMode.textContent = isEditing ? "重新填写 API Key 可替换旧密钥；留空则保留当前密钥。" : "保存后会自动启用为当前模型服务。";
  elements.providerApiKeyHint.textContent = isEditing ? "编辑已有 Provider 时，留空可保留当前密钥；如需更换，请重新输入新的 API Key。" : "首次创建必须填写；密钥会直接写入系统凭据库，不会出现在项目文件里。";
  elements.providerCount.textContent = `${providerCount} 个`;
  elements.workspaceLockHint.classList.toggle("hidden", configured);
  renderProviderTemplates();
  renderProviderList();
}

function renderProviderTemplates() {
  const templates = state.aiConfig?.templates ?? [];
  if (!templates.length) {
    elements.aiTemplates.innerHTML = '<p class="empty-state">当前没有可用的 Provider 模板。</p>';
    return;
  }
  elements.aiTemplates.innerHTML = templates.map((template) => `
    <button type="button" class="template-chip${template.type === state.selectedTemplateType ? " is-active" : ""}" data-template-type="${escapeHtml(template.type)}">
      <strong>${escapeHtml(template.label)}</strong>
      <span>${escapeHtml(template.description)}</span>
    </button>
  `).join("");
  elements.aiTemplates.querySelectorAll("[data-template-type]").forEach((button) => {
    button.addEventListener("click", () => applyTemplate(button.dataset.templateType || ""));
  });
}

function renderProviderList() {
  const providers = state.aiConfig?.providers ?? [];
  if (!providers.length) {
    elements.providerList.innerHTML = '<p class="empty-state">保存后，这里会显示你可切换的模型服务列表。</p>';
    return;
  }
  elements.providerList.innerHTML = providers.map((provider) => `
    <article class="provider-item${provider.is_active ? " is-active" : ""}">
      <div class="provider-item-copy">
        <div class="provider-item-title-row">
          <strong>${escapeHtml(provider.name)}</strong>
          <span class="provider-badge">${provider.is_active ? "当前使用" : provider.configured ? "已保存" : "未配置"}</span>
        </div>
        <p>${escapeHtml(provider.base_url)}</p>
        <small>${escapeHtml(provider.model)} · ${mapProviderLabel(provider.type)}</small>
      </div>
      <div class="provider-item-actions">
        <button type="button" class="mini-button" data-action="activate" data-provider-id="${escapeHtml(provider.id)}" ${provider.is_active ? "disabled" : ""}>启用</button>
        <button type="button" class="mini-button" data-action="edit" data-provider-id="${escapeHtml(provider.id)}">编辑</button>
        <button type="button" class="mini-button danger-button" data-action="delete" data-provider-id="${escapeHtml(provider.id)}">删除</button>
      </div>
    </article>
  `).join("");
  elements.providerList.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleProviderAction(button.dataset.action || "", button.dataset.providerId || ""));
  });
}

function ensureTemplateSelection() {
  const templates = state.aiConfig?.templates ?? [];
  if (!templates.length) {
    return;
  }
  const currentTemplate = templates.find((item) => item.type === state.selectedTemplateType);
  if (currentTemplate) {
    if (!state.editingProviderId && !elements.providerBaseUrl.value && !elements.providerModel.value) {
      applyTemplate(state.selectedTemplateType, { keepName: false });
    }
    return;
  }
  state.selectedTemplateType = templates[0].type;
  applyTemplate(state.selectedTemplateType, { keepName: false });
}

function applyTemplate(templateType, options = {}) {
  const template = getTemplate(templateType);
  if (!template) {
    return;
  }
  state.selectedTemplateType = template.type;
  const keepName = options.keepName ?? false;
  if (!keepName || !elements.providerName.value.trim()) {
    elements.providerName.value = template.label;
  }
  elements.providerBaseUrl.value = template.base_url;
  elements.providerModel.value = template.model;
  if (options.providerId !== undefined) {
    state.editingProviderId = options.providerId;
  }
  renderAiPanel();
}

async function handleSaveProvider(event) {
  event.preventDefault();
  await withBusyState(async () => {
    const payload = collectProviderPayload();
    const response = await apiRequest("/config/ai/providers", { method: "POST", body: payload });
    state.aiConfig = response;
    state.aiPanelExpanded = false;
    resetProviderForm({ preserveMessage: true });
    await refreshHealth();
    showMessage(`已保存并启用 Provider：${response.active_provider_name || payload.name}。`, "success");
  });
}

function collectProviderPayload() {
  const name = elements.providerName.value.trim();
  const baseUrl = elements.providerBaseUrl.value.trim();
  const model = elements.providerModel.value.trim();
  const apiKey = elements.providerApiKey.value.trim();
  if (!name) {
    throw new Error("请填写 Provider 名称。");
  }
  if (!baseUrl) {
    throw new Error("请填写 Base URL。");
  }
  if (!model) {
    throw new Error("请填写模型名称。");
  }
  if (!state.editingProviderId && !apiKey) {
    throw new Error("首次创建 Provider 时必须填写 API Key。");
  }
  return { provider_id: state.editingProviderId || null, type: state.selectedTemplateType, name, base_url: baseUrl, model, api_key: apiKey };
}

function resetProviderForm(options = {}) {
  const keepMessage = options.preserveMessage ?? false;
  state.editingProviderId = "";
  elements.providerApiKey.value = "";
  const fallbackType = state.aiConfig?.active_provider?.type || state.selectedTemplateType || "deepseek";
  state.selectedTemplateType = fallbackType;
  const template = getTemplate(fallbackType) || state.aiConfig?.templates?.[0];
  if (template) {
    elements.providerName.value = template.label;
    elements.providerBaseUrl.value = template.base_url;
    elements.providerModel.value = template.model;
  } else {
    elements.providerName.value = "";
    elements.providerBaseUrl.value = "";
    elements.providerModel.value = "";
  }
  if (!keepMessage) {
    showMessage("", "");
  }
  renderAiPanel();
}

async function handleProviderAction(action, providerId) {
  if (!providerId) {
    return;
  }
  if (action === "edit") {
    startEditProvider(providerId);
    return;
  }
  await withBusyState(async () => {
    if (action === "activate") {
      state.aiConfig = await apiRequest("/config/ai/activate", { method: "POST", body: { provider_id: providerId } });
      state.aiPanelExpanded = false;
      await refreshHealth();
      showMessage("已切换当前 AI Provider。", "success");
      return;
    }
    if (action === "delete") {
      const provider = state.aiConfig?.providers?.find((item) => item.id === providerId);
      const confirmed = window.confirm(`确定要删除 Provider “${provider?.name || "未命名"}” 吗？`);
      if (!confirmed) {
        return;
      }
      state.aiConfig = await apiRequest(`/config/ai/providers/${providerId}`, { method: "DELETE" });
      if (state.editingProviderId === providerId) {
        resetProviderForm({ preserveMessage: true });
      }
      await refreshHealth();
      showMessage("Provider 已删除。", "success");
    }
  });
}

function startEditProvider(providerId) {
  const provider = state.aiConfig?.providers?.find((item) => item.id === providerId);
  if (!provider) {
    showMessage("找不到要编辑的 Provider。", "error");
    return;
  }
  state.editingProviderId = provider.id;
  state.selectedTemplateType = provider.type;
  elements.providerName.value = provider.name;
  elements.providerBaseUrl.value = provider.base_url;
  elements.providerModel.value = provider.model;
  elements.providerApiKey.value = "";
  state.aiPanelExpanded = true;
  renderAiPanel();
}

function toggleAiPanel() {
  state.aiPanelExpanded = !state.aiPanelExpanded || !state.aiConfig?.llm_configured;
  renderAiPanel();
}
async function runFullFlow() {
  if (!validateAiConfigured() || !validateLoadInputs() || !validateQuestion()) {
    return;
  }
  await withBusyState(async () => {
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
  if (!validateAiConfigured() || !validateLoadInputs()) {
    return;
  }
  await withBusyState(async () => {
    const loadData = await callLoadRepo();
    if (getIndexableFileCount(loadData) === 0) {
      return;
    }
    showMessage(loadData.metadata.cache_reused ? "已复用本地缓存，仓库无需重复下载。" : "仓库导入成功。", "success");
  });
}

async function runIndexOnly() {
  if (!validateAiConfigured()) {
    return;
  }
  await withBusyState(async () => {
    await callIndexRepo(requireProjectId());
    showMessage("索引构建完成。", "success");
  });
}

async function runAnalyzeOnly() {
  if (!validateAiConfigured()) {
    return;
  }
  await withBusyState(async () => {
    await callAnalyzeRepo(requireProjectId());
    showMessage("仓库分析完成。", "success");
  });
}

async function runAskOnly() {
  if (!validateAiConfigured() || !validateQuestion()) {
    return;
  }
  await withBusyState(async () => {
    await callAsk(requireProjectId());
    showMessage("AI 已返回回答。", "success");
  });
}

async function callLoadRepo() {
  setStepState("load", "running", "正在从 GitHub 导入仓库...");
  setStepState("index", "idle", "等待仓库导入");
  setStepState("analyze", "idle", "等待索引完成");
  setStepState("ask", "idle", "等待提问");
  const payload = { github_url: elements.githubUrl.value.trim(), target_dir: elements.targetDir.value.trim() };
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
    response = await apiRequest("/repo/index", { method: "POST", body: { project_id: projectId } });
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
    startResponse = await apiRequest("/repo/analyze", { method: "POST", body: { project_id: projectId } });
  } catch (error) {
    throw new Error(rewriteAnalyzeError(error));
  }
  state.analyzeResponse = startResponse;
  render();
  return pollAnalyzeStatus(startResponse.job_id);
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
  setStepState("ask", "running", "正在把检索结果发送给当前 AI...");
  const response = await apiRequest("/ask", {
    method: "POST",
    body: { project_id: projectId, question: elements.question.value.trim(), top_k: Number(elements.topK.value) },
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
function validateAiConfigured() {
  if (state.aiConfig?.llm_configured) {
    return true;
  }
  state.aiPanelExpanded = true;
  renderAiPanel();
  showMessage("先完成上方 AI 配置，再使用仓库理解功能。", "error");
  return false;
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
    showMessage("向当前 AI 提问前，请先填写问题。", "error");
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

async function withBusyState(task, options = {}) {
  const showBusyMessage = options.showBusyMessage ?? true;
  state.busy = true;
  syncActionButtons();
  if (showBusyMessage) {
    showMessage("正在执行流程，请稍候...", "");
  }
  try {
    await task();
  } catch (error) {
    showMessage(error.message, "error");
    syncErrorState(error.message);
  } finally {
    state.busy = false;
    syncActionButtons();
    render();
  }
}

function syncActionButtons() {
  const locked = state.busy || !state.aiConfig?.llm_configured;
  actionButtons.forEach((button) => {
    button.disabled = locked;
    button.classList.toggle("is-disabled", locked);
  });
}

function syncErrorState(message) {
  const runningStep = ["load", "index", "analyze", "ask"].find((step) => stepElements[step].classList.contains("is-running"));
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
    setStepState("analyze", "success", `已分析 ${status.completed_files}/${status.total_files} 个文件${suffix}`);
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

function renderSources() {
  const sources = state.askResponse?.sources ?? [];
  elements.sourceCount.textContent = `共 ${sources.length} 条`;
  if (!sources.length) {
    elements.sourcesList.innerHTML = '<p class="empty-state">相关代码片段会显示在这里，方便你核对回答依据。</p>';
    return;
  }
  elements.sourcesList.innerHTML = sources.map((source) => `
    <article class="source-item">
      <strong>${escapeHtml(source.file_path)}</strong>
      <div class="source-meta">
        <span>行号 ${escapeHtml(source.line_range)}</span>
        <span>相关度 ${Number(source.score).toFixed(3)}</span>
      </div>
    </article>
  `).join("");
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
  const shouldAutofill = !state.targetDirTouched || !currentValue || currentValue === state.lastSuggestedTargetDir;
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
  return parsed ? `${DEFAULT_REPO_CACHE_ROOT}/${parsed.owner}__${parsed.repo}` : "";
}

function parseGithubUrl(rawUrl) {
  const match = rawUrl.trim().match(/^https:\/\/github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/);
  return match ? { owner: match[1], repo: match[2] } : null;
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
    elements.targetDirHint.textContent = "当前使用你自定义的目录；如果该目录已经是同一仓库缓存，系统仍会自动复用。";
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
  return state.analyzeResponse ? mapAnalyzeStatus(state.analyzeResponse.status) : "未开始";
}

function formatRepoSummaryState() {
  if (!isAnalysisReady()) {
    return "未生成";
  }
  if (state.analyzeResponse?.repo_summary_ready && state.analyzeResponse?.status === "running") {
    return "已生成（首轮）";
  }
  return "已生成";
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
  showMessage(`仓库已导入，但没有发现可索引文件。当前支持的文件类型：${INDEXABLE_EXTENSIONS.join(", ")}。`, "error");
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
  if (message.includes("尚未配置可用的 AI Provider") || message.includes("当前激活的 AI Provider")) {
    return "当前没有可用的 AI Provider，请先完成上方配置。";
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

function getTemplate(templateType) {
  return (state.aiConfig?.templates ?? []).find((item) => item.type === templateType) || null;
}

function mapProviderLabel(providerType) {
  const template = getTemplate(providerType);
  return template?.label || providerType;
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
