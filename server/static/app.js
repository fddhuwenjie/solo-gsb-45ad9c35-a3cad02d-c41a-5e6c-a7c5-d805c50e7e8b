/* 本地双卷印发校核 —— 原生 JavaScript 前端（hash 路由，无构建步骤） */
"use strict";

const view = document.getElementById("view");
const LETTERS = ["A", "B", "C", "D"];

/* ---------------------------------------------------------------- helpers */

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(url, opt);
  let data = null;
  try { data = await res.json(); } catch (_) { /* ignore */ }
  if (!res.ok || !data || data.ok === false) {
    throw new Error((data && data.error) || `请求失败（${res.status}）`);
  }
  return data;
}

let toastTimer = null;
function toast(msg, kind) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast " + (kind || "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.appendChild(typeof child === "string" || typeof child === "number"
      ? document.createTextNode(String(child)) : child);
  }
  return el;
}

function setActiveNav(name) {
  document.querySelectorAll(".topbar nav a").forEach(a =>
    a.classList.toggle("active", a.dataset.route === name));
}

/* ------------------------------------------------------------ home page */

function renderHome() {
  setActiveNav("home");
  view.replaceChildren(
    h("h1", null, "本地双卷印发校核"),
    h("p", { class: "muted" }, "单选题库 → 分别编排 A、B 卷 → 同一题库修订封存 → 打印试卷 / 答题卡 / 答案表 → 勘误并同步两卷答案 → 登记答题卡并按勘误复核成绩 → 按批次发布成绩并逐批对照回看。"),
    h("div", { class: "grid2" },
      h("div", { class: "card" },
        h("h3", null, "① 维护题库"),
        h("p", { class: "small muted" }, "每道题和每个选项都有稳定标识（Q 题号 / O 选项号），封存后以快照形式引用。"),
        h("a", { class: "btn", href: "#/questions" }, "进入题库")
      ),
      h("div", { class: "card" },
        h("h3", null, "② 编排 A / B 卷"),
        h("p", { class: "small muted" }, "两卷独立调整题序和每题四个选项的顺序，保存草稿。"),
        h("a", { class: "btn", href: "#/arrange" }, "开始编排")
      ),
      h("div", { class: "card" },
        h("h3", null, "③ 修订封存与打印"),
        h("p", { class: "small muted" }, "从同一题库封存为一个版本，生成两卷各自的试卷、答题卡、答案表。封存后再改题库不影响已印卷面。"),
        h("a", { class: "btn", href: "#/seals" }, "查看封存卷")
      ),
      h("div", { class: "card" },
        h("h3", null, "④ 提交勘误"),
        h("p", { class: "small muted" }, "按封存题目和当时印出的选项修正答案，同时更新两卷答案表；非法提交整次拒绝、原答案不变。"),
        h("a", { class: "btn ghost", href: "#/seals" }, "去封存卷页操作")
      ),
      h("div", { class: "card" },
        h("h3", null, "⑤ 登记答题卡与复核"),
        h("p", { class: "small muted" }, "按封存卷印出的题号登记考生作答（每题 1 分、空白 0 分）；勘误后按原作答的封存选项重新核分，对照登记成绩与当前成绩。"),
        h("a", { class: "btn ghost", href: "#/seals" }, "去封存卷页操作")
      ),
      h("div", { class: "card" },
        h("h3", null, "⑥ 发布成绩批次"),
        h("p", { class: "small muted" }, "把当前已登记答题卡按当前答案表核分，发布为不可变批次；再次发布时与上一批逐人对照，标出新登记者与逐题得分变化。"),
        h("a", { class: "btn ghost", href: "#/seals" }, "去封存卷页操作")
      )
    )
  );
}

/* -------------------------------------------------------- question bank */

function questionForm(q) {
  const isEdit = !!q;
  const card = h("div", { class: "card screen-only" },
    h("h3", null, isEdit ? `编辑题目 Q${q.id}` : "新增题目"));
  const stem = h("textarea", { rows: 2, placeholder: "题干内容" });
  card.appendChild(h("label", null, "题干"));
  card.appendChild(stem);

  const optInputs = [];
  const radios = [];
  const optsBox = h("div");
  card.appendChild(h("label", null, "四个选项（点选单选钮指定正确选项）"));
  card.appendChild(optsBox);
  for (let i = 0; i < 4; i++) {
    const inp = h("input", { type: "text", placeholder: `选项 ${LETTERS[i]}` });
    const radio = h("input", { type: "radio", name: "correct", value: String(i) });
    const row = h("div", { class: "optrow" }, radio, h("b", { class: "letter" }, LETTERS[i] + "."), inp);
    optInputs.push(inp); radios.push(radio);
    optsBox.appendChild(row);
  }

  if (isEdit) {
    stem.value = q.stem;
    q.options.forEach((o, i) => { optInputs[i].value = o.content; });
    radios[q.options.findIndex(o => o.id === q.correct_option_id)].checked = true;
  } else {
    radios[0].checked = true;
  }

  const msg = h("div", { class: "small", style: "margin-top:8px;color:var(--err)" });
  const saveBtn = h("button", null, isEdit ? "保存修改" : "添加题目");
  const cancelBtn = h("button", { class: "ghost" }, "取消");

  async function onSave() {
    const correctIdx = radios.findIndex(r => r.checked);
    try {
      const body = {
        stem: stem.value.trim(),
        options: optInputs.map(i => i.value.trim()),
        correct_position: correctIdx,
      };
      if (isEdit) {
        await api("PUT", `/api/questions/${q.id}`, body);
        toast("已保存。注意：修改只影响题库和今后封存，不改变已封存卷面", "ok");
      } else {
        await api("POST", "/api/questions", body);
        toast("题目已添加", "ok");
      }
      renderQuestions(isEdit ? q.id : null);
    } catch (e) { toast(e.message, "err"); }
  }
  saveBtn.addEventListener("click", onSave);
  cancelBtn.addEventListener("click", () => renderQuestions(isEdit ? q.id : null));
  card.appendChild(h("div", { class: "toolbar" }, saveBtn, isEdit ? cancelBtn : null, msg));
  return card;
}

