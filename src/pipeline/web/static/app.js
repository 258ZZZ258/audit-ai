const state = {
  overview: null,
  batches: [],
  batch: null,
  doc: null,
  files: [],
};

const $ = (id) => document.getElementById(id);

const actionLabels = {
  fix: "修复后重试",
  degrade: "降级索引",
  reject: "驳回",
  release: "放行",
  approve: "确认",
};

const artifactLabels = {
  raw: "原件",
  rendition: "规范渲染件",
  ir: "IR 解析结果",
  chunks: "分块",
  milvus: "Milvus 索引",
};

const queueLabels = {
  qc_fix: "质检处理",
  quarantine: "隔离处理",
  meta_confirm: "元数据确认",
};

const nodeStatusLabels = {
  done: "已完成",
  running: "处理中",
  waiting: "等待人工",
  failed: "失败",
  pending: "未开始",
};

// 冲突字段中文名(与 l1_rules.cross_check 字段一致)。
const conflictFieldLabels = {
  title: "标题",
  doc_number: "发文字号",
  issue_date: "成文日期",
  issuer: "发布机关",
};

function conflictFieldLabel(field) {
  return conflictFieldLabels[field] || field;
}

// 错误码目录:管线码(E1xx–E8xx,states.py:ErrorCode)+ 服务/HTTP 码(app.py:_send_error)。
// 每码给「标题 / 含义 / 处理建议」,在错误横幅、事件流、API 失败日志统一翻译,免得操作者只看到裸码。
const errorCatalog = {
  "E101-DEMO": { title: "格式不在白名单", detail: "demo 仅支持 .docx / .pdf。", fix: "转换为 docx/pdf 后重新上传。" },
  "E202-DEMO": { title: "疑似扫描件 · OCR 未启用", detail: "每页可抽取字符数低于阈值,判为扫描影像件;demo 未接 OCR。", fix: "改用带文字层的电子版;或在队列中「降级索引」(仅全文检索)。" },
  "E203": { title: "解析超时", detail: "单文档解析超过配置时限(parse.parse_timeout_sec)。", fix: "拆分超大文档,或调高 config 超时后 reprocess。" },
  "E204-DEMO": { title: "规范渲染失败", detail: "soffice 生成对齐用 PDF 失败,docx 无法定位页码。", fix: "检查 LibreOffice(PIPELINE_SOFFICE)可用性;修复后 reprocess。" },
  "E301": { title: "质检硬关卡未通过", detail: "七项质检指标存在硬性不达标(乱码率 / 页码锚定等)。", fix: "查看队列中的具体指标:修复重试 / 降级索引 / 驳回。" },
  "E701": { title: "PG / Milvus 数量不平", detail: "投影块数与权威库不一致;对账已尝试以 PG 冷备重灌。", fix: "重跑对账;仍不平则「重建」集合。" },
  "E801": { title: "冒烟未命中", detail: "T2 合成查询未在 hit@N 内检索到文档自身。", fix: "检查嵌入 / 索引完整性;非阻断,仅记入报告。" },
  "E802": { title: "检索缺 status 过滤位", detail: "search 未携带 status==effective,staging / 旧版可能可见。", fix: "代码级断言失败,无需操作者处理,记入报告。" },
  BAD_INPUT: { title: "输入有误", detail: "请求参数不合法。", fix: "检查表单 / 参数后重试。" },
  NOT_FOUND: { title: "未找到", detail: "目标资源不存在(可能已清理或 ID 有误)。", fix: "刷新后重试。" },
  PIPELINE_FAILED: { title: "管线处理失败", detail: "stage 推进中途异常,文档未达预期终态(可重试)。", fix: "看文档详情的事件与错误码定位 stage;修复后 reprocess。" },
  PAYLOAD_TOO_LARGE: { title: "上传体过大", detail: "请求体超过上限(整批 200MB / API 1MB)。", fix: "减少单次上传文件数量或体积。" },
  INTERNAL: { title: "服务器内部错误", detail: "未预期异常,细节见服务端日志。", fix: "查看 /tmp/pipeline_web.log;必要时重启服务。" },
};

