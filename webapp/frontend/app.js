/* 연구개발계획서 웹서비스 — 프론트엔드 (vanilla JS)
 * API base = same origin. 모든 호출은 fetch 기반.
 */
"use strict";

/* ------------------------------------------------------------------ */
/* 상태                                                                */
/* ------------------------------------------------------------------ */
const state = {
  pid: null,
  tree: [],
  nid: null,
  node: null, // GET /nodes/{nid} 결과
  rfp: null, // {filename, chars, text} — 업로드된 RFP(작성 프롬프트 아래 참조 표시)
  overview: "", // 제반사항 직렬화 텍스트(② 미러 표시용)
  overviewData: null, // 제반사항 구조화 데이터 {institutions,period,funding,goal}
};

/* ------------------------------------------------------------------ */
/* DOM 헬퍼                                                            */
/* ------------------------------------------------------------------ */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const el = (tag, props = {}, children = []) => {
  const n = document.createElement(tag);
  Object.entries(props).forEach(([k, v]) => {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  });
  (Array.isArray(children) ? children : [children]).forEach((c) => {
    if (c == null) return;
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return n;
};

/* ------------------------------------------------------------------ */
/* 토스트 / 상태 메시지                                                */
/* ------------------------------------------------------------------ */
let toastTimer = null;
function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (kind ? " " + kind : "");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.className = "toast hidden";
  }, 2800);
}

/* ------------------------------------------------------------------ */
/* API 래퍼 (same origin)                                              */
/* ------------------------------------------------------------------ */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.status + " " + res.statusText;
    try {
      const body = await res.json();
      if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      /* non-json error */
    }
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}
const jsonBody = (obj) => ({
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});
const postJson = (obj) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(obj),
});

/* ---- 엔드포인트 (ARCHITECTURE REST 계약과 1:1) ---- */
const API = {
  createProject: (name) => api("/api/projects", postJson({ use_default: true, name: name || null })),
  deleteProject: (pid) => api(`/api/projects/${pid}`, { method: "DELETE" }),
  listProjects: () => api("/api/projects"),
  getTree: (pid) => api(`/api/projects/${pid}/tree`),
  getNode: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}`),
  putTemplate: (pid, nid, template) => api(`/api/projects/${pid}/nodes/${nid}/template`, jsonBody({ template })),
  generateTemplate: (pid, nid, description) =>
    api(`/api/projects/${pid}/nodes/${nid}/template/generate`, postJson({ description })),
  putPrompts: (pid, nid, body) =>
    api(`/api/projects/${pid}/nodes/${nid}/prompts`, jsonBody(body)),
  getPreset: (nid) => api(`/api/presets/${nid}`),
  getTables: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/tables`),
  putTables: (pid, nid, cells) => api(`/api/projects/${pid}/nodes/${nid}/tables`, jsonBody({ cells })),
  tablesXlsxUrl: (pid, nid) => `/api/projects/${pid}/nodes/${nid}/tables.xlsx`,
  importTablesXlsx: (pid, nid, formData) =>
    api(`/api/projects/${pid}/nodes/${nid}/tables/import-xlsx`, { method: "POST", body: formData }),
  tableStructure: (pid, nid, op, table_path, index) =>
    api(`/api/projects/${pid}/nodes/${nid}/tables/structure`, postJson({ op, table_path, index })),
  getFormulas: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/tables/formulas`),
  putFormulas: (pid, nid, formulas) =>
    api(`/api/projects/${pid}/nodes/${nid}/tables/formulas`, jsonBody({ formulas })),
  putInput: (pid, nid, input) => api(`/api/projects/${pid}/nodes/${nid}/input`, jsonBody({ input })),
  chat: (pid, nid, message, apply) =>
    api(`/api/projects/${pid}/nodes/${nid}/chat`, postJson({ message, apply })),
  clearChat: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/chat`, { method: "DELETE" }),
  convert: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/convert`, postJson({})),
  build: (pid) => api(`/api/projects/${pid}/build`, postJson({})),
  downloadUrl: (pid) => `/api/projects/${pid}/download`,
  previewUrl: (pid) => `/api/projects/${pid}/preview.pdf`,
  sectionHwpxUrl: (pid, nid) => `/api/projects/${pid}/nodes/${nid}/section.hwpx`,
  regulationsPdfUrl: (pid, nid) => `/api/projects/${pid}/nodes/${nid}/regulations.pdf`,
  getRegulation: (nid) => api(`/api/regulations/${nid}`),
  getRfp: (pid) => api(`/api/projects/${pid}/rfp`),
  uploadRfp: (pid, formData) => api(`/api/projects/${pid}/rfp`, { method: "POST", body: formData }),
  getOverview: (pid) => api(`/api/projects/${pid}/overview`),
  saveOverview: (pid, data, apply) => api(`/api/projects/${pid}/overview`, jsonBody({ data, apply: !!apply })),
  coverAutofillRfp: (pid) => api(`/api/projects/${pid}/cover/autofill-rfp`, { method: "POST" }),
  coverClassify: (pid) => api(`/api/projects/${pid}/cover/classify`, { method: "POST" }),
  coverTranslate: (pid, text) => api(`/api/projects/${pid}/cover/translate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }),
  summarySuggest: (pid) => api(`/api/projects/${pid}/summary/suggest`, { method: "POST" }),
  budgetSyncStages: (pid) => api(`/api/projects/${pid}/budget/sync-stages`, { method: "POST" }),
  budgetSyncDetail: (pid) => api(`/api/projects/${pid}/budget/sync-detail`, { method: "POST" }),
};

/* ------------------------------------------------------------------ */
/* 미니 YAML (template.yaml 표시/편집용 — 얕은 맵/스칼라 지원)          */
/* ------------------------------------------------------------------ */
const YAMLMini = {
  dump(obj) {
    const lines = [];
    const isScalar = (v) => v === null || typeof v !== "object";
    const scalar = (v) => {
      if (v === null || v === undefined) return "";
      if (typeof v === "boolean") return v ? "true" : "false";
      if (typeof v === "number") return String(v);
      const s = String(v);
      if (s === "" || /^[\s#].*|.*[:#].*|^(true|false|null|~|-?\d+(\.\d+)?)$/i.test(s) || /[:{}\[\],&*!|>'"%@`]/.test(s)) {
        return '"' + s.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
      }
      return s;
    };
    const walk = (o, indent) => {
      const pad = "  ".repeat(indent);
      if (Array.isArray(o)) {
        o.forEach((item) => {
          if (isScalar(item)) lines.push(pad + "- " + scalar(item));
          else {
            lines.push(pad + "-");
            walk(item, indent + 1);
          }
        });
      } else {
        Object.entries(o).forEach(([k, v]) => {
          if (isScalar(v)) lines.push(pad + k + ": " + scalar(v));
          else {
            lines.push(pad + k + ":");
            walk(v, indent + 1);
          }
        });
      }
    };
    if (obj == null) return "";
    walk(obj, 0);
    return lines.join("\n") + "\n";
  },

  parseScalar(s) {
    s = s.trim();
    if (s === "" || s === "~" || s.toLowerCase() === "null") return null;
    if (s.toLowerCase() === "true") return true;
    if (s.toLowerCase() === "false") return false;
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
      const inner = s.slice(1, -1);
      return s[0] === '"' ? inner.replace(/\\"/g, '"').replace(/\\\\/g, "\\") : inner;
    }
    if (/^-?\d+$/.test(s)) return parseInt(s, 10);
    if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s);
    return s;
  },

  // 들여쓰기 기반 맵/리스트 파서 (template.yaml 서브셋)
  load(text) {
    const rawLines = text.split(/\r?\n/);
    const lines = [];
    for (const ln of rawLines) {
      // 전체 주석/빈 줄 제거
      const noComment = stripComment(ln);
      if (noComment.trim() === "") continue;
      const indent = noComment.length - noComment.trimStart().length;
      lines.push({ indent, content: noComment.trim() });
    }
    let i = 0;
    function parseBlock(minIndent) {
      // 첫 항목이 리스트인지 맵인지 판별
      if (i >= lines.length) return null;
      const first = lines[i];
      const isList = first.content.startsWith("- ") || first.content === "-";
      const container = isList ? [] : {};
      const baseIndent = first.indent;
      while (i < lines.length && lines[i].indent >= baseIndent) {
        if (lines[i].indent > baseIndent) {
          // 예상치 못한 깊은 들여쓰기 — 안전하게 스킵
          i++;
          continue;
        }
        const { content } = lines[i];
        if (isList) {
          const item = content === "-" ? "" : content.slice(2);
          if (item === "") {
            i++;
            const child = i < lines.length && lines[i].indent > baseIndent ? parseBlock(lines[i].indent) : null;
            container.push(child);
          } else {
            i++;
            container.push(YAMLMini.parseScalar(item));
          }
        } else {
          const ci = content.indexOf(":");
          if (ci === -1) {
            i++;
            continue;
          }
          const key = content.slice(0, ci).trim();
          const rest = content.slice(ci + 1).trim();
          if (rest === "") {
            i++;
            if (i < lines.length && lines[i].indent > baseIndent) {
              container[key] = parseBlock(lines[i].indent);
            } else {
              container[key] = null;
            }
          } else {
            i++;
            container[key] = YAMLMini.parseScalar(rest);
          }
        }
      }
      return container;
    }
    const result = parseBlock(0);
    return result == null ? {} : result;
  },
};

function stripComment(line) {
  // 따옴표 밖의 # 이후 제거
  let inS = false,
    inD = false;
  for (let k = 0; k < line.length; k++) {
    const c = line[k];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS) inD = !inD;
    else if (c === "#" && !inS && !inD) return line.slice(0, k).replace(/\s+$/, "");
  }
  return line;
}

/* ------------------------------------------------------------------ */
/* 프로젝트                                                            */
/* ------------------------------------------------------------------ */
async function loadProjects(selectPid) {
  const sel = $("#project-select");
  try {
    const projects = await API.listProjects();
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "", text: "프로젝트 선택…" }));
    projects.forEach((p) => {
      sel.appendChild(el("option", { value: p.id, text: `${p.name || p.id}` }));
    });
    if (selectPid) sel.value = selectPid;
    updateDelButton();
  } catch (e) {
    toast("프로젝트 목록 조회 실패: " + e.message, "err");
  }
}

// 삭제 버튼은 프로젝트가 선택돼 있을 때만 활성화
function updateDelButton() {
  const btn = $("#btn-del-project");
  if (btn) btn.disabled = !$("#project-select").value;
}

async function openProject(pid) {
  if (!pid) return;
  state.pid = pid;
  state.nid = null;
  state.node = null;
  state.rfp = null;
  $("#btn-build").disabled = false;
  $("#build-links").classList.add("hidden");
  updateDelButton();
  showNodeEmpty();
  await loadTree();
  refreshRfpStatus();
  refreshOverview();
}