function questionCard(q) {
  const correctIdx = q.options.findIndex(o => o.id === q.correct_option_id);
  const opts = q.options.map((o, i) =>
    h("div", { class: "optrow" + (i === correctIdx ? "" : "") },
      h("b", { class: "letter" }, LETTERS[i] + "."),
      h("span", { class: "ocode" }, o.stable_code || ("O" + o.id)),
      h("span", { class: "grow" }, o.content),
      i === correctIdx ? h("span", { class: "pill ok" }, "正确") : null));
  const used = (q.seal_count || 0) > 0
    ? h("span", { class: "pill warn" }, `已封存 ${q.seal_count} 次：编辑不影响旧卷`)
    : h("span", { class: "pill" }, "未封存");
  return h("div", { class: "qcard", "data-qid": q.id },
    h("div", { class: "qcard-head" },
      h("strong", { class: "qcode" }, "Q" + q.id),
      h("span", { class: "grow" }, q.stem),
      used,
      h("button", { class: "mini ghost", onclick: () => renderQuestions(q.id) }, "编辑"),
      h("button", {
        class: "mini danger",
        onclick: async () => {
          if (!confirm(`删除 Q${q.id}？已封存卷内的快照不受影响；编排草稿中该题会被移除。`)) return;
          try { await api("DELETE", `/api/questions/${q.id}`); toast("已删除", "ok"); renderQuestions(); }
          catch (e) { toast(e.message, "err"); }
        }
      }, "删除")),
    h("div", { style: "margin:6px 0 0 26px" }, ...opts));
}

async function renderQuestions(editId) {
  setActiveNav("questions");
  view.replaceChildren(h("p", null, "加载中…"));
  let qs = [];
  try { qs = (await api("GET", "/api/questions")).questions; }
  catch (e) { view.replaceChildren(h("p", { class: "pill err" }, e.message)); return; }

  const editing = editId ? qs.find(q => q.id === editId) : null;
  view.replaceChildren(
    h("h1", null, "题库"),
    h("p", { class: "muted small" }, "题目标识 Q# 与选项标识 O# 全程稳定。封存卷保存的是封存时刻的内容快照。"),
    editing ? questionForm(editing) : questionForm(null),
    h("h2", null, `题目列表（${qs.length}）`),
    ...qs.map(questionCard)
  );
}

/* ------------------------------------------------------------ arrange */

const arrangeState = { bank: [], drafts: { A: null, B: null } };

function optLabel(q, oid) {
  const o = q.options.find(x => x.id === oid);
  return o ? `O${o.id} ${o.content}` : `?${oid}`;
}

function arrangeCard(paper, item, index, total) {
  const q = arrangeState.bank.find(x => x.id === item.id);
  const card = h("div", { class: "qcard" },
    h("div", { class: "qcard-head" },
      h("strong", { class: "qcode" }, "Q" + item.id),
      h("span", { class: "grow" }, q ? q.stem : "(题目已从题库删除)"),
      h("button", {
        class: "mini ghost", disabled: index === 0,
        onclick: () => moveItem(paper, index, -1), title: "上移"
      }, "↑"),
      h("button", {
        class: "mini ghost", disabled: index === total - 1,
        onclick: () => moveItem(paper, index, 1), title: "下移"
      }, "↓"),
      h("button", {
        class: "mini ghost",
        onclick: () => {
          // rotate options forward: ABCD -> DABC
          item.options.unshift(item.options.pop());
          renderArrangePanels();
        }, title: "选项顺移"
      }, "选项顺移"),
      h("button", {
        class: "mini ghost",
        onclick: () => {
          item.options = [q.options[0].id, q.options[1].id, q.options[2].id, q.options[3].id];
          renderArrangePanels();
        }, title: "恢复题库顺序"
      }, "重置选项")
    ));
  const opts = h("div", { style: "margin:6px 0 0 26px" });
  item.options.forEach((oid, i) => {
    const o = q && q.options.find(x => x.id === oid);
    const sel = h("select", {});
    q.options.forEach(av => {
      const op = h("option", { value: av.id }, "O" + av.id + " " + av.content);
      if (av.id === oid) op.selected = true;
      sel.appendChild(op);
    });
    sel.addEventListener("change", () => {
      const newId = Number(sel.value);
      const otherIdx = item.options.findIndex(x => x === newId);
      item.options[otherIdx] = oid;
      item.options[i] = newId;
      renderArrangePanels();
    });
    const isCorrect = o && o.id === q.correct_option_id;
    opts.appendChild(h("div", { class: "optrow" },
      h("b", { class: "letter" }, LETTERS[i] + "."), sel,
      isCorrect ? h("span", { class: "pill ok" }, "当前答案") : null));
  });
  card.appendChild(opts);
  return card;
}

