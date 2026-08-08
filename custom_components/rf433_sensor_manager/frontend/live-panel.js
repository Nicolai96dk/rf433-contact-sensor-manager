const DOMAIN = "rf433_sensor_manager";

class RF433SensorManagerLivePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._connected = false;
    this._started = false;
    this._snapshot = undefined;
    this._areas = [];
    this._deviceValues = new Map();
  }

  set hass(value) {
    this._hass = value;
    this._start();
  }

  set route(_value) {}

  set panel(_value) {}

  connectedCallback() {
    this._connected = true;
    this._start();
  }

  disconnectedCallback() {
    this._connected = false;
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = undefined;
    }
  }

  async _start() {
    if (!this._connected || !this._hass || this._started) return;
    this._started = true;
    const flowId = new URL(window.location.href).searchParams.get("flow_id");
    if (!flowId) {
      this._renderError("This live setup link is incomplete.");
      return;
    }
    this._flowId = flowId;
    this._renderLoading();
    try {
      const areaResult = await this._hass.callWS({ type: "config/area_registry/list" });
      this._areas = Array.isArray(areaResult) ? areaResult : areaResult.areas || [];
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (snapshot) => this._update(snapshot),
        { type: `${DOMAIN}/live/subscribe`, flow_id: flowId },
      );
    } catch (err) {
      this._renderError(err?.message || "The live setup session could not be opened.");
    }
  }

  _styles() {
    return `
      :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); }
      main { box-sizing: border-box; width: min(760px, calc(100% - 32px)); margin: 32px auto; }
      ha-card { display: block; padding: 28px; }
      h1 { margin: 0 0 8px; font-size: 28px; }
      h2 { margin: 24px 0 12px; font-size: 20px; }
      p { color: var(--secondary-text-color); line-height: 1.45; }
      .reading { padding: 16px; border-radius: 12px; background: var(--secondary-background-color); margin: 20px 0; }
      .reading strong { display: block; color: var(--secondary-text-color); font-size: 13px; margin-bottom: 6px; }
      .code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 22px; letter-spacing: .04em; }
      .devices { display: grid; gap: 12px; }
      .device { border: 1px solid var(--divider-color); border-radius: 12px; padding: 16px; }
      .device-id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 20px; font-weight: 600; }
      .meta { color: var(--secondary-text-color); font-size: 13px; margin-top: 4px; }
      .fields { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
      label { display: grid; gap: 6px; color: var(--secondary-text-color); font-size: 13px; }
      input, select { box-sizing: border-box; width: 100%; min-height: 44px; padding: 9px 11px; border: 1px solid var(--divider-color); border-radius: 8px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
      .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
      .profile-grid .wide { grid-column: 1 / -1; }
      .actions { display: flex; justify-content: flex-end; margin-top: 24px; }
      button { border: 0; border-radius: 22px; padding: 11px 24px; background: var(--primary-color); color: var(--text-primary-color, white); font: inherit; font-weight: 600; cursor: pointer; }
      button:disabled { opacity: .55; cursor: wait; }
      .error { color: var(--error-color); margin-top: 12px; }
      .empty { padding: 24px; border: 1px dashed var(--divider-color); border-radius: 12px; text-align: center; color: var(--secondary-text-color); }
      @media (max-width: 600px) { main { margin: 16px auto; } ha-card { padding: 20px; } .fields, .profile-grid { grid-template-columns: 1fr; } .profile-grid .wide { grid-column: auto; } }
    `;
  }

  _shell(content) {
    this.shadowRoot.innerHTML = `<style>${this._styles()}</style><main><ha-card>${content}</ha-card></main>`;
  }

  _renderLoading() {
    this._shell("<h1>RF433 Sensor Manager</h1><p>Opening the live receiver…</p>");
  }

  _renderError(message) {
    this._shell(`<h1>RF433 Sensor Manager</h1><p class="error">${this._escape(message)}</p>`);
  }

  _update(snapshot) {
    const first = !this._snapshot || this._snapshot.mode !== snapshot.mode;
    this._snapshot = snapshot;
    if (first) {
      if (snapshot.mode === "profile") this._renderProfile();
      else this._renderDiscovery();
    }
    if (snapshot.mode === "profile") this._updateProfileReading();
    else this._updateDiscovery(snapshot);
  }

  _renderProfile() {
    const p = this._snapshot.profile;
    const fields = [
      ["name", "Profile name", "text", true],
      ["payload_length", "Expected payload length", "number"],
      ["device_start", "Device ID start", "number"],
      ["device_length", "Device ID length", "number"],
      ["event_start", "Event start", "number"],
      ["event_length", "Event length", "number"],
      ["open_code", "Open code", "text"],
      ["closed_code", "Closed code", "text"],
      ["tamper_code", "Tamper code (optional)", "text"],
      ["battery_code", "Low-battery code (optional)", "text"],
    ];
    const inputs = fields.map(([key, label, type, wide]) => `
      <label class="${wide ? "wide" : ""}">${label}
        <input data-profile="${key}" type="${type}" value="${this._escape(p[key] ?? "")}">
      </label>`).join("");
    this._shell(`
      <h1>Configure the default protocol profile</h1>
      <p>Trigger a sensor while this page is open. The RF code and its interpretation update immediately.</p>
      <div class="reading"><strong>Latest RF reading</strong><span id="latest" class="code">Waiting for a signal…</span><div id="preview" class="meta"></div></div>
      <div class="profile-grid">${inputs}</div>
      <div id="error" class="error"></div>
      <div class="actions"><button id="done">Done</button></div>`);
    this.shadowRoot.querySelectorAll("[data-profile]").forEach((input) => input.addEventListener("input", () => this._updateProfileReading()));
    this.shadowRoot.getElementById("done").addEventListener("click", () => this._finishProfile());
  }

  _updateProfileReading() {
    const latest = this.shadowRoot.getElementById("latest");
    if (!latest) return;
    const raw = this._snapshot.latest;
    latest.textContent = raw || "Waiting for a signal…";
    const preview = this.shadowRoot.getElementById("preview");
    if (!raw) {
      preview.textContent = "Open or close a sensor to capture a sample.";
      return;
    }
    const values = this._profileValues();
    const ds = Number(values.device_start), dl = Number(values.device_length);
    const es = Number(values.event_start), el = Number(values.event_length);
    const expected = Number(values.payload_length || 0);
    if ([ds, dl, es, el].some((value) => !Number.isInteger(value)) || dl < 1 || el < 1 || (expected && raw.length !== expected) || ds < 0 || es < 0 || ds + dl > raw.length || es + el > raw.length) {
      preview.textContent = "The current positions do not match this code.";
      return;
    }
    const device = raw.slice(ds, ds + dl), event = raw.slice(es, es + el);
    const mapping = { [String(values.open_code).toUpperCase()]: "open", [String(values.closed_code).toUpperCase()]: "closed", [String(values.tamper_code).toUpperCase()]: "tamper", [String(values.battery_code).toUpperCase()]: "low battery" };
    preview.textContent = `Device ${device} · event ${event} (${mapping[event] || "unknown"})`;
  }

  _profileValues() {
    return Object.fromEntries([...this.shadowRoot.querySelectorAll("[data-profile]")].map((input) => [input.dataset.profile, input.value]));
  }

  async _finishProfile() {
    await this._finish({ profile: this._profileValues() });
  }

  _renderDiscovery() {
    this._shell(`
      <h1>${this._snapshot.title || "Learn RF sensors"}</h1>
      <p>Trigger each sensor. New device IDs appear immediately and scanning continues until you press Done.</p>
      <div class="reading"><strong>Latest RF reading</strong><span id="latest" class="code">Waiting for a signal…</span><div id="found" class="meta">0 devices identified</div></div>
      <h2>Identified devices</h2>
      <div id="empty" class="empty">No devices identified yet.</div>
      <div id="devices" class="devices"></div>
      <div id="error" class="error"></div>
      <div class="actions"><button id="done">Done</button></div>`);
    this.shadowRoot.getElementById("done").addEventListener("click", () => this._finishDiscovery());
  }

  _updateDiscovery(snapshot) {
    this.shadowRoot.getElementById("latest").textContent = snapshot.latest || "Waiting for a signal…";
    const detections = snapshot.detections || [];
    this.shadowRoot.getElementById("found").textContent = `${detections.length} device${detections.length === 1 ? "" : "s"} identified`;
    this.shadowRoot.getElementById("empty").hidden = detections.length > 0;
    const container = this.shadowRoot.getElementById("devices");
    for (const detection of detections) {
      if (!this._deviceValues.has(detection.device_id)) {
        this._deviceValues.set(detection.device_id, { name: `RF sensor ${detection.device_id}`, area_id: "" });
      }
      let card = container.querySelector(`[data-device-id="${detection.device_id}"]`);
      if (!card) {
        card = document.createElement("div");
        card.className = "device";
        card.dataset.deviceId = detection.device_id;
        const value = this._deviceValues.get(detection.device_id);
        card.innerHTML = `
          <div class="device-id">${detection.device_id}</div><div class="meta"></div>
          <div class="fields"><label>Name<input data-name value="${this._escape(value.name)}"></label><label>Area<select data-area>${this._areaOptions(value.area_id)}</select></label></div>`;
        card.querySelector("[data-name]").addEventListener("input", (event) => { value.name = event.target.value; });
        card.querySelector("[data-area]").addEventListener("change", (event) => { value.area_id = event.target.value; });
        container.append(card);
      }
      card.querySelector(".meta").textContent = `${detection.count} signal${detection.count === 1 ? "" : "s"} · latest ${detection.last_raw}`;
    }
  }

  _areaOptions(selected) {
    return `<option value="">No area</option>${this._areas.map((area) => `<option value="${this._escape(area.area_id)}" ${area.area_id === selected ? "selected" : ""}>${this._escape(area.name)}</option>`).join("")}`;
  }

  async _finishDiscovery() {
    const devices = (this._snapshot.detections || []).map((detection) => ({ device_id: detection.device_id, ...this._deviceValues.get(detection.device_id) }));
    await this._finish({ devices });
  }

  async _finish(data) {
    const button = this.shadowRoot.getElementById("done");
    const error = this.shadowRoot.getElementById("error");
    button.disabled = true;
    error.textContent = "";
    try {
      await this._hass.callWS({ type: `${DOMAIN}/live/done`, flow_id: this._flowId, data });
      this._shell("<h1>Done</h1><p>Your changes were sent to Home Assistant. You can close this page and return to the setup dialog.</p>");
      window.setTimeout(() => window.close(), 250);
    } catch (err) {
      error.textContent = err?.message || "Home Assistant could not save these values.";
      button.disabled = false;
    }
  }

  _escape(value) {
    return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[char]);
  }
}

if (!customElements.get("rf433-sensor-manager-live-panel")) {
  customElements.define("rf433-sensor-manager-live-panel", RF433SensorManagerLivePanel);
}