async function createProject() {
  const btn = $("#btn-new-project");
  const nameField = $("#project-name");
  const name = (nameField ? nameField.value : "").trim();
  btn.disabled = true;
  toast("기본 문서로 프로젝트 생성 중… (변환·추출)");
  try {
    const res = await API.createProject(name);
    const pid = res.pid || res.id;
    if (nameField) nameField.value = "";
    await loadProjects(pid);
    await openProject(pid);
    toast("프로젝트 생성 완료", "ok");
  } catch (e) {
    toast("프로젝트 생성 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function deleteProject() {
  const sel = $("#project-select");
  const pid = sel.value || state.pid;
  if (!pid) {
    toast("삭제할 프로젝트를 먼저 선택하세요.", "err");
    return;
  }
  const opt = sel.options[sel.selectedIndex];
  const name = opt && opt.value === pid ? opt.text : pid;
  if (
    !confirm(
      `프로젝트 "${name}" 를 삭제할까요?\n` +
        "입력·변환·빌드 산출물 등 이 프로젝트의 모든 파일이 지워지며 되돌릴 수 없습니다."
    )
  )
    return;

  const btn = $("#btn-del-project");
  btn.disabled = true;
  try {
    await API.deleteProject(pid);
    toast(`프로젝트 "${name}" 를 삭제했습니다.`, "ok");
    // 현재 열려 있던 프로젝트를 지웠으면 편집 화면을 비운다
    if (state.pid === pid) {
      state.pid = null;
      state.nid = null;
      state.node = null;
      state.rfp = null;
      $("#btn-build").disabled = true;
      $("#build-links").classList.add("hidden");
      showNodeEmpty();
      $("#tree").innerHTML = "";
      $("#tree").appendChild(el("p", { class: "placeholder", text: "프로젝트를 선택하거나 새로 만드세요." }));
      setRfpStatus("");
      state.overview = "";
      state.overviewData = null;
      renderOverviewForm({});
      renderOverviewSummary({});
      setOverviewStatus("");
      renderOverviewRef();
      closeOverviewModal(false);
    }
    await loadProjects(state.pid || "");
    if (!state.pid) $("#project-select").value = "";
  } catch (e) {
    toast("삭제 실패: " + e.message, "err");
  } finally {
    updateDelButton();
  }
}

/* ------------------------------------------------------------------ */
/* 트리                                                                */
/* ------------------------------------------------------------------ */
async function loadTree() {
  const box = $("#tree");
  box.innerHTML = "";
  box.appendChild(el("p", { class: "placeholder", text: "목차 로드 중…" }));
  try {
    state.tree = await API.getTree(state.pid);
    renderTree();
  } catch (e) {
    box.innerHTML = "";
    box.appendChild(el("p", { class: "placeholder", text: "목차 로드 실패: " + e.message }));
    toast("목차 로드 실패: " + e.message, "err");
  }
}

function renderTree() {
  const box = $("#tree");
  box.innerHTML = "";
  if (!state.tree || state.tree.length === 0) {
    box.appendChild(el("p", { class: "placeholder", text: "목차가 비어 있습니다." }));
    return;
  }
  state.tree.forEach((chap) => {
    const children = chap.children || [];
    const caret = el("span", { class: "tree-caret", text: "▾" });
    const head = el(
      "div",
      {
        class: "tree-chapter-head",
        onclick: (ev) => {
          // 캐럿/장 헤더 클릭 = 접기토글, 하지만 장 자체도 편집 가능한 노드
          wrap.classList.toggle("collapsed");
        },
      },
      [caret, el("span", { class: "tree-num", text: chap.label }), el("span", { class: "tree-title-txt", text: chap.title || "" })]
    );

    const childBox = el("div", { class: "tree-children" });
    // 장 자체를 편집 대상으로 여는 leaf (선택)
    childBox.appendChild(makeLeaf(chap, true));
    children.forEach((sec) => childBox.appendChild(makeLeaf(sec, false)));

    const wrap = el("div", { class: "tree-chapter" }, [head, childBox]);
    box.appendChild(wrap);
  });
}

function makeLeaf(node, isChapter) {
  const kids = [
    el("span", { class: "tree-num", text: node.label }),
    el("span", { class: "tree-title-txt", text: node.title || "" }),
  ];
  const leaf = el(
    "div",
    {
      class: "tree-leaf" + (isChapter ? " chapter-leaf" : ""),
      "data-nid": node.id,
      onclick: () => selectNode(node.id),
    },
    kids
  );
  return leaf;
}

function highlightLeaf(nid) {
  $$(".tree-leaf").forEach((l) => l.classList.toggle("active", l.getAttribute("data-nid") === nid));
}

/* ------------------------------------------------------------------ */
/* 노드 로드 / 렌더                                                    */
/* ------------------------------------------------------------------ */
function showNodeEmpty() {
  $("#node-empty").classList.remove("hidden");
  $("#node-view").classList.add("hidden");
}

async function selectNode(nid) {
  if (!state.pid) return;
  highlightLeaf(nid);
  try {
    const node = await API.getNode(state.pid, nid);
    state.nid = nid;
    state.node = node;
    renderNode(node);
    loadTables(nid);
  } catch (e) {
    console.error("[selectNode] 노드 로드 실패:", e);  // 실제 원인(스택)을 콘솔에 남김
    toast("노드 로드 실패: " + (e && e.message ? e.message : e), "err");
  }
}

function renderNode(node) {
  $("#node-empty").classList.add("hidden");
  $("#node-view").classList.remove("hidden");

  $("#node-title").textContent = (node.label ? node.label + "  " : "") + (node.title || "");
  const cnt = node.node_count != null ? node.node_count : node.content_count;
  $("#node-meta").textContent = cnt != null ? `대상 문단 ${cnt}개` : "";

  // 가이드라인(※)
  const guides = node.guidelines || [];
  const gbox = $("#guidelines-box");
  const glist = $("#guidelines-list");
  glist.innerHTML = "";
  if (guides.length) {
    guides.forEach((g) => glist.appendChild(el("li", { text: g })));
    gbox.classList.remove("hidden");
  } else {
    gbox.classList.add("hidden");
  }

  // 1) 템플릿 → YAML 텍스트
  $("#template-text").value = node.template ? YAMLMini.dump(node.template) : "";
  $("#template-desc").value = "";

  // 2) 프롬프트 — 문체 스타일 3원천(① 한글파일 요구 ② 스킬 제공 ③ 추가) + 구성
  // setVal: 요소가 없으면(옛 캐시 DOM 등) 조용히 건너뛴다 → 노드 로드 전체가 깨지지 않게.
  const setVal = (sel, v) => { const e = $(sel); if (e) e.value = v; };
  const p = node.prompts || {};
  const preset = node.preset || {};
  // ① 기존 한글파일에서 요구하는 것 = ※작성요령(guidelines). 읽기전용 참조.
  const docGuides = (p.guidelines && p.guidelines.length ? p.guidelines : guides) || [];
  setVal("#prompt-style-doc", docGuides.join("\n"));
  // ② 스킬로 제공한 것 = rnd-write 작성 스킬(_프롬프트 핵심). read_node 가 항상 현재
  // 프리셋에서 파생해 style_skill 로 준다(읽기전용, 저장 안 함).
  setVal("#prompt-style-skill", p.style_skill != null ? p.style_skill : (preset.style || ""));
  // ③ 추가로 작성 = 사용자 보완분.
  setVal("#prompt-style-extra", p.style_extra != null ? p.style_extra : "");
  // 구성(structure)
  setVal("#prompt-structure",
    p.structure != null && p.structure !== "" ? p.structure : (preset.structure || ""));
  // 참조 문체 프리셋 출처(rnd-write-*) 표시
  const skill = preset.skill || p.preset_skill || "";
  const origin = $("#preset-origin");
  if (origin) {
    origin.textContent = skill ? `참조 스킬: ${skill}` : "참조 프리셋 없음";
  }
  // 작성 프롬프트 아래: 이 절 관련 작성 규정 + RFP 본문(참조용) 표시
  renderRegRef(node.id);
  renderRfpRef();
  renderOverviewRef();

  // 3) 입력 + 작성 채팅 이력
  $("#input-text").value = node.input || "";
  $("#chat-input").value = "";
  renderChat(node.chat);

  // 4) 변환 결과 (기존 result 표시)
  renderConvertResult(node.result);

  // 첫 탭으로
  switchTab("template");
}

/* ------------------------------------------------------------------ */
/* 탭                                                                  */
/* ------------------------------------------------------------------ */
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.getAttribute("data-tab") === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.getAttribute("data-panel") === name));
}

/* ------------------------------------------------------------------ */
/* 저장 / 생성 / 변환 액션                                             */
/* ------------------------------------------------------------------ */
function guardNode() {
  if (!state.pid || !state.nid) {
    toast("먼저 목차에서 절을 선택하세요.", "err");
    return false;
  }
  return true;
}

async function saveTemplate() {
  if (!guardNode()) return;
  let template;
  try {
    template = YAMLMini.load($("#template-text").value);
  } catch (e) {
    toast("YAML 파싱 오류: " + e.message, "err");
    return;
  }
  try {
    await API.putTemplate(state.pid, state.nid, template);
    if (state.node) state.node.template = template;
    toast("양식 템플릿 저장됨", "ok");
  } catch (e) {
    toast("템플릿 저장 실패: " + e.message, "err");
  }
}