function explainError(code) {
  return code ? errorCatalog[code] || null : null;
}

// 统一错误日志:在原文案后补「错误标题 — 处理建议」,并把 code/guidance 一并落进活动日志数据。
function logError(context, err) {
  const info = explainError(err && err.code);
  const data = { error: err ? err.message : String(err) };
  if (err && err.code) data.code = err.code;
  if (info) data.guidance = info.fix;
  log(info ? `${context}：${info.title} — ${info.fix}` : context, data);
}

function log(message, data) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  const extra = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  $("activityLog").textContent = `${line}${extra}\n\n${$("activityLog").textContent}`;
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const text = await res.text();
  const payload = text ? JSON.parse(text) : {};
  // 错误体结构化为 {error:{code,message}};兼容旧扁平字符串 + statusText 兜底
  if (!res.ok) {
    const err = new Error(payload.error?.message || payload.error || res.statusText);
    err.code = payload.error?.code; // 供 logError / 错误目录翻译
    throw err;
  }
  return payload;
}

async function refreshAll() {
  const [overview, batches, queue] = await Promise.all([
    api("/api/overview"),
    api("/api/batches"),
    api(`/api/queue?all=${$("showAllQueue").checked}`),
  ]);
  state.overview = overview;
  state.batches = batches.batches;
  renderMetrics();
  renderFlow();
  renderBatches();
  renderQueue(queue.items);
  if (state.batch) await selectBatch(state.batch.batch_id, false);
}

