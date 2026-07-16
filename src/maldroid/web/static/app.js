const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { bootstrap: null, workspace: { active: false }, activeId: null, socket: null, socketQueue: Promise.resolve(), busy: false, activities: [], unread: 0, files: [], collapsedDirectories: new Set(), selectedFile: null, fileFilter: "", touchedFiles: new Set(), showLogs: false, theme: "dark", work: { startedAt: 0, timer: null, phase: 1, tools: 0, tokens: 0, context: 0, steps: [] } };

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

async function boot() {
  initializeTheme();
  initializeFilePreferences();
  try {
    state.bootstrap = await api("/api/bootstrap");
    state.workspace = state.bootstrap.workspace;
    state.activeId = state.workspace.case?.case_id || null;
    $("#version-label").textContent = `v${state.bootstrap.version}`;
    renderProjects(); renderWorkspace(); fillSettings(); renderConnectors(); connectSocket(); bindUI();
    if (state.activeId) await loadProjectData(state.activeId);
  } catch (error) {
    document.body.textContent = `MalDroid could not load: ${error.message}`;
  }
}

function bindUI() {
  document.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action) await handleAction(action, event.target.closest("[data-action]"));
    const tab = event.target.closest("[data-tab]")?.dataset.tab;
    if (tab) selectInspectorTab(tab);
    const settingsTab = event.target.closest("[data-settings-tab]")?.dataset.settingsTab;
    if (settingsTab) selectSettingsTab(settingsTab);
    const command = event.target.closest("[data-command]")?.dataset.command;
    if (command) await runCommand(command, {});
    if (!event.target.closest("#menu") && !event.target.closest("[data-action='profile'],[data-action='reasoning'],[data-action='command-palette']")) hideMenu();
  });
  $("#message-input").addEventListener("input", resizeComposer);
  $("#file-filter").addEventListener("input", (event) => { state.fileFilter = event.target.value.trim().toLowerCase(); renderFiles(); });
  $("#theme-setting").addEventListener("change", (event) => setTheme(event.target.value));
  $("#message-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); }
  });
  $("#send-button").addEventListener("click", sendMessage);
  $("#project-form").addEventListener("submit", createProject);
  $("#settings-form").addEventListener("submit", saveSettings);
  window.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); showActionMenu($("[data-action='command-palette']")); }
    if (event.key === "Escape") hideMenu();
  });
  window.addEventListener("resize", syncPaneState);
  syncPaneState();
}

function connectSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.socket = socket;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    state.socketQueue = state.socketQueue
      .then(() => state.socket === socket ? handleSocket(message) : undefined)
      .catch(error => { setBusy(false); toast(error.message, true); });
  };
  socket.onclose = () => { if (state.socket !== socket) return; state.socket = null; setTimeout(connectSocket, 1200); };
}

async function handleSocket(message) {
  if (message.type === "connected") { state.workspace = message.workspace || { active: false }; setBusy(false); await refreshBootstrap(); state.activeId = state.workspace.case?.case_id || null; renderWorkspace(); renderProjects(); if (state.activeId) await loadProjectData(state.activeId); else clearProjectData(); return; }
  if (message.type === "activity") { addActivity(message.event, message.data); updateProgress(message.event, message.data); return; }
  if (message.type === "runtime_start") { startLiveWork("Starting local model", "Loading llama.cpp and case-scoped MCP tools…", false); setBusy(true, "Starting local model", "Loading llama.cpp and case-scoped MCP tools…"); return; }
  if (message.type === "runtime_ready") { state.workspace = message.workspace; state.activeId = state.workspace.case.case_id; setBusy(false); renderWorkspace(); await refreshBootstrap(); await loadProjectData(state.activeId); $("#message-input").focus(); toast("Local model and MCP workspace are ready. You can message MalDroid below."); return; }
  if (message.type === "turn_start") { state.touchedFiles.clear(); renderFiles(); startLiveWork("Thinking", "Planning the next research step…", true); setBusy(true, "Thinking", "Planning the next research step…"); return; }
  if (message.type === "turn_stopping") { $("#stop-turn").disabled = true; $("#progress-title").textContent = "Stopping"; $("#progress-detail").textContent = "Finishing the current safe boundary…"; appendLiveWorkStep("turn_stopping"); return; }
  if (message.type === "turn_stopped") { state.workspace = message.workspace; setBusy(false); renderWorkspace(); renderResearch(); await loadFiles(); $("#message-input").focus(); toast("Model turn stopped. Durable research state was preserved."); return; }
  if (message.type === "assistant") { addMessage("assistant", message.content); state.workspace = message.workspace; setBusy(false); renderWorkspace(); renderResearch(); await loadFiles(); return; }
  if (message.type === "error") { setBusy(false); try { await refreshBootstrap(); state.activeId = state.workspace.case?.case_id || null; renderWorkspace(); renderProjects(); if (state.activeId) await loadProjectData(state.activeId); else clearProjectData(); } catch {} toast(message.error, true); }
}

async function refreshBootstrap() {
  const fresh = await api("/api/bootstrap");
  state.bootstrap = fresh;
  state.workspace = fresh.workspace;
  renderProjects(); fillSettings(); renderConnectors();
}