function moveItem(paper, index, dir) {
  const arr = arrangeState.drafts[paper].questions;
  const [it] = arr.splice(index, 1);
  arr.splice(index + dir, 0, it);
  renderArrangePanels();
}

function paperPanel(paper) {
  const draft = arrangeState.drafts[paper];
  const panel = h("div", { class: "card screen-only", id: "panel-" + paper },
    h("h3", null, paper + " 卷编排"),
    h("p", { class: "small muted" }, "题序用 ↑/↓ 调整；每题选项可用下拉换位、顺移或重置。"));
  const list = h("div");
  draft.questions.forEach((item, i) =>
    list.appendChild(arrangeCard(paper, item, i, draft.questions.length)));
  panel.appendChild(list);
  return panel;
}

function renderArrangePanels() {
  const old = document.getElementById("arrange-panels");
  if (!old) return;
  old.replaceChildren(paperPanel("A"), paperPanel("B"));
}

async function renderArrange() {
  setActiveNav("arrange");
  view.replaceChildren(h("p", null, "加载中…"));
  try {
    arrangeState.bank = (await api("GET", "/api/questions")).questions;
    arrangeState.drafts.A = (await api("GET", "/api/draft/A")).draft;
    arrangeState.drafts.B = (await api("GET", "/api/draft/B")).draft;
  } catch (e) { view.replaceChildren(h("p", { class: "pill err" }, e.message)); return; }

  const noteInput = h("input", { type: "text", placeholder: "封存备注（可选，如：2026 秋季期中）" });
  const panelsWrap = h("div", { class: "grid2", id: "arrange-panels" });
  view.replaceChildren(
    h("h1", null, "A / B 卷编排"),
    h("p", { class: "muted small" }, "两卷须包含相同题目集合（题序、选项顺序各自独立）。保存草稿后可封存；封存不会改动草稿。"),
    h("div", { class: "card screen-only" },
      h("div", { class: "toolbar" },
        h("button", {
          onclick: async () => {
            try {
              await api("PUT", "/api/draft/A", arrangeState.drafts.A);
              await api("PUT", "/api/draft/B", arrangeState.drafts.B);
              toast("两卷草稿已保存", "ok");
            } catch (e) { toast(e.message, "err"); }
          }
        }, "保存两卷草稿"),
        h("button", {
          class: "ghost",
          onclick: () => {
            for (const p of ["A", "B"]) {
              arrangeState.drafts[p].questions = arrangeState.bank
                .map(q => ({ id: q.id, options: q.options.map(o => o.id) }));
            }
            renderArrangePanels();
          }
        }, "两卷均重置为题库顺序"),
        h("span", { class: "grow" }),
        h("label", { style: "margin:0" }, "封存备注"),
        noteInput,
        h("button", {
          onclick: async () => {
            try {
              await api("PUT", "/api/draft/A", arrangeState.drafts.A);
              await api("PUT", "/api/draft/B", arrangeState.drafts.B);
              const r = await api("POST", "/api/seals", { note: noteInput.value });
              toast(`已封存为第 ${r.version} 版`, "ok");
              location.hash = `#/seals/${r.seal_id}`;
            } catch (e) { toast(e.message, "err"); }
          }
        }, "保存并封存新版本")
      ),
      h("div", { class: "small muted" }, "封存时会复制题库当前题干、选项与答案为快照；之后修改题库不会改变本版本的卷面与答题卡。")),
    panelsWrap
  );
  renderArrangePanels();
}

/* ------------------------------------------------------- seals list */

async function renderSeals() {
  setActiveNav("seals");
  view.replaceChildren(h("p", null, "加载中…"));
  let seals = [];
  try { seals = (await api("GET", "/api/seals")).seals; }
  catch (e) { view.replaceChildren(h("p", { class: "pill err" }, e.message)); return; }

  const rows = seals.length
    ? seals.map(s => h("tr", null,
        h("td", null, "第 " + s.version + " 版"),
        h("td", null, s.note || "—"),
        h("td", null, s.question_count + " 题"),
        h("td", null, s.erratum_count > 0
          ? h("span", { class: "pill warn" }, s.erratum_count + " 次勘误")
          : h("span", { class: "pill ok" }, "无勘误")),
        h("td", null, s.created_at),
        h("td", null, h("a", { class: "btn mini", href: `#/seals/${s.id}` }, "回看 / 打印 / 勘误"))))
    : [h("tr", null, h("td", { colspan: "6", class: "muted" }, "尚无封存卷，请先到「A/B 卷编排」封存。"))];

  view.replaceChildren(
    h("h1", null, "封存卷与勘误"),
    h("div", { class: "card" },
      h("table", { class: "data" },
        h("thead", null, h("tr", null,
          h("th", null, "版本"), h("th", null, "备注"), h("th", null, "题量"),
          h("th", null, "勘误"), h("th", null, "封存时间"), h("th", null, "操作"))),
        h("tbody", null, ...rows))));
}

/* ------------------------------------------------------- seal detail */

const sealState = { detail: null, errata: [], tab: "paperA" };
const sheetState = { list: [], detail: null, paper: "A" };
const releaseState = { list: [], detail: null, sheet: null };

