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
  createProject: () => api("/api/projects", postJson({ use_default: true })),
  listProjects: () => api("/api/projects"),
  getTree: (pid) => api(`/api/projects/${pid}/tree`),
  getNode: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}`),
  putTemplate: (pid, nid, template) => api(`/api/projects/${pid}/nodes/${nid}/template`, jsonBody({ template })),
  generateTemplate: (pid, nid, description) =>
    api(`/api/projects/${pid}/nodes/${nid}/template/generate`, postJson({ description })),
  putPrompts: (pid, nid, style, structure) =>
    api(`/api/projects/${pid}/nodes/${nid}/prompts`, jsonBody({ style, structure })),
  getPreset: (nid) => api(`/api/presets/${nid}`),
  putInput: (pid, nid, input) => api(`/api/projects/${pid}/nodes/${nid}/input`, jsonBody({ input })),
  chat: (pid, nid, message, apply) =>
    api(`/api/projects/${pid}/nodes/${nid}/chat`, postJson({ message, apply })),
  clearChat: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/chat`, { method: "DELETE" }),
  convert: (pid, nid) => api(`/api/projects/${pid}/nodes/${nid}/convert`, postJson({})),
  build: (pid) => api(`/api/projects/${pid}/build`, postJson({})),
  downloadUrl: (pid) => `/api/projects/${pid}/download`,
  previewUrl: (pid) => `/api/projects/${pid}/preview.pdf`,
  regulationsPdfUrl: (pid, nid) => `/api/projects/${pid}/nodes/${nid}/regulations.pdf`,
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
  } catch (e) {
    toast("프로젝트 목록 조회 실패: " + e.message, "err");
  }
}

async function openProject(pid) {
  if (!pid) return;
  state.pid = pid;
  state.nid = null;
  state.node = null;
  $("#btn-build").disabled = false;
  $("#build-links").classList.add("hidden");
  showNodeEmpty();
  await loadTree();
}

async function createProject() {
  const btn = $("#btn-new-project");
  btn.disabled = true;
  toast("기본 문서로 프로젝트 생성 중… (변환·추출)");
  try {
    const res = await API.createProject();
    const pid = res.pid || res.id;
    await loadProjects(pid);
    await openProject(pid);
    toast("프로젝트 생성 완료", "ok");
  } catch (e) {
    toast("프로젝트 생성 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
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
  const leaf = el(
    "div",
    {
      class: "tree-leaf" + (isChapter ? " chapter-leaf" : ""),
      "data-nid": node.id,
      onclick: () => selectNode(node.id),
    },
    [el("span", { class: "tree-num", text: node.label }), el("span", { class: "tree-title-txt", text: node.title || "" })]
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
    toast("빌드 완료 — 다운로드/미리보기 가능", "ok");
  } catch (e) {
    toast("빌드 실패: " + e.message, "err");
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* 이벤트 바인딩 / 부팅                                                */
/* ------------------------------------------------------------------ */
function bindEvents() {
  $("#btn-new-project").addEventListener("click", createProject);
  $("#project-select").addEventListener("change", (e) => openProject(e.target.value));
  $("#btn-tree-refresh").addEventListener("click", () => state.pid && loadTree());
  $("#btn-build").addEventListener("click", doBuild);

  $$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.getAttribute("data-tab"))));

  $("#btn-template-save").addEventListener("click", saveTemplate);
  $("#btn-template-generate").addEventListener("click", generateTemplate);
  $("#btn-prompts-save").addEventListener("click", savePrompts);
  $("#btn-preset-load").addEventListener("click", loadPreset);
  $("#btn-input-save").addEventListener("click", saveInput);
  $("#btn-convert").addEventListener("click", doConvert);
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

async function boot() {
  bindEvents();
  await loadProjects();
  // 프로젝트가 하나면 자동 선택
  const sel = $("#project-select");
  if (sel.options.length === 2) {
    sel.selectedIndex = 1;
    await openProject(sel.value);
  }
}

document.addEventListener("DOMContentLoaded", boot);