function renderProjects() {
  const list = $("#project-list"); list.replaceChildren();
  for (const project of state.bootstrap.projects) {
    const button = el("button", "project-item" + (project.case_id === state.activeId ? " active" : ""));
    button.dataset.caseId = project.case_id;
    button.addEventListener("click", () => activateProject(project.case_id));
    const icon = el("span", "project-icon", "◇");
    const copy = el("span", "project-copy"); copy.append(el("strong", "", project.name), el("small", "", relativeTime(project.last_opened_at)));
    button.append(icon, copy, el("span", "project-profile", shortProfile(project.profile)));
    list.append(button);
  }
  if (!state.bootstrap.projects.length) list.append(el("div", "empty-state", "No investigations yet."));
}

async function activateProject(caseId) {
  if (state.busy) return toast("Wait for the active operation to finish.", true);
  state.activeId = caseId; state.touchedFiles.clear(); renderProjects();
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return toast("Workspace connection is reconnecting.", true);
  state.socket.send(JSON.stringify({ type: "activate", case_id: caseId }));
  if (innerWidth <= 900) $(".sidebar").classList.remove("open");
}

function renderWorkspace() {
  const active = state.workspace.active && state.workspace.case;
  const current = state.workspace.case || state.bootstrap?.projects.find(item => item.case_id === state.activeId);
  $("#project-title").textContent = current?.name || "MalDroid Workspace";
  $("#project-path").textContent = current?.path || "Select or create an investigation";
  $("#welcome").classList.toggle("hidden", Boolean(current));
  $("#messages").classList.toggle("hidden", !current);
  $("#composer-disabled").classList.toggle("hidden", Boolean(active));
  $("#composer").classList.toggle("hidden", !active);
  $("#composer-disabled").textContent = current ? (state.busy ? "Starting the local model and research tools…" : "Local model offline. Check Settings, then reopen this investigation.") : "Open an investigation to begin";
  const status = $("#runtime-status"); status.className = `status-pill ${active ? "" : "idle"}`; $("span", status).textContent = active ? "Model ready" : "Model offline";
  if (active) {
    $("#profile-button").textContent = `${capitalize(state.workspace.profile_mode)} · ${state.workspace.case.profile}⌄`;
    $("#reasoning-button").textContent = `${capitalize(state.workspace.reasoning)} reasoning⌄`;
    const ratio = Math.min(1, state.workspace.context?.ratio || 0); $("#context-label").textContent = `${Math.round(ratio * 100)}%`; $("#context-meter").style.width = `${ratio * 100}%`;
    $("#mcp-state").textContent = "MCP connected"; $("#tool-count").textContent = `${state.workspace.external_mcp?.reduce((n,x)=>n+(x.tools||0),0) || 0} external tools`;
  } else { $("#context-label").textContent = "0%"; $("#context-meter").style.width = "0"; $("#mcp-state").textContent = "MCP offline"; }
  renderResearch();
}

async function loadProjectData(caseId) {
  const messages = await api(`/api/projects/${encodeURIComponent(caseId)}/history`);
  const container = $("#messages"); container.replaceChildren(); messages.messages.forEach(item => addMessage(item.role, item.content, item.timestamp, false));
  if (!messages.messages.length && state.workspace.active) {
    const empty = el("div", "conversation-empty");
    empty.append(el("strong", "", "Start the conversation"), el("span", "", "Use the message box below to describe what you want MalDroid to investigate."));
    container.append(empty);
  }
  await loadFiles(); renderResearch(); scrollMessages();
}

function clearProjectData() { state.files = []; state.selectedFile = null; state.touchedFiles.clear(); $("#messages").replaceChildren(); $("#file-preview").classList.add("hidden"); renderFiles(); }

function addMessage(role, content, timestamp = null, scroll = true) {
  if (!content) return;
  const rtl = isRTL(content); const article = el("article", `message ${role}`); article.dir = rtl ? "rtl" : "ltr";
  const avatar = el("div", "message-avatar", role === "assistant" ? "M" : "YOU");
  const copy = el("div", "message-copy"); const head = el("div", "message-head");
  head.append(el("strong", "", role === "assistant" ? "MalDroid" : "You"), el("time", "", timestamp ? new Date(timestamp).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) : "now"));
  const body = el("div", "message-body"); renderText(body, typeof content === "string" ? content : JSON.stringify(content, null, 2));
  copy.append(head, body); article.append(avatar, copy); $("#messages").append(article); if (scroll) scrollMessages();
}

