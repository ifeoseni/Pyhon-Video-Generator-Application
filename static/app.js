/* ═══════════════════════════════════════════════════════════════════════════
   ExplainerAI — Scene Editor Frontend Logic (v2)
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────
  let scenes = [];
  let voices = [];
  let animations = [];
  let transitions = [];
  let sceneCounter = 0;
  let currentOrientation = "landscape";
  let currentProjectId = null;
  let globalLogoUrl = null;
  let imageProviders = [];
  let apiKeys = {};

  // ── DOM References ───────────────────────────────────────────────────
  const sceneList = document.getElementById("scene-list");
  const emptyState = document.getElementById("empty-state");
  const sceneCountEl = document.getElementById("scene-count");
  const btnAddScene = document.getElementById("btn-add-scene");
  const btnRender = document.getElementById("btn-render");
  const sceneTemplate = document.getElementById("scene-template");
  const projectNameInput = document.getElementById("project-name");
  const logoUploadInput = document.getElementById("logo-upload-input");
  const logoPositionSelect = document.getElementById("logo-position-select");
  const btnRemoveLogo = document.getElementById("btn-remove-logo");
  const logoUploadText = document.getElementById("logo-upload-text");

  // Guide
  const btnGuide = document.getElementById("btn-guide");
  const guideOverlay = document.getElementById("guide-overlay");
  const guideClose = document.getElementById("guide-close");

  // Render overlay
  const renderOverlay = document.getElementById("render-overlay");
  const renderStatusText = document.getElementById("render-status-text");
  const renderProgressBar = document.getElementById("render-progress-bar");
  const renderSubText = document.getElementById("render-sub-text");
  const renderEstimateLine = document.getElementById("render-estimate-line");
  const renderDownloadBtn = document.getElementById("render-download-btn");
  const renderCloseBtn = document.getElementById("render-close-btn");

  // Project save/load
  const btnSave = document.getElementById("btn-save-project");
  const btnLoad = document.getElementById("btn-load-project");
  const projectsOverlay = document.getElementById("projects-overlay");
  const projectsClose = document.getElementById("projects-close");
  const projectsListCont = document.getElementById("projects-list-container");
  const templatesListCont = document.getElementById("templates-list-container");

  // Orientation
  const orientBtns = document.querySelectorAll(".orient-btn");
  const imageProviderSelect = document.getElementById("image-provider-select");

  // API Keys
  const btnKeys = document.getElementById("btn-keys");
  const keysOverlay = document.getElementById("keys-overlay");
  const keysClose = document.getElementById("keys-close");
  const btnKeysSave = document.getElementById("btn-keys-save");
  const btnKeysClear = document.getElementById("btn-keys-clear");
  const keysForm = document.getElementById("keys-form");

  // Toast container
  const toastContainer = document.createElement("div");
  toastContainer.className = "toast-container";
  document.body.appendChild(toastContainer);

  // ── Init ─────────────────────────────────────────────────────────────
  async function init() {
    await Promise.all([
      loadVoices(),
      loadAnimations(),
      loadTransitions(),
      loadImageProviders(),
    ]);
    loadApiKeys();
    bindGlobalEvents();
  }

  function loadApiKeys() {
    try {
      const stored = localStorage.getItem("explainer_api_keys");
      if (stored) {
        apiKeys = JSON.parse(stored);
      }
    } catch {
      apiKeys = {};
    }
    // Update inputs in modal
    if (keysForm) {
      keysForm.querySelectorAll("input").forEach(input => {
        const k = input.dataset.key;
        if (apiKeys[k]) input.value = apiKeys[k];
      });
    }
  }

  function saveApiKeys() {
    if (!keysForm) return;
    const newKeys = {};
    keysForm.querySelectorAll("input").forEach(input => {
      const k = input.dataset.key;
      const v = input.value.trim();
      if (v) newKeys[k] = v;
    });
    apiKeys = newKeys;
    localStorage.setItem("explainer_api_keys", JSON.stringify(apiKeys));
    showToast("API keys saved locally.", "success");
    keysOverlay.classList.remove("active");
  }

  async function loadImageProviders() {
    try {
      imageProviders = await (await fetch("/api/image-providers")).json();
    } catch {
      imageProviders = [];
    }
    if (!imageProviderSelect) return;
    imageProviderSelect.innerHTML = "";
    if (!imageProviders.length) {
      const o = document.createElement("option");
      o.value = "pollinations";
      o.textContent = "Pollinations.ai";
      imageProviderSelect.appendChild(o);
      return;
    }
    imageProviders.forEach((p) => {
      const o = document.createElement("option");
      o.value = p.id;
      o.textContent = p.name + (p.requires_api_key ? " · key" : "");
      o.title = p.description || "";
      imageProviderSelect.appendChild(o);
    });
    const saved = localStorage.getItem("explainer_image_provider");
    if (saved && [...imageProviderSelect.options].some((x) => x.value === saved))
      imageProviderSelect.value = saved;
  }

  async function loadVoices() {
    try {
      voices = await (await fetch("/api/voices")).json();
    } catch {
      voices = [{ id: "en-US-JennyNeural", name: "Jenny (US Female)" }];
    }
  }

  async function loadAnimations() {
    try {
      animations = await (await fetch("/api/animations")).json();
    } catch {
      animations = [{ id: "ken_burns", name: "Ken Burns" }];
    }
  }

  async function loadTransitions() {
    try {
      transitions = await (await fetch("/api/transitions")).json();
    } catch {
      transitions = [{ id: "crossfade", name: "Crossfade" }];
    }
  }

  function bindGlobalEvents() {
    btnAddScene.addEventListener("click", () => addScene());
    btnRender.addEventListener("click", startRender);

    if (imageProviderSelect) {
      imageProviderSelect.addEventListener("change", () => {
        localStorage.setItem(
          "explainer_image_provider",
          imageProviderSelect.value,
        );
      });
    }

    btnGuide.addEventListener("click", () =>
      guideOverlay.classList.add("active"),
    );
    guideClose.addEventListener("click", () =>
      guideOverlay.classList.remove("active"),
    );
    guideOverlay.addEventListener("click", (e) => {
      if (e.target === guideOverlay) guideOverlay.classList.remove("active");
    });

    renderCloseBtn.addEventListener("click", () =>
      renderOverlay.classList.remove("active"),
    );
    renderOverlay.addEventListener("click", (e) => {
      if (
        e.target === renderOverlay &&
        !renderCloseBtn.classList.contains("hidden")
      )
        renderOverlay.classList.remove("active");
    });

    // Orientation toggle
    orientBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        orientBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentOrientation = btn.dataset.orient;
      });
    });

    // Save / Load
    btnSave.addEventListener("click", saveProject);
    btnLoad.addEventListener("click", openProjectsModal);
    projectsClose.addEventListener("click", () =>
      projectsOverlay.classList.remove("active"),
    );
    projectsOverlay.addEventListener("click", (e) => {
      if (e.target === projectsOverlay)
        projectsOverlay.classList.remove("active");
    });

    // Logo upload
    if (logoUploadInput) {
      logoUploadInput.addEventListener("change", async () => {
        if (!logoUploadInput.files || logoUploadInput.files.length === 0)
          return;
        const f = logoUploadInput.files[0];
        const fd = new FormData();
        fd.append("file", f);
        try {
          showToast("Uploading logo…", "info");
          const res = await fetch("/api/upload-logo", {
            method: "POST",
            body: fd,
          });
          if (!res.ok) throw new Error("Logo upload failed");
          const data = await res.json();
          globalLogoUrl = data.url;
          if (logoUploadText) logoUploadText.textContent = "Logo Ready";
          if (btnRemoveLogo) btnRemoveLogo.classList.remove("hidden");
          showToast(
            "Logo uploaded! It will appear on the final render.",
            "success",
          );
        } catch (e) {
          showToast(e.message || "Logo upload failed.", "error");
        }
      });
    }

    if (btnRemoveLogo) {
      btnRemoveLogo.addEventListener("click", () => {
        globalLogoUrl = null;
        logoUploadInput.value = "";
        if (logoUploadText) logoUploadText.textContent = "Upload Logo";
        btnRemoveLogo.classList.add("hidden");
        showToast("Logo removed.", "info");
      });
    }

    // API Keys logic
    if (btnKeys) {
      btnKeys.addEventListener("click", () => {
        loadApiKeys();
        keysOverlay.classList.add("active");
      });
    }
    if (keysClose) {
      keysClose.addEventListener("click", () => keysOverlay.classList.remove("active"));
    }
    if (keysOverlay) {
      keysOverlay.addEventListener("click", (e) => {
        if (e.target === keysOverlay) keysOverlay.classList.remove("active");
      });
    }
    if (btnKeysSave) {
      btnKeysSave.addEventListener("click", saveApiKeys);
    }
    if (btnKeysClear) {
      btnKeysClear.addEventListener("click", () => {
        if (confirm("Clear all locally saved API keys?")) {
          apiKeys = {};
          localStorage.removeItem("explainer_api_keys");
          keysForm.querySelectorAll("input").forEach(i => i.value = "");
          showToast("API keys cleared.", "info");
        }
      });
    }
  }

  // ── Toasts ───────────────────────────────────────────────────────────
  function fmtDurationSeconds(sec) {
    if (sec == null || Number.isNaN(sec)) return "—";
    const n = Math.max(0, Math.round(Number(sec)));
    if (n < 60) return `${n}s`;
    const m = Math.floor(n / 60);
    const s = n % 60;
    return s ? `${m}m ${s}s` : `${m}m`;
  }

  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 3600);
  }

  // ── UI Sync ──────────────────────────────────────────────────────────
  function syncUI() {
    const count = scenes.length;
    sceneCountEl.textContent = `${count} scene${count !== 1 ? "s" : ""}`;
    emptyState.classList.toggle("hidden", count > 0);
    sceneList.classList.toggle("hidden", count === 0);

    const allReady =
      count > 0 &&
      scenes.every((s) => (s.audioReady || s.muteAudio) && s.visualReady);
    btnRender.disabled = !allReady;

    scenes.forEach((s) => {
      const card = document.querySelector(
        `.scene-card[data-scene-id="${s.id}"]`,
      );
      if (!card) return;
      const ab = card.querySelector('[data-badge="audio"]');
      const vb = card.querySelector('[data-badge="visual"]');
      ab.className = `badge ${s.audioReady || s.muteAudio ? "badge-ready" : "badge-pending"}`;
      vb.className = `badge ${s.visualReady ? "badge-ready" : "badge-pending"}`;
    });
  }

  // ── Add Scene ────────────────────────────────────────────────────────
  function addScene(prefill = {}) {
    sceneCounter++;
    const id = `scene-${Date.now()}-${sceneCounter}`;

    const state = {
      id,
      number: sceneCounter,
      sceneIdServer: prefill.scene_id || null,
      audioReady: !!prefill.has_audio,
      visualReady: !!prefill.has_visual,
      mediaType: prefill.media_type || "image",
      animation: prefill.animation || "ken_burns",
      transition: prefill.transition || "crossfade",
      volume: prefill.volume ?? 1.0,
      muteAudio: prefill.mute_audio || false,
      showSubtitles: false,
      subtitleOverride: prefill.subtitle || "",
      animateUpload: true,
      geminiSource: false,
    };
    scenes.push(state);

    const fragment = sceneTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".scene-card");
    card.dataset.sceneId = id;
    card.querySelector(".scene-number").textContent = sceneCounter;

    // Populate voice selector
    const voiceSelect = card.querySelector(".voice-select");
    voices.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.name;
      voiceSelect.appendChild(opt);
    });

    // Populate animation selector
    const animSel = card.querySelector(".animation-select");
    animations.forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = `${a.name}`;
      opt.title = a.description;
      if (a.id === state.animation) opt.selected = true;
      animSel.appendChild(opt);
    });

    // Populate transition selector
    const transSel = card.querySelector(".transition-select");
    transitions.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = `${t.name}`;
      opt.title = t.description;
      if (t.id === state.transition) opt.selected = true;
      transSel.appendChild(opt);
    });

    // Pre-fill text fields
    if (prefill.narration)
      card.querySelector(".scene-text").value = prefill.narration;
    if (prefill.image_prompt)
      card.querySelector(".image-prompt-input").value = prefill.image_prompt;

    // Audio controls
    const muteCb = card.querySelector(".audio-mute-cb");
    const volumeSlider = card.querySelector(".volume-slider");
    const volumeLabel = card.querySelector(".volume-label");
    muteCb.checked = state.muteAudio;
    volumeSlider.value = Math.round(state.volume * 100);
    volumeLabel.textContent = `${Math.round(state.volume * 100)}%`;

    bindSceneEvents(card, state);
    sceneList.appendChild(card);
    syncUI();
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function bindSceneEvents(card, state) {
    card.querySelector(".scene-delete").addEventListener("click", () => {
      scenes = scenes.filter((s) => s.id !== state.id);
      card.style.animation = "slideOut 0.25s ease forwards";
      card.addEventListener("animationend", () => {
        card.remove();
        syncUI();
      });
    });

    card
      .querySelector(".generate-audio-btn")
      .addEventListener("click", () => generateAudio(card, state));
    card
      .querySelector(".generate-image-btn")
      .addEventListener("click", () => generateImage(card, state));

    const uploadInput = card.querySelector(".upload-input");
    uploadInput.addEventListener("change", () => {
      if (uploadInput.files.length > 0)
        uploadMedia(card, state, uploadInput.files[0]);
    });

    const uploadAudioInput = card.querySelector(".upload-audio-input");
    uploadAudioInput.addEventListener("change", () => {
      if (uploadAudioInput.files.length > 0)
        uploadMedia(card, state, uploadAudioInput.files[0]);
    });

    // Animation & transition
    card.querySelector(".animation-select").addEventListener("change", (e) => {
      state.animation = e.target.value;
    });
    card.querySelector(".transition-select").addEventListener("change", (e) => {
      state.transition = e.target.value;
    });

    // Subtitles toggle and override
    const subsCb = card.querySelector(".subtitles-cb");
    const subsInput = card.querySelector(".subtitle-input");
    if (subsCb) {
      subsCb.addEventListener("change", () => {
        state.showSubtitles = subsCb.checked;
      });
    }
    if (subsInput) {
      subsInput.addEventListener("input", () => {
        state.subtitleOverride = subsInput.value.trim();
      });
    }

    // Animate uploaded image toggle
    const animCb = card.querySelector(".animate-upload-cb");
    if (animCb) {
      animCb.checked = state.animateUpload;
      animCb.addEventListener("change", () => {
        state.animateUpload = animCb.checked;
        if (state.animateUpload)
          state.animation = state.animation || "ken_burns";
        else state.animation = "none";
      });
    }

    // Gemini watermark removal toggle
    const geminiCb = card.querySelector(".gemini-source-cb");
    if (geminiCb) {
      geminiCb.checked = state.geminiSource;
      geminiCb.addEventListener("change", () => {
        state.geminiSource = geminiCb.checked;
      });
    }

    // Audio mute
    const muteCb = card.querySelector(".audio-mute-cb");
    muteCb.addEventListener("change", () => {
      state.muteAudio = muteCb.checked;
      syncUI();
    });

    // Volume slider
    const volumeSlider = card.querySelector(".volume-slider");
    const volumeLabel = card.querySelector(".volume-label");
    volumeSlider.addEventListener("input", () => {
      const pct = parseInt(volumeSlider.value);
      state.volume = pct / 100;
      volumeLabel.textContent = `${pct}%`;
    });
  }

  // ── Generate Audio ───────────────────────────────────────────────────
  async function generateAudio(card, state) {
    const text = card.querySelector(".scene-text").value.trim();
    if (!text) {
      showToast("Please enter narration text first.", "error");
      return;
    }

    const voice = card.querySelector(".voice-select").value;
    showSceneLoading(card, "Generating voiceover…");

    try {
      const form = new FormData();
      form.append("text", text);
      form.append("voice", voice);
      if (state.sceneIdServer) form.append("scene_id", state.sceneIdServer);

      const res = await fetch("/api/generate-audio", {
        method: "POST",
        body: form,
      });
      if (!res.ok)
        throw new Error(
          (await res.json()).detail || "Audio generation failed.",
        );

      const data = await res.json();
      state.sceneIdServer = data.scene_id;
      state.audioReady = true;

      const audioPreview = card.querySelector(".audio-preview");
      card.querySelector(".audio-player").src =
        data.audio_url + `?t=${Date.now()}`;
      audioPreview.classList.remove("hidden");
      showToast("Voiceover generated!", "success");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      hideSceneLoading(card);
      syncUI();
    }
  }

  // ── Generate Image ───────────────────────────────────────────────────
  async function generateImage(card, state) {
    const prompt = card.querySelector(".image-prompt-input").value.trim();
    if (!prompt) {
      showToast("Please enter an image description.", "error");
      return;
    }

    showSceneLoading(card, "Generating AI image…");
    const dims =
      currentOrientation === "portrait"
        ? { w: 1080, h: 1920 }
        : { w: 1920, h: 1080 };

    try {
      const form = new FormData();
      form.append("prompt", prompt);
      form.append("width", dims.w);
      form.append("height", dims.h);
      if (imageProviderSelect)
        form.append("provider", imageProviderSelect.value);
      
      // Determine which key to send
      let keyToSend = null;
      const provider = imageProviderSelect?.value || "pollinations";
      if (provider === "openai") keyToSend = apiKeys["OPENAI_API_KEY"];
      else if (provider === "together") keyToSend = apiKeys["TOGETHER_API_KEY"];
      else if (provider === "huggingface_flux") keyToSend = apiKeys["HF_TOKEN"];
      else if (provider === "deepai") keyToSend = apiKeys["DEEPAI_API_KEY"];
      else if (provider === "stable_horde") keyToSend = apiKeys["STABLE_HORDE_API_KEY"];
      else if (provider.startsWith("gemini") || provider === "imagen_fast") keyToSend = apiKeys["GEMINI_API_KEY"];
      
      if (keyToSend) form.append("api_key", keyToSend);

      if (state.sceneIdServer) form.append("scene_id", state.sceneIdServer);

      const res = await fetch("/api/generate-image", {
        method: "POST",
        body: form,
      });
      if (!res.ok)
        throw new Error(
          (await res.json()).detail || "Image generation failed.",
        );

      const data = await res.json();
      state.sceneIdServer = data.scene_id;
      state.visualReady = true;
      state.mediaType = "image";
      state.geminiSource = !!data.gemini_source;
      // Sync the per-scene checkbox to match the auto-detected value
      const geminiCb = card.querySelector(".gemini-source-cb");
      if (geminiCb) geminiCb.checked = state.geminiSource;
      showImagePreview(card, data.image_url, state.animateUpload);
      showToast("AI image generated!", "success");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      hideSceneLoading(card);
      syncUI();
    }
  }

  // ── Upload Media ─────────────────────────────────────────────────────
  async function uploadMedia(card, state, file) {
    showSceneLoading(card, "Uploading file…");
    try {
      const form = new FormData();
      form.append("file", file);
      if (state.sceneIdServer) form.append("scene_id", state.sceneIdServer);

      const res = await fetch("/api/upload-media", {
        method: "POST",
        body: form,
      });
      if (!res.ok)
        throw new Error((await res.json()).detail || "Upload failed.");

      const data = await res.json();
      state.sceneIdServer = data.scene_id;

      if (data.media_type === "audio") {
        state.audioReady = true;
        const audioPreview = card.querySelector(".audio-preview");
        const audioPlayer = card.querySelector(".audio-player");
        audioPlayer.src = data.media_url + `?t=${Date.now()}`;
        audioPreview.classList.remove("hidden");
        showToast("Audio uploaded!", "success");
      } else {
        state.visualReady = true;
        state.mediaType = data.media_type;
        if (data.media_type === "video") showVideoPreview(card, data.media_url);
        else showImagePreview(card, data.media_url, state.animateUpload);
        showToast("Visual media uploaded!", "success");
      }
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      hideSceneLoading(card);
      syncUI();
    }
  }

  // ── Preview Helpers ──────────────────────────────────────────────────
  async function detectImageExtension(sceneId) {
    const extensions = ['.jpg', '.jpeg', '.png', '.webp', '.bmp'];
    for (const ext of extensions) {
      try {
        const res = await fetch(`/api/media/${sceneId}/image${ext}`);
        if (res.ok) {
          console.log(`Found image with extension: ${ext}`);
          return ext;
        }
      } catch (e) {
        console.log(`Extension ${ext} not found for scene ${sceneId}`);
      }
    }
    console.log(`No image found for scene ${sceneId}, defaulting to .jpg`);
    return '.jpg';
  }

  function showImagePreview(card, url, animate = false) {
    const c = card.querySelector(".visual-preview");
    const img = card.querySelector(".preview-image");
    const vid = card.querySelector(".preview-video");
    // reset + cache-bust
    img.classList.remove("preview-animate");
    void img.offsetWidth; // force reflow so animation restarts
    img.src = url + `?t=${Date.now()}`;
    if (animate) img.classList.add("preview-animate");
    img.classList.remove("hidden");
    vid.classList.add("hidden");
    c.classList.remove("hidden");
  }

  function showVideoPreview(card, url) {
    const c = card.querySelector(".visual-preview");
    const img = card.querySelector(".preview-image");
    const vid = card.querySelector(".preview-video");
    vid.src = url + `?t=${Date.now()}`;
    vid.classList.remove("hidden");
    img.classList.add("hidden");
    c.classList.remove("hidden");
  }

  function showSceneLoading(card, text = "Generating…") {
    const o = card.querySelector(".scene-loading");
    o.querySelector(".scene-loading-text").textContent = text;
    o.classList.remove("hidden");
  }

  function hideSceneLoading(card) {
    card.querySelector(".scene-loading").classList.add("hidden");
  }

  // ── Render Video ─────────────────────────────────────────────────────
  async function startRender() {
    const scenesData = scenes
      .filter((s) => (s.audioReady || s.muteAudio) && s.visualReady)
      .map((s) => {
        const card = document.querySelector(
          `.scene-card[data-scene-id="${s.id}"]`,
        );
        const narration = card
          ? card.querySelector(".scene-text").value.trim()
          : "";
        return {
          scene_id: s.sceneIdServer,
          media_type: s.mediaType,
          animation: s.animation,
          transition: s.transition,
          volume: s.volume,
          mute_audio: s.muteAudio,
          narration: narration,
          show_subtitles: !!s.showSubtitles,
          subtitle: s.subtitleOverride || narration,
          gemini_source: !!s.geminiSource,
        };
      });

    if (!scenesData.length) {
      showToast("All scenes need audio/visuals before rendering.", "error");
      return;
    }

    renderOverlay.classList.add("active");
    renderStatusText.textContent = "Preparing render…";
    renderEstimateLine.textContent = "";
    renderProgressBar.style.width = "0%";
    renderDownloadBtn.classList.add("hidden");
    renderCloseBtn.classList.add("hidden");
    const renderEtaEl = document.getElementById("render-eta");
    renderEtaEl.style.display = "none";
    renderEtaEl.textContent = "";
    renderOverlay.querySelector(".render-spinner").classList.remove("hidden");

    try {
      const form = new FormData();
      form.append("scenes", JSON.stringify(scenesData));
      form.append("orientation", currentOrientation);
      form.append(
        "render_preset",
        document.getElementById("render-preset").value,
      );
      if (globalLogoUrl) form.append("logo_url", globalLogoUrl);
      if (logoPositionSelect)
        form.append(
          "logo_position",
          logoPositionSelect.value || "bottom-right",
        );

      const res = await fetch("/api/render", { method: "POST", body: form });
      if (!res.ok)
        throw new Error((await res.json()).detail || "Render failed.");

      const data = await res.json();
      const {
        job_id,
        output_duration_seconds,
        estimated_render_seconds,
        render_preset,
      } = data;
      const presetLabel = render_preset || "balanced";
      renderEstimateLine.textContent = `Output length ~${fmtDurationSeconds(output_duration_seconds)} · Est. total render ~${fmtDurationSeconds(estimated_render_seconds)} (${presetLabel})`;
      pollRenderStatus(job_id);
    } catch (e) {
      renderStatusText.textContent = "Render failed";
      renderEstimateLine.textContent = e.message;
      renderOverlay.querySelector(".render-spinner").classList.add("hidden");
      renderCloseBtn.classList.remove("hidden");
    }
  }

  async function pollRenderStatus(jobId) {
    const poll = async () => {
      try {
        const data = await (await fetch(`/api/render-status/${jobId}`)).json();
        if (data.progress !== undefined)
          renderProgressBar.style.width = data.progress + "%";

        const etaEl = document.getElementById("render-eta");
        if (data.eta_seconds !== undefined && data.eta_seconds > 0) {
          const rem = data.eta_seconds;
          const m = Math.floor(rem / 60);
          const s = rem % 60;
          const clock = new Date(Date.now() + rem * 1000).toLocaleTimeString(
            [],
            { hour: "numeric", minute: "2-digit" },
          );
          const leftStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
          etaEl.style.display = "block";
          etaEl.textContent = `~${leftStr} remaining · estimated finish around ${clock}`;
        } else {
          etaEl.style.display = "none";
        }

        if (data.status === "done") {
          renderStatusText.textContent = "Video ready! 🎉";
          renderEstimateLine.textContent =
            "Rendering complete. Download your video below.";
          etaEl.style.display = "none";
          renderProgressBar.style.width = "100%";
          renderOverlay
            .querySelector(".render-spinner")
            .classList.add("hidden");
          renderDownloadBtn.href = data.output_url;
          renderDownloadBtn.classList.remove("hidden");
          renderCloseBtn.classList.remove("hidden");
          showToast("Video rendered successfully!", "success");
          return;
        }
        if (data.status === "error") {
          renderStatusText.textContent = "Render failed";
          renderEstimateLine.textContent = data.error || "Unknown error.";
          etaEl.style.display = "none";
          renderOverlay
            .querySelector(".render-spinner")
            .classList.add("hidden");
          renderCloseBtn.classList.remove("hidden");
          showToast("Render failed.", "error");
          return;
        }
        renderStatusText.textContent =
          data.status === "rendering" ? "Rendering video…" : "Queued…";
        setTimeout(poll, 1500);
      } catch {
        setTimeout(poll, 3000);
      }
    };
    poll();
  }

  // ── Project Save ─────────────────────────────────────────────────────
  async function saveProject() {
    const projectData = {
      id: currentProjectId,
      name: projectNameInput.value.trim() || "Untitled Project",
      orientation: currentOrientation,
      image_provider: imageProviderSelect ? imageProviderSelect.value : "pollinations",
      scenes: scenes.map((s) => {
        const card = document.querySelector(
          `.scene-card[data-scene-id="${s.id}"]`,
        );
        return {
          scene_id: s.sceneIdServer,
          narration: card ? card.querySelector(".scene-text").value : "",
          image_prompt: card
            ? card.querySelector(".image-prompt-input").value
            : "",
          animation: s.animation,
          transition: s.transition,
          volume: s.volume,
          mute_audio: s.muteAudio,
          media_type: s.mediaType,
          has_audio: s.audioReady,
          has_visual: s.visualReady,
        };
      }),
    };

    try {
      const form = new FormData();
      form.append("payload", JSON.stringify(projectData));
      const res = await fetch("/api/projects/save", {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error("Save failed.");
      const saved = await res.json();
      currentProjectId = saved.id;
      showToast("Project saved!", "success");
    } catch (e) {
      showToast(e.message, "error");
    }
  }

  // ── Project Load Modal ───────────────────────────────────────────────
  async function openProjectsModal() {
    projectsOverlay.classList.add("active");
    projectsListCont.innerHTML =
      '<p class="loading-text">Loading projects…</p>';
    templatesListCont.innerHTML =
      '<p class="loading-text">Loading templates…</p>';

    try {
      const [projects, templates] = await Promise.all([
        fetch("/api/projects").then((r) => r.json()),
        fetch("/api/templates").then((r) => r.json()),
      ]);

      if (projects.length === 0) {
        projectsListCont.innerHTML =
          '<p class="empty-text">No saved projects yet.</p>';
      } else {
        projectsListCont.innerHTML = projects
          .map(
            (p) => `
                    <div class="project-item" data-id="${p.id}">
                        <div class="project-item-info">
                            <span class="project-item-name">${p.name}</span>
                            <span class="project-item-meta">${p.scene_count} scenes · ${p.orientation}</span>
                        </div>
                        <div class="project-item-actions">
                            <button class="btn btn-sm btn-accent load-project-btn" data-id="${p.id}">Load</button>
                            <button class="btn btn-sm btn-ghost delete-project-btn" data-id="${p.id}">×</button>
                        </div>
                    </div>
                `,
          )
          .join("");

        projectsListCont
          .querySelectorAll(".load-project-btn")
          .forEach((btn) => {
            btn.addEventListener("click", () => loadProject(btn.dataset.id));
          });
        projectsListCont
          .querySelectorAll(".delete-project-btn")
          .forEach((btn) => {
            btn.addEventListener("click", async () => {
              await fetch(`/api/projects/${btn.dataset.id}`, {
                method: "DELETE",
              });
              btn.closest(".project-item").remove();
              showToast("Project deleted.", "info");
            });
          });
      }

      templatesListCont.innerHTML = templates
        .map(
          (t) => `
                <div class="template-item" data-id="${t.id}">
                    <div class="template-item-info">
                        <span class="template-item-name">${t.name}</span>
                        <span class="template-item-desc">${t.description}</span>
                    </div>
                    <button class="btn btn-sm btn-outline load-template-btn" data-id="${t.id}">Use</button>
                </div>
            `,
        )
        .join("");

      templatesListCont
        .querySelectorAll(".load-template-btn")
        .forEach((btn) => {
          btn.addEventListener("click", () => loadTemplate(btn.dataset.id));
        });
    } catch (e) {
      projectsListCont.innerHTML =
        '<p class="error-text">Failed to load projects.</p>';
      templatesListCont.innerHTML =
        '<p class="error-text">Failed to load templates.</p>';
    }
  }

  async function loadProject(projId) {
    try {
      console.log(`Loading project: ${projId}`);
      const proj = await (await fetch(`/api/projects/${projId}`)).json();
      console.log("Project data:", proj);
      
      clearAllScenes();
      currentProjectId = proj.id;
      projectNameInput.value = proj.name || "Untitled Project";
      currentOrientation = proj.orientation || "landscape";
      orientBtns.forEach((b) =>
        b.classList.toggle("active", b.dataset.orient === currentOrientation),
      );

      if (imageProviderSelect && proj.image_provider) {
        if (
          [...imageProviderSelect.options].some((o) => o.value === proj.image_provider)
        ) {
          imageProviderSelect.value = proj.image_provider;
          localStorage.setItem("explainer_image_provider", proj.image_provider);
        }
      }

      for (const s of proj.scenes) {
        addScene(s);
      }
      
      // Small delay to ensure DOM is ready
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Restore media previews for loaded scenes
      for (let i = 0; i < proj.scenes.length; i++) {
        const s = proj.scenes[i];
        console.log(`Processing scene ${i}:`, s);
        
        if (!s.scene_id) {
          console.log(`Scene ${i} has no scene_id, skipping`);
          continue;
        }
        
        const sceneState = scenes[i];
        const card = document.querySelector(`.scene-card[data-scene-id="${sceneState.id}"]`);
        console.log(`Card for scene ${i}:`, card);
        
        if (!card) {
          console.log(`No card found for scene ${i}`);
          continue;
        }
        
        // Restore audio
        if (s.has_audio) {
          console.log(`Restoring audio for scene ${i}`);
          const audioPreview = card.querySelector(".audio-preview");
          const audioPlayer = card.querySelector(".audio-player");
          if (audioPreview && audioPlayer) {
            audioPlayer.src = `/api/media/${s.scene_id}/voiceover.mp3?t=${Date.now()}`;
            audioPreview.classList.remove("hidden");
            console.log(`Audio restored for scene ${i}`);
          }
        }
        
        // Restore visual
        if (s.has_visual) {
          console.log(`Restoring visual for scene ${i}`);
          const visualPreview = card.querySelector(".visual-preview");
          if (!visualPreview) {
            console.log(`No visual-preview found for scene ${i}`);
            continue;
          }
          
          if (s.media_type === "video") {
            const videoEl = card.querySelector(".preview-video");
            const imgEl = card.querySelector(".preview-image");
            if (videoEl && imgEl) {
              videoEl.src = `/api/media/${s.scene_id}/video.mp4?t=${Date.now()}`;
              videoEl.classList.remove("hidden");
              imgEl.classList.add("hidden");
              visualPreview.classList.remove("hidden");
              console.log(`Video restored for scene ${i}`);
            }
          } else {
            const ext = await detectImageExtension(s.scene_id);
            const imgEl = card.querySelector(".preview-image");
            const videoEl = card.querySelector(".preview-video");
            if (imgEl && videoEl) {
              imgEl.src = `/api/media/${s.scene_id}/image${ext}?t=${Date.now()}`;
              imgEl.classList.remove("hidden");
              videoEl.classList.add("hidden");
              if (s.animation !== "none") imgEl.classList.add("preview-animate");
              visualPreview.classList.remove("hidden");
              console.log(`Image restored for scene ${i} with extension ${ext}`);
            }
          }
        }
      }
      
      syncUI();
      projectsOverlay.classList.remove("active");
      showToast("Project loaded!", "success");
      console.log("Project loaded successfully");
    } catch (e) {
      console.error("Load project error:", e);
      showToast("Failed to load project.", "error");
    }
  }

  async function loadTemplate(tplId) {
    try {
      const tpl = await (await fetch(`/api/templates/${tplId}`)).json();
      clearAllScenes();
      currentProjectId = null;
      projectNameInput.value = tpl.name;
      currentOrientation = tpl.orientation || "landscape";
      orientBtns.forEach((b) =>
        b.classList.toggle("active", b.dataset.orient === currentOrientation),
      );

      for (const s of tpl.scenes) addScene(s);
      projectsOverlay.classList.remove("active");
      showToast(`Template "${tpl.name}" loaded!`, "success");
    } catch (e) {
      showToast("Failed to load template.", "error");
    }
  }

  function clearAllScenes() {
    scenes = [];
    sceneCounter = 0;
    sceneList.innerHTML = "";
    syncUI();
  }

  // ── CSS for scene removal ────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
        @keyframes slideOut {
            from { opacity: 1; transform: translateY(0); }
            to   { opacity: 0; transform: translateY(-16px); height: 0; margin: 0; padding: 0; overflow: hidden; }
        }
    `;
  document.head.appendChild(style);

  // ── Start ────────────────────────────────────────────────────────────
  init();
})();