async function generateTemplate() {
  if (!guardNode()) return;
  const desc = $("#template-desc").value.trim();
  if (!desc) {
    toast("생성 설명을 입력하세요.", "err");
    return;
  }
  const btn = $("#btn-template-generate");
  btn.disabled = true;
  toast("AI가 양식을 생성 중…");
  try {
    const res = await API.generateTemplate(state.pid, state.nid, desc);
    const tpl = res.template || res;
    $("#template-text").value = YAMLMini.dump(tpl);
    if (state.node) state.node.template = tpl;
    toast("양식 생성 완료 (저장됨)", "ok");
  } catch (e) {
    toast("양식 생성 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function loadPreset() {
  if (!guardNode()) return;
  try {
    const preset = await API.getPreset(state.nid);
    // ②(스킬 제공)는 항상 자동 표시(읽기전용)이므로, 이 버튼은 '구성(structure)'만 프리셋으로 채운다.
    $("#prompt-style-skill").value = preset.style || "";
    $("#prompt-structure").value = preset.structure || "";
    const origin = $("#preset-origin");
    if (origin) origin.textContent = preset.skill ? `참조 스킬: ${preset.skill}` : "참조 프리셋 없음";
    toast("참조 프리셋으로 구성(structure)을 채웠습니다(저장 눌러 반영)", "ok");
  } catch (e) {
    toast("프리셋 불러오기 실패: " + e.message, "err");
  }
}

async function savePrompts() {
  if (!guardNode()) return;
  try {
    // ②(스킬 제공)는 자동 파생·읽기전용이라 저장하지 않는다. 사용자 소유는 ③·구성뿐.
    const body = {
      style_extra: $("#prompt-style-extra").value,
      structure: $("#prompt-structure").value,
    };
    const saved = await API.putPrompts(state.pid, state.nid, body);
    if (state.node) state.node.prompts = saved.prompts || saved;
    toast("작성 프롬프트 저장됨", "ok");
  } catch (e) {
    toast("프롬프트 저장 실패: " + e.message, "err");
  }
}

async function saveInput() {
  if (!guardNode()) return;
  try {
    await API.putInput(state.pid, state.nid, $("#input-text").value);
    if (state.node) state.node.input = $("#input-text").value;
    toast("입력 저장됨", "ok");
  } catch (e) {
    toast("입력 저장 실패: " + e.message, "err");
  }
}

/* ------------------------------------------------------------------ */
/* 작성 채팅 (입력 패널 하단)                                          */
/* ------------------------------------------------------------------ */
function renderChat(chat) {
  const box = $("#chat-log");
  box.innerHTML = "";
  if (!chat || !chat.length) {
    box.appendChild(
      el("p", {
        class: "placeholder",
        text: "양식·작성요령·문체를 참고해 위 본문을 대신 써 드립니다. 재료나 수정 지시를 적어 보세요.",
      })
    );
    return;
  }
  chat.forEach((turn) => {
    box.appendChild(
      el("div", { class: "chat-msg chat-" + (turn.role === "user" ? "user" : "ai") }, [
        el("span", { class: "chat-role", text: turn.role === "user" ? "나" : "AI" }),
        el("div", { class: "chat-text", text: turn.content || "" }),
      ])
    );
  });
  box.scrollTop = box.scrollHeight;
}

async function sendChat() {
  if (!guardNode()) return;
  const field = $("#chat-input");
  const message = field.value.trim();
  if (!message) {
    toast("보낼 내용을 입력하세요.", "err");
    return;
  }
  const btn = $("#btn-chat-send");
  btn.disabled = true;
  field.disabled = true;
  // 낙관적 표시: 내 말풍선을 먼저 붙이고 답변을 기다린다.
  const pending = (state.node && state.node.chat ? state.node.chat.slice() : []).concat([
    { role: "user", content: message },
    { role: "assistant", content: "작성 중… (양식·문체를 반영해 다시 쓰는 중이라 30초~1분 걸릴 수 있습니다)" },
  ]);
  renderChat(pending);
  try {
    const apply = $("#chat-apply").checked;
    const res = await API.chat(state.pid, state.nid, message, apply);
    renderChat(res.chat);
    field.value = "";
    if (state.node) state.node.chat = res.chat;
    if (apply && res.draft != null) {
      $("#input-text").value = res.input || "";
      if (state.node) state.node.input = res.input || "";
      toast("본문을 다시 써서 입력에 반영했습니다.", "ok");
    } else {
      toast("답변이 도착했습니다.", "ok");
    }
  } catch (e) {
    renderChat(state.node ? state.node.chat : []);
    toast("채팅 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
    field.disabled = false;
    field.focus();
  }
}

async function clearChat() {
  if (!guardNode()) return;
  try {
    const res = await API.clearChat(state.pid, state.nid);
    if (state.node) state.node.chat = res.chat || [];
    renderChat(res.chat);
    toast("대화를 초기화했습니다(본문은 그대로).", "ok");
  } catch (e) {
    toast("초기화 실패: " + e.message, "err");
  }
}

async function doConvert() {
  if (!guardNode()) return;
  const btn = $("#btn-convert");
  btn.disabled = true;
  toast("변환 중…");
  try {
    const res = await API.convert(state.pid, state.nid);
    const result = res.result || res;
    renderConvertResult(result);
    if (state.node) state.node.result = result;
    toast("변환 완료 — YAML에 반영됨", "ok");
  } catch (e) {
    toast("변환 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function downloadSectionHwpx() {
  if (!guardNode()) return;
  const btn = $("#btn-convert-hwpx");
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ HWPX 변환 중…";
  toast("HWPX 변환 중… (YAML→hwpx 복원)");
  try {
    const resp = await fetch(API.sectionHwpxUrl(state.pid, state.nid));
    if (!resp.ok) {
      let msg = String(resp.status);
      try {
        const j = await resp.json();
        if (j && j.detail) msg = j.detail;
      } catch (_) {}
      throw new Error(msg);
    }
    const blob = await resp.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = "연구개발계획서.hwpx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
    toast("HWPX 다운로드 완료", "ok");
  } catch (e) {
    toast("HWPX 변환 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function renderConvertResult(result) {
  const box = $("#convert-result");
  box.innerHTML = "";
  if (!result || !result.length) {
    box.appendChild(el("p", { class: "placeholder", text: "아직 변환 결과가 없습니다." }));
    return;
  }
  result.forEach((r) => {
    const marker = r.marker ? el("span", { class: "diff-marker", text: r.marker }) : null;
    const before = el("div", { class: "diff-cell diff-before" }, [
      el("span", { class: "diff-label", text: "변경 전" }),
      document.createTextNode(r.before != null ? r.before : ""),
    ]);
    const afterCell = el("div", { class: "diff-cell diff-after" }, [el("span", { class: "diff-label", text: "변경 후" })]);
    if (marker) afterCell.appendChild(marker);
    afterCell.appendChild(document.createTextNode(r.after != null ? r.after : ""));
    const rowCols = el("div", { class: "diff-cols" }, [before, afterCell]);
    const row = el("div", { class: "diff-row" }, [el("div", { class: "diff-path", text: r.path || "" }), rowCols]);
    box.appendChild(row);
  });
}

/* ------------------------------------------------------------------ */
/* 작성 규정 PDF (노드 헤더 우측)                                       */
/* ------------------------------------------------------------------ */
async function openRegulationsPdf() {
  if (!guardNode()) return;
  const btn = $("#btn-reg-pdf");
  // 팝업 차단 회피: 클릭 즉시 탭을 열고, 받은 PDF 를 그 탭에 실어준다.
  const win = window.open("", "_blank");
  btn.disabled = true;
  toast("작성 규정 PDF 생성 중…");
  try {
    const res = await fetch(API.regulationsPdfUrl(state.pid, state.nid));
    if (!res.ok) {
      let detail = res.status + " " + res.statusText;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch (_) {
        /* non-json error */
      }
      throw new Error(detail);
    }
    const url = URL.createObjectURL(await res.blob());
    if (win) win.location = url;
    else window.open(url, "_blank"); // 팝업이 막힌 경우 재시도
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    toast("작성 규정 PDF 를 열었습니다.", "ok");
  } catch (e) {
    if (win) win.close();
    toast("규정 PDF 생성 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* 이 절 관련 작성 규정(법령·요령·지침) — 작성 프롬프트 하단 표시        */
/* ------------------------------------------------------------------ */
async function renderRegRef(nid) {
  const box = $("#reg-ref");
  const list = $("#reg-ref-list");
  const meta = $("#reg-ref-meta");
  if (!box || !list) return;
  list.innerHTML = "";
  box.classList.add("hidden");
  if (!nid) return;
  let reg;
  try {
    reg = await API.getRegulation(nid);
  } catch (_) {
    return; // 규정 조회 실패해도 노드 로드에는 영향 없음
  }
  // 다른 절로 이동했으면 반영하지 않음(레이스 방지)
  if (state.nid !== nid) return;
  const laws = (reg && reg.laws) || [];
  if (!laws.length) return;
  if (meta) {
    meta.textContent = `— ${laws.length}건` + (reg.reg_as_of ? ` · 기준일 ${reg.reg_as_of}` : "");
  }
  laws.forEach((lw) => {
    const head = [lw.title, lw.kind ? `(${lw.kind})` : ""].filter(Boolean).join(" ");
    const kids = [
      el("div", { class: "reg-item-title", text: head }),
    ];
    if (lw.article) kids.push(el("div", { class: "reg-item-art", text: lw.article }));
    if (lw.authority) kids.push(el("div", { class: "reg-item-auth", text: "소관: " + lw.authority }));
    if (lw.requirement) kids.push(el("div", { class: "reg-item-req", text: lw.requirement }));
    const foot = [];
    if (lw.source_url) foot.push(el("a", { class: "reg-item-src", href: lw.source_url, target: "_blank", rel: "noopener", text: "출처 원문" }));
    if (lw.effective_date) foot.push(el("span", { class: "reg-item-eff", text: "시행 " + lw.effective_date }));
    if (foot.length) kids.push(el("div", { class: "reg-item-foot" }, foot));
    list.appendChild(el("div", { class: "reg-item" }, kids));
  });
  box.classList.remove("hidden");
}

/* ------------------------------------------------------------------ */
/* RFP 업로드 → 각 절 '작성 프롬프트' 아래 참조 표시                    */
/* ------------------------------------------------------------------ */
function setRfpStatus(text, kind) {
  const box = $("#rfp-status");
  if (!box) return;
  box.textContent = text || "";
  box.className = "rfp-status" + (kind ? " " + kind : "") + (text ? "" : " hidden");
}

// 현재 열린 절의 '작성 프롬프트' 패널 아래에 RFP 본문(state.rfp.text)을 표시/숨김.
function renderRfpRef() {
  const box = $("#rfp-ref");
  const ta = $("#rfp-ref-text");
  const meta = $("#rfp-ref-meta");
  if (!box || !ta) return;
  const rfp = state.rfp;
  if (rfp && (rfp.text || "").trim()) {
    ta.value = rfp.text;
    if (meta) meta.textContent = `— ${rfp.filename || "업로드됨"} (${rfp.chars || rfp.text.length}자)`;
    box.classList.remove("hidden");
  } else {
    ta.value = "";
    if (meta) meta.textContent = "";
    box.classList.add("hidden");
  }
}

// 프로젝트를 열 때 업로드된 RFP(본문 포함)를 불러와 state 에 담고 상태줄·참조박스 갱신.
async function refreshRfpStatus() {
  state.rfp = null;
  if (!state.pid) {
    setRfpStatus("");
    renderRfpRef();
    return;
  }
  try {
    const info = await API.getRfp(state.pid);
    const m = (info && info.meta) || {};
    if (m.filename) {
      state.rfp = { filename: m.filename, chars: m.chars || 0, text: info.text || "" };
      setRfpStatus(`RFP: ${m.filename} (${m.chars || 0}자) — 각 절 '작성 프롬프트' 아래에 표시됨`, "ok");
    } else {
      setRfpStatus("");
    }
  } catch (_) {
    setRfpStatus("");
  }
  renderRfpRef();
}

/* ------------------------------------------------------------------ */
/* 제반사항(전체 작성 공통 참고) — 좌측 입력 + ② 패널 읽기전용 미러       */
/* ------------------------------------------------------------------ */
function setOverviewStatus(text, kind) {
  const box = $("#overview-status");
  if (box) {
    box.textContent = text || "";
    box.className = "overview-status" + (kind ? " " + kind : "") + (text ? "" : " hidden");
  }
  const mbox = $("#overview-modal-status");
  if (mbox) {
    mbox.textContent = text || "";
    mbox.className = "overview-status" + (kind ? " " + kind : "");
  }
}

// 좌측 사이드바 요약줄(참여기관·연차·정부출연금 건수).
function renderOverviewSummary(data) {
  const box = $("#overview-summary");
  if (!box) return;
  data = data || {};
  const nInst = (data.institutions || []).filter((i) => (i.name || "").trim()).length;
  const nYear = (data.periods || []).filter((p) => (p.year || "").trim()).length;
  const nFund = (data.funding || []).filter((f) => (f.amount || "").trim()).length;
  const cov = data.cover || {};
  const hasCover = Object.values(cov).some((v) => (v || "").toString().trim());
  const sm = data.summary || {};
  const hasSummary = (sm.goal_final || "").trim() ||
    (sm.goals || []).some((g) => (g.text || "").trim()) ||
    (sm.contents || []).some((c) => (c.text || "").trim());
  if (!nInst && !nYear && !nFund && !hasCover && !hasSummary) {
    box.textContent = "아직 입력된 표지/요약문 내용이 없습니다.";
    box.classList.remove("filled");
    return;
  }
  const parts = [];
  if (nInst) parts.push(`참여기관 ${nInst}`);
  if (nYear) parts.push(`연차 ${nYear}`);
  if (nFund) parts.push(`정부출연금 ${nFund}건`);
  if (hasCover) parts.push("표지 ✓");
  if (hasSummary) parts.push("요약문 ✓");
  box.textContent = parts.join(" · ") || "입력됨";
  box.classList.add("filled");
}

// ② 작성 프롬프트 패널의 읽기전용 미러(#overview-ref)를 state.overview 로 채움/숨김.
function renderOverviewRef() {
  const box = $("#overview-ref");
  const ta = $("#overview-ref-text");
  const meta = $("#overview-ref-meta");
  const focus = $("#overview-ref-focus");
  if (!box || !ta) return;
  const txt = (state.overview || "").trim();
  if (txt) {
    ta.value = state.overview;
    if (meta) meta.textContent = `— ${txt.length}자 (모든 절 참고)`;
    // 이 절에서 특히 반영할 항목 안내(백엔드 overview_focus).
    const f = state.node && state.node.overview_focus;
    if (focus) {
      if (f) {
        focus.textContent = f;
        focus.classList.remove("hidden");
      } else {
        focus.textContent = "";
        focus.classList.add("hidden");
      }
    }
    box.classList.remove("hidden");
  } else {
    ta.value = "";
    if (meta) meta.textContent = "";
    if (focus) {
      focus.textContent = "";
      focus.classList.add("hidden");
    }
    box.classList.add("hidden");
  }
}

// ── 구조화 폼: 행(참여기관/정부출연금) 생성 ─────────────────────────────────
const OV_ROLES = ["주관", "공동"];
const OV_TYPES = ["비영리", "대기업", "중견기업", "중소기업", "대학", "출연연", "기타"];

function ovMakeInst(inst = {}) {
  const opt = (arr, sel) =>
    arr.map((v) => `<option${v === sel ? " selected" : ""}>${v}</option>`).join("");
  const div = el("div", { class: "ov-card", "data-inst": "1" });
  div.innerHTML =
    `<div class="ov-card-row">` +
    `<select class="ov-inst-role" title="구분">${opt(OV_ROLES, inst.role || "주관")}</select>` +
    `<select class="ov-inst-type" title="기관형태">${opt(OV_TYPES, inst.type || "비영리")}</select>` +
    `<button type="button" class="ov-del" title="이 기관 삭제">×</button>` +
    `</div>` +
    `<input class="ov-inst-name ov-input" placeholder="기관명" />` +
    `<input class="ov-inst-duty ov-input" placeholder="주요 담당 연구내용" />` +
    `<div class="ov-inst-lead">` +
    `<span class="ov-inst-lead-cap" title="주관기관 책임자는 표지의 '연구책임자'로, 공동기관 책임자는 '공동연구개발기관' 칸으로 들어갑니다">책임자</span>` +
    `<input class="ov-inst-lead-name ov-input" placeholder="성명" />` +
    `<input class="ov-inst-lead-title ov-input" placeholder="직위" />` +
    `<input class="ov-inst-lead-mobile ov-input" placeholder="휴대전화" />` +
    `<input class="ov-inst-lead-email ov-input" placeholder="전자우편" />` +
    `</div>`;
  // 사용자 값은 property 로 넣어 HTML 주입을 피한다.
  div.querySelector(".ov-inst-name").value = inst.name || "";
  div.querySelector(".ov-inst-duty").value = inst.duty || "";
  div.querySelector(".ov-inst-lead-name").value = inst.lead_name || "";
  div.querySelector(".ov-inst-lead-title").value = inst.lead_title || "";
  div.querySelector(".ov-inst-lead-mobile").value = inst.lead_mobile || "";
  div.querySelector(".ov-inst-lead-email").value = inst.lead_email || "";
  return div;
}

// 연차별 연구기간 행: 단계 + 차년도 + 기간. 라벨은 "N단계 M차년도".
function ovMakePeriod(p = {}, idx = 0) {
  const div = el("div", { class: "ov-prow", "data-period": "1" });
  div.innerHTML =
    `<input class="ov-period-stage ov-input ov-narrow3" placeholder="단계" title="단계(예: 1)" />` +
    `<input class="ov-period-year ov-input ov-narrow2" placeholder="차년도" title="차년도(예: 1차년도)" />` +
    `<input class="ov-period-range ov-input" placeholder="예: 2026.10~2027.09" />` +
    `<button type="button" class="ov-del" title="이 연차 삭제">×</button>`;
  // stage 는 로드 데이터에 없으면 빈 값(구 데이터 호환: 라벨=차년도). 새 행(+연차)은 "1" 로 만든다.
  div.querySelector(".ov-period-stage").value = p.stage || "";
  div.querySelector(".ov-period-year").value = p.year || `${idx + 1}차년도`;
  div.querySelector(".ov-period-range").value = p.range || "";
  return div;
}

// 단계+차년도 → 표시/키 라벨. 예 "1단계 1차년도"(단계 없으면 차년도만).
function ovPeriodLabel(stage, year) {
  stage = (stage || "").trim();
  year = (year || "").trim();
  if (stage && year) return `${stage}단계 ${year}`;
  return year || (stage ? `${stage}단계` : "");
}

// ── 정부출연금 매트릭스 그리드(행=참여기관 × 열=연차) ─────────────────────────
// 셀 금액은 (기관, 연차) 키로 ovFundMap 에 보존. 참여기관/연차가 바뀌면 그리드만
// 다시 그리되 기존 금액은 유지한다.
const OV_SEP = ""; // internal key separator (not shown/saved)
let ovFundMap = {};

const ovFundKey = (org, year) => `${org}${OV_SEP}${year}`;
const ovNumOnly = (s) => (String(s == null ? "" : s).replace(/[^\d]/g, ""));
const ovFmt = (n) => (n ? Number(n).toLocaleString("en-US") : "0");

// 현재 폼(DOM)의 참여기관명·연차 라벨(미저장 편집 반영, 빈 값 제외·중복 제거).
function ovCurrentInstNames() {
  const seen = new Set();
  return $$("#inst-list .ov-card .ov-inst-name")
    .map((i) => (i.value || "").trim())
    .filter((n) => n && !seen.has(n) && seen.add(n));
}
// 현재 폼의 연차 라벨(= "N단계 M차년도") 목록. 정부출연금 그리드·요약문 열 키로 쓰인다.
function ovCurrentPeriodYears() {
  const seen = new Set();
  const out = [];
  $$("#period-list .ov-prow").forEach((row) => {
    const s = (row.querySelector(".ov-period-stage") || {}).value || "";
    const y = (row.querySelector(".ov-period-year") || {}).value || "";
    const lab = ovPeriodLabel(s, y);
    if (lab && !seen.has(lab)) { seen.add(lab); out.push(lab); }
  });
  return out;
}

// 그리드 입력 셀 → ovFundMap 반영(재구성 전에 호출해 값 보존).
function ovReadGridIntoMap() {
  $$("#fund-grid-wrap .fg-cell").forEach((c) => {
    const k = c.getAttribute("data-key");
    if (k) ovFundMap[k] = ovNumOnly(c.value);
  });
}

// 행·열·총 합계 재계산.
function ovRecalcTotals() {
  const insts = ovCurrentInstNames();
  const years = ovCurrentPeriodYears();
  const colSum = years.map(() => 0);
  let grand = 0;
  insts.forEach((org, r) => {
    let row = 0;
    years.forEach((yr, c) => {
      const v = Number(ovFundMap[ovFundKey(org, yr)] || 0);
      row += v;
      colSum[c] += v;
    });
    grand += row;
    const rc = $(`#fund-grid-wrap .fg-rowtot[data-r="${r}"]`);
    if (rc) rc.textContent = ovFmt(row);
  });
  years.forEach((yr, c) => {
    const cc = $(`#fund-grid-wrap .fg-coltot[data-c="${c}"]`);
    if (cc) cc.textContent = ovFmt(colSum[c]);
  });
  const gc = $("#fund-grid-wrap .fg-grandtot");
  if (gc) gc.textContent = ovFmt(grand);
}

// 참여기관 × 연차로 그리드를 (재)구성. 값은 ovFundMap 에서 복원.
function renderFundingGrid() {
  const wrap = $("#fund-grid-wrap");
  if (!wrap) return;
  const insts = ovCurrentInstNames();
  const years = ovCurrentPeriodYears();
  wrap.innerHTML = "";
  if (!insts.length || !years.length) {
    wrap.appendChild(el("div", {
      class: "fund-grid-empty",
      text: "참여기관과 연차별 연구기간을 입력하면 정부출연금 표가 자동 생성됩니다.",
    }));
    return;
  }
  const table = el("table", { class: "fund-grid" });
  // 헤더
  const thead = el("thead");
  const htr = el("tr");
  htr.appendChild(el("th", { class: "fg-corner", text: "기관 ＼ 연차" }));
  years.forEach((yr) => htr.appendChild(el("th", { class: "fg-yh", text: yr })));
  htr.appendChild(el("th", { class: "fg-tot-h", text: "계" }));
  thead.appendChild(htr);
  table.appendChild(thead);
  // 본문
  const tbody = el("tbody");
  insts.forEach((org, r) => {
    const tr = el("tr");
    tr.appendChild(el("th", { class: "fg-orgh", text: org }));
    years.forEach((yr, c) => {
      const td = el("td");
      const inp = el("input", {
        class: "fg-cell", type: "text", inputmode: "numeric",
        "data-key": ovFundKey(org, yr), "data-r": r, "data-c": c,
        placeholder: "0",
      });
      inp.value = ovFundMap[ovFundKey(org, yr)] ? ovFmt(ovFundMap[ovFundKey(org, yr)]) : "";
      td.appendChild(inp);
      tr.appendChild(td);
    });
    tr.appendChild(el("td", { class: "fg-rowtot", "data-r": r, text: "0" }));
    tbody.appendChild(tr);
  });
  // 합계 행
  const ftr = el("tr", { class: "fg-totrow" });
  ftr.appendChild(el("th", { class: "fg-orgh", text: "계" }));
  years.forEach((_, c) => ftr.appendChild(el("td", { class: "fg-coltot", "data-c": c, text: "0" })));
  ftr.appendChild(el("td", { class: "fg-grandtot", text: "0" }));
  tbody.appendChild(ftr);
  table.appendChild(tbody);
  wrap.appendChild(table);
  ovRecalcTotals();
}

// 참여기관/연차 변경 시 그리드 재구성(기존 금액 보존).
function ovRebuildGrid() {
  ovReadGridIntoMap();
  renderFundingGrid();
}

// ── 표지(사업계획서 표지) 필드 ────────────────────────────────────────────────
// 표지 입력 필드(입력/셀렉트 공통 — .value 로 읽고/쓴다). id ↔ cover 키.
const OV_COVER_FIELDS = [
  // 문서 구분(선택)
  ["cov-proj-type", "proj_type"], ["cov-doc-type", "doc_type"],
  ["cov-security", "security"], ["cov-selection", "selection"],
  // 사업 정보
  ["cov-gov-dept", "gov_dept"], ["cov-agency", "agency"],
  ["cov-sub-biz", "sub_biz"], ["cov-detail-biz", "detail_biz"],
  ["cov-notice-no", "notice_no"], ["cov-master-no", "master_no"], ["cov-task-no", "task_no"],
  // 과제명
  ["cov-master-title-ko", "master_title_ko"], ["cov-master-title-en", "master_title_en"],
  ["cov-title-ko", "title_ko"], ["cov-title-en", "title_en"],
  // 기술분류
  ["cov-ind-class1", "ind_class1"], ["cov-ind-pct1", "ind_pct1"],
  ["cov-ind-class2", "ind_class2"], ["cov-ind-pct2", "ind_pct2"],
  ["cov-ind-class3", "ind_class3"], ["cov-ind-pct3", "ind_pct3"],
  ["cov-nat-class1", "nat_class1"], ["cov-nat-pct1", "nat_pct1"],
  ["cov-nat-class2", "nat_class2"], ["cov-nat-pct2", "nat_pct2"],
  ["cov-nat-class3", "nat_class3"], ["cov-nat-pct3", "nat_pct3"],
  // 주관기관 문서정보
  ["cov-biz-no", "biz_no"], ["cov-corp-no", "corp_no"], ["cov-address", "address"],
  // 실무책임자
  ["cov-pm-name", "pm_name"], ["cov-pm-title", "pm_title"], ["cov-pm-tel", "pm_tel"],
  ["cov-pm-mobile", "pm_mobile"], ["cov-pm-email", "pm_email"],
  ["cov-pm-researcher", "pm_researcher_no"],
];

// ── 요약문: 연차별 목표·개발내용(연차 라벨로 보존) ───────────────────────────
let ovSumGoal = {};     // year → 목표 text
let ovSumContent = {};  // year → 개발내용 text

function ovReadSummaryIntoMaps() {
  $$("#summary-year-list .ov-sum-goal").forEach((t) => {
    ovSumGoal[t.getAttribute("data-year")] = t.value || "";
  });
  $$("#summary-year-list .ov-sum-content").forEach((t) => {
    ovSumContent[t.getAttribute("data-year")] = t.value || "";
  });
}

// 현재 연차(연차별 연구기간)에 맞춰 연차별 목표·개발내용 칸을 (재)구성.
function renderSummaryYears() {
  const box = $("#summary-year-list");
  if (!box) return;
  const years = ovCurrentPeriodYears();
  box.innerHTML = "";
  if (!years.length) {
    box.appendChild(el("div", {
      class: "fund-grid-empty",
      text: "연차별 연구기간을 입력하면 연차별 목표·개발내용 칸이 생성됩니다.",
    }));
    return;
  }
  years.forEach((y) => {
    const wrap = el("div", { class: "ov-sumrow" });
    wrap.appendChild(el("div", { class: "ov-sumrow-head", text: y }));
    const g = el("textarea", {
      class: "ov-input ov-sum-goal", "data-year": y, rows: "2",
      spellcheck: "false", placeholder: `${y} 목표`,
    });
    g.value = ovSumGoal[y] || "";
    const c = el("textarea", {
      class: "ov-input ov-sum-content", "data-year": y, rows: "2",
      spellcheck: "false", placeholder: `${y} 개발내용`,
    });
    c.value = ovSumContent[y] || "";
    wrap.appendChild(g);
    wrap.appendChild(c);
    box.appendChild(wrap);
  });
}

// 연차 변경 시 연차별 목표·개발내용 칸 재구성(기존 텍스트 보존).
function ovRebuildSummary() {
  ovReadSummaryIntoMaps();
  renderSummaryYears();
}

// 구조화 데이터로 폼을 채운다(비어 있으면 참여기관·연차 각각 빈 행 1개).
function renderOverviewForm(data) {
  data = data || {};
  const instList = $("#inst-list");
  if (instList) {
    instList.innerHTML = "";
    const insts = data.institutions || [];
    (insts.length ? insts : [{}]).forEach((i) => instList.appendChild(ovMakeInst(i)));
  }
  const periodList = $("#period-list");
  if (periodList) {
    periodList.innerHTML = "";
    const periods = data.periods || [];
    (periods.length ? periods : [{}]).forEach((p, i) =>
      periodList.appendChild(ovMakePeriod(p, i)));
  }
  // 정부출연금 맵을 저장된 funding 으로 초기화 후 그리드 렌더.
  ovFundMap = {};
  (data.funding || []).forEach((f) => {
    const org = (f.org || "").trim();
    const yr = (f.year || "").trim();
    const amt = ovNumOnly(f.amount);
    if (org && yr && amt) ovFundMap[ovFundKey(org, yr)] = amt;
  });
  renderFundingGrid();
  // 표지 필드
  const cov = data.cover || {};
  OV_COVER_FIELDS.forEach(([id, key]) => {
    const eln = $("#" + id);
    if (eln) eln.value = cov[key] || "";
  });
  // 요약문: 연차별 목표·개발내용
  const sm = data.summary || {};
  ovSumGoal = {};
  ovSumContent = {};
  (sm.goals || []).forEach((g) => {
    if (g && (g.year || "").trim()) ovSumGoal[g.year] = g.text || "";
  });
  (sm.contents || []).forEach((c) => {
    if (c && (c.year || "").trim()) ovSumContent[c.year] = c.text || "";
  });
  const gf = $("#sum-goal-final");
  if (gf) gf.value = sm.goal_final || "";
  renderSummaryYears();
}

// 폼 → 구조화 데이터(빈 행은 버린다).
function collectOverviewData() {
  const instVal = (c, sel) => (c.querySelector(sel).value || "").trim();
  const institutions = $$("#inst-list .ov-card")
    .map((c) => ({
      role: c.querySelector(".ov-inst-role").value,
      name: instVal(c, ".ov-inst-name"),
      type: c.querySelector(".ov-inst-type").value,
      duty: instVal(c, ".ov-inst-duty"),
      lead_name: instVal(c, ".ov-inst-lead-name"),
      lead_title: instVal(c, ".ov-inst-lead-title"),
      lead_mobile: instVal(c, ".ov-inst-lead-mobile"),
      lead_email: instVal(c, ".ov-inst-lead-email"),
    }))
    .filter((i) => i.name || i.duty || i.lead_name);
  const periods = $$("#period-list .ov-prow")
    .map((r) => ({
      stage: (r.querySelector(".ov-period-stage").value || "").trim(),
      year: (r.querySelector(".ov-period-year").value || "").trim(),
      range: (r.querySelector(".ov-period-range").value || "").trim(),
    }))
    .filter((p) => p.stage || p.year || p.range);
  // 정부출연금: 현재 그리드 값을 맵에 반영 후, 기관×연차 조합 중 금액 있는 것만.
  ovReadGridIntoMap();
  const names = ovCurrentInstNames();
  const years = ovCurrentPeriodYears();
  const funding = [];
  names.forEach((org) => {
    years.forEach((yr) => {
      const amt = ovFundMap[ovFundKey(org, yr)];
      if (amt) funding.push({ org, year: yr, amount: amt });
    });
  });
  // 하위호환용 period(문자열): 단계·연차별 기간을 요약.
  const period = periods
    .map((p) => [ovPeriodLabel(p.stage, p.year), p.range].filter(Boolean).join(": "))
    .filter(Boolean)
    .join(" / ");
  // 표지 필드
  const cover = {};
  OV_COVER_FIELDS.forEach(([id, key]) => {
    const eln = $("#" + id);
    const v = eln ? (eln.value || "").trim() : "";
    if (v) cover[key] = v;
  });
  // 요약문: 현재 연차 기준 목표·개발내용
  ovReadSummaryIntoMaps();
  const goals = years
    .map((y) => ({ year: y, text: (ovSumGoal[y] || "").trim() }))
    .filter((g) => g.text);
  const contents = years
    .map((y) => ({ year: y, text: (ovSumContent[y] || "").trim() }))
    .filter((c) => c.text);
  const summary = {
    goal_final: (($("#sum-goal-final") || {}).value || "").trim(),
    goals,
    contents,
  };
  return {
    institutions,
    period,
    periods,
    funding,
    goal: "",
    cover,
    summary,
  };
}

// 프로젝트를 열 때 저장된 제반사항을 불러와 폼·미러를 채운다.
async function refreshOverview() {
  state.overview = "";
  state.overviewData = null;
  if (!state.pid) {
    renderOverviewForm({});
    setOverviewStatus("");
    renderOverviewRef();
    return;
  }
  try {
    const info = await API.getOverview(state.pid);
    state.overviewData = (info && info.data) || {};
    state.overview = (info && info.text) || "";
    renderOverviewForm(state.overviewData);
    setOverviewStatus(state.overview.trim() ? `저장됨 (${state.overview.length}자)` : "", "ok");
  } catch (_) {
    renderOverviewForm({});
    setOverviewStatus("");
  }
  renderOverviewSummary(state.overviewData);
  renderOverviewRef();
}

// 제반사항 모달 열기/닫기.
function openOverviewModal() {
  const m = $("#overview-modal");
  if (!m) return;
  if (!state.pid) {
    toast("프로젝트를 먼저 열어 주세요.", "err");
    return;
  }
  // 현재 저장 데이터로 폼을 다시 채우고 연다.
  renderOverviewForm(state.overviewData || {});
  m.classList.remove("hidden");
  m.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}
function closeOverviewModal(save = true) {
  const m = $("#overview-modal");
  if (!m || m.classList.contains("hidden")) return;
  if (save) saveOverview({ silent: true });
  m.classList.add("hidden");
  m.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

// {cover키: 값} 을 해당 입력칸에 채운다(빈 값 무시). 채운 개수 반환.
function ovSetCoverFields(fields) {
  const byKey = Object.fromEntries(OV_COVER_FIELDS.map(([id, key]) => [key, id]));
  let n = 0;
  Object.entries(fields || {}).forEach(([key, val]) => {
    const id = byKey[key];
    if (!id) return;
    const eln = $("#" + id);
    if (eln && (val || "").toString().trim()) {
      eln.value = val;
      n++;
    }
  });
  return n;
}

// RFP 원문에서 표지 상단 항목(기관·사업명·공고번호) 추출해 채움.
async function coverAutofillFromRfp() {
  if (!state.pid) { toast("프로젝트를 먼저 열어 주세요.", "err"); return; }
  const btn = $("#btn-cover-rfp");
  setOverviewStatus("RFP에서 표지 항목 추출 중…", "busy");
  if (btn) btn.disabled = true;
  try {
    const res = await API.coverAutofillRfp(state.pid);
    const n = ovSetCoverFields(res && res.fields);
    if (n) {
      await saveOverview({ silent: true });
      toast(`RFP에서 ${n}개 항목을 채웠습니다.`, "ok");
      setOverviewStatus(`RFP 자동채움 ${n}개`, "ok");
    } else {
      toast("RFP에서 채울 항목을 찾지 못했습니다.", "err");
      setOverviewStatus("RFP 자동채움: 해당 항목 없음", "");
    }
  } catch (e) {
    toast("RFP 자동채움 실패: " + e.message, "err");
    setOverviewStatus("RFP 자동채움 실패: " + e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 국문 과제명 입력 후 이탈 시, 영문칸이 비어 있으면 자동 번역해 채운다.
let ovTranslating = {};  // 중복 호출 방지
async function maybeTranslateTitle(koId, enId) {
  if (!state.pid) return;
  const ko = $("#" + koId);
  const en = $("#" + enId);
  if (!ko || !en) return;
  const koVal = (ko.value || "").trim();
  if (!koVal) return;
  if ((en.value || "").trim()) return;   // 사용자가 영문을 이미 넣었으면 건드리지 않음
  if (ovTranslating[enId] === koVal) return;
  ovTranslating[enId] = koVal;
  setOverviewStatus("영문 과제명 번역 중…", "busy");
  try {
    const res = await API.coverTranslate(state.pid, koVal);
    const enVal = ((res && res.en) || "").trim();
    if (enVal && !(en.value || "").trim()) {
      en.value = enVal;
      await saveOverview({ silent: true });
      setOverviewStatus("영문 과제명 자동 완성", "ok");
    } else {
      setOverviewStatus("", "");
    }
  } catch (e) {
    setOverviewStatus("영문 번역 실패: " + e.message, "err");
  } finally {
    delete ovTranslating[enId];
  }
}

// 8.1 지원·부담계획 표를 현재 단계 수에 맞춰 재구성(구조편집, 수십 초) 후 채운다.
async function budgetSyncStages() {
  if (!state.pid) { toast("프로젝트를 먼저 열어 주세요.", "err"); return; }
  const btn = $("#btn-budget-sync");
  // 먼저 현재 내용 저장(문서 반영 포함) 후 구조 재구성.
  await saveOverview({ silent: true });
  setOverviewStatus("8.1 표 단계 구조 재구성 중… (수십 초 소요, 표 구조 변경)", "busy");
  if (btn) btn.disabled = true;
  try {
    const res = await API.budgetSyncStages(state.pid);
    const rb = res && res.rebuilt;
    if (rb && rb.changed) {
      toast(`8.1 표를 ${rb.stages}단계 구조로 재구성하고 채웠습니다.`, "ok");
      setOverviewStatus(`8.1 표 ${rb.stages}단계 반영 완료`, "ok");
    } else {
      toast("8.1 표가 이미 현재 단계 구조와 일치합니다(값은 갱신).", "ok");
      setOverviewStatus("8.1 표 단계 일치 — 값 갱신", "ok");
    }
  } catch (e) {
    toast("8.1 표 재구성 실패: " + e.message, "err");
    setOverviewStatus("8.1 표 재구성 실패: " + e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 8장 비목별 세부 사용계획 표를 참여기관 수만큼 복제하고 연구개발비 총액을 채운다(구조편집).
async function budgetSyncDetail() {
  if (!state.pid) { toast("프로젝트를 먼저 열어 주세요.", "err"); return; }
  const btn = $("#btn-detail-sync");
  await saveOverview({ silent: true });
  setOverviewStatus("8장 세부표 구조 재구성 중… (수십 초 소요, 표 구조 변경)", "busy");
  if (btn) btn.disabled = true;
  try {
    const res = await API.budgetSyncDetail(state.pid);
    const rb = res && res.rebuilt;
    if (rb && rb.changed) {
      toast(`8장 세부표를 ${rb.institutions}개(기관 수)로 맞추고 연구개발비 총액을 채웠습니다.`, "ok");
      setOverviewStatus(`8장 세부표 ${rb.institutions}개 반영 완료`, "ok");
    } else {
      toast("8장 세부표 개수가 이미 참여기관 수와 일치합니다(값은 갱신).", "ok");
      setOverviewStatus("8장 세부표 일치 — 값 갱신", "ok");
    }
  } catch (e) {
    toast("8장 세부표 재구성 실패: " + e.message, "err");
    setOverviewStatus("8장 세부표 재구성 실패: " + e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 요약문 '연구개발 목표 및 내용'(최종목표+연차별 목표·개발내용)을 AI 가 제안해 빈 칸을 채움.
async function summarySuggestAi() {
  if (!state.pid) { toast("프로젝트를 먼저 열어 주세요.", "err"); return; }
  const btn = $("#btn-summary-suggest");
  setOverviewStatus("연구개발 목표·내용 제안 중… (십여 초)", "busy");
  if (btn) btn.disabled = true;
  try {
    const res = await API.summarySuggest(state.pid);
    let n = 0;
    const gf = $("#sum-goal-final");
    if (gf && ((res && res.goal_final) || "").trim() && !(gf.value || "").trim()) {
      gf.value = res.goal_final.trim();
      n++;
    }
    // 현재 연차별 텍스트를 맵에 반영 후, 빈 연차에만 제안을 채운다.
    ovReadSummaryIntoMaps();
    const years = new Set(ovCurrentPeriodYears());
    ((res && res.goals) || []).forEach((g) => {
      const y = (g.year || "").trim();
      const t = (g.text || "").trim();
      if (y && t && years.has(y) && !(ovSumGoal[y] || "").trim()) { ovSumGoal[y] = t; n++; }
    });
    ((res && res.contents) || []).forEach((c) => {
      const y = (c.year || "").trim();
      const t = (c.text || "").trim();
      if (y && t && years.has(y) && !(ovSumContent[y] || "").trim()) { ovSumContent[y] = t; n++; }
    });
    renderSummaryYears();
    if (n) {
      await saveOverview({ silent: true });
      toast(`목표·내용 ${n}개 항목을 제안했습니다. 수정 가능합니다.`, "ok");
      setOverviewStatus(`AI 목표·내용 제안 ${n}개`, "ok");
    } else {
      toast("이미 채워져 있거나 제안 결과가 없습니다.", "err");
      setOverviewStatus("AI 제안: 추가 항목 없음", "");
    }
  } catch (e) {
    toast("목표·내용 제안 실패: " + e.message, "err");
    setOverviewStatus("AI 제안 실패: " + e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 과제 내용·RFP 로 산업기술·국가과학기술 분류를 AI 가 조사·제안해 채움.
async function coverClassifyAi() {
  if (!state.pid) { toast("프로젝트를 먼저 열어 주세요.", "err"); return; }
  const btn = $("#btn-cover-classify");
  setOverviewStatus("기술분류 제안 중… (십여 초)", "busy");
  if (btn) btn.disabled = true;
  try {
    const res = await API.coverClassify(state.pid);
    const n = ovSetCoverFields(res && res.fields);
    if (n) {
      await saveOverview({ silent: true });
      toast(`기술분류 ${n}개 항목을 제안·채웠습니다.`, "ok");
      setOverviewStatus(`AI 분류 제안 ${n}개`, "ok");
    } else {
      toast("기술분류 제안을 받지 못했습니다.", "err");
      setOverviewStatus("AI 분류 제안: 결과 없음", "");
    }
  } catch (e) {
    toast("AI 분류 제안 실패: " + e.message, "err");
    setOverviewStatus("AI 분류 제안 실패: " + e.message, "err");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 폼 내용을 저장하고 미러를 갱신. (버튼/자동저장 공용)
async function saveOverview(opts = {}) {
  if (!state.pid) {
    if (!opts.silent) setOverviewStatus("프로젝트를 먼저 열어 주세요.", "err");
    return;
  }
  const data = collectOverviewData();
  // 자동저장은 바뀐 게 없으면 조용히 건너뛴다.
  if (opts.silent && JSON.stringify(data) === JSON.stringify(state.overviewData || {})) return;
  try {
    setOverviewStatus(opts.silent ? "저장 중…" : "저장·문서 반영 중…", "busy");
    // 명시적 저장(저장 버튼)이면 저장 직후 문서 표(표지·요약문·편성도·연구비)에 즉시 반영.
    const res = await API.saveOverview(state.pid, data, !opts.silent);
    state.overviewData = (res && res.data) || data;
    state.overview = (res && res.text) || "";
    const n = (state.overview || "").length;
    const cells = res && res.applied && res.applied.cells_written;
    setOverviewStatus(
      n ? `저장됨 (${n}자)` + (cells ? ` · 문서 표 ${cells}칸 반영` : "") : "저장됨 (빈 값)", "ok");
    if (!opts.silent) {
      toast(cells
        ? `저장 완료 — 문서 표에 ${cells}칸 반영됨(빌드 시 최종 출력).`
        : "표지/요약문 저장 완료.", "ok");
    }
    renderOverviewSummary(state.overviewData);
    renderOverviewRef();
  } catch (e) {
    const stale = /method not allowed|not found|\b40[45]\b/i.test(e.message || "");
    const hint = stale ? " — 서버(uvicorn)를 재시작해야 반영됩니다." : "";
    setOverviewStatus("저장 실패: " + e.message + hint, "err");
    if (!opts.silent) toast("표지/요약문 저장 실패: " + e.message + hint, "err");
  }
}

let rfpTimer = null;
function startElapsed(prefix) {
  const t0 = Date.now();
  const tick = () => setRfpStatus(`${prefix} (${Math.round((Date.now() - t0) / 1000)}초)`, "busy");
  tick();
  if (rfpTimer) clearInterval(rfpTimer);
  rfpTimer = setInterval(tick, 1000);
}
function stopElapsed() {
  if (rfpTimer) clearInterval(rfpTimer);
  rfpTimer = null;
}

async function onRfpSelected(file) {
  if (!file) return;
  // 프로젝트가 없으면 기본 문서로 자동 생성(절 트리가 필요).
  if (!state.pid) {
    setRfpStatus("프로젝트가 없어 기본 문서로 새로 생성 중…", "busy");
    try {
      const res = await API.createProject();
      const pid = res.pid || res.id;
      await loadProjects(pid);
      $("#project-select").value = pid;
      await openProject(pid);
    } catch (e) {
      setRfpStatus("프로젝트 생성 실패: " + e.message, "err");
      return;
    }
  }

  const label = document.querySelector(".rfp-btn");
  const fileInput = $("#rfp-file");
  if (label) label.classList.add("disabled");
  if (fileInput) fileInput.disabled = true;

  try {
    // 업로드 + 텍스트 추출 → 각 절 '작성 프롬프트' 아래에 참조로 표시.
    startElapsed(`RFP 업로드·분석 중… (${file.name})`);
    const fd = new FormData();
    fd.append("file", file);
    const up = await API.uploadRfp(state.pid, fd);
    stopElapsed();
    state.rfp = { filename: up.filename || file.name, chars: up.chars || 0, text: up.text || "" };
    setRfpStatus(`RFP: ${state.rfp.filename} (${up.chars}자) — 각 절 '작성 프롬프트' 아래에 표시됨`, "ok");
    toast(`RFP 분석 완료: ${up.chars}자 추출. 각 절 '작성 프롬프트' 아래에 표시됩니다.`, "ok");
    renderRfpRef();
    // RFP 에서 표지 항목이 자동 채워졌으면 표지/요약문 입력을 새로고침해 반영.
    const cf = (up && up.cover_filled) || [];
    if (cf.length) {
      await refreshOverview();
      toast(`RFP에서 표지 항목 ${cf.length}개를 자동으로 채웠습니다.`, "ok");
    }
  } catch (e) {
    stopElapsed();
    // 405/Method Not Allowed = 실행 중인 서버에 RFP 라우트가 없음(옛 코드) → 재시작 안내
    const stale = /method not allowed|\b405\b/i.test(e.message || "");
    const hint = stale ? " — 서버(uvicorn)를 재시작해야 RFP 기능이 반영됩니다." : "";
    setRfpStatus("RFP 업로드 실패: " + e.message + hint, "err");
    toast("RFP 업로드 실패: " + e.message + hint, "err");
  } finally {
    if (label) label.classList.remove("disabled");
    if (fileInput) {
      fileInput.disabled = false;
      fileInput.value = "";
    }
  }
}

/* ------------------------------------------------------------------ */
/* 빌드                                                                */
/* ------------------------------------------------------------------ */
async function doBuild() {
  if (!state.pid) {
    toast("먼저 프로젝트를 선택하세요.", "err");
    return;
  }
  const btn = $("#btn-build");
  btn.disabled = true;
  toast("hwpx 빌드 중… (YAML→hwpx 복원 + PDF)");
  try {
    const res = await API.build(state.pid);
    const dl = res.download || API.downloadUrl(state.pid);
    const pv = res.preview || API.previewUrl(state.pid);
    const bust = "?t=" + Date.now();
    $("#link-download").href = dl + bust;
    $("#link-preview").href = pv + bust;
    $("#build-links").classList.remove("hidden");
    const flushed = res && res.flushed ? ` · 입력 ${res.flushed}개 절 자동 반영` : "";
    toast("빌드 완료 — 다운로드/미리보기 가능" + flushed, "ok");
  } catch (e) {
    toast("빌드 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* 이벤트 바인딩 / 부팅                                                */
/* ------------------------------------------------------------------ */
/* ------------------------------------------------------------------ */
/* 표(엑셀형 그리드) 입력 — 8장 등 표 중심 절                          */
/* ------------------------------------------------------------------ */
// dirty: cellKey(anchorPath) → {paths, text(계산값)} · formulas: anchorPath → "=..."
const tablesState = { data: null, dirty: new Map(), formulas: new Map(), sel: null, busy: false };

async function loadTables(nid) {
  const wrap = $("#tables-editor");
  if (!nid || !state.pid) { wrap.hidden = true; return; }   // null nid 조기 차단(경쟁 방지)
  tablesState.data = null;
  tablesState.dirty.clear();
  tablesState.formulas.clear();
  tablesState.sel = null;
  $("#tables-grids").innerHTML = "";
  try {
    const [data, fres] = await Promise.all([
      API.getTables(state.pid, nid),
      API.getFormulas(state.pid, nid).catch(() => ({ formulas: {} })),
    ]);
    if (state.nid !== nid) return;                          // 스테일 응답 무시(다른 절로 이동)
    if (!data.has_tables) { wrap.hidden = true; return; }
    tablesState.data = data;
    Object.entries(fres.formulas || {}).forEach(([k, v]) => tablesState.formulas.set(k, v));
    wrap.hidden = false;
    $("#btn-tables-xlsx").href = API.tablesXlsxUrl(state.pid, nid);
    renderTables(data);
  } catch (_) {
    if (state.nid === nid) wrap.hidden = true;
  }
}

/* ---- 수식 엔진 (엑셀식: =SUM(A1:A5), =A1+B2*2) ---- */
const colToIdx = (s) => { let n = 0; for (const ch of s.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64); return n - 1; };
const numOf = (v) => { const m = String(v == null ? "" : v).replace(/[,\s₩%]/g, "").match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : 0; };

function tablePosIndex(t) {
  // "r,c"(병합 커버 포함) → anchor cell
  const pos = new Map();
  t.cells.forEach((c) => {
    for (let dr = 0; dr < (c.rowspan || 1); dr++)
      for (let dc = 0; dc < (c.colspan || 1); dc++)
        pos.set((c.row + dr) + "," + (c.col + dc), c);
  });
  return pos;
}

function computeTable(t) {
  // 반환: anchorPath → 표시값(수식이면 계산값). 여러 패스로 의존 수식 해소.
  const pos = tablePosIndex(t);
  const val = new Map(); // anchorPath → 표시문자열
  const anchorAt = (r, c) => pos.get(r + "," + c);
  t.cells.forEach((c) => {
    const ap = c.paths[0];
    const f = tablesState.formulas.get(ap);
    val.set(ap, f ? "" : (c.text || ""));
  });
  const cellVal = (r, c) => { const a = anchorAt(r, c); return a ? val.get(a.paths[0]) : ""; };
  const rangeCells = (rng) => {
    const m = rng.match(/([A-Z]+)(\d+):([A-Z]+)(\d+)/i);
    if (!m) { const s = rng.match(/([A-Z]+)(\d+)/i); return s ? [[+s[2] - 1, colToIdx(s[1])]] : []; }
    const r1 = +m[2] - 1, c1 = colToIdx(m[1]), r2 = +m[4] - 1, c2 = colToIdx(m[3]);
    const out = [], seen = new Set();
    for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++)
      for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) {
        const a = anchorAt(r, c); if (!a) continue;
        if (seen.has(a.paths[0])) continue; seen.add(a.paths[0]); out.push([r, c]);
      }
    return out;
  };
  const evalF = (expr) => {
    let e = expr.slice(1);
    e = e.replace(/SUM\(([^)]*)\)/gi, (_m, rng) => rangeCells(rng).reduce((s, [r, c]) => s + numOf(cellVal(r, c)), 0));
    e = e.replace(/AVERAGE\(([^)]*)\)/gi, (_m, rng) => { const cs = rangeCells(rng); return cs.length ? cs.reduce((s, [r, c]) => s + numOf(cellVal(r, c)), 0) / cs.length : 0; });
    e = e.replace(/([A-Z]+)(\d+)/g, (_m, col, row) => numOf(cellVal(+row - 1, colToIdx(col))));
    if (!/^[-+*/().\d\s.eE]*$/.test(e)) return "#ERR";
    try { const v = Function('"use strict";return (' + e + ")")(); return Number.isFinite(v) ? String(v) : "#ERR"; } catch (_) { return "#ERR"; }
  };
  for (let pass = 0; pass < 6; pass++) {
    let changed = false;
    t.cells.forEach((c) => {
      const ap = c.paths[0], f = tablesState.formulas.get(ap);
      if (!f) return;
      const nv = evalF(f);
      if (nv !== val.get(ap)) { val.set(ap, nv); changed = true; }
    });
    if (!changed) break;
  }
  return val;
}

function recalc(ti) {
  const t = tablesState.data.tables[ti];
  const val = computeTable(t);
  // 수식 셀 표시 갱신 + dirty(계산값) 반영
  $$(`#tables-grids td[data-ti="${ti}"]`).forEach((td) => {
    const ap = td.dataset.anchor;
    if (tablesState.formulas.has(ap) && document.activeElement !== td) {
      const v = val.get(ap) || "";
      td.textContent = v;
      td.classList.add("has-formula");
      markDirty(td, v);
    } else if (!tablesState.formulas.has(ap)) {
      td.classList.remove("has-formula");
    }
  });
}

function markDirty(td, computedText) {
  const orig = td.dataset.orig || "";
  const val = computedText != null ? computedText : td.innerText.replace(/\n$/, "");
  const k = td.dataset.anchor;
  const hasF = tablesState.formulas.has(k);
  if (!hasF && val === orig) tablesState.dirty.delete(k);
  else tablesState.dirty.set(k, { paths: JSON.parse(td.dataset.paths), text: val });
  const n = tablesState.dirty.size;
  $("#btn-tables-save").textContent = n ? `표 저장 (${n})` : "표 저장";
}

function renderTables(data) {
  const host = $("#tables-grids");
  host.innerHTML = "";
  data.tables.forEach((t, ti) => {
    // 표별 툴바(행/열 추가·삭제)
    const bar = el("div", { class: "grid-cap" }, [
      el("span", { text: `표 ${ti + 1} · ${t.rows}행 × ${t.cols}열 · 셀에 =SUM(A1:A5) 등 수식 가능` }),
    ]);
    const ops = el("span", { class: "grid-ops" });
    const mkbtn = (label, op) => {
      const b = el("button", { class: "btn btn-secondary grid-op", text: label });
      b.addEventListener("click", () => structOp(op, ti));
      return b;
    };
    ops.append(mkbtn("＋행", "add_row"), mkbtn("－행", "del_row"), mkbtn("＋열", "add_col"), mkbtn("－열", "del_col"));
    bar.appendChild(ops);
    host.appendChild(bar);

    const cmap = new Map();
    t.cells.forEach((c) => cmap.set(c.row + "," + c.col, c));
    const covered = new Set();
    t.cells.forEach((c) => {
      for (let dr = 0; dr < (c.rowspan || 1); dr++)
        for (let dc = 0; dc < (c.colspan || 1); dc++)
          if (dr || dc) covered.add(c.row + dr + "," + (c.col + dc));
    });
    const table = el("table", { class: "xls-grid" });
    for (let r = 0; r < t.rows; r++) {
      const tr = el("tr");
      for (let c = 0; c < t.cols; c++) {
        if (covered.has(r + "," + c)) continue;
        const cell = cmap.get(r + "," + c);
        const td = el("td", { class: r === 0 ? "hd" : "" });
        if (cell) {
          if ((cell.rowspan || 1) > 1) td.rowSpan = cell.rowspan;
          if ((cell.colspan || 1) > 1) td.colSpan = cell.colspan;
          const ap = cell.paths[0];
          td.contentEditable = "true";
          td.dataset.ti = ti; td.dataset.row = cell.row; td.dataset.col = cell.col;
          td.dataset.anchor = ap; td.dataset.paths = JSON.stringify(cell.paths);
          td.dataset.orig = cell.text || "";
          td.textContent = cell.text || "";
          if (tablesState.formulas.has(ap)) td.classList.add("has-formula");
          td.addEventListener("focus", () => {
            tablesState.sel = { ti, row: cell.row, col: cell.col };
            const f = tablesState.formulas.get(ap);
            if (f) td.textContent = f;                       // 편집 시 수식 노출
          });
          td.addEventListener("blur", () => {
            const val = td.innerText.replace(/\n$/, "").trim();
            if (val.startsWith("=")) tablesState.formulas.set(ap, val);
            else { tablesState.formulas.delete(ap); td.dataset.orig = td.dataset.orig; }
            if (!val.startsWith("=")) markDirty(td, val);
            recalc(ti);                                      // 의존 수식 갱신
          });
          td.addEventListener("keydown", gridKeydown);
        } else {
          td.className += " empty";
        }
        tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    const scroll = el("div", { class: "grid-scroll" });
    scroll.appendChild(table);
    host.appendChild(scroll);
    recalc(ti);   // 초기 수식 계산
  });
  $("#btn-tables-save").textContent = tablesState.dirty.size ? `표 저장 (${tablesState.dirty.size})` : "표 저장";
}

function gridKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const td = e.target, tr = td.parentElement;
    const idx = Array.from(tr.children).indexOf(td);
    const nextRow = tr.nextElementSibling;
    if (nextRow && nextRow.children[idx]) nextRow.children[idx].focus();
  }
}

async function structOp(op, ti) {
  if (tablesState.busy) return;
  const sel = tablesState.sel;
  const t = tablesState.data.tables[ti];
  const isRow = op.endsWith("row");
  const idx = sel && sel.ti === ti ? (isRow ? sel.row : sel.col) : (isRow ? t.rows - 1 : t.cols - 1);
  const what = { add_row: "행 추가", del_row: "행 삭제", add_col: "열 추가", del_col: "열 삭제" }[op];
  if (!confirm(`표 ${ti + 1}: ${isRow ? idx + 1 + "행" : idx + 1 + "열"} 기준 ${what}?\n(문서 구조를 바꿔 다소 시간이 걸립니다)`)) return;
  tablesState.busy = true;
  toast(`${what} 처리 중… (구조 변경, 수십 초 걸릴 수 있음)`);
  try {
    // 변경 전 현재 편집분 저장(구조편집은 yaml 재추출로 좌표가 바뀌므로)
    if (tablesState.dirty.size) await saveTables(true);
    await API.tableStructure(state.pid, state.nid, op, t.path, idx);
    await loadTables(state.nid);
    toast(`${what} 완료.`, "ok");
  } catch (e) {
    toast(`${what} 실패: ${e.message}`, "err");
  } finally {
    tablesState.busy = false;
  }
}

async function saveTables(silent) {
  if (!state.pid || !state.nid) return;
  const cells = Array.from(tablesState.dirty.values());
  const formulas = Object.fromEntries(tablesState.formulas);
  try {
    if (cells.length) await API.putTables(state.pid, state.nid, cells);
    await API.putFormulas(state.pid, state.nid, formulas);
    tablesState.dirty.clear();
    $("#btn-tables-save").textContent = "표 저장";
    if (!silent) toast(`표 저장됨 (${cells.length}셀). [hwpx 빌드]로 표에 반영됩니다.`, "ok");
  } catch (e) {
    if (!silent) toast("표 저장 실패: " + e.message, "err");
    else throw e;
  }
}

async function importTablesXlsx(file) {
  if (!state.pid || !state.nid || !file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const st = await API.importTablesXlsx(state.pid, state.nid, fd);
    toast(`엑셀 가져오기 완료 (${st.updated}셀). 다시 로드합니다.`, "ok");
    await loadTables(state.nid);
  } catch (e) {
    toast("엑셀 가져오기 실패: " + e.message, "err");
  }
}

function bindEvents() {
  $("#btn-new-project").addEventListener("click", createProject);
  $("#btn-del-project").addEventListener("click", deleteProject);
  $("#project-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) createProject();
  });
  $("#project-select").addEventListener("change", (e) => {
    updateDelButton();
    openProject(e.target.value);
  });
  $("#btn-tree-refresh").addEventListener("click", () => state.pid && loadTree());
  $("#btn-build").addEventListener("click", doBuild);

  $("#rfp-file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) onRfpSelected(f);
  });

  // 제반사항 모달 열기/닫기
  $("#btn-overview-open").addEventListener("click", openOverviewModal);
  $("#btn-overview-close").addEventListener("click", () => closeOverviewModal(true));
  $("#btn-overview-cancel").addEventListener("click", () => closeOverviewModal(true));
  $("#btn-overview-save").addEventListener("click", () => saveOverview());
  $("#btn-cover-rfp").addEventListener("click", coverAutofillFromRfp);
  $("#btn-cover-classify").addEventListener("click", coverClassifyAi);
  $("#btn-summary-suggest").addEventListener("click", summarySuggestAi);
  $("#btn-budget-sync").addEventListener("click", budgetSyncStages);
  $("#btn-detail-sync").addEventListener("click", budgetSyncDetail);
  // 배경(오버레이) 클릭으로 닫기
  $("#overview-modal").addEventListener("mousedown", (e) => {
    if (e.target.id === "overview-modal") closeOverviewModal(true);
  });
  // ESC 로 닫기
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeOverviewModal(true);
  });
  // 행 추가
  $("#btn-inst-add").addEventListener("click", () => {
    $("#inst-list").appendChild(ovMakeInst());
  });
  $("#btn-period-add").addEventListener("click", () => {
    const n = $$("#period-list .ov-prow").length;
    $("#period-list").appendChild(ovMakePeriod({ stage: "1" }, n));
    ovRebuildGrid();
    ovRebuildSummary();
  });
  // 모달 내 상호작용(위임): 행 삭제 / 그리드 재구성 / 자동 저장
  const modalBody = $("#overview-modal .modal-body");
  // 행 삭제(참여기관/연차) → 그리드 갱신 + 자동 저장
  modalBody.addEventListener("click", (e) => {
    const del = e.target.closest(".ov-del");
    if (!del) return;
    const row = del.closest(".ov-card, .ov-prow");
    if (row) {
      const wasPeriod = row.classList.contains("ov-prow");
      row.remove();
      ovRebuildGrid();
      if (wasPeriod) ovRebuildSummary();
      saveOverview({ silent: true });
    }
  });
  // 금액 셀 입력 중에는 합계만 즉시 갱신.
  modalBody.addEventListener("input", (e) => {
    if (e.target.classList.contains("fg-cell")) {
      const c = e.target;
      ovFundMap[c.getAttribute("data-key")] = ovNumOnly(c.value);
      ovRecalcTotals();
    }
  });
  // 참여기관명·연차 라벨을 확정(포커스 이탈)하면 그리드·연차별 요약칸을 재구성.
  modalBody.addEventListener("change", (e) => {
    if (e.target.closest(".ov-inst-name, .ov-period-year, .ov-period-stage")) {
      ovRebuildGrid();
    }
    if (e.target.closest(".ov-period-year, .ov-period-stage")) {
      ovRebuildSummary();
    }
  });
  // 그리드 셀은 포커스 빠질 때 콤마 서식으로 정리.
  modalBody.addEventListener("focusout", (e) => {
    if (e.target.classList.contains("fg-cell")) {
      const v = ovNumOnly(e.target.value);
      e.target.value = v ? ovFmt(v) : "";
      saveOverview({ silent: true });
    } else if (e.target.closest(".ov-input, .ov-inst-role, .ov-inst-type")) {
      saveOverview({ silent: true });
      // 국문 과제명 이탈 시 영문 자동 번역(영문칸 비었을 때만).
      if (e.target.id === "cov-master-title-ko") {
        maybeTranslateTitle("cov-master-title-ko", "cov-master-title-en");
      } else if (e.target.id === "cov-title-ko") {
        maybeTranslateTitle("cov-title-ko", "cov-title-en");
      }
    }
  });

  $$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.getAttribute("data-tab"))));

  $("#btn-template-save").addEventListener("click", saveTemplate);
  $("#btn-template-generate").addEventListener("click", generateTemplate);
  $("#btn-prompts-save").addEventListener("click", savePrompts);
  $("#btn-preset-load").addEventListener("click", loadPreset);
  $("#btn-tables-save").addEventListener("click", saveTables);
  $("#tables-xlsx-file").addEventListener("change", (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) importTablesXlsx(f);
    e.target.value = "";
  });
  $("#btn-input-save").addEventListener("click", saveInput);
  $("#btn-convert").addEventListener("click", doConvert);
  $("#btn-convert-hwpx").addEventListener("click", downloadSectionHwpx);
  $("#btn-reg-pdf").addEventListener("click", openRegulationsPdf);

  $("#btn-chat-send").addEventListener("click", sendChat);
  $("#btn-chat-clear").addEventListener("click", clearChat);
  $("#chat-input").addEventListener("keydown", (ev) => {
    // Enter 전송 / Shift+Enter 줄바꿈 (IME 조합 중에는 무시)
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      sendChat();
    }
  });
}

async function loadRegStatus() {
  // 절별 법령·규정 데이터셋 기준일을 📕 버튼 툴팁에 반영
  try {
    const s = await api("/api/reg-status");
    const btn = $("#btn-reg-pdf");
    if (btn && s && s.as_of) {
      btn.title =
        `이 절 적용 법령·규정 + 작성요령을 PDF 로 엽니다.\n` +
        `법령 기준일 ${s.as_of} · 공통 ${s.common_count}건 / 절별 ${s.law_count}건 (제출 전 최신 공고·협약과 대조 필요)`;
    }
  } catch (_) { /* 데이터셋 없어도 무시 */ }
}

async function boot() {
  bindEvents();
  renderOverviewForm({}); // 모달 폼 골격(빈 행) 초기화
  renderOverviewSummary({});
  loadRegStatus();
  await loadProjects();
  // 프로젝트가 하나면 자동 선택
  const sel = $("#project-select");
  if (sel.options.length === 2) {
    sel.selectedIndex = 1;
    await openProject(sel.value);
  }
}

document.addEventListener("DOMContentLoaded", boot);
