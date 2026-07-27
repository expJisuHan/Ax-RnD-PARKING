"use strict";

const elements = {
  video: document.querySelector("#cameraVideo"),
  canvas: document.querySelector("#overlayCanvas"),
  cameraEmpty: document.querySelector("#cameraEmpty"),
  cameraStage: document.querySelector("#cameraStage"),
  startCamera: document.querySelector("#startCameraButton"),
  capture: document.querySelector("#captureButton"),
  undoPoint: document.querySelector("#undoPointButton"),
  setupTab: document.querySelector("#setupTab"),
  monitorTab: document.querySelector("#monitorTab"),
  setupTools: document.querySelector("#setupTools"),
  slotId: document.querySelector("#slotIdInput"),
  addSlot: document.querySelector("#addSlotButton"),
  saveConfig: document.querySelector("#saveConfigButton"),
  pointGuide: document.querySelector("#pointGuide"),
  slotEditorList: document.querySelector("#slotEditorList"),
  startMonitor: document.querySelector("#startMonitorButton"),
  stopMonitor: document.querySelector("#stopMonitorButton"),
  analyze: document.querySelector("#analyzeButton"),
  monitorBadge: document.querySelector("#monitorBadge"),
  occupancyRate: document.querySelector("#occupancyRate"),
  occupiedCount: document.querySelector("#occupiedCount"),
  emptyCount: document.querySelector("#emptyCount"),
  unknownCount: document.querySelector("#unknownCount"),
  intervalText: document.querySelector("#intervalText"),
  lastAnalyzed: document.querySelector("#lastAnalyzed"),
  retentionText: document.querySelector("#retentionText"),
  modelState: document.querySelector("#modelState"),
  analysisState: document.querySelector("#analysisState"),
  slotResults: document.querySelector("#slotResults"),
  snapshotList: document.querySelector("#snapshotList"),
  serverDot: document.querySelector("#serverDot"),
  serverText: document.querySelector("#serverText"),
  toast: document.querySelector("#toast"),
};

const state = {
  stream: null,
  config: null,
  slots: [],
  pendingPoints: [],
  referenceImage: null,
  referenceReady: false,
  mode: "setup",
  editingSlotId: null,
  monitorTimer: null,
  analyzing: false,
  toastTimer: null,
};

const canvasContext = elements.canvas.getContext("2d");