function renderText(container, text) {
  const parts = text.split(/(`[^`]+`)/g);
  for (const part of parts) part.startsWith("`") && part.endsWith("`") ? container.append(el("code", "", part.slice(1,-1))) : container.append(document.createTextNode(part));
}

function sendMessage() {
  const input = $("#message-input"), content = input.value.trim();
  if (!content || state.busy || !state.workspace.active) return;
  if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return toast("Workspace connection is reconnecting.", true);
  addMessage("user", content); input.value = ""; resizeComposer(); state.socket.send(JSON.stringify({ type: "message", content }));
}

function setBusy(busy, title = "Thinking", detail = "Working on the investigation…") {
  state.busy = busy; $("#send-button").disabled = busy; $("#message-input").disabled = busy;
  $("#turn-progress").classList.toggle("hidden", !busy); $("#progress-title").textContent = title; $("#progress-detail").textContent = detail;
  const status = $("#runtime-status"); status.classList.toggle("loading", busy); if (busy) $("span", status).textContent = title;
  else { stopLiveWork(); renderWorkspace(); }
}

function updateProgress(event, data) {
  const labels = {
    model_start: ["Thinking", `Research phase ${data.phase || 1} · tool round ${(data.total_tool_rounds || 0) + 1}`],
    generation_start: ["Loading model context", "Preparing a cached local generation…"],
    prompt_progress: ["Loading context", `${data.processed || 0} / ${data.total || 0} tokens · ${data.cached || 0} cached`],
    generation_first_token: ["Model responding", `First token after ${Number(data.seconds || 0).toFixed(1)} seconds`],
    generation_progress: ["Generating response", `Working locally · approximately ${data.completion_tokens_estimate || 0} tokens`],
    empty_response_recovery: ["Recovering empty response", "Retrying once with reasoning disabled…"],
    empty_response_recovered: ["Response recovered", "The local model resumed normally."],
    generation_repetition_detected: ["Stopping repeated output", "A local generation loop was detected…"],
    repetition_recovery: ["Recovering automatically", `Continuing safely in session ${data.new_session || "new"}…`],
    repetition_recovery_exhausted: ["Generation stopped safely", "Investigation state was preserved."],
    tool_loop_warning: ["Changing research strategy", `The result from ${shortTool(data.name)} did not change…`],
    tool_loop_stopped: ["Repeated tool loop stopped", "Completed results and durable research remain safe."],
    tool_start: ["Running a tool", shortTool(data.name)], tool_result: [data.status === "completed" ? "Tool completed" : "Tool needs attention", shortTool(data.name)],
    checkpoint_required: ["Saving research", "Creating a durable progress checkpoint…"], state_discipline_required: ["Organizing research", "Updating findings and TODOs…"],
    compaction_start: ["Compacting context", "Preserving durable state and reclaiming context…"], phase_rollover: ["Continuing autonomously", `Starting research phase ${(data.completed_phase || 1) + 1}…`]
  };
  if (labels[event]) { $("#progress-title").textContent = labels[event][0]; $("#progress-detail").textContent = labels[event][1]; }
  if (event === "model_start") { state.work.phase = data.phase || state.work.phase; state.work.context = data.input_tokens_estimate || state.work.context; }
  if (event === "prompt_progress") state.work.context = data.total || state.work.context;
  if (event === "generation_progress") state.work.tokens = data.completion_tokens_estimate || state.work.tokens;
  if (event === "generation_complete") state.work.tokens = data.completion_tokens || state.work.tokens;
  if (event === "tool_start") state.work.tools += 1;
  if (event === "tool_start" || event === "tool_result") markTouchedFiles(data);
  renderLiveWorkMetrics();
  if (event !== "generation_progress" && event !== "prompt_progress" && event !== "generation_start" && event !== "generation_complete") appendLiveWorkStep(event, data);
}

function startLiveWork(title, detail, cancellable = false) {
  stopLiveWork(); state.work = { startedAt: Date.now(), timer: null, phase: 1, tools: 0, tokens: 0, context: 0, steps: [] };
  $("#progress-title").textContent = title; $("#progress-detail").textContent = detail; $("#live-work-steps").replaceChildren();
  $("#stop-turn").classList.toggle("hidden", !cancellable); $("#stop-turn").disabled = false;
  appendLiveWorkStep("work_started", { title, detail }); renderLiveWorkMetrics(); updateWorkElapsed();
  state.work.timer = setInterval(updateWorkElapsed, 1000);
}

function stopLiveWork() { if (state.work.timer) clearInterval(state.work.timer); state.work.timer = null; $("#stop-turn").classList.add("hidden"); $("#stop-turn").disabled = false; }
function updateWorkElapsed() { const seconds = Math.max(0, Math.floor((Date.now() - state.work.startedAt) / 1000)); $("#work-elapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`; }
function renderLiveWorkMetrics() { $("#work-phase").textContent = String(state.work.phase); $("#work-tools").textContent = String(state.work.tools); $("#work-tokens").textContent = `${state.work.tokens || 0} tok`; $("#work-context").textContent = `${state.work.context || 0} tok`; }
function appendLiveWorkStep(event, data = {}) {
  const descriptions = {
    work_started: [data.title || "Work started", data.detail || "Preparing the investigation", "running"],
    model_start: [`Research phase ${data.phase || 1}`, `Preparing model context for tool round ${(data.total_tool_rounds || 0) + 1}`, "running"],
    generation_first_token: ["Model response started", `First token after ${Number(data.seconds || 0).toFixed(1)} seconds`, "success"],
    tool_start: [`Using ${shortTool(data.name)}`, liveToolDetail(data), "running"],
    tool_result: [data.status === "completed" ? `${shortTool(data.name)} completed` : `${shortTool(data.name)} needs attention`, data.error || (data.output_file ? "Full output saved in the case" : "Result returned to the model"), data.status === "completed" ? "success" : "warning"],
    checkpoint_required: ["Preserving research progress", "Saving findings, TODOs, and the exact next action", "running"],
    state_discipline_required: ["Organizing durable research", "Updating evidence-backed Findings and TODOs", "running"],
    automatic_checkpoint: ["Research checkpoint saved", data.status || "Durable progress is available to future sessions", "success"],
    phase_checkpoint: ["Phase checkpoint saved", "Findings, TODOs, and the next action are durable", "success"],
    compaction_start: ["Reclaiming context", "Summarizing durable state before continuing", "running"],
    compaction_complete: ["Context compacted", "Continuing with the preserved research state", "success"],
    phase_rollover: [`Continuing with phase ${(data.completed_phase || 1) + 1}`, "The investigation remains active", "success"],
    model_retry: ["Retrying the local model", `Attempt ${data.attempt || 1} after a temporary error`, "warning"],
    empty_response_recovery: ["Recovering an empty response", `First attempt ended with ${data.finish_reason || "no finish reason"}`, "warning"],
    empty_response_recovered: ["Empty response recovered", "Continuing the same turn without losing context", "success"],
    empty_response_recovery_failed: ["Empty response recovery failed", "Check the model template and response-token setting", "warning"],
    generation_repetition_detected: ["Repeated output stopped", "Protecting the context before automatic recovery", "warning"],
    repetition_recovery: ["Continued in a clean session", `Recovery attempt ${data.attempt || 1}`, "success"],
    repetition_recovery_exhausted: ["Recovery stopped safely", "Investigation state was preserved for the next message", "warning"],
    tool_loop_warning: ["Repeated tool result detected", `Changing strategy after ${data.repetitions || 3} unchanged results`, "warning"],
    tool_loop_stopped: ["Repeated tool loop stopped", "No more duplicate work will be performed in this turn", "warning"],
    turn_stopping: ["Stop requested", "Waiting for the current safe boundary", "warning"],
    turn_cancelled: ["Model turn stopped", "Durable research state and completed tool results were preserved", "success"],
  };
  const description = descriptions[event]; if (!description) return;
  state.work.steps.push({ event, title: description[0], detail: description[1], status: description[2] }); state.work.steps = state.work.steps.slice(-3);
  const root = $("#live-work-steps"); root.replaceChildren();
  for (const step of state.work.steps) { const row = el("div", `live-work-step ${step.status}`), marker = el("i", "", step.status === "success" ? "✓" : step.status === "warning" ? "!" : ""); const copy = el("div"); copy.append(el("strong", "", step.title), el("span", "", step.detail)); row.append(marker, copy); root.append(row); }
}

function addActivity(event, data = {}) {
  const titleMap = { model_start:"Model turn started", generation_first_token:"First model token received", generation_complete:"Generation completed", empty_response_recovery:"Recovering empty model response", empty_response_recovered:"Empty response recovered", empty_response_recovery_failed:"Empty response recovery failed", generation_repetition_detected:"Repeated output stopped", repetition_recovery:"Continued in a fresh session", repetition_recovery_exhausted:"Repeated generation stopped safely", tool_loop_warning:"Changing repeated tool strategy", tool_loop_stopped:"Repeated tool loop stopped", turn_cancelled:"Model turn stopped", tool_start:`Running ${shortTool(data.name)}`, tool_result:`${shortTool(data.name)} ${data.status || "completed"}`, checkpoint_required:"Durable checkpoint requested", automatic_checkpoint:"Checkpoint saved", phase_rollover:"Autonomous phase continued", compaction_complete:"Context compacted", external_mcp_connection:`MCP ${data.nickname || "connector"}` };
  if (event === "generation_progress" || event === "prompt_progress" || event === "generation_start") return;
  state.activities.unshift({ event, title: titleMap[event] || event.replaceAll("_", " "), detail: activityDetail(data), time: new Date() }); state.activities = state.activities.slice(0, 100);
  if (!$("[data-tab='activity']").classList.contains("active")) state.unread++;
  renderActivity();
}

function renderActivity() {
  const list = $("#activity-list"); list.replaceChildren(); list.classList.toggle("empty-state", !state.activities.length);
  if (!state.activities.length) list.textContent = "Tool calls and model progress will appear here.";
  for (const item of state.activities) { const row=el("div","activity-item"), dot=el("div","activity-dot", item.event.includes("tool")?"⌘":"◆"), copy=el("div","activity-copy"); copy.append(el("strong","",item.title),el("span","",`${item.detail} · ${item.time.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"})}`)); row.append(dot,copy); list.append(row); }
  $("#activity-count").textContent = String(state.unread);
}

async function loadFiles() {
  const tree = $("#file-tree"); if (!state.activeId) return;
  tree.className = "file-tree empty-state"; tree.textContent = "Loading case files…";
  try {
    const result = await api(`/api/projects/${encodeURIComponent(state.activeId)}/files?depth=8`);
    state.files = result.data?.entries || [];
    state.filesTruncated = Boolean(result.data?.truncated);
    state.filesLimit = result.data?.limit || state.files.length;
    renderFiles();
  } catch(error){tree.textContent=error.message;}
}

function renderFiles() {
  const tree = $("#file-tree"), query = state.fileFilter;
  tree.replaceChildren(); tree.className = "file-tree";
  const logs = state.files.filter(item => isLogPath(item.path));
  const visible = state.files.filter(item => {
    if (!state.showLogs && isLogPath(item.path)) return false;
    if (query) return item.path.toLowerCase().includes(query);
    const parents = item.path.split("/").slice(0, -1);
    return !parents.some((_, index) => state.collapsedDirectories.has(parents.slice(0, index + 1).join("/")));
  });
  $("#file-count").textContent = query ? `${visible.length} matches` : `${visible.length} items${!state.showLogs && logs.length ? ` · ${logs.length} hidden` : ""}`;
  const logToggle = $("#toggle-logs"); logToggle.textContent = state.showLogs ? "Showing logs" : "Logs hidden"; logToggle.setAttribute("aria-pressed", String(state.showLogs)); logToggle.setAttribute("aria-label", state.showLogs ? "Hide log files" : "Show log files");
  if (state.filesTruncated) tree.append(el("div", "file-limit", `Showing the first ${state.filesLimit} entries`));
  for (const item of visible) {
    const depth = Math.max(0, item.path.split("/").length - 1), directory = item.type === "directory";
    const normalizedPath = normalizeCasePath(item.path), touched = item.type !== "directory" && state.touchedFiles.has(normalizedPath), containsTouched = directory && [...state.touchedFiles].some(path => path === normalizedPath || path.startsWith(`${normalizedPath}/`));
    const row = el("div", `file-row ${item.type}${state.selectedFile === item.path ? " selected" : ""}${touched ? " touched" : ""}${containsTouched ? " contains-touched" : ""}`);
    row.style.paddingLeft = `${5 + depth * 14}px`; row.title = touched ? `${item.path} · Used by MalDroid in the latest turn` : containsTouched ? `${item.path} · Contains work from the latest turn` : item.path;
    row.append(
      el("span", "file-disclosure", directory ? (state.collapsedDirectories.has(item.path) ? "▸" : "▾") : ""),
      el("span", "file-icon", fileIcon(item)),
      el("span", "file-label", item.path.split("/").pop())
    );
    if (touched || containsTouched) { const marker = el("span", `file-worked-dot${containsTouched ? " directory-marker" : ""}`); marker.title = touched ? "Used by MalDroid in the latest turn" : "Contains work from the latest turn"; marker.setAttribute("aria-label", marker.title); row.append(marker); }
    if (directory) {
      row.tabIndex = 0; row.setAttribute("role", "button"); row.setAttribute("aria-expanded", String(!state.collapsedDirectories.has(item.path)));
      const toggle = () => { state.collapsedDirectories.has(item.path) ? state.collapsedDirectories.delete(item.path) : state.collapsedDirectories.add(item.path); renderFiles(); };
      row.addEventListener("click", toggle); row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); } });
    } else if (item.type === "file") {
      const open = () => openFile(item.path); row.tabIndex = 0; row.setAttribute("role", "button");
      row.addEventListener("click", open); row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } }); row.append(el("small", "", formatBytes(item.size)));
    }
    tree.append(row);
  }
  if (!visible.length) tree.append(el("div", "file-empty", query ? `No files match “${state.fileFilter}”.` : "This investigation has no visible files."));
}