function sheetHeader(subtitle) {
  const s = sealState.detail;
  return h("div", { class: "sheet-head" },
    h("h2", null, subtitle),
    h("div", { class: "small muted" }, `封存第 ${s.version} 版 · ${s.note || "无备注"} · 封存时间 ${s.created_at}`));
}

function examSheet(paper) {
  const s = sealState.detail;
  const p = s.papers[paper];
  const sheet = h("div", { class: "sheet" },
    sheetHeader(`${paper} 卷 · 试 卷`),
    h("div", { class: "sheet-meta" },
      h("span", null, "姓名：", h("span", { class: "fillline" })),
      h("span", null, "学号：", h("span", { class: "fillline" })),
      h("span", null, `共 ${p.questions.length} 题，每题只有一个正确选项`)));
  p.questions.forEach(q => {
    sheet.appendChild(h("div", { class: "exam-q" },
      h("div", { class: "stem" }, `${q.number}. ${q.stem}　`,
        h("span", { class: "ocode" }, `（${q.stable_code}）`)),
      ...q.options.map(o => h("div", { class: "exam-opt" },
        h("b", null, o.letter + "."), o.content, " ",
        h("span", { class: "ocode" }, "(" + o.stable_code + ")")))));
  });
  return sheet;
}

function answerCardSheet(paper) {
  const s = sealState.detail;
  const p = s.papers[paper];
  const sheet = h("div", { class: "sheet" },
    sheetHeader(`${paper} 卷 · 答 题 卡`),
    h("div", { class: "sheet-meta" },
      h("span", null, "姓名：", h("span", { class: "fillline" })),
      h("span", null, "考号：", h("span", { class: "fillline" })),
      h("span", null, "得分：", h("span", { class: "fillline", style: "min-width:90px" }))),
    h("p", { class: "small muted" }, "题号与选项字母与同版 " + paper + " 卷卷面完全一致；每题在 A B C D 中涂黑一项。"));

  const table = h("table", { class: "answer-table" });
  const perRow = 5;
  for (let start = 0; start < p.questions.length; start += perRow) {
    const chunk = p.questions.slice(start, start + perRow);
    const trNum = h("tr", null, h("th", null, "题号"));
    const rows = LETTERS.map(L => h("tr", null, h("th", null, L)));
    chunk.forEach(q => {
      trNum.appendChild(h("td", null, String(q.number)));
      LETTERS.forEach((L, i) => rows[i].appendChild(h("td", null, "○")));
    });
    table.appendChild(trNum);
    rows.forEach(r => table.appendChild(r));
  }
  sheet.appendChild(table);
  sheet.appendChild(h("p", { class: "small muted", style: "margin-top:14px" },
    "试卷题目标识：" + p.questions.map(q => `${q.number}=${q.stable_code}`).join("，")));
  return sheet;
}

function keySheet(paper) {
  const s = sealState.detail;
  const p = s.papers[paper];
  const correctedIds = new Set();
  sealState.errata.forEach(b => b.items.forEach(it => correctedIds.add(it.sealed_question_id)));

  const sheet = h("div", { class: "sheet" },
    sheetHeader(`${paper} 卷 · 答 案 表`));
  if (sealState.errata.length) {
    sheet.appendChild(h("div", { class: "note-box" },
      `本答案表已包含 ${sealState.errata.length} 次勘误，带 * 题号为曾勘误题目。`));
  }
  const table = h("table", { class: "answer-table" });
  const perRow = 5;
  for (let start = 0; start < p.questions.length; start += perRow) {
    const chunk = p.questions.slice(start, start + perRow);
    const trNum = h("tr", null, h("th", null, "题号"));
    const trAns = h("tr", null, h("th", null, "答案"));
    chunk.forEach(q => {
      trNum.appendChild(h("td", null, q.number + (correctedIds.has(q.id) ? "*" : "")));
      trAns.appendChild(h("td", null, h("strong", null, q.correct_letter || "—")));
    });
    table.appendChild(trNum); table.appendChild(trAns);
  }
  sheet.appendChild(table);
  sheet.appendChild(h("p", { class: "small muted", style: "margin-top:12px" },
    "答案对应选项标识：" + p.questions.map(q => {
      const o = q.options.find(x => x.is_correct);
      return `${q.number}.${q.correct_letter}(${o ? o.stable_code : "?"})`;
    }).join("，")));
  return sheet;
}