function showToast(message, isError = false) {
  clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", isError);
  elements.toast.classList.add("show");
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 3200);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `요청 실패 (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // A non-JSON server response still gets a useful status message.
    }
    throw new Error(message);
  }
  return response.json();
}

function setCanvasSize(width, height) {
  elements.canvas.width = Math.max(1, Math.round(width));
  elements.canvas.height = Math.max(1, Math.round(height));
}

function drawOverlay() {
  const { width, height } = elements.canvas;
  canvasContext.clearRect(0, 0, width, height);
  if (state.mode === "setup" && state.referenceImage) {
    canvasContext.drawImage(state.referenceImage, 0, 0, width, height);
  }

  state.slots.forEach((slot) => {
    const isEditing = slot.id === state.editingSlotId;
    drawPolygon(slot.points, isEditing ? "#e0a129" : "#32b77d", slot.id, isEditing);
  });

  if (state.pendingPoints.length) {
    drawPolygon(state.pendingPoints, "#e0a129", "", false);
    state.pendingPoints.forEach((point, index) => {
      canvasContext.beginPath();
      canvasContext.arc(point[0], point[1], 7, 0, Math.PI * 2);
      canvasContext.fillStyle = "#e0a129";
      canvasContext.fill();
      canvasContext.fillStyle = "#171b19";
      canvasContext.font = "bold 11px sans-serif";
      canvasContext.textAlign = "center";
      canvasContext.fillText(String(index + 1), point[0], point[1] + 4);
    });
  }
}

function drawPolygon(points, color, label, dashed) {
  if (!points.length) return;
  canvasContext.save();
  canvasContext.strokeStyle = color;
  canvasContext.fillStyle = `${color}30`;
  canvasContext.lineWidth = 3;
  canvasContext.setLineDash(dashed ? [9, 7] : []);
  canvasContext.beginPath();
  canvasContext.moveTo(points[0][0], points[0][1]);
  points.slice(1).forEach((point) => canvasContext.lineTo(point[0], point[1]));
  if (points.length === 4) {
    canvasContext.closePath();
    canvasContext.fill();
  }
  canvasContext.stroke();
  canvasContext.restore();

  if (label && points.length === 4) {
    const center = points.reduce(
      (sum, point) => [sum[0] + point[0] / 4, sum[1] + point[1] / 4],
      [0, 0],
    );
    canvasContext.font = "bold 15px sans-serif";
    canvasContext.textAlign = "center";
    canvasContext.fillStyle = "#ffffff";
    canvasContext.strokeStyle = "#18211d";
    canvasContext.lineWidth = 4;
    canvasContext.strokeText(label, center[0], center[1]);
    canvasContext.fillText(label, center[0], center[1]);
  }
}

function canvasPoint(event) {
  const rect = elements.canvas.getBoundingClientRect();
  const clientX = event.touches ? event.touches[0].clientX : event.clientX;
  const clientY = event.touches ? event.touches[0].clientY : event.clientY;
  return [
    Math.round(((clientX - rect.left) / rect.width) * elements.canvas.width),
    Math.round(((clientY - rect.top) / rect.height) * elements.canvas.height),
  ];
}

function onCanvasPointer(event) {
  if (state.mode !== "setup" || !state.referenceReady || state.pendingPoints.length >= 4) {
    return;
  }
  event.preventDefault();
  state.pendingPoints.push(canvasPoint(event));
  elements.undoPoint.disabled = false;
  elements.addSlot.disabled = state.pendingPoints.length !== 4;
  elements.pointGuide.textContent =
    state.pendingPoints.length === 4
      ? "네 점을 모두 선택했습니다. 주차면 ID를 확인하고 추가하세요."
      : `${state.pendingPoints.length}/4점 선택됨`;
  drawOverlay();
}

async function startCamera() {
  try {
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
    }
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    });
    elements.video.srcObject = state.stream;
    await elements.video.play();
    await new Promise((resolve) => {
      if (elements.video.videoWidth) {
        resolve();
        return;
      }
      elements.video.addEventListener("loadedmetadata", resolve, { once: true });
    });
    setCanvasSize(elements.video.videoWidth, elements.video.videoHeight);
    state.referenceImage = null;
    state.referenceReady = false;
    elements.cameraEmpty.classList.add("hidden");
    elements.capture.disabled = false;
    elements.analyze.disabled = false;
    elements.startCamera.textContent = "카메라 다시 연결";
    drawOverlay();
    showToast("카메라가 연결되었습니다.");
  } catch (error) {
    showToast(`카메라 연결 실패: ${error.message}`, true);
  }
}

function captureReference() {
  if (!state.stream || !elements.video.videoWidth) return;
  setMode("setup");
  const captureCanvas = document.createElement("canvas");
  captureCanvas.width = elements.video.videoWidth;
  captureCanvas.height = elements.video.videoHeight;
  captureCanvas.getContext("2d").drawImage(elements.video, 0, 0);
  const image = new Image();
  image.onload = () => {
    setCanvasSize(captureCanvas.width, captureCanvas.height);
    state.referenceImage = image;
    state.referenceReady = true;
    state.pendingPoints = [];
    state.editingSlotId = null;
    elements.video.style.visibility = "hidden";
    elements.pointGuide.textContent = "주차면의 네 모서리를 시계 방향으로 선택하세요.";
    elements.addSlot.disabled = true;
    elements.undoPoint.disabled = true;
    drawOverlay();
  };
  image.src = captureCanvas.toDataURL("image/jpeg", 0.9);
}

function setMode(mode) {
  state.mode = mode;
  const setup = mode === "setup";
  elements.setupTab.classList.toggle("active", setup);
  elements.monitorTab.classList.toggle("active", !setup);
  elements.setupTools.classList.toggle("hidden", !setup);
  elements.video.style.visibility = setup && state.referenceReady ? "hidden" : "visible";
  if (!setup && state.stream && elements.video.videoWidth) {
    setCanvasSize(elements.video.videoWidth, elements.video.videoHeight);
  }
  drawOverlay();
}

function addOrUpdateSlot() {
  const slotId = elements.slotId.value.trim();
  if (!slotId) {
    showToast("주차면 ID를 입력하세요.", true);
    return;
  }
  if (state.pendingPoints.length !== 4) {
    showToast("주차면의 네 점을 먼저 선택하세요.", true);
    return;
  }
  const duplicate = state.slots.some(
    (slot) => slot.id === slotId && slot.id !== state.editingSlotId,
  );
  if (duplicate) {
    showToast("이미 사용 중인 주차면 ID입니다.", true);
    return;
  }

  const newSlot = { id: slotId, points: state.pendingPoints.map((point) => [...point]) };
  if (state.editingSlotId) {
    state.slots = state.slots.map((slot) => (slot.id === state.editingSlotId ? newSlot : slot));
  } else {
    state.slots.push(newSlot);
  }
  state.pendingPoints = [];
  state.editingSlotId = null;
  elements.slotId.value = "";
  elements.addSlot.disabled = true;
  elements.undoPoint.disabled = true;
  elements.addSlot.textContent = "주차면 추가";
  elements.pointGuide.textContent = "다음 주차면의 네 모서리를 선택하세요.";
  renderSlotEditors();
  renderEmptyResults();
  drawOverlay();
}

function editSlot(slotId) {
  const slot = state.slots.find((item) => item.id === slotId);
  if (!slot) return;
  state.editingSlotId = slotId;
  state.pendingPoints = [];
  elements.slotId.value = slot.id;
  elements.addSlot.textContent = "수정 적용";
  elements.addSlot.disabled = true;
  elements.pointGuide.textContent = `${slot.id} 영역의 네 모서리를 다시 선택하세요.`;
  drawOverlay();
}

function deleteSlot(slotId) {
  state.slots = state.slots.filter((slot) => slot.id !== slotId);
  if (state.editingSlotId === slotId) {
    state.editingSlotId = null;
    state.pendingPoints = [];
    elements.slotId.value = "";
    elements.addSlot.textContent = "주차면 추가";
  }
  renderSlotEditors();
  renderEmptyResults();
  drawOverlay();
}

function renderSlotEditors() {
  if (!state.slots.length) {
    elements.slotEditorList.innerHTML = '<p class="empty-list">등록된 주차면이 없습니다.</p>';
    return;
  }
  elements.slotEditorList.innerHTML = "";
  state.slots.forEach((slot) => {
    const item = document.createElement("div");
    item.className = "slot-editor-item";
    item.innerHTML = `
      <strong>${escapeHtml(slot.id)}</strong>
      <div class="slot-item-actions">
        <button class="mini-button" type="button" data-edit="${escapeHtml(slot.id)}">수정</button>
        <button class="mini-button danger" type="button" data-delete="${escapeHtml(slot.id)}">삭제</button>
      </div>
    `;
    elements.slotEditorList.append(item);
  });
}

function renderEmptyResults() {
  if (!state.slots.length) {
    elements.slotResults.innerHTML = '<p class="empty-list">등록된 주차면이 없습니다.</p>';
    return;
  }
  renderResults({
    slots: state.slots.map((slot) => ({ id: slot.id, status: "unknown", score: 0 })),
    occupancy_rate: 0,
    occupied_slots: 0,
    empty_slots: 0,
    unknown_slots: state.slots.length,
  });
}

async function saveConfig() {
  const config = {
    ...state.config,
    frame_width: elements.canvas.width,
    frame_height: elements.canvas.height,
    slots: state.slots,
  };
  try {
    const result = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    state.config = result.config;
    showToast("주차면 설정을 저장했습니다.");
  } catch (error) {
    showToast(`설정 저장 실패: ${error.message}`, true);
  }
}

function captureCurrentFrame() {
  if (!state.stream || !elements.video.videoWidth) {
    throw new Error("카메라가 연결되지 않았습니다.");
  }
  const frameCanvas = document.createElement("canvas");
  frameCanvas.width = elements.video.videoWidth;
  frameCanvas.height = elements.video.videoHeight;
  frameCanvas.getContext("2d").drawImage(elements.video, 0, 0);
  return new Promise((resolve, reject) => {
    frameCanvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("프레임 캡처에 실패했습니다."))),
      "image/jpeg",
      0.86,
    );
  });
}

async function analyzeNow() {
  if (state.analyzing) return;
  if (!state.slots.length) {
    showToast("분석할 주차면을 먼저 등록하세요.", true);
    return;
  }
  state.analyzing = true;
  elements.analysisState.textContent = "분석 중";
  elements.analyze.disabled = true;
  try {
    const blob = await captureCurrentFrame();
    const form = new FormData();
    form.append("image", blob, "camera-frame.jpg");
    const result = await api("/api/analyze", { method: "POST", body: form });
    renderResults(result);
    await loadSnapshots();
    if (!result.model_ready) {
      showToast("캡처는 저장했지만 YOLO 모델 파일이 없어 상태는 판단 보류입니다.", true);
    } else {
      showToast("점유 분석을 완료했습니다.");
    }
  } catch (error) {
    elements.analysisState.textContent = "오류";
    showToast(`분석 실패: ${error.message}`, true);
  } finally {
    state.analyzing = false;
    elements.analyze.disabled = !state.stream;
  }
}

function renderResults(result) {
  elements.occupancyRate.innerHTML = `${Number(result.occupancy_rate || 0).toFixed(1)}<small>%</small>`;
  elements.occupiedCount.textContent = result.occupied_slots ?? 0;
  elements.emptyCount.textContent = result.empty_slots ?? 0;
  elements.unknownCount.textContent = result.unknown_slots ?? 0;
  elements.lastAnalyzed.textContent = result.timestamp
    ? new Date(result.timestamp).toLocaleString("ko-KR")
    : "-";
  elements.analysisState.textContent = result.timestamp ? "분석 완료" : "설정 대기";
  if (typeof result.model_ready === "boolean") {
    elements.modelState.textContent = result.model_ready ? "준비됨" : "모델 파일 필요";
  }

  const labels = {
    occupied: "점유",
    empty: "비어 있음",
    unknown: "판단 보류",
  };
  const slots = result.slots || [];
  if (!slots.length) {
    elements.slotResults.innerHTML = '<p class="empty-list">등록된 주차면이 없습니다.</p>';
    return;
  }
  elements.slotResults.innerHTML = "";
  slots.forEach((slot) => {
    const item = document.createElement("div");
    item.className = `slot-result ${slot.status}`;
    item.innerHTML = `
      <strong>${escapeHtml(slot.id)}</strong>
      <span class="slot-state">${labels[slot.status] || slot.status}</span>
    `;
    elements.slotResults.append(item);
  });
}

function startMonitoring() {
  if (!state.stream) {
    showToast("카메라를 먼저 연결하세요.", true);
    return;
  }
  if (!state.slots.length) {
    showToast("주차면을 먼저 등록하고 설정을 저장하세요.", true);
    return;
  }
  clearInterval(state.monitorTimer);
  const intervalMs = Number(state.config.analysis_interval_minutes) * 60 * 1000;
  state.monitorTimer = setInterval(analyzeNow, intervalMs);
  elements.monitorBadge.textContent = "실행 중";
  elements.monitorBadge.classList.add("running");
  elements.startMonitor.disabled = true;
  elements.stopMonitor.disabled = false;
  setMode("monitor");
  analyzeNow();
}

function stopMonitoring() {
  clearInterval(state.monitorTimer);
  state.monitorTimer = null;
  elements.monitorBadge.textContent = "정지";
  elements.monitorBadge.classList.remove("running");
  elements.startMonitor.disabled = false;
  elements.stopMonitor.disabled = true;
}

async function loadSnapshots() {
  const data = await api("/api/snapshots");
  elements.retentionText.textContent = `${data.count} / ${data.retention_count}장`;
  if (!data.items.length) {
    elements.snapshotList.innerHTML =
      '<p class="empty-list">아직 분석한 이미지가 없습니다.</p>';
    return;
  }
  elements.snapshotList.innerHTML = "";
  data.items.forEach((snapshot) => {
    const link = document.createElement("a");
    link.className = "snapshot-item";
    link.href = snapshot.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.title = new Date(snapshot.modified_at).toLocaleString("ko-KR");
    link.innerHTML = `<img src="${snapshot.url}" alt="분석 캡처">`;
    elements.snapshotList.append(link);
  });
}

async function loadInitialState() {
  try {
    const [health, config, latest] = await Promise.all([
      api("/health"),
      api("/api/config"),
      api("/api/results/latest"),
    ]);
    state.config = config;
    state.slots = config.slots || [];
    elements.serverDot.classList.add("online");
    elements.serverText.textContent = "서버 연결됨";
    elements.intervalText.textContent = `${config.analysis_interval_minutes}분`;
    elements.retentionText.textContent = `0 / ${config.snapshot_retention_count}장`;
    elements.modelState.textContent = health.model_file_exists ? "파일 확인됨" : "모델 파일 필요";
    renderSlotEditors();
    const configuredIds = state.slots.map((slot) => slot.id).sort();
    const resultIds = (latest.result?.slots || []).map((slot) => slot.id).sort();
    const resultMatchesConfig =
      configuredIds.length === resultIds.length &&
      configuredIds.every((slotId, index) => slotId === resultIds[index]);
    if (latest.result && resultMatchesConfig) {
      renderResults(latest.result);
    } else {
      renderEmptyResults();
    }
    await loadSnapshots();
  } catch (error) {
    elements.serverDot.classList.add("offline");
    elements.serverText.textContent = "서버 연결 실패";
    showToast(error.message, true);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

elements.startCamera.addEventListener("click", startCamera);
elements.capture.addEventListener("click", captureReference);
elements.setupTab.addEventListener("click", () => setMode("setup"));
elements.monitorTab.addEventListener("click", () => setMode("monitor"));
elements.canvas.addEventListener("click", onCanvasPointer);
elements.undoPoint.addEventListener("click", () => {
  state.pendingPoints.pop();
  elements.addSlot.disabled = state.pendingPoints.length !== 4;
  elements.undoPoint.disabled = state.pendingPoints.length === 0;
  elements.pointGuide.textContent = `${state.pendingPoints.length}/4점 선택됨`;
  drawOverlay();
});
elements.addSlot.addEventListener("click", addOrUpdateSlot);
elements.saveConfig.addEventListener("click", saveConfig);
elements.startMonitor.addEventListener("click", startMonitoring);
elements.stopMonitor.addEventListener("click", stopMonitoring);
elements.analyze.addEventListener("click", analyzeNow);
elements.slotEditorList.addEventListener("click", (event) => {
  const editButton = event.target.closest("[data-edit]");
  const deleteButton = event.target.closest("[data-delete]");
  if (editButton) editSlot(editButton.dataset.edit);
  if (deleteButton) deleteSlot(deleteButton.dataset.delete);
});
window.addEventListener("beforeunload", () => {
  clearInterval(state.monitorTimer);
  state.stream?.getTracks().forEach((track) => track.stop());
});

loadInitialState();
