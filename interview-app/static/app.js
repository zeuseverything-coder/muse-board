"use strict";
const $ = s => document.querySelector(s);
const api = async (path, opt = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opt });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
const state = { session: null, token: null, ws: null, curQid: null, answers: {}, micStream: null, audioCtx: null };

// ---------- theme / display prefs ----------
if (localStorage.getItem("isa_dark") === "1") document.body.classList.add("dark");
$("#themeBtn").onclick = () => {
  document.body.classList.toggle("dark");
  localStorage.setItem("isa_dark", document.body.classList.contains("dark") ? "1" : "0");
};
$("#fontSize").oninput = e => {
  document.documentElement.style.setProperty("--pts", (e.target.value * 0.079) + "rem");
  document.body.style.fontSize = e.target.value + "px";
};
$("#pointsOnly").onchange = e => { $("#answerBodyWrap").classList.toggle("hidden", e.target.checked); };

// ---------- tabs ----------
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#tabs button").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  $("#view-" + b.dataset.view).classList.add("active");
  if (b.dataset.view === "history") loadHistory();
});

// ---------- system status ----------
async function loadStatus() {
  try {
    const s = await api("/api/system/status");
    $("#sysStatus").innerHTML =
      `音声認識(faster-whisper/${s.whisper_model}): <b>${s.whisper_available ? "利用可" : "未導入"}</b><br>` +
      `生成AI: <b>${s.generator === "ollama" ? "Ollama(" + s.ollama_model + ")" : "モック生成（Ollama未接続）"}</b><br>` +
      `意味検索: <b>${s.embedder}</b> / VAD: <b>${s.vad}</b>`;
  } catch (e) { $("#sysStatus").textContent = "状態取得に失敗: " + e.message; }
}

// ---------- profiles ----------
async function loadProfiles() {
  const ps = await api("/api/profiles");
  const opts = ps.map(p => `<option value="${p.id}">${p.company_name}</option>`).join("");
  $("#prepProfile").innerHTML = `<option value="">（共通のみ）</option>` + opts;
  $("#docProfile").innerHTML = `<option value="">共通</option>` + opts;
  $("#qaProfile").innerHTML = `<option value="">共通</option>` + opts;
  $("#profList").innerHTML = ps.map(p => `<div class="item"><b>${p.company_name}</b>
    <div class="meta">${(p.job_info || "").slice(0, 120)}</div>
    <button data-del-prof="${p.id}">削除</button></div>`).join("") || "<p>未登録</p>";
  document.querySelectorAll("[data-del-prof]").forEach(b => b.onclick = async () => {
    await api(`/api/profiles/${b.dataset.delProf}`, { method: "DELETE" }); loadProfiles();
  });
}
$("#addProfBtn").onclick = async () => {
  await api("/api/profiles", { method: "POST", body: JSON.stringify({
    company_name: $("#profName").value, job_info: $("#profJob").value, notes: $("#profNotes").value }) });
  $("#profName").value = ""; loadProfiles();
};

// ---------- documents ----------
const KINDS = ["履歴書","職務経歴書","自己分析","自己PR","転職理由","退職理由","志望動機","業務経験","成功体験","失敗体験","強み・弱み","キャリアプラン","企業情報","求人票","その他"];
$("#docKind").innerHTML = KINDS.map(k => `<option>${k}</option>`).join("");
async function loadDocs() {
  const ds = await api("/api/documents");
  $("#docList").innerHTML = ds.map(d => `<div class="item"><b>[${d.kind}] ${d.title}</b>
    <span class="meta">${d.profile_id ? "企業別" : "共通"} / ${d.content.length}字</span>
    <div class="meta">${d.content.slice(0, 100)}…</div>
    <button data-del-doc="${d.id}">削除</button></div>`).join("") || "<p>未登録</p>";
  document.querySelectorAll("[data-del-doc]").forEach(b => b.onclick = async () => {
    await api(`/api/documents/${b.dataset.delDoc}`, { method: "DELETE" }); loadDocs();
  });
}
$("#addDocBtn").onclick = async () => {
  await api("/api/documents", { method: "POST", body: JSON.stringify({
    kind: $("#docKind").value, title: $("#docTitle").value || "無題",
    content: $("#docContent").value, profile_id: $("#docProfile").value ? +$("#docProfile").value : null }) });
  $("#docContent").value = ""; loadDocs();
};
$("#importDocBtn").onclick = async () => {
  const f = $("#docFile").files[0]; if (!f) return;
  const fd = new FormData();
  fd.append("kind", $("#docKind").value);
  if ($("#docProfile").value) fd.append("profile_id", $("#docProfile").value);
  fd.append("file", f);
  const r = await fetch("/api/documents/import", { method: "POST", body: fd });
  alert(r.ok ? "取り込みました" : "失敗: " + await r.text());
  loadDocs(); loadQa();
};