function erratumFormPanel() {
  const s = sealState.detail;
  // Every sealed question exists in both papers (guaranteed at seal time).
  const questions = s.papers.A.questions;
  const rowsBox = h("div");

  function addRow(presetSqId) {
    const sqSel = h("select", {});
    questions.forEach(q => {
      const op = h("option", { value: q.id }, `${q.number}(A卷)/${s.papers.B.questions.find(x => x.id === q.id).number}(B卷) · ${q.stable_code} · ${q.stem.slice(0, 30)}`);
      if (q.id === presetSqId) op.selected = true;
      sqSel.appendChild(op);
    });
    const optSel = h("select", {});
    const preview = h("div", { class: "small muted" });

    function refresh() {
      const sq = questions.find(x => x.id === Number(sqSel.value));
      optSel.replaceChildren();
      sq.options.filter(o => !o.is_correct).forEach(o => {
        optSel.appendChild(h("option", { value: o.sealed_option_id },
          `A卷 ${o.letter} / B卷 ${letterIn(s, sq.id, "B", o.sealed_option_id)} · ${o.stable_code} · ${o.content}`));
      });
      const newId = Number(optSel.value);
      const beforeA = sq.correct_letter;
      const beforeB = letterIn(s, sq.id, "B", currentCorrectId(s, sq.id));
      const afterA = letterIn(s, sq.id, "A", newId);
      const afterB = letterIn(s, sq.id, "B", newId);
      preview.textContent = `勘误后：A卷 ${beforeA} → ${afterA}；B卷 ${beforeB} → ${afterB}`;
    }
    sqSel.addEventListener("change", refresh);
    optSel.addEventListener("change", refresh);

    const row = h("div", { class: "rowbox" },
      h("div", { class: "grid2" },
        h("div", null, h("label", null, "封存题目"), sqSel),
        h("div", null, h("label", null, "改为正确的选项（按封存时印出的选项）"), optSel)),
      preview,
      h("div", { class: "toolbar" },
        h("button", { class: "mini danger", onclick: () => row.remove() }, "移除本条")));
    rowsBox.appendChild(row);
    refresh();
  }

  const reason = h("input", { type: "text", placeholder: "勘误原因（可选）" });
  const result = h("div");

  const panel = h("div", { class: "card screen-only erratum-form" },
    h("h3", null, "提交勘误"),
    h("p", { class: "small muted" },
      "只能选择本次封存题目及其封存选项。任一小题若不属于封存题目、或任一卷缺少映射，整次拒绝、原答案不变；成功则同时更新两卷答案表。"),
    h("label", null, "勘误原因"), reason,
    rowsBox,
    h("div", { class: "toolbar" },
      h("button", { class: "ghost", onclick: () => addRow() }, "+ 增加一条修正"),
      h("button", {
        onclick: async () => {
          const items = [...rowsBox.querySelectorAll(".rowbox")].map(row => ({
            sealed_question_id: Number(row.querySelector("select").value),
            new_sealed_option_id: Number(row.querySelectorAll("select")[1].value),
          }));
          result.replaceChildren();
          try {
            const r = await api("POST", `/api/seals/${s.id}/errata`, { reason: reason.value, items });
            toast("勘误已生效，两卷答案表已更新", "ok");
            await loadSeal(s.id, "errata");
          } catch (e) {
            result.replaceChildren(h("p", { class: "pill err" }, "已整次拒绝，原答案不变：" + e.message));
          }
        }
      }, "提交勘误（全部成功或全部不生效）")),
    result);
  addRow();
  return panel;
}

function currentCorrectId(s, sqId) {
  const q = s.papers.A.questions.find(x => x.id === sqId);
  const o = q.options.find(x => x.is_correct);
  return o ? o.sealed_option_id : null;
}
function letterIn(s, sqId, paper, sealedOptionId) {
  const q = s.papers[paper].questions.find(x => x.id === sqId);
  const o = q.options.find(x => x.sealed_option_id === sealedOptionId);
  return o ? o.letter : "?";
}

function errataHistoryPanel() {
  const s = sealState.detail;
  const card = h("div", { class: "card screen-only" },
    h("h3", null, "历次勘误记录"));
  if (!sealState.errata.length) {
    card.appendChild(h("p", { class: "muted small" }, "暂无勘误。"));
    return card;
  }
  sealState.errata.forEach((b, bi) => {
    card.appendChild(h("h2", { style: "margin-top:14px" },
      `第 ${bi + 1} 次勘误 · ${b.created_at}`,
      b.reason ? h("span", { class: "muted small" }, "　原因：" + b.reason) : null));
    const trs = b.items.map(it => {
      const nA = s.papers.A.questions.find(q => q.id === it.sealed_question_id).number;
      const nB = s.papers.B.questions.find(q => q.id === it.sealed_question_id).number;
      return h("tr", null,
        h("td", null, h("span", { class: "qcode" }, it.question_code)),
        h("td", null, `A卷 第${nA}题：${it.paper_a_old_letter} → ${it.paper_a_new_letter}`),
        h("td", null, `B卷 第${nB}题：${it.paper_b_old_letter} → ${it.paper_b_new_letter}`),
        h("td", null, h("span", { class: "ocode" },
          `${it.paper_a_old_option_code}→${it.paper_a_new_option_code} / ${it.paper_b_old_option_code}→${it.paper_b_new_option_code}`)));
    });
    card.appendChild(h("table", { class: "data" },
      h("thead", null, h("tr", null,
        h("th", null, "封存题目"), h("th", null, "A 卷题号与选项字母"),
        h("th", null, "B 卷题号与选项字母"), h("th", null, "封存选项标识"))),
      h("tbody", null, ...trs)));
  });
  return card;
}

/* ------------------------------------------------------- answer sheets */