async function openFile(path) {
  state.selectedFile = path; renderFiles();
  const preview=$("#file-preview"); preview.classList.remove("hidden"); $("#preview-name").textContent=path; $("#preview-meta").textContent="Loading bounded preview…"; $("#preview-content").textContent="";
  try { const result=await api(`/api/projects/${encodeURIComponent(state.activeId)}/file?path=${encodeURIComponent(path)}&start=1&end=500`); if(result.status!=="completed") throw new Error(result.error?.message||"Preview failed"); const data=result.data; $("#preview-meta").textContent=data.lines?`${data.returned_lines} lines · bounded preview${data.content_truncated?" · long lines shortened":""}`:`${data.length || 4096} bytes · hexadecimal preview`; $("#preview-content").textContent=data.lines?data.lines.map(x=>`${String(x.line).padStart(6)}  ${x.text}${x.truncated?" … [line shortened]":""}`).join("\n"):JSON.stringify(data,null,2); } catch(error){$("#preview-content").textContent=error.message;}
}

function renderResearch() {
  const caseData=state.workspace.case; const stats=$("#research-stats"), content=$("#research-content"); stats.replaceChildren();
  const values=[[caseData?.findings?.length||0,"Findings"],[caseData?.todos?.filter(x=>x.status==="open").length||0,"Open TODOs"],[caseData?.checkpoints?.length||0,"Checkpoints"]];
  for(const [number,label] of values){const card=el("div","research-stat");card.append(el("strong","",String(number)),el("span","",label));stats.append(card)}
  content.replaceChildren(); content.className="research-content"; if(!caseData){content.classList.add("empty-state");content.textContent="Findings, TODOs, and checkpoints will appear here.";return}
  researchGroup(content,"Findings",caseData.findings||[],item=>({tag:`${item.severity} · ${item.confidence}`,title:`${item.id} — ${item.title}`,body:item.summary}));
  researchGroup(content,"Open TODOs",(caseData.todos||[]).filter(x=>x.status==="open"),item=>({tag:item.id,title:item.text,body:"Open research task"}));
  researchGroup(content,"Recent checkpoints",(caseData.checkpoints||[]).slice(-5).reverse(),item=>({tag:item.status,title:item.objective,body:item.next_action?`Next: ${item.next_action}`:(item.completed_work||[]).join(" · ")}));
  if(!content.children.length){content.classList.add("empty-state");content.textContent="No durable research has been recorded yet."}
}