// ---------- qa ----------
async function loadQa() {
  const qs = await api("/api/qa");
  $("#qaList").innerHTML = qs.map(q => `<div class="item"><b>Q: ${q.question}</b>
    <div class="meta">A: ${q.answer.slice(0, 120)}…</div>
    <button data-del-qa="${q.id}">削除</button></div>`).join("") || "<p>未登録</p>";
  document.querySelectorAll("[data-del-qa]").forEach(b => b.onclick = async () => {
    await api(`/api/qa/${b.dataset.delQa}`, { method: "DELETE" }); loadQa();
  });
}
$("#addQaBtn").onclick = async () => {
  await api("/api/qa", { method: "POST", body: JSON.stringify({
    question: $("#qaQuestion").value, answer: $("#qaAnswer").value,
    profile_id: $("#qaProfile").value ? +$("#qaProfile").value : null }) });
  $("#qaQuestion").value = ""; $("#qaAnswer").value = ""; loadQa();
};
$("#qaSearchBtn").onclick = async () => {
  const r = await api("/api/qa/search", { method: "POST", body: JSON.stringify({ query: $("#qaSearchInput").value }) });
  $("#qaSearchResult").innerHTML = r.results.map(x =>
    `<div class="item">score ${x.score} / ${x.qa.question}</div>`).join("") +
    `<div class="meta">検索時間 ${r.elapsed_ms} ms</div>`;
};