function sheetRegisterPanel() {
  const s = sealState.detail;
  const paperSel = h("select", {},
    h("option", { value: "A" }, "A 卷"),
    h("option", { value: "B" }, "B 卷"));
  paperSel.value = sheetState.paper;
  const examinee = h("input", { type: "text", placeholder: "考生编号" });
  const grid = h("div", { class: "sheet-grid" });
  const result = h("div");

  function buildGrid() {
    const p = s.papers[paperSel.value];
    grid.replaceChildren();
    p.questions.forEach(q => {
      const sel = h("select", { "data-number": q.number },
        h("option", { value: "" }, "（空白）"),
        ...LETTERS.map(L => h("option", { value: L }, L)));
      grid.appendChild(h("div", { class: "sheet-cell" },
        h("label", null, `第 ${q.number} 题`), sel));
    });
  }
  paperSel.addEventListener("change", () => { sheetState.paper = paperSel.value; buildGrid(); });
  buildGrid();

  return h("div", { class: "card screen-only" },
    h("h3", null, "登记答题卡"),
    h("p", { class: "small muted" },
      "按所选卷别印出的题号逐题选择作答字母，可留空（空白计 0 分，每题 1 分）。" +
      "同一考生在同一封存版本只能登记一张；题号缺失、重复、多余或字母不属于该题时整张拒绝。"),
    h("div", { class: "grid2" },
      h("div", null, h("label", null, "卷别"), paperSel),
      h("div", null, h("label", null, "考生编号"), examinee)),
    h("label", null, "逐题作答（不选即为空白）"),
    grid,
    h("div", { class: "toolbar" },
      h("button", {
        onclick: async () => {
          const answers = [...grid.querySelectorAll("select")].map(sel => ({
            number: Number(sel.dataset.number),
            letter: sel.value || null,
          }));
          result.replaceChildren();
          try {
            const r = await api("POST", `/api/seals/${s.id}/sheets`, {
              paper: paperSel.value, examinee: examinee.value, answers });
            toast(`已登记，考生 ${examinee.value.trim()} 得分 ${r.total_score}`, "ok");
            await refreshSheets();
          } catch (e) {
            result.replaceChildren(h("p", { class: "pill err" }, "整张拒绝，未留下记录：" + e.message));
          }
        }
      }, "登记答题卡")),
    result);
}

async function refreshSheets() {
  sheetState.list = (await api("GET", `/api/seals/${sealState.detail.id}/sheets`)).sheets;
  sheetState.detail = null;
  renderSealDetailBody();
}

function sheetListPanel() {
  const card = h("div", { class: "card screen-only" }, h("h3", null, "已登记答题卡"));
  if (!sheetState.list.length) {
    card.appendChild(h("p", { class: "muted small" }, "尚无登记。"));
    return card;
  }
  const rows = sheetState.list.map(sh => {
    const diff = sh.current_total !== sh.total_score;
    return h("tr", null,
      h("td", null, sh.examinee),
      h("td", null, sh.paper + " 卷"),
      h("td", null, String(sh.total_score)),
      h("td", null, h("span", { class: "pill " + (diff ? "warn" : "ok") }, String(sh.current_total))),
      h("td", null, sh.created_at),
      h("td", null, h("button", {
        class: "mini ghost",
        onclick: async () => {
          try {
            sheetState.detail = (await api(
              "GET", `/api/seals/${sealState.detail.id}/sheets/${sh.id}`));
            renderSealDetailBody();
          } catch (e) { toast(e.message, "err"); }
        }
      }, "查看复核")));
  });
  card.appendChild(h("table", { class: "data" },
    h("thead", null, h("tr", null,
      h("th", null, "考生编号"), h("th", null, "卷别"), h("th", null, "登记成绩"),
      h("th", null, "当前成绩"), h("th", null, "登记时间"), h("th", null, "操作"))),
    h("tbody", null, ...rows)));
  card.appendChild(h("p", { class: "small muted" },
    "当前成绩按最新答案表（含历次勘误）对原作答的封存选项重新核分；登记成绩与作答记录不变。"));
  return card;
}

function sheetDetailPanel() {
  const d = sheetState.detail;
  const sh = d.sheet;
  const diff = sh.current_total !== sh.total_score;
  const card = h("div", { class: "card" },
    h("h3", null, `答题卡复核 · 考生 ${sh.examinee} · ${sh.paper} 卷`),
    h("p", { class: "small muted" }, `登记时间 ${sh.created_at}`),
    h("p", null,
      "登记成绩 ", h("span", { class: "pill ok" }, sh.total_score + " 分"),
      "　当前成绩 ", h("span", { class: "pill " + (diff ? "warn" : "ok") }, sh.current_total + " 分")));
  if (d.changes.length) {
    card.appendChild(h("div", { class: "note-box" },
      "勘误后得分变化：" + d.changes
        .map(c => `第 ${c.number} 题 ${c.before} → ${c.after}`).join("；")));
  } else {
    card.appendChild(h("p", { class: "small muted" }, "历次勘误未改变本张答题卡的逐题得分。"));
  }
  const rows = d.items.map(it => {
    const changed = it.registered_score !== it.current_score;
    return h("tr", changed ? { class: "changed" } : null,
      h("td", null, String(it.number)),
      h("td", null, it.letter || "（空白）"),
      h("td", null, h("span", { class: "ocode" }, it.option_code || "—")),
      h("td", null, String(it.registered_score)),
      h("td", null, String(it.current_score)));
  });
  card.appendChild(h("table", { class: "data" },
    h("thead", null, h("tr", null,
      h("th", null, "题号"), h("th", null, "作答字母"), h("th", null, "封存选项"),
      h("th", null, "登记得分"), h("th", null, "当前得分"))),
    h("tbody", null, ...rows)));
  card.appendChild(h("div", { class: "toolbar no-print" },
    h("button", {
      class: "ghost",
      onclick: () => { sheetState.detail = null; renderSealDetailBody(); }
    }, "← 返回列表")));
  return card;
}

