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
  filled: new Set(), // RFP 자동작성으로 채워진 절 nid
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
  putPrompts: (pid, nid, style, structure) =>
    api(`/api/projects/${pid}/nodes/${nid}/prompts`, jsonBody({ style, structure })),
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
  getRfp: (pid) => api(`/api/projects/${pid}/rfp`),
  uploadRfp: (pid, formData) => api(`/api/projects/${pid}/rfp`, { method: "POST", body: formData }),
  autofillRfp: (pid, sections, apply) =>
    api(`/api/projects/${pid}/rfp/autofill`, postJson({ sections: sections || null, apply: !!apply })),
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
  state.filled = new Set();
  $("#btn-build").disabled = false;
  $("#build-links").classList.add("hidden");
  updateDelButton();
  showNodeEmpty();
  await loadTree();
  refreshRfpStatus();
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
      state.filled = new Set();
      $("#btn-build").disabled = true;
      $("#build-links").classList.add("hidden");
      showNodeEmpty();
      $("#tree").innerHTML = "";
      $("#tree").appendChild(el("p", { class: "placeholder", text: "프로젝트를 선택하거나 새로 만드세요." }));
      setRfpStatus("");
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
  const isFilled = state.filled.has(node.id);
  const kids = [
    el("span", { class: "tree-num", text: node.label }),
    el("span", { class: "tree-title-txt", text: node.title || "" }),
  ];
  if (isFilled) kids.push(el("span", { class: "tree-badge", text: "✓ 자동작성", title: "RFP 기반 자동작성됨" }));
  const leaf = el(
    "div",
    {
      class: "tree-leaf" + (isChapter ? " chapter-leaf" : "") + (isFilled ? " filled" : ""),
      "data-nid": node.id,
      onclick: () => selectNode(node.id),
    },
    kids
  );
  return leaf;
}

// 특정 절 leaf 에 자동작성 배지를 즉시 부여(트리 재렌더 없이).
function markLeafFilled(nid) {
  state.filled.add(nid);
  const leaf = document.querySelector(`.tree-leaf[data-nid="${nid}"]`);
  if (leaf && !leaf.classList.contains("filled")) {
    leaf.classList.add("filled");
    leaf.appendChild(el("span", { class: "tree-badge", text: "✓ 자동작성", title: "RFP 기반 자동작성됨" }));
  }
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
    toast("노드 로드 실패: " + e.message, "err");
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

  // 2) 프롬프트
  const p = node.prompts || {};
  $("#prompt-style").value = p.style || "";
  $("#prompt-structure").value = p.structure || "";
  // guidelines 프리필: style 비어있으면 ※ 가이드로 채움
  if (!p.style && guides.length) {
    $("#prompt-structure").value = p.structure || guides.join("\n");
  }
  // 참조 문체 프리셋 출처(rnd-write-*) 표시
  const preset = node.preset || {};
  const skill = preset.skill || p.preset_skill || "";
  const origin = $("#preset-origin");
  if (origin) {
    origin.textContent = skill ? `참조 스킬: ${skill}` : "참조 프리셋 없음";
  }

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
    $("#prompt-style").value = preset.style || "";
    $("#prompt-structure").value = preset.structure || "";
    const origin = $("#preset-origin");
    if (origin) origin.textContent = preset.skill ? `참조 스킬: ${preset.skill}` : "참조 프리셋 없음";
    toast("참조 문체 프리셋을 불러왔습니다(저장 눌러 반영)", "ok");
  } catch (e) {
    toast("프리셋 불러오기 실패: " + e.message, "err");
  }
}

async function savePrompts() {
  if (!guardNode()) return;
  try {
    await API.putPrompts(state.pid, state.nid, $("#prompt-style").value, $("#prompt-structure").value);
    if (state.node) state.node.prompts = { style: $("#prompt-style").value, structure: $("#prompt-structure").value };
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
/* RFP 업로드 → 절 자동작성                                            */
/* ------------------------------------------------------------------ */
function setRfpStatus(text, kind) {
  const box = $("#rfp-status");
  if (!box) return;
  box.textContent = text || "";
  box.className = "rfp-status" + (kind ? " " + kind : "") + (text ? "" : " hidden");
}

// 업로드된 RFP 가 이미 있으면 상태줄에 표시(프로젝트 열 때).
async function refreshRfpStatus() {
  if (!state.pid) return setRfpStatus("");
  try {
    const info = await API.getRfp(state.pid);
    const m = (info && info.meta) || {};
    if (m.filename) setRfpStatus(`RFP: ${m.filename} (${m.chars || 0}자) — 다시 올리면 재작성`, "ok");
    else setRfpStatus("");
  } catch (_) {
    setRfpStatus("");
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
  // 프로젝트가 없으면 기본 문서로 자동 생성(자동작성 대상 절 트리가 필요).
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
    // 1) 업로드 + 텍스트 추출
    startElapsed(`RFP 업로드·분석 중… (${file.name})`);
    const fd = new FormData();
    fd.append("file", file);
    const up = await API.uploadRfp(state.pid, fd);
    stopElapsed();
    toast(`RFP 분석 완료: ${up.chars}자 추출. 자동작성을 시작합니다.`, "ok");

    // 2) 자동작성(병렬) — 대상 절 전체
    const sections = up.sections || null;
    const nSec = (sections && sections.length) || 10;
    const apply = $("#rfp-apply") && $("#rfp-apply").checked;
    startElapsed(`AI가 인터넷 조사 기반으로 자동작성 중… ${nSec}개 절 병렬 (조사 포함, 수 분 소요)`);
    const res = await API.autofillRfp(state.pid, sections, apply);
    stopElapsed();

    const results = res.results || [];
    results.forEach((r) => {
      if (r.ok) markLeafFilled(r.nid);
    });
    const failed = results.filter((r) => !r.ok);
    const okN = res.ok_count != null ? res.ok_count : results.filter((r) => r.ok).length;
    setRfpStatus(
      `자동작성 완료 — ${okN}/${results.length}개 절` +
        (failed.length ? ` (실패: ${failed.map((r) => r.nid).join(", ")})` : "") +
        (apply ? " · YAML 반영됨" : " · 각 절 [변환]으로 반영"),
      failed.length ? "warn" : "ok"
    );
    toast(`자동작성 완료: ${okN}/${results.length}개 절`, failed.length ? "warn" : "ok");

    // 현재 열린 절이 자동작성 대상이면 다시 로드해 입력칸을 갱신
    if (state.nid && results.some((r) => r.nid === state.nid && r.ok)) {
      await selectNode(state.nid);
    }
  } catch (e) {
    stopElapsed();
    // 405/Method Not Allowed = 실행 중인 서버에 RFP 라우트가 없음(옛 코드) → 재시작 안내
    const stale = /method not allowed|\b405\b/i.test(e.message || "");
    const hint = stale ? " — 서버(uvicorn)를 재시작해야 RFP 기능이 반영됩니다." : "";
    setRfpStatus("RFP 자동작성 실패: " + e.message + hint, "err");
    toast("RFP 자동작성 실패: " + e.message + hint, "err");
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