// ---------- session / websocket ----------
function setConn(ok, text) {
  const el = $("#connStatus");
  el.textContent = text; el.className = "badge " + (ok ? "ok" : "ng");
}
function connectWs() {
  if (!state.session) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${state.session}?token=${encodeURIComponent(state.token)}`);
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  ws.onopen = () => setConn(true, "接続中（同期OK）");
  ws.onclose = () => { setConn(false, "切断（再接続します）"); setTimeout(connectWs, 1500); };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
  ws.onmessage = ev => handleEvent(JSON.parse(ev.data));
}
$("#startSessionBtn").onclick = async () => {
  const pid = $("#prepProfile").value ? +$("#prepProfile").value : null;
  const s = await api("/api/sessions", { method: "POST", body: JSON.stringify({ profile_id: pid }) });
  state.session = s.session_id; state.token = s.token;
  localStorage.setItem("isa_session", s.session_id); localStorage.setItem("isa_token", s.token);
  const base = location.origin;
  $("#sessionInfo").innerHTML = `セッションID: ${s.session_id}<br>スマホはQRコードを読み取るか、次回この端末で自動再接続されます。`;
  $("#qrBox").innerHTML = `<img src="/api/sessions/${s.session_id}/qr?base=${encodeURIComponent(base)}" alt="QR">`;
  $("#endSessionBtn").disabled = false;
  connectWs();
};
$("#endSessionBtn").onclick = async () => {
  if (state.session) await api(`/api/sessions/${state.session}/end`, { method: "POST" });
  state.session = null; localStorage.removeItem("isa_session"); localStorage.removeItem("isa_token");
  if (state.ws) state.ws.close();
  setConn(false, "未接続"); $("#qrBox").innerHTML = ""; $("#sessionInfo").textContent = "セッションを終了しました（トークン無効化済み）";
  $("#endSessionBtn").disabled = true;
};

// host audio (Windows loopback / PC mic)
$("#startLoopbackBtn").onclick = () => hostAudio("wasapi_loopback");
$("#startMicBtn").onclick = () => hostAudio("mic");
async function hostAudio(kind) {
  if (!state.session) { alert("先にセッションを開始してください"); return; }
  const fd = new FormData(); fd.append("kind", kind);
  const r = await fetch(`/api/sessions/${state.session}/audio/start`, { method: "POST", body: fd });
  const j = await r.json().catch(() => ({}));
  alert(r.ok ? `${kind} を開始しました` : "開始できません: " + (j.detail || r.status));
  if (r.ok) $("#recStatus").classList.remove("hidden");
}
$("#stopAudioBtn").onclick = async () => {
  for (const kind of ["wasapi_loopback", "mic"]) {
    const fd = new FormData(); fd.append("kind", kind);
    await fetch(`/api/sessions/${state.session}/audio/stop`, { method: "POST", body: fd });
  }
  $("#recStatus").classList.add("hidden");
};

// ---------- live events ----------
function handleEvent(ev) {
  if (ev.type === "transcript_interim") {
    $("#interim").textContent = "（認識中）" + ev.text;
  } else if (ev.type === "audio_level") {
    $("#levelBar").style.width = Math.round(ev.level * 100) + "%";
  } else if (ev.type === "transcript_final") {
    $("#interim").textContent = "";
    const d = document.createElement("div");
    d.textContent = (ev.source === "user" ? "自分: " : "面接官: ") + ev.text;
    $("#transcriptFeed").prepend(d);
  } else if (ev.type === "question_skipped") {
    const d = document.createElement("div");
    d.textContent = "（回答生成なし: " + ev.reason + "）" + ev.text;
    $("#transcriptFeed").prepend(d);
  } else if (ev.type === "answer_start") {
    state.curQid = ev.qid;
    state.answers[ev.qid] = { question: ev.question, answer: "", points: [] };
    $("#answerCard").classList.remove("hidden");
    $("#curQuestion").textContent = ev.question;
    $("#curPoints").innerHTML = ""; $("#curAnswer").textContent = "";
    $("#curSupplement").textContent = ""; $("#curFollowups").innerHTML = "";
    const b = $("#srcBadge");
    if (ev.source_kind === "registered") { b.textContent = "登録済み回答"; b.className = "badge reg"; }
    else if (ev.source_kind === "ai") { b.textContent = "AI生成"; b.className = "badge ai"; }
    else { b.textContent = "AI生成（モック）"; b.className = "badge mock"; }
  } else if (ev.type === "answer_points" && ev.qid === state.curQid) {
    $("#curPoints").innerHTML = ev.items.map(i => `<li>${i}</li>`).join("");
    state.answers[ev.qid].points = ev.items;
  } else if (ev.type === "answer_chunk" && ev.qid === state.curQid) {
    $("#curAnswer").textContent += ev.text;
    state.answers[ev.qid].answer += ev.text;
  } else if (ev.type === "answer_supplement" && ev.qid === state.curQid) {
    $("#curSupplement").textContent = ev.text;
  } else if (ev.type === "answer_followups" && ev.qid === state.curQid) {
    $("#curFollowups").innerHTML = "<b>想定される深掘り:</b><br>" + ev.items.map(i => "・" + i).join("<br>");
  } else if (ev.type === "answer_done") {
    const a = state.answers[ev.qid];
    if (a) {
      const d = document.createElement("div");
      d.className = "item";
      d.innerHTML = `<b>Q: ${a.question}</b><div>${a.answer.slice(0, 300)}</div>`;
      $("#historyFeed").prepend(d);
    }
  } else if (ev.type === "status") {
    setConn(true, ev.text);
  }
}
$("#pauseBtn").onclick = () => {
  if (!state.ws) return;
  const paused = $("#pauseBtn").textContent.includes("一時停止");
  state.ws.send(JSON.stringify({ type: paused ? "pause" : "resume" }));
  $("#pauseBtn").textContent = paused ? "認識を再開" : "認識を一時停止";
  $("#recStatus").classList.toggle("hidden", paused);
};
$("#manualSendBtn").onclick = () => sendManual(false);
$("#manualForceBtn").onclick = () => sendManual(true);
function sendManual(force) {
  const t = $("#manualText").value.trim(); if (!t) return;
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type: "manual_text", text: t, force }));
  }
  $("#manualText").value = "";
}
$("#regenBtn").onclick = () => {
  const a = state.answers[state.curQid];
  if (a && state.ws) state.ws.send(JSON.stringify({ type: "regenerate", question: a.question }));
};
$("#editQuestionBtn").onclick = () => {
  const a = state.answers[state.curQid]; if (!a) return;
  const t = prompt("質問を修正してください", a.question);
  if (t && state.ws) state.ws.send(JSON.stringify({ type: "regenerate", question: t }));
};

// browser mic capture -> 16kHz float32 -> WS binary
$("#browserMicBtn").onclick = async () => {
  if (state.micStream) {
    state.micStream.getTracks().forEach(t => t.stop());
    state.micStream = null; state.audioCtx && state.audioCtx.close();
    $("#browserMicBtn").textContent = "ブラウザマイク開始"; $("#recStatus").classList.add("hidden");
    return;
  }
  if (!state.ws) { alert("先にセッションへ接続してください"); return; }
  try {
    state.micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) { alert("マイクを利用できません: " + e.message); return; }
  const ctx = new AudioContext(); state.audioCtx = ctx;
  const src = ctx.createMediaStreamSource(state.micStream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  src.connect(proc); proc.connect(ctx.destination);
  proc.onaudioprocess = e => {
    if (!state.ws || state.ws.readyState !== 1) return;
    const input = e.inputBuffer.getChannelData(0);
    const ratio = ctx.sampleRate / 16000;
    const n = Math.floor(input.length / ratio);
    const out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = input[Math.floor(i * ratio)];
    state.ws.send(out.buffer);
  };
  $("#browserMicBtn").textContent = "ブラウザマイク停止";
  $("#recStatus").classList.remove("hidden");
};

// ---------- history / settings ----------
async function loadHistory() {
  const hs = await api("/api/history");
  $("#historyList").innerHTML = hs.map(h => `<div class="item"><b>Q: ${h.question}</b>
    <div class="meta">${new Date(h.created_at * 1000).toLocaleString()} / ${h.source}</div>
    <div>${(h.answer || "").slice(0, 300)}</div></div>`).join("") || "<p>履歴はありません</p>";
}
$("#clearHistoryBtn").onclick = async () => { await api("/api/history", { method: "DELETE" }); loadHistory(); };
async function loadSettings() {
  const s = await api("/api/settings");
  $("#setSaveHistory").checked = s.save_history === "1";
  if (s.answer_length) $("#setAnswerLength").value = s.answer_length;
  if (s.qa_threshold) $("#setQaThreshold").value = s.qa_threshold;
}
$("#saveSettingsBtn").onclick = async () => {
  const put = (key, value) => api("/api/settings", { method: "PUT", body: JSON.stringify({ key, value }) });
  await put("save_history", $("#setSaveHistory").checked ? "1" : "0");
  await put("answer_length", $("#setAnswerLength").value);
  if ($("#setQaThreshold").value) await put("qa_threshold", $("#setQaThreshold").value);
  alert("保存しました（しきい値はサーバー再起動後に反映）");
};
$("#deleteAllBtn").onclick = async () => {
  if (!confirm("全データを削除します。よろしいですか？")) return;
  await api("/api/all-data", { method: "DELETE" });
  loadDocs(); loadQa(); loadProfiles(); loadHistory();
  alert("削除しました");
};

// ---------- self test ----------
$("#runTestsBtn").onclick = async () => {
  const out = [];
  const t0 = performance.now();
  const st = await api("/api/system/status");
  out.push(`システム状態: 音声認識=${st.whisper_available ? "OK" : "未導入"} / 生成=${st.generator} / 検索=${st.embedder}`);
  const sr = await api("/api/qa/search", { method: "POST", body: JSON.stringify({ query: "転職を決意した背景を教えてください" }) });
  out.push(`意味検索テスト: ${sr.results.length ? "ヒット score=" + sr.results[0].score : "ヒットなし（想定問答を登録してください）"} / ${sr.elapsed_ms}ms`);
  if (state.ws && state.ws.readyState === 1) {
    const p0 = performance.now();
    state.ws.send(JSON.stringify({ type: "ping" }));
    out.push("WebSocket: 接続中（ping送信済み）");
  } else out.push("WebSocket: 未接続（セッションを開始してください）");
  out.push(`総チェック時間: ${Math.round(performance.now() - t0)}ms`);
  $("#testResults").innerHTML = out.map(x => `<div class="item">${x}</div>`).join("");
};

// ---------- init ----------
(async () => {
  await loadStatus(); await loadProfiles(); await loadDocs(); await loadQa(); await loadSettings();
  const params = new URLSearchParams(location.search);
  const sid = params.get("session") || localStorage.getItem("isa_session");
  const tok = params.get("token") || localStorage.getItem("isa_token");
  if (sid && tok) {
    state.session = sid; state.token = tok;
    localStorage.setItem("isa_session", sid); localStorage.setItem("isa_token", tok);
    $("#endSessionBtn").disabled = false;
    connectWs();
    document.querySelector('[data-view="live"]').click();
  }
  try {
    const devs = await api("/api/audio/devices");
    $("#audioDeviceList").innerHTML = devs.devices.map(d => `<div class="meta">${d.kind}: ${d.name}</div>`).join("") || "<span class='meta'>利用可能な音声デバイスなし（この環境では未検出）</span>";
  } catch (e) {}
})();