function renderMetrics() {
  const o = state.overview || {};
  $("metrics").innerHTML = [
    ["文档数", o.doc_count || 0],
    ["批次数", o.batch_count || 0],
    ["已索引", o.indexed_count || 0],
    ["待处理队列", o.open_queue_count || 0],
  ].map(([k, v]) => h`<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join("");
}

const stages = [
  "REGISTERED", "PARSING", "QC_PENDING", "STRUCTURING",
  "META_REVIEW", "EMBEDDING", "INDEXING", "INDEXED",
];

function renderFlow() {
  const counts = state.overview?.state_counts || {};
  $("flow").innerHTML = stages.map((s) => h`
    <div class="stage">
      <strong>${s}</strong>
      <span>${counts[s] || 0}</span>
    </div>
  `).join("");
}

function renderBatches() {
  $("batchList").innerHTML = state.batches.map((b) => h`
    <div class="list-item ${state.batch?.batch_id === b.batch_id ? "active" : ""}" data-batch="${b.batch_id}">
      <strong>${short(b.batch_id)}</strong>
      <div class="meta">${b.doc_count} 个文档 · ${formatCounts(b.status_counts)}</div>
    </div>
  `).join("");
  document.querySelectorAll("[data-batch]").forEach((el) => {
    el.onclick = () => selectBatch(el.dataset.batch);
  });
}

async function selectBatch(batchId, announce = true) {
  state.batch = await api(`/api/batches/${batchId}`);
  state.doc = null;
  renderBatches();
  renderDocs();
  $("docDetail").innerHTML = `<div class="detail-empty">请选择一个文档</div>`;
  if (announce) log(`已加载批次 ${batchId}`);
}

function renderDocs() {
  const docs = state.batch?.docs || [];
  $("docTable").innerHTML = h`
    <div class="row header"><span>标题</span><span>状态</span><span>语料</span><span>分块</span></div>
    ${raw(docs.map((d) => h`
      <div class="row" data-doc="${d.doc_version_id}">
        <span class="title">${d.title || d.source_filename || d.doc_version_id}</span>
        <span><i class="badge s-${d.pipeline_status}">${d.pipeline_status}</i></span>
        <span>${d.corpus_type || "-"}</span>
        <span>${d.chunk_count ?? 0}${d.degraded ? " · 降级" : ""}</span>
      </div>
    `).join(""))}
  `;
  document.querySelectorAll("[data-doc]").forEach((el) => {
    el.onclick = () => selectDoc(el.dataset.doc);
  });
}

async function selectDoc(dvid) {
  state.doc = await api(`/api/docs/${dvid}`);
  renderDocDetail();
  log(`已加载文档 ${dvid}`);
}

// 错误横幅:文档带 last_error_code 时,详情顶部给「码 · 含义 · 处理建议」。返回安全 HTML 串(调用处 raw 包裹)。
function errorBannerHtml(d) {
  if (!d.last_error_code) return "";
  const info = explainError(d.last_error_code);
  const body = info
    ? h`<div class="eb-detail">${info.detail}</div><div class="eb-fix">处理建议：${info.fix}</div>`
    : "";
  return h`<div class="error-banner">
      <strong>⚠ 错误 ${d.last_error_code}${info ? ` · ${info.title}` : ""}</strong>
      ${raw(body)}
    </div>`;
}

// 事件流里的错误码小标:鼠标悬停看含义+建议。返回安全 HTML 串(调用处 raw 包裹)。
function errorCodeChip(code) {
  if (!code) return "";
  const info = explainError(code);
  const tip = info ? `${info.detail} 处理建议：${info.fix}` : code;
  return h`<span class="err-chip" title="${tip}">${code}${info ? ` ${info.title}` : ""}</span>`;
}

function renderDocDetail() {
  const d = state.doc.doc;
  $("detailTitle").textContent = d.title || d.source_filename || "文档详情";
  const verify = state.doc.events.filter((e) => e.detail && e.detail.verify).slice(-1)[0];
  $("docDetail").innerHTML = h`
    <div class="detail">
      ${raw(errorBannerHtml(d))}
      <div class="kv"><span>文档版本</span><strong>${d.doc_version_id}</strong></div>
      <div class="kv"><span>管线状态</span><span><i class="badge s-${d.pipeline_status}">${d.pipeline_status}</i></span></div>
      <div class="kv"><span>版本状态</span><span>${d.version_status || "-"}</span></div>
      <div class="kv"><span>来源文件</span><span>${d.source_filename || "-"}</span></div>
      <div class="kv"><span>发布机构</span><span>${d.issuer || "-"}</span></div>
      <div class="kv"><span>分块数量</span><span>${d.chunk_count ?? state.doc.chunks.length}</span></div>
      <div class="kv"><span>验证结果</span><span>${verify ? JSON.stringify(verify.detail.verify) : "-"}</span></div>
      <h3>管线节点</h3>
      <div class="node-list">${raw(state.doc.nodes.map((n) => h`
        <div class="node s-node-${n.status}">
          <div>
            <strong>${n.key} · ${n.label}</strong>
            <div class="meta">${n.event_count} 条事件 · ${n.last_event_at || "-"}</div>
          </div>
          <span>${nodeStatusLabels[n.status] || n.status}</span>
          ${n.artifacts.length ? raw(`<small>${n.artifacts.map((k) => escapeHtml(artifactLabel(k))).join("，")}</small>`) : ""}
        </div>
      `).join(""))}</div>
      <h3>产物</h3>
      <div class="artifact-list">${raw(state.doc.artifacts.map((a) => h`
        <div class="artifact">
          <strong>${artifactLabel(a.kind)}</strong>
          <div class="meta">${a.exists ? "已生成" : "缺失"} · ${a.key || "-"}</div>
          ${a.url ? raw(`<a href="${escapeHtml(a.url)}" target="_blank" rel="noreferrer">打开产物</a>`) : ""}
        </div>
      `).join(""))}</div>
      <h3>事件</h3>
      <div class="event-list">${raw(state.doc.events.slice().reverse().map((e) => h`
        <div class="event"><strong>${e.from_state || "开始"} → ${e.to_state}</strong>
          <div class="meta">${e.actor || "system"} · ${e.created_at || ""} ${raw(errorCodeChip(e.error_code))}</div>
          ${e.detail ? raw(`<pre>${escapeHtml(JSON.stringify(e.detail, null, 2))}</pre>`) : ""}
        </div>
      `).join(""))}</div>
      <h3>分块</h3>
      <div class="chunk-list">${raw(state.doc.chunks.map((c) => h`
        <div class="chunk">
          <strong>${c.clause_path || "根节点"}</strong>
          <div class="meta">序号 ${c.seq} · 页码 ${c.page_start || "-"} · ${c.chunk_status} · ${c.tags.length} 个标签</div>
          <pre>${c.text || ""}</pre>
        </div>
      `).join(""))}</div>
    </div>
  `;
}

// 元数据冲突块:逐字段列「manifest 声明 vs 文档实际」,并为每个 L1 抽取候选给「采用并确认」按钮。
// 返回安全 HTML 串(调用处 raw 包裹);按钮 data-* 用 escapeHtml 防注入(同 queueButtons)。
function conflictBlockHtml(q) {
  const conflicts = (q.evidence && q.evidence.conflicts) || [];
  if (q.queue_type !== "meta_confirm" || !conflicts.length) return "";
  const rows = conflicts.map((c) => {
    const candidates = String(c.extracted || "").split("/").map((s) => s.trim()).filter(Boolean);
    const buttons = candidates.map((v) =>
      `<button class="suggest-btn" data-resolve-qid="${escapeHtml(q.queue_id)}" data-resolve-field="${escapeHtml(c.field)}" data-resolve-value="${escapeHtml(v)}">采用文档实际值「${escapeHtml(v)}」并确认</button>`
    ).join("");
    return h`
      <div class="conflict">
        <div class="conflict-field">字段 <strong>${conflictFieldLabel(c.field)}</strong> 不一致</div>
        <div class="conflict-vals">
          <span class="cv-label">manifest 声明</span><code>${c.manifest || "(空)"}</code>
          <span class="cv-label">文档实际</span><code>${c.extracted || "(未抽到)"}</code>
        </div>
        ${raw(buttons)}
      </div>`;
  }).join("");
  return h`<div class="conflicts">${raw(rows)}</div>`;
}

function renderQueue(items) {
  $("queueList").innerHTML = items.map((q) => h`
    <div class="queue-item">
      <strong>${queueLabel(q.queue_type)} · ${short(q.queue_id)}</strong>
      <div class="meta">${short(q.doc_version_id)} · ${queueStatusLabel(q.status)} · ${q.reason || ""}</div>
      ${q.status === "open" ? raw(conflictBlockHtml(q)) : ""}
      ${q.status === "open" ? raw(`<div class="queue-actions">${queueButtons(q)}</div>`) : ""}
    </div>
  `).join("");
  document.querySelectorAll("[data-queue-action]").forEach((btn) => {
    btn.onclick = () => runQueueAction(btn.dataset.queueId, btn.dataset.queueAction, btn);
  });
  document.querySelectorAll("[data-resolve-qid]").forEach((btn) => {
    btn.onclick = () => applySuggestion(
      btn.dataset.resolveQid, btn.dataset.resolveField, btn.dataset.resolveValue, btn
    );
  });
}

function renderSearch(res) {
  const panel = $("searchResults");
  const hits = res.hits || [];
  if (!hits.length) {
    panel.innerHTML = h`<div class="search-empty">检索「${res.query}」· 无命中</div>`;
    panel.hidden = false;
    return;
  }
  panel.innerHTML = h`
    <div class="search-head">检索「${res.query}」· ${res.retrieval_mode || "hybrid"} · ${hits.length} 命中</div>
    ${raw(hits.map((hit, i) => h`
      <div class="search-hit">
        <div class="hit-head">
          <span class="hit-rank">#${i + 1}</span>
          <strong>${hit.clause_path || "根节点"}</strong>
          ${hit.is_obligation ? raw('<span class="tag-obligation">[义务]</span>') : ""}
          <span class="hit-score">${(hit.score ?? 0).toFixed(4)}</span>
        </div>
        <div class="meta">${hit.corpus_type || "-"} · 页 ${hit.page_start || "-"} · ${hit.status || "-"} · ${short(hit.doc_version_id)}</div>
      </div>
    `).join(""))}
  `;
  panel.hidden = false;
}

function queueButtons(q) {
  const map = {
    qc_fix: ["fix", "degrade", "reject"],
    quarantine: ["release", "reject"],
    meta_confirm: ["approve", "reject"],
  };
  return (map[q.queue_type] || []).map((a) =>
    `<button data-queue-id="${escapeHtml(q.queue_id)}" data-queue-action="${a}">${escapeHtml(actionLabels[a] || a)}</button>`
  ).join("");
}

async function runQueueAction(qid, action, btn) {
  await withBusy(btn, async () => {
    try {
      if (action === "approve") {
        await api("/api/meta/confirm", postJson({ queue_id: qid, operator: "web" }));
      } else {
        await api(`/api/queue/${qid}/${action}`, postJson({ operator: "web" }));
      }
      log(`队列动作已完成：${actionLabels[action] || action}`, { qid });
      await refreshAll();
    } catch (err) {
      logError(`队列动作失败：${actionLabels[action] || action}`, err);
    }
  });
}

// 一键采用某冲突字段的 L1 抽取值:全清且非修订件 → 服务端自动放行至 INDEXED;否则留闸显示剩余冲突。
async function applySuggestion(qid, field, value, btn) {
  await withBusy(btn, async () => {
    try {
      const res = await api("/api/meta/resolve", postJson({ queue_id: qid, field, value, operator: "web" }));
      if (res.resolved) {
        log(`已采用${conflictFieldLabel(field)}「${value}」并放行至 ${res.final}`, { doc_version_id: res.doc_version_id });
      } else {
        const n = (res.remaining_conflicts || []).length;
        const tail = res.is_revision ? "(修订件仍需人工确认放行)" : `,仍有 ${n} 项冲突待处理`;
        log(`已采用${conflictFieldLabel(field)}「${value}」${tail}`, { remaining: res.remaining_conflicts });
      }
      await refreshAll();
      await selectDoc(res.doc_version_id);
    } catch (err) {
      logError("采用推荐值失败", err);
    }
  });
}

function postJson(body) {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

// 慢/变更类操作:运行期间禁用触发按钮 + 显示「处理中…」,结束恢复。防止"界面卡住"观感与重复点击
// (双击把请求打到已关闭的队列项)。无按钮时直接执行。
async function withBusy(btn, fn) {
  if (!btn) return fn();
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "处理中…";
  try {
    return await fn();
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

function bindUpload() {
  const drop = $("dropZone");
  const input = $("fileInput");
  input.onchange = () => setFiles([...input.files]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("dragging"); };
  drop.ondragleave = () => drop.classList.remove("dragging");
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove("dragging");
    setFiles([...e.dataTransfer.files]);
  };
  $("uploadBtn").onclick = uploadFiles;
}

function setFiles(files) {
  state.files = files;
  $("uploadCount").textContent = `${files.length} 个文件`;
}

async function uploadFiles() {
  if (!state.files.length) return log("尚未选择文件");
  const fd = new FormData();
  for (const file of state.files) {
    fd.append(file.name.toLowerCase().endsWith(".xlsx") ? "manifest" : "files", file, file.name);
  }
  fd.append("corpus_type", $("corpusType").value);
  fd.append("perm_tag", $("permTag").value);
  fd.append("biz_domain", $("bizDomain").value);
  fd.append("issuer", $("issuer").value);
  await withBusy($("uploadBtn"), async () => {
    try {
      const res = await api("/api/upload", { method: "POST", body: fd });
      log("上传已进入管线", res);
      state.files = [];
      $("uploadCount").textContent = "0 个文件";
      await refreshAll();
      await selectBatch(res.batch_id);
    } catch (err) {
      logError("上传失败", err);
    }
  });
}

async function runBatchReport() {
  if (!state.batch) return;
  await withBusy($("reportBtn"), async () => {
    try {
      const rep = await api("/api/report", postJson({ batch_id: state.batch.batch_id }));
      log("报告已刷新", rep);
      await selectBatch(state.batch.batch_id, false);
    } catch (err) {
      logError("报告生成失败", err);
    }
  });
}

async function runVerify(name, btn) {
  await withBusy(btn, async () => {
    try {
      const body = state.batch ? { batch_id: state.batch.batch_id } : {};
      const res = await api(`/api/verify/${name}`, postJson(body));
      log(`${verifyLabel(name)} 已完成`, res);
      await refreshAll();
    } catch (err) {
      logError(`${verifyLabel(name)} 失败`, err);
    }
  });
}

async function search() {
  const query = $("searchInput").value.trim();
  if (!query) return;
  await withBusy($("searchBtn"), async () => {
    try {
      const res = await api("/api/search", postJson({ query, topk: 10 }));
      renderSearch(res);
      log("检索完成", { query, hits: res.hits?.length ?? 0 });
    } catch (err) {
      logError("检索失败", err);
    }
  });
}

async function confirmSelected() {
  if (!state.doc) return;
  const q = state.doc.queue.find((item) => item.queue_type === "meta_confirm" && item.status === "open");
  if (!q) return log("当前文档没有待确认的元数据队列");
  await runQueueAction(q.queue_id, "approve", $("confirmDocBtn"));
}

async function reprocessSelected() {
  if (!state.doc) return;
  await withBusy($("reprocessBtn"), async () => {
    try {
      const res = await api("/api/reprocess", postJson({ doc_version_id: state.doc.doc.doc_version_id }));
      log("重跑完成", res);
      await refreshAll();
      await selectDoc(state.doc.doc.doc_version_id);
    } catch (err) {
      logError("重跑失败", err);
    }
  });
}

function short(s) {
  if (!s) return "-";
  return s.length > 12 ? `${s.slice(0, 8)}..` : s;
}

function formatCounts(counts = {}) {
  return Object.entries(counts).map(([k, v]) => `${k}:${v}`).join(" ") || "暂无文档";
}

function artifactLabel(kind) {
  return artifactLabels[kind] || kind;
}

function queueLabel(type) {
  return queueLabels[type] || type;
}

function queueStatusLabel(status) {
  return { open: "待处理", closed: "已关闭" }[status] || status;
}

function verifyLabel(name) {
  return {
    smoke: "烟测",
    replay: "锚点回放",
    reconcile: "对账",
    rebuild: "重建",
  }[name] || name;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// 标签模板:插值**默认 HTML 转义**,从根上杜绝 innerHTML XSS(逐字段手转易漏)。已是安全 HTML 的
// 片段(嵌套渲染结果、拼好的子串)用 raw() 包裹跳过转义。所有写 innerHTML 的渲染函数一律走 h``。
function raw(html) {
  return { __raw: String(html) };
}
function h(strings, ...vals) {
  return strings.reduce((out, s, i) => {
    if (i >= vals.length) return out + s;
    const v = vals[i];
    const piece = v && v.__raw !== undefined ? v.__raw : escapeHtml(v ?? "");
    return out + s + piece;
  }, "");
}

function bindActions() {
  $("refreshBtn").onclick = refreshAll;
  $("showAllQueue").onchange = refreshAll;
  $("reportBtn").onclick = runBatchReport;
  $("smokeBtn").onclick = () => runVerify("smoke", $("smokeBtn"));
  $("replayBtn").onclick = () => runVerify("replay", $("replayBtn"));
  $("reconcileBtn").onclick = () => runVerify("reconcile", $("reconcileBtn"));
  $("searchBtn").onclick = search;
  $("searchInput").onkeydown = (e) => { if (e.key === "Enter") search(); };
  $("confirmDocBtn").onclick = confirmSelected;
  $("reprocessBtn").onclick = reprocessSelected;
  $("clearLogBtn").onclick = () => { $("activityLog").textContent = ""; };
}

bindUpload();
bindActions();
refreshAll().catch((err) => logError("初始化加载失败", err));