function researchGroup(root,title,items,mapper){if(!items.length)return;const group=el("div","research-group");group.append(el("h3","",title));for(const item of items){const v=mapper(item),card=el("article","research-card"), heading=el("div");heading.append(el("span","tag",v.tag),el("strong","",v.title));card.append(heading,el("p","",v.body||""));group.append(card)}root.append(group)}

async function runCommand(action,payload){if(!state.workspace.active)return toast("Open an investigation first.",true);try{toast(`${capitalize(action)} started…`);const result=await api("/api/workspace/command",{method:"POST",body:JSON.stringify({action,...payload})});if(result.status==="error")throw new Error(result.error?.message||"Action failed");addActivity("workspace_action",{action,status:"completed"});if(!["clear","profile","reasoning"].includes(action))addMessage("assistant",formatActionResult(action,result.data));toast(`${capitalize(action)} completed.`);await refreshBootstrap();renderWorkspace();if(action==="report"&&result.data?.path)await openFile(result.data.path);}catch(error){toast(error.message,true)}}

async function handleAction(action,target){
  if(action==="new-project"){ $("#project-error").textContent=""; $("#project-dialog").showModal(); }
  else if(action==="settings"){fillSettings();renderConnectors();$("#settings-dialog").showModal()}
  else if(action==="toggle-sidebar"){if(innerWidth<=900){document.body.classList.remove("sidebar-collapsed");$(".inspector").classList.remove("open");$(".sidebar").classList.toggle("open")}else document.body.classList.toggle("sidebar-collapsed");syncPaneState()}
  else if(action==="toggle-theme")setTheme(state.theme === "dark" ? "light" : "dark");
  else if(action==="toggle-inspector"){if(innerWidth<=900){document.body.classList.remove("inspector-collapsed");$(".sidebar").classList.remove("open");$(".inspector").classList.toggle("open")}else document.body.classList.toggle("inspector-collapsed");syncPaneState()}
  else if(action==="refresh-files")await loadFiles(); else if(action==="close-preview")$("#file-preview").classList.add("hidden");
  else if(action==="toggle-logs"){state.showLogs=!state.showLogs;localStorage.setItem("maldroid-show-logs",String(state.showLogs));renderFiles()}
  else if(action==="clear-activity"){state.activities=[];state.unread=0;renderActivity()}
  else if(action==="stop-workspace")await stopWorkspace();
  else if(action==="profile")showChoiceMenu(target,["auto","generic","react-native","native"],state.workspace.case?.profile,choice=>runCommand("profile",{profile:choice}));
  else if(action==="reasoning")showChoiceMenu(target,["off","low","medium","high","unlimited"],state.workspace.reasoning,choice=>runCommand("reasoning",{level:choice}));
  else if(action==="command-palette")showActionMenu(target);
  else if(action==="stop-turn"){if(!state.busy||!state.socket||state.socket.readyState!==WebSocket.OPEN)return;target.disabled=true;state.socket.send(JSON.stringify({type:"stop"}))}
  else if(action==="add-connector")await addConnector();
}