/* ------------------------------------------------------- score releases */

function releasePublishPanel() {
  const s = sealState.detail;
  const result = h("div");
  return h("div", { class: "card screen-only" },
    h("h3", null, "发布成绩批次"),
    h("p", { class: "small muted" },
      "把本封存版本当前已登记的全部答题卡，按当前答案表（含已生效勘误）核分并保存为一个不可变批次：" +
      "名单按卷别、考生编号排序记录总分，并保存每张卡按印出题号排列的逐题得分。" +
      "名单与得分取自同一数据库状态——与发布交错的登记或勘误要么整体进入本批，要么整体留到下一批。" +
      "已发布批次不随之后的登记、勘误或题库修改改变；没有已登记答题卡时拒绝发布。"),
    h("div", { class: "toolbar" },
      h("button", {
        onclick: async () => {
          result.replaceChildren();
          try {
            const r = await api("POST", `/api/seals/${s.id}/releases`);
            toast(`已发布第 ${r.batch_no} 批，共 ${r.sheet_count} 张答题卡`, "ok");
            await refreshReleases(r.batch_id);
          } catch (e) {
            result.replaceChildren(h("p", { class: "pill err" }, "已拒绝发布：" + e.message));
          }
        }
      }, "发布当前成绩批次")),
    result);
}

async function refreshReleases(openBatchId) {
  const sid = sealState.detail.id;
  releaseState.list = (await api("GET", `/api/seals/${sid}/releases`)).batches;
  if (openBatchId) {
    releaseState.detail = await api("GET", `/api/seals/${sid}/releases/${openBatchId}`);
    releaseState.sheet = null;
  }
  renderSealDetailBody();
}

function releaseListPanel() {
  const card = h("div", { class: "card screen-only" }, h("h3", null, "已发布批次"));
  if (!releaseState.list.length) {
    card.appendChild(h("p", { class: "muted small" }, "尚未发布过成绩批次。"));
    return card;
  }
  const rows = releaseState.list.map(b => h("tr",
    releaseState.detail && releaseState.detail.batch.id === b.id ? { class: "changed" } : null,
    h("td", null, "第 " + b.batch_no + " 批"),
    h("td", null, b.created_at),
    h("td", null, b.sheet_count + " 张"),
    h("td", null, h("button", {
      class: "mini ghost",
      onclick: async () => {
        try {
          releaseState.detail = await api(
            "GET", `/api/seals/${sealState.detail.id}/releases/${b.id}`);
          releaseState.sheet = null;
          renderSealDetailBody();
        } catch (e) { toast(e.message, "err"); }
      }
    }, "查看名单与对照"))));
  card.appendChild(h("table", { class: "data" },
    h("thead", null, h("tr", null,
      h("th", null, "批次"), h("th", null, "发布时间"),
      h("th", null, "答题卡数"), h("th", null, "操作"))),
    h("tbody", null, ...rows)));
  return card;
}

function releaseDiffBox(diff) {
  const box = h("div", { class: "note-box" },
    h("b", null, `与第 ${diff.previous_batch_no} 批逐人对照`));
  box.appendChild(h("div", null,
    diff.new_examinees.length
      ? "新登记者：" + diff.new_examinees.map(e => `${e.examinee}（${e.paper} 卷）`).join("、")
      : "无新登记者。"));
  if (diff.changes.length) {
    box.appendChild(h("div", null, "得分变化考生的总分对照：" +
      diff.totals.map(t => `${t.examinee}（${t.paper} 卷）${t.before} → ${t.after}`).join("；") +
      "。逐题变化如下（总分相抵的也一并列出）："));
    const trs = diff.changes.map(c => h("tr", null,
      h("td", null, c.examinee),
      h("td", null, c.paper + " 卷"),
      h("td", null, "第 " + c.number + " 题"),
      h("td", null, (c.before == null ? "—" : c.before) + " → " + c.after)));
    box.appendChild(h("table", { class: "data", style: "margin-top:6px" },
      h("thead", null, h("tr", null,
        h("th", null, "考生编号"), h("th", null, "卷别"),
        h("th", null, "题号"), h("th", null, "得分 前 → 后"))),
      h("tbody", null, ...trs)));
  } else {
    box.appendChild(h("div", null, "在册考生逐题得分无变化。"));
  }
  return box;
}

function releaseDetailPanel() {
  const d = releaseState.detail;
  const b = d.batch;
  const card = h("div", { class: "card" },
    h("h3", null, `第 ${b.batch_no} 批名单 · ${b.created_at}`),
    h("p", { class: "small muted" },
      `共 ${b.sheet_count} 张答题卡，按卷别、考生编号排序；本批为发布时刻的快照，` +
      "之后的登记、勘误或题库修改都不会改变本批。"));
  card.appendChild(d.diff
    ? releaseDiffBox(d.diff)
    : h("p", { class: "small muted" }, "本版首个发布批次，无上一批可对照。"));
  const rows = d.sheets.map(sh => h("tr", null,
    h("td", null, sh.paper + " 卷"),
    h("td", null, sh.examinee),
    h("td", null, String(sh.total_score)),
    h("td", { class: "no-print" }, h("button", {
      class: "mini ghost",
      onclick: () => { releaseState.sheet = sh; renderSealDetailBody(); }
    }, "逐题得分"))));
  card.appendChild(h("table", { class: "data" },
    h("thead", null, h("tr", null,
      h("th", null, "卷别"), h("th", null, "考生编号"),
      h("th", null, "总分"), h("th", { class: "no-print" }, "操作"))),
    h("tbody", null, ...rows)));
  return card;
}

