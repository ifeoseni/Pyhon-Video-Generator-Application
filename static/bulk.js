/* ═══════════════════════════════════════════════════════════════════════════
   ExplainerAI — Bulk Mode Frontend Logic
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
    "use strict";

    // ── State ────────────────────────────────────────────────────────────
    let voices = [];
    let animations = [];
    let transitions = [];
    let parsedScenes = [];
    let currentOrientation = "landscape";
    let imageSource = "ai";
    let apiKeys = {};

    // ── DOM ──────────────────────────────────────────────────────────────
    const steps = [1, 2, 3, 4].map(n => document.getElementById(`step-${n}`));
    const wizardSteps = document.querySelectorAll(".wizard-step");

    const voiceSelect       = document.getElementById("bulk-voice");
    const bulkImageProvider = document.getElementById("bulk-image-provider");
    const bulkRenderPreset  = document.getElementById("bulk-render-preset");
    const templateSelect    = document.getElementById("bulk-template-select");
    const btnLoadTemplate   = document.getElementById("btn-load-template");
    const orientBtns        = document.querySelectorAll("#bulk-orient-toggle .orient-btn");
    const radioCards        = document.querySelectorAll("#bulk-image-source .radio-card");

    const bulkScript        = document.getElementById("bulk-script");
    const previewList       = document.getElementById("bulk-preview-list");

    const btnToStep2        = document.getElementById("btn-to-step-2");
    const btnBackTo1        = document.getElementById("btn-back-to-1");
    const btnToStep3        = document.getElementById("btn-to-step-3");
    const btnBackTo2        = document.getElementById("btn-back-to-2");
    const btnToStep4        = document.getElementById("btn-to-step-4");

    const btnStartBulk      = document.getElementById("btn-start-bulk");
    const bulkSpinner       = document.getElementById("bulk-spinner");
    const bulkProgressSec   = document.getElementById("bulk-progress-section");
    const bulkProgressBar   = document.getElementById("bulk-progress-bar");
    const bulkStepLabel     = document.getElementById("bulk-step-label");
    const bulkGenTitle      = document.getElementById("bulk-gen-title");
    const bulkGenDesc       = document.getElementById("bulk-gen-desc");
    const bulkDownloadBtn   = document.getElementById("bulk-download-btn");
    const btnBulkReset      = document.getElementById("btn-bulk-reset");

    // API Keys
    const btnKeys           = document.getElementById("btn-keys");
    const keysOverlay      = document.getElementById("keys-overlay");
    const keysClose        = document.getElementById("keys-close");
    const btnKeysSave      = document.getElementById("btn-keys-save");
    const btnKeysClear      = document.getElementById("btn-keys-clear");
    const keysForm         = document.getElementById("keys-form");

    // Toast
    const toastContainer = document.createElement("div");
    toastContainer.className = "toast-container";
    document.body.appendChild(toastContainer);

    function fmtDurationSeconds(sec) {
        if (sec == null || Number.isNaN(sec)) return "—";
        const n = Math.max(0, Math.round(Number(sec)));
        if (n < 60) return `${n}s`;
        const m = Math.floor(n / 60);
        const s = n % 60;
        return s ? `${m}m ${s}s` : `${m}m`;
    }

    function showToast(msg, type = "info") {
        const t = document.createElement("div");
        t.className = `toast toast-${type}`;
        t.textContent = msg;
        toastContainer.appendChild(t);
        setTimeout(() => t.remove(), 3600);
    }

    // ── Init ─────────────────────────────────────────────────────────────
    async function init() {
        await Promise.all([loadVoices(), loadImageProviders(), loadAnimations(), loadTransitions(), loadTemplates()]);
        loadApiKeys();
        bindEvents();
    }

    function loadApiKeys() {
        try {
            const stored = localStorage.getItem("explainer_api_keys");
            if (stored) apiKeys = JSON.parse(stored);
        } catch { apiKeys = {}; }
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

    function getApiKeyForProvider(provider) {
        if (!provider) return null;
        if (provider === "openai") return apiKeys["OPENAI_API_KEY"];
        if (provider === "together") return apiKeys["TOGETHER_API_KEY"];
        if (provider === "huggingface_flux") return apiKeys["HF_TOKEN"];
        if (provider === "deepai") return apiKeys["DEEPAI_API_KEY"];
        if (provider === "stable_horde") return apiKeys["STABLE_HORDE_API_KEY"];
        if (provider.startsWith("gemini") || provider === "imagen_fast") return apiKeys["GEMINI_API_KEY"];
        return null;
    }

    async function loadImageProviders() {
        if (!bulkImageProvider) return;
        let list = [];
        try { list = await (await fetch("/api/image-providers")).json(); } catch { list = []; }
        bulkImageProvider.innerHTML = "";
        if (!list.length) {
            const o = document.createElement("option");
            o.value = "pollinations";
            o.textContent = "Pollinations.ai";
            bulkImageProvider.appendChild(o);
            return;
        }
        list.forEach(p => {
            const o = document.createElement("option");
            o.value = p.id;
            o.textContent = p.name + (p.requires_api_key ? " · key" : "");
            o.title = p.description || "";
            bulkImageProvider.appendChild(o);
        });
        const saved = localStorage.getItem("explainer_image_provider");
        if (saved && [...bulkImageProvider.options].some(x => x.value === saved))
            bulkImageProvider.value = saved;
    }

    async function loadVoices() {
        try { voices = await (await fetch("/api/voices")).json(); } catch { voices = []; }
        voices.forEach(v => {
            const o = document.createElement("option"); o.value = v.id; o.textContent = v.name;
            voiceSelect.appendChild(o);
        });
    }

    async function loadAnimations() {
        try { animations = await (await fetch("/api/animations")).json(); } catch { animations = []; }
    }

    async function loadTransitions() {
        try { transitions = await (await fetch("/api/transitions")).json(); } catch { transitions = []; }
    }

    async function loadTemplates() {
        try {
            const templates = await (await fetch("/api/templates")).json();
            templates.forEach(t => {
                const o = document.createElement("option"); o.value = t.id; o.textContent = `${t.name} (${t.scene_count} scenes)`;
                templateSelect.appendChild(o);
            });
        } catch {}
    }

    function bindEvents() {
        // Orientation
        orientBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                orientBtns.forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentOrientation = btn.dataset.orient;
            });
        });

        // Image source
        radioCards.forEach(card => {
            card.addEventListener("click", () => {
                radioCards.forEach(c => c.classList.remove("active"));
                card.classList.add("active");
                card.querySelector("input").checked = true;
                imageSource = card.dataset.src;
            });
        });

        if (bulkImageProvider) {
            bulkImageProvider.addEventListener("change", () => {
                localStorage.setItem("explainer_image_provider", bulkImageProvider.value);
            });
        }

        // Template loader
        btnLoadTemplate.addEventListener("click", loadSelectedTemplate);

        // Step navigation
        btnToStep2.addEventListener("click", () => goToStep(2));
        btnBackTo1.addEventListener("click", () => goToStep(1));
        btnToStep3.addEventListener("click", () => { parseScript(); goToStep(3); });
        btnBackTo2.addEventListener("click", () => goToStep(2));
        btnToStep4.addEventListener("click", () => { collectPreviewEdits(); goToStep(4); });

        // Generate
        btnStartBulk.addEventListener("click", startBulkGenerate);
        btnBulkReset.addEventListener("click", () => { goToStep(1); resetStep4(); });

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
                    if (keysForm) keysForm.querySelectorAll("input").forEach(i => i.value = "");
                    showToast("API keys cleared.", "info");
                }
            });
        }
    }

    // ── Step Navigation ──────────────────────────────────────────────────
    function goToStep(n) {
        steps.forEach((s, i) => s.classList.toggle("hidden", i !== n - 1));
        wizardSteps.forEach(ws => {
            const sn = parseInt(ws.dataset.step);
            ws.classList.toggle("active", sn === n);
            ws.classList.toggle("done", sn < n);
        });
    }

    // ── Template Loader ──────────────────────────────────────────────────
    async function loadSelectedTemplate() {
        const tplId = templateSelect.value;
        if (!tplId) { showToast("Please select a template first.", "error"); return; }

        try {
            const tpl = await (await fetch(`/api/templates/${tplId}`)).json();
            const lines = tpl.scenes.map(s => {
                let block = s.narration || "";
                if (s.image_prompt) block += `\n[IMAGE: ${s.image_prompt}]`;
                return block;
            }).join("\n---\n");

            bulkScript.value = lines;
            document.getElementById("bulk-project-name").value = tpl.name;
            showToast(`Template "${tpl.name}" loaded!`, "success");
        } catch { showToast("Failed to load template.", "error"); }
    }

    // ── Parse Script ─────────────────────────────────────────────────────
    function parseScript() {
        const raw = bulkScript.value.trim();
        if (!raw) { showToast("Please paste a script first.", "error"); return; }

        const blocks = raw.split(/\n---\n|\n---$|^---\n/);
        parsedScenes = blocks.filter(b => b.trim()).map((block, i) => {
            const lines = block.trim().split("\n");
            let narration = [];
            let imagePrompt = "";

            for (const line of lines) {
                const imgMatch = line.match(/^\[IMAGE:\s*(.+?)\]$/i);
                if (imgMatch) {
                    imagePrompt = imgMatch[1].trim();
                } else {
                    narration.push(line);
                }
            }

            return {
                scene_id: "bulk-" + Date.now() + Math.random().toString(36).substr(2, 9),
                index: i,
                narration: narration.join("\n").trim(),
                image_prompt: imagePrompt,
                subtitle: "",
                show_subtitles: false,
                animation: "ken_burns",
                transition: i === 0 ? "none" : "crossfade",
                volume: 1.0,
                mute_audio: false,
                media_url: null,
                media_type: null
            };
        });

        renderPreview();
    }

    function renderPreview() {
        previewList.innerHTML = parsedScenes.map((s, i) => `
            <div class="bulk-preview-item glass" data-index="${i}">
                <div class="bpi-header">
                    <span class="bpi-num">${i + 1}</span>
                    <span class="bpi-title">Scene ${i + 1}</span>
                    <button class="btn-icon bpi-delete" data-index="${i}" title="Remove scene">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>
                <div class="bpi-body">
                    <div class="bpi-col">
                        <label class="setting-label">Narration / Audio</label>
                        <textarea class="bpi-narration" rows="3" placeholder="Type the narration scene…">${s.narration}</textarea>
                        
                        <div class="upload-row" style="margin-top: 0.5rem;">
                            <button class="btn btn-sm btn-accent btn-gen-audio-bpi" data-index="${i}">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
                                Gen Audio
                            </button>
                            <span class="or-divider">OR</span>
                            <div style="position:relative;">
                                <button class="btn btn-sm btn-outline btn-upload-audio-bpi" data-index="${i}">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                                    Upload
                                </button>
                                <input type="file" class="file-audio-input hidden" accept="audio/*" />
                            </div>
                        </div>

                        ${s.audio_url ? `
                            <div class="audio-preview">
                                <audio controls src="${s.audio_url}" class="preview-audio" style="width:100%; height:32px;"></audio>
                            </div>
                        ` : ''}

                        <div class="subtitle-row" style="margin-top: 0.6rem; display: flex; align-items: center; gap: 0.5rem;">
                            <label class="audio-mute-label" style="margin: 0;">
                                <input type="checkbox" class="bpi-show-subs" ${s.show_subtitles ? "checked" : ""} />
                                <span>Subtitles</span>
                            </label>
                            <input type="text" class="bpi-subtitle" value="${s.subtitle || ""}" placeholder="Subtitle override (auto-detects narration)" style="flex: 1; padding: 0.3rem 0.5rem; border-radius: 4px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.2); color: white; font-size: 0.82rem;" />
                        </div>
                    </div>
                    <div class="bpi-col">
                        <label class="setting-label">Visual Content</label>
                        <div class="image-prompt-row">
                            <input type="text" class="bpi-img-prompt" value="${s.image_prompt}" placeholder="Describe the image…" />
                            <button class="btn btn-sm btn-primary btn-generate-bpi" data-index="${i}">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                                Generate
                            </button>
                        </div>
                        <div class="upload-row">
                            <span class="or-divider">OR</span>
                            <div style="position:relative;">
                                <button class="btn btn-sm btn-outline btn-upload-bpi" data-index="${i}">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                                    Upload File
                                </button>
                                <input type="file" class="file-input hidden" accept="image/*,video/*" />
                            </div>
                        </div>

                        ${s.media_url ? `
                            <div class="visual-preview">
                                ${s.media_type === "video" 
                                    ? `<video src="${s.media_url}" class="preview-video" controls></video>`
                                    : `<img src="${s.media_url}" class="preview-image" alt="Scene Visual">`
                                }
                            </div>
                        ` : ''}
                    </div>
                </div>
                <div class="bpi-settings">
                    <div class="setting-group">
                        <label class="setting-label">Animation</label>
                        <select class="bpi-animation">
                            ${animations.map(a => `<option value="${a.id}" ${a.id === s.animation ? "selected" : ""}>${a.name}</option>`).join("")}
                        </select>
                    </div>
                    <div class="setting-group">
                        <label class="setting-label">Transition</label>
                        <select class="bpi-transition">
                            ${transitions.map(t => `<option value="${t.id}" ${t.id === s.transition ? "selected" : ""}>${t.name}</option>`).join("")}
                        </select>
                    </div>
                    <div class="setting-group">
                        <label class="setting-label">Volume</label>
                        <div class="vol-row">
                            <input type="range" class="bpi-volume" min="0" max="200" value="${Math.round(s.volume * 100)}" step="5" />
                            <span class="bpi-vol-label">${Math.round(s.volume * 100)}%</span>
                        </div>
                    </div>
                    <div class="setting-group">
                        <label class="audio-mute-label">
                            <input type="checkbox" class="bpi-mute" ${s.mute_audio ? "checked" : ""} />
                            <span>Mute</span>
                        </label>
                    </div>
                </div>
            </div>
        `).join("");

        // Bind volume labels
        previewList.querySelectorAll(".bpi-volume").forEach(sl => {
            sl.addEventListener("input", () => {
                sl.parentElement.querySelector(".bpi-vol-label").textContent = sl.value + "%";
            });
        });

        // Bind delete
        previewList.querySelectorAll(".bpi-delete").forEach(btn => {
            btn.addEventListener("click", () => {
                const idx = parseInt(btn.dataset.index);
                parsedScenes.splice(idx, 1);
                parsedScenes.forEach((s, i) => s.index = i);
                renderPreview();
            });
        });

        // Bind generate image
        previewList.querySelectorAll(".btn-generate-bpi").forEach(btn => {
            btn.addEventListener("click", async () => {
                const idx = parseInt(btn.dataset.index);
                const s = parsedScenes[idx];
                const item = btn.closest(".bulk-preview-item");
                const prompt = item.querySelector(".bpi-img-prompt").value;
                if (!prompt) { showToast("Enter a prompt first.", "error"); return; }
                
                s.image_prompt = prompt;
                btn.classList.add("hidden");

                try {
                    const form = new FormData();
                    form.append("prompt", prompt);
                    const dims = currentOrientation === "portrait" ? { w: 1080, h: 1920 } : { w: 1920, h: 1080 };
                    form.append("width", String(dims.w));
                    form.append("height", String(dims.h));
                    if (bulkImageProvider) form.append("provider", bulkImageProvider.value);
                    
                    const keyToSend = getApiKeyForProvider(bulkImageProvider?.value);
                    if (keyToSend) form.append("api_key", keyToSend);

                    form.append("scene_id", s.scene_id);

                    const res = await fetch("/api/generate-image", { method: "POST", body: form });
                    const dat = await res.json();
                    
                    s.media_url = dat.image_url;
                    s.media_type = "image";
                    renderPreview();
                } catch {
                    showToast("Generator failed.", "error");
                    btn.classList.remove("hidden");
                }
            });
        });

        // Bind upload image
        previewList.querySelectorAll(".btn-upload-bpi").forEach(btn => {
            const idx = parseInt(btn.dataset.index);
            const s = parsedScenes[idx];
            const fileInput = btn.nextElementSibling;

            btn.addEventListener("click", () => fileInput.click());
            
            fileInput.addEventListener("change", async (e) => {
                const file = e.target.files[0];
                if (!file) return;

                const form = new FormData();
                form.append("file", file);
                form.append("scene_id", s.scene_id);

                try {
                    btn.textContent = "Uploading...";
                    const res = await fetch("/api/upload-media", { method: "POST", body: form });
                    const dat = await res.json();
                    s.media_url = dat.media_url;
                    s.media_type = dat.media_type;
                    renderPreview();
                } catch {
                    showToast("Upload failed.", "error");
                    btn.textContent = "Upload File";
                }
            });
        });

        // Bind generate audio
        previewList.querySelectorAll(".btn-gen-audio-bpi").forEach(btn => {
            btn.addEventListener("click", async () => {
                const idx = parseInt(btn.dataset.index);
                const s = parsedScenes[idx];
                const item = btn.closest(".bulk-preview-item");
                const text = item.querySelector(".bpi-narration").value.trim();
                
                if (!text) { showToast("Enter narration first.", "error"); return; }
                s.narration = text;
                
                btn.classList.add("hidden");

                try {
                    const form = new FormData();
                    form.append("text", text);
                    form.append("voice", voiceSelect.value);
                    form.append("scene_id", s.scene_id);

                    const res = await fetch("/api/generate-audio", { method: "POST", body: form });
                    const dat = await res.json();
                    
                    s.audio_url = dat.audio_url;
                    renderPreview();
                } catch {
                    showToast("Audio generation failed.", "error");
                    btn.classList.remove("hidden");
                }
            });
        });

        // Bind upload audio
        previewList.querySelectorAll(".btn-upload-audio-bpi").forEach(btn => {
            const idx = parseInt(btn.dataset.index);
            const s = parsedScenes[idx];
            const fileInput = btn.nextElementSibling;

            btn.addEventListener("click", () => fileInput.click());
            
            fileInput.addEventListener("change", async (e) => {
                const file = e.target.files[0];
                if (!file) return;

                const form = new FormData();
                form.append("file", file);
                form.append("scene_id", s.scene_id);

                try {
                    btn.textContent = "Uploading...";
                    const res = await fetch("/api/upload-media", { method: "POST", body: form });
                    const dat = await res.json();
                    s.audio_url = dat.media_url;
                    renderPreview();
                } catch {
                    showToast("Audio upload failed.", "error");
                    btn.textContent = "Upload";
                }
            });
        });
    }

    function collectPreviewEdits() {
        const items = previewList.querySelectorAll(".bulk-preview-item");
        items.forEach((item, i) => {
            if (parsedScenes[i]) {
                parsedScenes[i].narration = item.querySelector(".bpi-narration").value.trim();
                parsedScenes[i].image_prompt = item.querySelector(".bpi-img-prompt").value.trim();
                parsedScenes[i].animation = item.querySelector(".bpi-animation").value;
                parsedScenes[i].transition = item.querySelector(".bpi-transition").value;
                parsedScenes[i].volume = parseInt(item.querySelector(".bpi-volume").value) / 100;
                parsedScenes[i].mute_audio = item.querySelector(".bpi-mute").checked;
                parsedScenes[i].show_subtitles = item.querySelector(".bpi-show-subs").checked;
                parsedScenes[i].subtitle = item.querySelector(".bpi-subtitle").value.trim();
            }
        });
    }

    // ── Bulk Generate ────────────────────────────────────────────────────
    async function startBulkGenerate() {
        if (!parsedScenes.length) { showToast("No scenes to generate.", "error"); return; }

        btnStartBulk.classList.add("hidden");
        bulkSpinner.classList.remove("hidden");
        bulkProgressSec.classList.remove("hidden");
        bulkGenTitle.textContent = "Generating…";
        bulkGenDesc.textContent = "Sit back while we create your video.";
        bulkProgressBar.style.width = "0%";

        const payload = {
            orientation: currentOrientation,
            default_voice: voiceSelect.value,
            image_source: imageSource,
            image_provider: bulkImageProvider ? bulkImageProvider.value : "pollinations",
            render_preset: bulkRenderPreset ? bulkRenderPreset.value : "balanced",
            scenes: parsedScenes.map(s => ({
                scene_id: s.scene_id,
                narration: s.narration,
                image_prompt: s.image_prompt,
                animation: s.animation,
                transition: s.transition,
                volume: s.volume,
                mute_audio: s.mute_audio,
                show_subtitles: s.show_subtitles,
                subtitle: s.subtitle,
            })),
        };

        const keyToSend = getApiKeyForProvider(bulkImageProvider?.value);
        if (keyToSend) payload.image_api_key = keyToSend;

        try {
            const form = new FormData();
            form.append("payload", JSON.stringify(payload));

            const res = await fetch("/api/bulk-generate", { method: "POST", body: form });
            if (!res.ok) throw new Error((await res.json()).detail || "Bulk generation failed.");

            const startData = await res.json();
            const { job_id, estimated_total_seconds } = startData;
            if (estimated_total_seconds != null) {
                bulkGenDesc.textContent = `Rough total job time ~${fmtDurationSeconds(estimated_total_seconds)} (varies with APIs and scene count).`;
            }
            pollBulkStatus(job_id);
        } catch (e) {
            bulkGenTitle.textContent = "Generation Failed";
            bulkGenDesc.textContent = e.message;
            bulkSpinner.classList.add("hidden");
            btnBulkReset.classList.remove("hidden");
        }
    }

    async function pollBulkStatus(jobId) {
        const poll = async () => {
            try {
                const data = await (await fetch(`/api/render-status/${jobId}`)).json();
                if (data.progress !== undefined) bulkProgressBar.style.width = data.progress + "%";
                if (data.current_step) document.getElementById("bulk-step-label-main").textContent = data.current_step;

                const bulkEta = document.getElementById("bulk-eta");
                if (data.eta_seconds !== undefined && data.eta_seconds > 0) {
                    const rem = data.eta_seconds;
                    const m = Math.floor(rem / 60);
                    const s = rem % 60;
                    const clock = new Date(Date.now() + rem * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
                    const leftStr = m > 0 ? `${m}m ${s}s` : `${s}s`;
                    bulkEta.style.display = "block";
                    bulkEta.textContent = `~${leftStr} remaining · estimated finish around ${clock}`;
                } else {
                    bulkEta.style.display = "none";
                }

                if (data.status === "done") {
                    bulkGenTitle.textContent = "Video Ready! 🎉";
                    bulkGenDesc.textContent = "Your bulk video has been generated successfully.";
                    bulkProgressBar.style.width = "100%";
                    bulkSpinner.classList.add("hidden");
                    document.getElementById("bulk-step-label-main").textContent = "Complete!";
                    bulkDownloadBtn.href = data.output_url;
                    bulkDownloadBtn.classList.remove("hidden");
                    btnBulkReset.classList.remove("hidden");
                    showToast("Video generated!", "success");
                    return;
                }

                if (data.status === "error") {
                    bulkGenTitle.textContent = "Generation Failed";
                    bulkGenDesc.textContent = data.error || "Unknown error.";
                    bulkSpinner.classList.add("hidden");
                    btnBulkReset.classList.remove("hidden");
                    showToast("Generation failed.", "error");
                    return;
                }

                // Update step label
                if (data.status === "generating_audio") document.getElementById("bulk-step-label-main").textContent = data.current_step || "Generating audio…";
                else if (data.status === "generating_images") document.getElementById("bulk-step-label-main").textContent = data.current_step || "Generating images…";
                else if (data.status === "rendering") document.getElementById("bulk-step-label-main").textContent = "Rendering video…";

                setTimeout(poll, 1500);
            } catch { setTimeout(poll, 3000); }
        };
        poll();
    }

    function resetStep4() {
        btnStartBulk.classList.remove("hidden");
        bulkSpinner.classList.add("hidden");
        bulkProgressSec.classList.add("hidden");
        bulkDownloadBtn.classList.add("hidden");
        btnBulkReset.classList.add("hidden");
        bulkGenTitle.textContent = "Ready to Generate";
        bulkGenDesc.textContent = "Click below to auto-generate audio, images, and render your final video in one pipeline.";
    }

    // ── Start ────────────────────────────────────────────────────────────
    init();
})();