async function createProject(event){event.preventDefault();const button=$("#create-project-button");button.disabled=true;$("#project-error").textContent="";try{const data=Object.fromEntries(new FormData(event.target));const result=await api("/api/projects",{method:"POST",body:JSON.stringify(data)});$("#project-dialog").close();event.target.reset();await refreshBootstrap();activateProject(result.project.case_id)}catch(error){$("#project-error").textContent=error.message}finally{button.disabled=false}}

function fillSettings(){if(!state.bootstrap)return;for(const input of $$("[data-key]",$("#settings-form"))){const value=getPath(state.bootstrap.settings,input.dataset.key);if(input.type==="checkbox")input.checked=Boolean(value);else input.value=value??""}$("#stop-workspace").disabled=!state.workspace.active||state.busy}
async function stopWorkspace(){if(state.busy)return toast("Stop the active turn before stopping the model.",true);const button=$("#stop-workspace");button.disabled=true;try{await api("/api/workspace/stop",{method:"POST"});await refreshBootstrap();state.activeId=state.workspace.case?.case_id||state.activeId;renderWorkspace();renderProjects();toast("Local model stopped. Settings can now be changed.")}catch(error){toast(error.message,true)}finally{button.disabled=!state.workspace.active}}
async function saveSettings(event){event.preventDefault();const changes={};for(const input of $$("[data-key]",event.target)){const old=getPath(state.bootstrap.settings,input.dataset.key),value=input.type==="checkbox"?input.checked:input.value;if(String(value)!==String(old))changes[input.dataset.key]=value}try{if(Object.keys(changes).length){const result=await api("/api/settings",{method:"PATCH",body:JSON.stringify(changes)});state.bootstrap.settings=result.settings}$("#settings-dialog").close();toast("Settings saved.")}catch(error){$("#settings-error").textContent=error.message}}