function releaseSheetPanel() {
  const sh = releaseState.sheet;
  const card = h("div", { class: "card" },
    h("h3", null, `逐题得分 · 考生 ${sh.examinee} · ${sh.paper} 卷 · 总分 ${sh.total_score}`),
    h("p", { class: "small muted" }, "按该卷印出题号排列。"));
  const rows = sh.items.map(it => h("tr", null,
    h("td", null, String(it.number)),
    h("td", null, String(it.score))));
  card.appendChild(h("table", { class: "data" },
    h("thead", null, h("tr", null, h("th", null, "题号"), h("th", null, "得分"))),
    h("tbody", null, ...rows)));
  card.appendChild(h("div", { class: "toolbar no-print" },
    h("button", {
      class: "ghost",
      onclick: () => { releaseState.sheet = null; renderSealDetailBody(); }
    }, "← 返回批次名单")));
  return card;
}

function renderSealTabs() {
  const tabs = [
    ["paperA", "A 卷试卷"], ["cardA", "A 卷答题卡"], ["keyA", "A 卷答案表"],
    ["paperB", "B 卷试卷"], ["cardB", "B 卷答题卡"], ["keyB", "B 卷答案表"],
    ["errata", "勘误"], ["sheets", "作答登记 / 复核"], ["releases", "成绩发布"],
  ];
  const bar = h("div", { class: "tabs no-print" });
  tabs.forEach(([key, label]) => {
    bar.appendChild(h("button", {
      class: sealState.tab === key ? "active" : "",
      onclick: () => { sealState.tab = key; renderSealDetailBody(); }
    }, label));
  });
  return bar;
}

function renderSealDetailBody() {
  const host = document.getElementById("seal-body");
  if (!host) return;
  host.replaceChildren(renderSealTabs());
  const s = sealState.detail;
  const printBtn = h("button", {
    onclick: () => window.print()
  }, "打印 / 另存 PDF 当前页");
  host.appendChild(h("div", { class: "toolbar no-print" },
    printBtn,
    h("a", { class: "btn ghost", href: "#/seals" }, "← 返回封存卷列表"),
    h("span", { class: "muted small" },
      "打印时只输出当前标签页内容（试卷、答题卡或答案表各占一页）。")));

  const content = h("div", { id: "seal-content" });
  switch (sealState.tab) {
    case "paperA": content.appendChild(examSheet("A")); break;
    case "cardA": content.appendChild(answerCardSheet("A")); break;
    case "keyA": content.appendChild(keySheet("A")); break;
    case "paperB": content.appendChild(examSheet("B")); break;
    case "cardB": content.appendChild(answerCardSheet("B")); break;
    case "keyB": content.appendChild(keySheet("B")); break;
    case "errata": content.appendChild(erratumFormPanel()); content.appendChild(errataHistoryPanel()); break;
    case "sheets":
      if (sheetState.detail) {
        content.appendChild(sheetDetailPanel());
      } else {
        content.appendChild(sheetRegisterPanel());
        content.appendChild(sheetListPanel());
      }
      break;
    case "releases":
      content.appendChild(releasePublishPanel());
      content.appendChild(releaseListPanel());
      if (releaseState.detail) {
        content.appendChild(releaseDetailPanel());
        if (releaseState.sheet) content.appendChild(releaseSheetPanel());
      }
      break;
  }
  host.appendChild(content);
}

async function loadSeal(id, tab) {
  setActiveNav("seals");
  view.replaceChildren(h("p", null, "加载中…"));
  try {
    sealState.detail = (await api("GET", `/api/seals/${id}`)).seal;
    sealState.errata = (await api("GET", `/api/seals/${id}/errata`)).batches;
    sheetState.list = (await api("GET", `/api/seals/${id}/sheets`)).sheets;
    sheetState.detail = null;
    releaseState.list = (await api("GET", `/api/seals/${id}/releases`)).batches;
    releaseState.detail = null;
    releaseState.sheet = null;
  } catch (e) { view.replaceChildren(h("p", { class: "pill err" }, e.message)); return; }
  if (tab) sealState.tab = tab;
  view.replaceChildren(
    h("h1", null, `封存第 ${sealState.detail.version} 版`),
    h("p", { class: "muted small screen-only" },
      `封存于 ${sealState.detail.created_at} · ${sealState.detail.question_count} 题 · `,
      sealState.detail.note || "无备注"),
    h("div", { id: "seal-body" }));
  renderSealDetailBody();
}

/* ---------------------------------------------------------------- router */

function router() {
  const hash = location.hash || "#/";
  const parts = hash.replace(/^#\//, "").split("/");
  if (parts[0] === "" || parts[0] === "home") return renderHome();
  if (parts[0] === "questions") return renderQuestions();
  if (parts[0] === "arrange") return renderArrange();
  if (parts[0] === "seals") {
    if (parts[1]) return loadSeal(Number(parts[1]));
    return renderSeals();
  }
  renderHome();
}
window.addEventListener("hashchange", router);
router();