function renderConnectors(){const root=$("#connector-list");root.replaceChildren();const connectors=state.bootstrap?.connectors||[];if(!connectors.length)root.append(el("div","empty-state","No external MCP connectors configured."));for(const connector of connectors){const row=el("div","connector-row"),copy=el("div");copy.append(el("strong","",connector.nickname),el("span","",connector.url));const test=el("button","","Test"),remove=el("button","","Remove");test.type=remove.type="button";test.onclick=()=>testConnector(connector.nickname);remove.onclick=()=>removeConnector(connector.nickname);row.append(copy,test,remove);root.append(row)}}
async function addConnector(){const url=$("#connector-url").value.trim(),nickname=$("#connector-name").value.trim();if(!url)return;try{await api("/api/connectors",{method:"POST",body:JSON.stringify({url,nickname:nickname||null})});$("#connector-url").value=$("#connector-name").value="";await refreshBootstrap();toast("MCP connector saved.")}catch(error){toast(error.message,true)}}
async function testConnector(name){try{const result=await api(`/api/connectors/${encodeURIComponent(name)}/test`,{method:"POST"});toast(`${name} connected · ${result.tools.length} tools`)}catch(error){toast(error.message,true)}}
async function removeConnector(name){try{await api(`/api/connectors/${encodeURIComponent(name)}`,{method:"DELETE"});await refreshBootstrap();toast(`${name} removed.`)}catch(error){toast(error.message,true)}}

function selectInspectorTab(tab){$$('[data-tab]').forEach(x=>x.classList.toggle("active",x.dataset.tab===tab));$$('.inspector-panel').forEach(x=>x.classList.toggle("active",x.id===`panel-${tab}`));if(tab==="activity"){state.unread=0;renderActivity()}}
function selectSettingsTab(tab){$$('[data-settings-tab]').forEach(x=>x.classList.toggle("active",x.dataset.settingsTab===tab));$$('[data-settings-panel]').forEach(x=>x.classList.toggle("active",x.dataset.settingsPanel===tab))}
function showChoiceMenu(target,choices,current,callback){const menu=$("#menu");menu.replaceChildren();for(const choice of choices){const button=el("button",choice===current?"active":"",capitalize(choice));button.onclick=()=>{hideMenu();callback(choice)};menu.append(button)}positionMenu(menu,target)}
function showActionMenu(target){const actions=[["dashboard","Research dashboard"],["inventory","Inventory case"],["triage","Run behavior triage"],["indicators","Extract network indicators"],["report","Build research report"],["tools","List active tools"],["timeline","Recent timeline"],["compact","Compact context"],["clear","Clear chat context"]],menu=$("#menu");menu.replaceChildren();for(const [key,label]of actions){const button=el("button","",label);button.onclick=()=>{hideMenu();runCommand(key,{})};menu.append(button)}positionMenu(menu,target)}
function positionMenu(menu,target){const rect=target.getBoundingClientRect();menu.style.top=`${Math.min(innerHeight-260,rect.bottom+5)}px`;menu.style.left=`${Math.max(8,Math.min(innerWidth-230,rect.right-215))}px`;menu.classList.remove("hidden")}
function hideMenu(){$("#menu").classList.add("hidden")}
function toast(message,error=false){const item=el("div",`toast${error?" error":""}`,message);$("#toast-region").append(item);setTimeout(()=>item.remove(),4200)}
function resizeComposer(){const input=$("#message-input");input.style.height="auto";input.style.height=`${Math.min(180,input.scrollHeight)}px`}
function scrollMessages(){requestAnimationFrame(()=>{$("#messages").scrollTop=$("#messages").scrollHeight})}
function el(tag,className="",text=""){const node=document.createElement(tag);if(className)node.className=className;if(text!=="")node.textContent=text;return node}
function getPath(object,path){return path.split(".").reduce((value,key)=>value?.[key],object)}
function shortProfile(value){return ({"react-native":"RN",native:"Native",generic:"Auto"})[value]||value}
function shortTool(value=""){return value.replace(/^MalDroid_/,"").replace(/^MCP_[^_]+_/,"").replaceAll("_"," ")}
function activityDetail(data){if(data.arguments){const args=parsedToolArguments(data.arguments),detail=Object.entries(args).slice(0,2).map(([k,v])=>`${k}: ${String(v).slice(0,60)}`).join(" · ");if(detail)return detail}if(data.error)return String(data.error).slice(0,120);if(data.seconds!=null)return `${Number(data.seconds).toFixed(1)} seconds`;if(data.completion_tokens!=null){const speed=Number(data.timings?.predicted_per_second||0),rate=speed?` · ${speed.toFixed(1)} tok/s`:"",finish=data.finish_reason?` · ${data.finish_reason}`:"";return `${data.completion_tokens} tokens${rate}${finish}`}if(data.finish_reason)return `Finish reason: ${data.finish_reason}`;if(data.action)return data.action;return data.status||"Local workspace"}
function parsedToolArguments(value){if(value&&typeof value==="object")return value;if(typeof value==="string"){try{const parsed=JSON.parse(value);return parsed&&typeof parsed==="object"?parsed:{}}catch{return {}}}return {}}
function liveToolDetail(data){const args=parsedToolArguments(data.arguments),safeKeys=["path","query","pattern","start_line","end_line","offset","length","nickname"],details=safeKeys.filter(key=>args[key]!==undefined).slice(0,2).map(key=>`${key}: ${String(args[key]).slice(0,60)}`);return details.join(" · ")||"Running a bounded local tool"}
function normalizeCasePath(value=""){let path=String(value).replaceAll("\\","/");const root=String(state.workspace.case?.path||"").replaceAll("\\","/").replace(/\/$/,"");if(root&&path.startsWith(`${root}/`))path=path.slice(root.length+1);return path.replace(/^\.\//,"").replace(/\/{2,}/g,"/")}
function markTouchedFiles(data={}){const args=parsedToolArguments(data.arguments),candidates=[];for(const [key,value]of Object.entries(args)){if(key==="path"||key.endsWith("_path")||key==="paths"){if(Array.isArray(value))candidates.push(...value);else candidates.push(value)}}if(data.output_file)candidates.push(data.output_file);for(const value of candidates){if(typeof value!=="string")continue;const path=normalizeCasePath(value);if(path&&path!==".")state.touchedFiles.add(path)}renderFiles()}
function isLogPath(path=""){const parts=String(path).toLowerCase().split("/");return parts.includes("logs")||parts[parts.length-1].endsWith(".log")}
function initializeFilePreferences(){state.showLogs=localStorage.getItem("maldroid-show-logs")==="true"}
function relativeTime(value){const seconds=Math.max(0,(Date.now()-new Date(value).getTime())/1000);if(seconds<60)return"just now";if(seconds<3600)return`${Math.floor(seconds/60)}m ago`;if(seconds<86400)return`${Math.floor(seconds/3600)}h ago`;return`${Math.floor(seconds/86400)}d ago`}
function formatBytes(bytes=0){if(bytes<1024)return`${bytes} B`;if(bytes<1048576)return`${(bytes/1024).toFixed(1)} KB`;return`${(bytes/1048576).toFixed(1)} MB`}
function fileIcon(item){if(item.type==="directory")return"▰";if(item.type==="symlink")return"↗";const extension=item.path.split(".").pop().toLowerCase();if(["js","jsx","ts","tsx"].includes(extension))return"JS";if(["java","kt","smali"].includes(extension))return"J";if(["c","cc","cpp","h","hpp"].includes(extension))return"C";if(["so","elf","bin","dex"].includes(extension))return"◆";if(["json","toml","yaml","yml","xml"].includes(extension))return"{}";if(["md","txt","log"].includes(extension))return"≡";return"·"}
function initializeTheme(){const saved=localStorage.getItem("maldroid-theme");setTheme(saved==="light"?"light":"dark")}
function setTheme(theme){state.theme=theme==="light"?"light":"dark";document.documentElement.dataset.theme=state.theme;localStorage.setItem("maldroid-theme",state.theme);const button=$("#theme-toggle"),light=state.theme==="light";if(button){button.textContent=light?"☾":"☀";button.setAttribute("aria-label",light?"Switch to dark mode":"Switch to light mode");button.title=button.getAttribute("aria-label")}if($("#theme-setting"))$("#theme-setting").value=state.theme}
function syncPaneState(){const compact=innerWidth<=900,sidebarOpen=compact?$(".sidebar").classList.contains("open"):!document.body.classList.contains("sidebar-collapsed"),inspectorOpen=compact?$(".inspector").classList.contains("open"):!document.body.classList.contains("inspector-collapsed");const menu=$(".mobile-menu"),inspector=$("#inspector-toggle");menu.setAttribute("aria-label",sidebarOpen?"Close projects":"Open projects");menu.setAttribute("aria-expanded",String(sidebarOpen));inspector.setAttribute("aria-label",inspectorOpen?"Close inspector":"Open inspector");inspector.setAttribute("aria-expanded",String(inspectorOpen))}
function formatActionResult(action,data){const title=`${capitalize(action)} result`;if(action==="report"&&data?.path)return`${title}\n\nResearch report rebuilt at: ${data.path}`;if(action==="tools"&&data?.tools)return`${title}\n\n${data.count} tools available:\n${data.tools.map(x=>`• ${shortTool(x.name)} — ${x.description||""}`).join("\n")}`;return`${title}\n\n${JSON.stringify(data,null,2)}`}
function capitalize(value=""){return value.charAt(0).toUpperCase()+value.slice(1)}
function isRTL(text){const rtl=(text.match(/[\u0590-\u08ff]/g)||[]).length,letters=(text.match(/[A-Za-z\u0590-\u08ff]/g)||[]).length;return letters>0&&rtl/letters>.3}

boot();
