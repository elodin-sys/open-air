  (() => {
    "use strict";

    const CONFIG = JSON.parse(document.getElementById("openair-studio-data").textContent);
    const SCHEMA = CONFIG.schema;
    const DEFS = SCHEMA.$defs || {};
    const clone = value => JSON.parse(JSON.stringify(value));
    const ORIGINAL = clone(CONFIG.initial);
    const ORIGINAL_BRIEF = CONFIG.briefMd || "# Concept brief\n";
    let design = clone(ORIGINAL);
    let savedDesign = clone(ORIGINAL);
    let drag = null;
    let calibrationMode = false;
    let toastTimer = 0;
    let vspPollTimer = null;
    let vspSessionActive = false;
    let vspRejectionSignature = "";
    let viewportUpdateTimer = 0;
    const frames = {};
    const overlays = {};
    const undoStack = [];
    const redoStack = [];
    const HISTORY_LIMIT = 120;
    const SVG_W = 1000;
    const SVG_H = 420;

    const $ = selector => document.querySelector(selector);
    const $$ = selector => Array.from(document.querySelectorAll(selector));
    const clamp = (value, lo, hi) => Math.min(Math.max(value, lo), hi);
    const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
    const round = (value, digits = 6) => Number(Number(value).toFixed(digits));
    const radians = degrees => Number(degrees) * Math.PI / 180;
    const escapeHtml = value => String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

    function toast(message) {
      const node = $("#toast");
      node.textContent = message;
      node.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => node.classList.remove("show"), 2600);
    }

    function nonNullSchema(node) {
      if (!node) return {};
      if (node.$ref) return DEFS[node.$ref.split("/").pop()] || {};
      if (node.anyOf) {
        const option = node.anyOf.find(item => item.type !== "null") || node.anyOf[0];
        return nonNullSchema(option);
      }
      return node;
    }

    function isNullable(node) {
      return Boolean(node && node.anyOf && node.anyOf.some(item => item.type === "null"));
    }

    function getPath(path, source = design) {
      return path.split(".").reduce((value, key) => value == null ? undefined : value[key], source);
    }

    function setPath(path, value, source = design) {
      const keys = path.split(".");
      let cursor = source;
      keys.slice(0, -1).forEach(key => {
        if (cursor[key] == null || typeof cursor[key] !== "object") cursor[key] = {};
        cursor = cursor[key];
      });
      cursor[keys.at(-1)] = value;
    }

    function cloneValue(value) {
      return value === undefined ? undefined : clone(value);
    }

    function valuesEqual(left, right) {
      return JSON.stringify(left) === JSON.stringify(right);
    }

    function schemaAtPath(path) {
      let node = SCHEMA;
      for (const part of path.split(".")) {
        const resolved = nonNullSchema(node);
        if (resolved.type === "array" || /^\d+$/.test(part)) {
          node = resolved.items || node.items || {};
        } else {
          node = (resolved.properties || {})[part] || {};
        }
      }
      return nonNullSchema(node);
    }

    function clampPatchValue(path, value) {
      const node = schemaAtPath(path);
      if (value == null) return value;
      if (["number", "integer"].includes(node.type)) {
        if (typeof value !== "number" || !Number.isFinite(value)) {
          throw new Error(`${path} must be a finite number`);
        }
      } else if (node.type === "boolean" && typeof value !== "boolean") {
        throw new Error(`${path} must be a boolean`);
      } else if (node.type === "string" && typeof value !== "string") {
        throw new Error(`${path} must be text`);
      } else if (node.type === "array" && !Array.isArray(value)) {
        throw new Error(`${path} must be a list`);
      } else if (
        node.type === "object"
        && (typeof value !== "object" || Array.isArray(value))
      ) {
        throw new Error(`${path} must be an object`);
      }
      if (typeof value !== "number") return value;
      let result = value;
      if (node.minimum != null) result = Math.max(result, Number(node.minimum));
      if (node.maximum != null) result = Math.min(result, Number(node.maximum));
      if (node.exclusiveMinimum != null) {
        const bound = Number(node.exclusiveMinimum);
        const epsilon = node.type === "integer"
          ? 1
          : Math.max(1e-6, Math.abs(bound) * 1e-6);
        result = Math.max(result, bound + epsilon);
      }
      if (node.exclusiveMaximum != null) {
        const bound = Number(node.exclusiveMaximum);
        const epsilon = node.type === "integer"
          ? 1
          : Math.max(1e-6, Math.abs(bound) * 1e-6);
        result = Math.min(result, bound - epsilon);
      }
      return node.type === "integer" ? Math.round(result) : round(result);
    }

    function refreshHistoryButtons() {
      $("#undo-design").disabled = undoStack.length === 0;
      $("#redo-design").disabled = redoStack.length === 0;
    }

    function recordHistory(entries, source, coalesce = false) {
      if (!entries.length) return;
      const now = performance.now();
      const previous = undoStack.at(-1);
      if (
        coalesce
        && previous
        && previous.source === source
        && now - previous.time < 800
        && entries.length === 1
        && previous.entries.length === 1
        && previous.entries[0].path === entries[0].path
      ) {
        previous.entries[0].newValue = cloneValue(entries[0].newValue);
        previous.time = now;
      } else {
        undoStack.push({
          source,
          time: now,
          entries: entries.map(entry => ({
            path: entry.path,
            oldValue: cloneValue(entry.oldValue),
            newValue: cloneValue(entry.newValue),
          })),
        });
        if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
      }
      redoStack.length = 0;
      refreshHistoryButtons();
    }

    function stationEnvelopeEntries(entries) {
      if (!entries.some(entry => entry.path.startsWith("fuselage.stations."))) return [];
      const stations = design.fuselage.stations;
      if (!Array.isArray(stations) || !stations.length) return [];
      const patches = [];
      const width = Math.max(...stations.map(station => number(station.width_m)));
      const height = Math.max(...stations.map(station => number(station.height_m)));
      if (width > number(design.fuselage.max_width_m)) {
        patches.push({path: "fuselage.max_width_m", value: round(width)});
      }
      if (height > number(design.fuselage.max_height_m)) {
        patches.push({path: "fuselage.max_height_m", value: round(height)});
      }
      return patches;
    }

    function applyPatches(
      patches,
      {source = "edit", record = true, coalesce = false, render = true} = {},
    ) {
      const pending = new Map();
      (patches || []).forEach(patch => {
        if (!patch || typeof patch.path !== "string" || !patch.path) return;
        pending.set(
          patch.path,
          cloneValue(clampPatchValue(patch.path, patch.value)),
        );
      });
      const entries = [];
      pending.forEach((value, path) => {
        const oldValue = cloneValue(getPath(path));
        if (valuesEqual(oldValue, value)) return;
        setPath(path, cloneValue(value));
        entries.push({path, oldValue, newValue: cloneValue(value)});
      });
      stationEnvelopeEntries(entries).forEach(patch => {
        if (pending.has(patch.path)) return;
        const oldValue = cloneValue(getPath(patch.path));
        const value = clampPatchValue(patch.path, patch.value);
        if (valuesEqual(oldValue, value)) return;
        setPath(patch.path, value);
        entries.push({path: patch.path, oldValue, newValue: cloneValue(value)});
      });
      if (!entries.length) return [];
      if (record) recordHistory(entries, source, coalesce);
      const structural = entries.some(entry => {
        const value = entry.newValue;
        return value === null || typeof value === "object";
      });
      if (structural) renderForm();
      else entries.forEach(entry => refreshInput(entry.path));
      if (render) updateAll();
      return entries;
    }

    function replacementPatches(before, after, prefix = "") {
      if (valuesEqual(before, after)) return [];
      const beforeObject = before && typeof before === "object" && !Array.isArray(before);
      const afterObject = after && typeof after === "object" && !Array.isArray(after);
      if (!beforeObject || !afterObject) {
        return prefix ? [{path: prefix, value: cloneValue(after)}] : [];
      }
      const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
      return Array.from(keys).flatMap(key => replacementPatches(
        before[key],
        after[key],
        prefix ? `${prefix}.${key}` : key,
      ));
    }

    function replaceDesign(nextDesign, source) {
      return applyPatches(
        replacementPatches(design, nextDesign),
        {source},
      );
    }

    function applyHistoryBatch(batch, direction) {
      const patches = batch.entries.map(entry => ({
        path: entry.path,
        value: cloneValue(direction === "undo" ? entry.oldValue : entry.newValue),
      }));
      applyPatches(patches, {source: direction, record: false});
    }

    function undo() {
      const batch = undoStack.pop();
      if (!batch) return;
      applyHistoryBatch(batch, "undo");
      redoStack.push(batch);
      refreshHistoryButtons();
    }

    function redo() {
      const batch = redoStack.pop();
      if (!batch) return;
      applyHistoryBatch(batch, "redo");
      undoStack.push(batch);
      refreshHistoryButtons();
    }

    function flattenDesign(value, prefix = "", output = new Map()) {
      if (Array.isArray(value)) {
        output.set(prefix, clone(value));
      } else if (value && typeof value === "object") {
        Object.entries(value).forEach(([key, child]) => {
          flattenDesign(child, prefix ? `${prefix}.${key}` : key, output);
        });
      } else if (prefix) {
        output.set(prefix, value);
      }
      return output;
    }

    function designDiff(base, current) {
      const before = flattenDesign(base);
      const after = flattenDesign(current);
      return Array.from(new Set([...before.keys(), ...after.keys()]))
        .sort()
        .filter(path => !valuesEqual(before.get(path), after.get(path)))
        .map(path => ({path, before: before.get(path), after: after.get(path)}));
    }

    function displayValue(value) {
      if (Array.isArray(value)) return `${value.length} station${value.length === 1 ? "" : "s"}`;
      if (value == null) return "none";
      if (typeof value === "number") return Number(value.toPrecision(7)).toString();
      const text = String(value);
      return text.length > 32 ? `${text.slice(0, 29)}…` : text;
    }

    function renderDiff() {
      const entries = designDiff(ORIGINAL, design);
      $("#diff-count").textContent = String(entries.length);
      $("#parameter-diff").innerHTML = entries.length
        ? `<ol>${entries.map(entry => `<li><code>${escapeHtml(entry.path)}</code><span>${escapeHtml(displayValue(entry.before))} → ${escapeHtml(displayValue(entry.after))}</span></li>`).join("")}</ol>`
        : "<p>No changes from the starting design.</p>";
      const unsaved = designDiff(savedDesign, design).length;
      const badge = $("#unsaved-count");
      badge.textContent = String(unsaved);
      badge.hidden = unsaved === 0;
    }

    function titleFor(name, node) {
      return node.title || name.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
    }

    function unitFor(name) {
      const units = [
        ["_kg_s", "kg/s"], ["_kg_m3", "kg/m³"], ["_mps", "m/s"],
        ["_pa", "Pa"], ["_deg", "deg"], ["_kg", "kg"], ["_m2", "m²"],
        ["_m3", "m³"], ["_m", "m"], ["_s", "s"],
      ];
      const match = units.find(([suffix]) => name.endsWith(suffix));
      return match ? match[1] : "";
    }

    function boundText(node) {
      const values = [];
      if (node.minimum != null) values.push(`≥ ${node.minimum}`);
      if (node.exclusiveMinimum != null) values.push(`> ${node.exclusiveMinimum}`);
      if (node.maximum != null) values.push(`≤ ${node.maximum}`);
      if (node.exclusiveMaximum != null) values.push(`< ${node.exclusiveMaximum}`);
      return values.join(" · ");
    }

    function inputHtml(name, node, path, value) {
      const resolved = nonNullSchema(node);
      const type = resolved.type;
      const unit = unitFor(name);
      const bounds = boundText(resolved);
      const label = `<label><span>${escapeHtml(titleFor(name, node))}</span><span>${escapeHtml(unit)}</span></label>`;
      const hint = `<span class="hint" title="${escapeHtml(resolved.description || "")}">${escapeHtml(bounds || resolved.description || path)}</span>`;
      const sectionLocked = (
        Array.isArray(design.wing.sections)
        && design.wing.sections.length >= 3
        && new Set([
          "wing.span_m",
          "wing.root_chord_m",
          "wing.taper",
          "wing.le_sweep_deg",
          "wing.dihedral_deg",
          "wing.x_le_root_m",
          "wing.z_root_m",
        ]).has(path)
      );
      const common = `data-path="${escapeHtml(path)}" aria-label="${escapeHtml(path)}"${sectionLocked ? ' disabled title="Derived from wing.sections"' : ""}`;
      if (resolved.enum) {
        const options = resolved.enum.map(option =>
          `<option value="${escapeHtml(option)}"${option === value ? " selected" : ""}>${escapeHtml(option)}</option>`
        ).join("");
        return `<div class="field">${label}<select ${common}>${options}</select>${hint}</div>`;
      }
      if (type === "boolean") {
        return `<div class="field">${label}<input ${common} type="checkbox"${value ? " checked" : ""}>${hint}</div>`;
      }
      if (type === "number" || type === "integer") {
        const attrs = [
          resolved.minimum != null ? `min="${resolved.minimum}"` : "",
          resolved.maximum != null ? `max="${resolved.maximum}"` : "",
          resolved.exclusiveMinimum != null ? `data-exclusive-min="${resolved.exclusiveMinimum}"` : "",
          resolved.exclusiveMaximum != null ? `data-exclusive-max="${resolved.exclusiveMaximum}"` : "",
          `step="${type === "integer" ? "1" : "any"}"`,
        ].filter(Boolean).join(" ");
        return `<div class="field">${label}<input ${common} type="number" ${attrs} value="${value == null ? "" : escapeHtml(value)}">${hint}</div>`;
      }
      const wide = name === "notes" ? " wide" : "";
      if (name === "notes") {
        return `<div class="field${wide}">${label}<textarea ${common}>${escapeHtml(value || "")}</textarea>${hint}</div>`;
      }
      const pattern = resolved.pattern ? ` pattern="${escapeHtml(resolved.pattern)}"` : "";
      return `<div class="field${wide}">${label}<input ${common} type="text"${pattern} value="${escapeHtml(value ?? "")}">${hint}</div>`;
    }

    function stationEditor(path, node) {
      const stations = getPath(path);
      const arraySchema = nonNullSchema(node);
      const itemSchema = nonNullSchema(arraySchema.items || {});
      const names = Object.keys(itemSchema.properties || {});
      if (!Array.isArray(stations)) {
        return `<div class="station-editor"><div class="optional-note">
          <span>Simple envelope body is active — enable stations for full shape control.</span>
          <button type="button" data-action="enable-stations">Enable fuselage stations</button>
        </div><div class="station-row station-head">${names.map(name => `<span>${escapeHtml(name.replaceAll("_", " "))}</span>`).join("")}<span></span></div></div>`;
      }
      const header = `<div class="station-row station-head">${names.map(name => `<span>${escapeHtml(name.replaceAll("_", " "))}</span>`).join("")}<span></span></div>`;
      const rows = stations.map((station, index) => {
        const inputs = names.map(name => {
          const field = nonNullSchema(itemSchema.properties[name]);
          const attrs = [
            field.minimum != null ? `min="${field.minimum}"` : "",
            field.maximum != null ? `max="${field.maximum}"` : "",
            name === "x_over_length" && (index === 0 || index === stations.length - 1) ? "readonly" : "",
            `step="any"`,
          ].filter(Boolean).join(" ");
          return `<input type="number" ${attrs} data-path="${path}.${index}.${name}" aria-label="${path}.${index}.${name}" value="${escapeHtml(station[name])}">`;
        }).join("");
        const fixedEndpoint = index === 0 || index === stations.length - 1;
        return `<div class="station-row">${inputs}<button class="danger" type="button" data-action="remove-station" data-index="${index}" title="Remove station"${fixedEndpoint ? " disabled" : ""}>×</button></div>`;
      }).join("");
      return `<div class="station-editor">${header}${rows}<div class="station-actions">
        <button type="button" data-action="add-station"${stations.length >= 8 ? " disabled" : ""}>Add station</button>
        <button type="button" data-action="disable-stations">Switch to simple envelope</button>
        <span class="hint">4–8 stations · endpoints at x/L 0 and 1 · drag green handles in top/side views</span>
      </div></div>`;
    }

    function fairingEditor(path) {
      const fairings = getPath(path);
      const value = JSON.stringify(fairings || [], null, 2);
      return `<div class="field wide"><label><span>Measured body fairings</span><span>read-only</span></label>
        <textarea data-path="${escapeHtml(path)}" aria-label="${escapeHtml(path)}" disabled title="Regenerate fairings with openair.reference ingest">${escapeHtml(value)}</textarea>
        <span class="hint">Measured loft-fidelity geometry; regenerate from the reference scan rather than editing in Studio.</span></div>`;
    }

    function renderProperties(properties, prefix) {
      return Object.entries(properties).map(([name, node]) => {
        const path = prefix ? `${prefix}.${name}` : name;
        const resolved = nonNullSchema(node);
        const value = getPath(path);
        if (resolved.type === "array") {
          if (path === "fuselage.stations") return stationEditor(path, node);
          if (path === "fuselage.fairings") return fairingEditor(path);
          return inputHtml(name, {type: "string", title: node.title}, path, JSON.stringify(value || []));
        }
        if (resolved.type === "object" || resolved.properties) {
          const nullable = isNullable(node);
          const note = nullable ? `<div class="optional-note">
            <span>${value == null ? "Optional section is disabled; fields remain available for tracing/export." : "Optional section is enabled."}</span>
            <button type="button" data-action="toggle-optional" data-path="${path}">${value == null ? "Enable" : "Disable"}</button>
          </div>` : "";
          return `${note}${renderProperties(resolved.properties || {}, path)}`;
        }
        return inputHtml(name, node, path, value);
      }).join("");
    }

    function renderForm() {
      const top = SCHEMA.properties || {};
      const rootFields = ["name", "notes"];
      const chunks = [];
      const basics = Object.fromEntries(rootFields.filter(key => top[key]).map(key => [key, top[key]]));
      chunks.push(`<details class="section" open><summary>Concept</summary><div class="fields">${renderProperties(basics, "")}</div></details>`);
      Object.entries(top).forEach(([name, node]) => {
        if (rootFields.includes(name)) return;
        const resolved = nonNullSchema(node);
        const open = ["wing", "fuselage"].includes(name) ? " open" : "";
        chunks.push(`<details class="section"${open}><summary>${escapeHtml(titleFor(name, node))}</summary><div class="fields">${renderProperties(resolved.properties || {}, name)}</div></details>`);
      });
      $("#schema-form").innerHTML = chunks.join("");
      validateExclusiveInputs();
    }

    function validateExclusiveInputs() {
      $$("[data-exclusive-min], [data-exclusive-max]").forEach(input => {
        const check = () => {
          if (input.disabled || input.value === "") {
            input.setCustomValidity("");
            return;
          }
          const value = Number(input.value);
          const lo = input.dataset.exclusiveMin;
          const hi = input.dataset.exclusiveMax;
          let message = "";
          if (lo != null && value <= Number(lo)) message = `Must be greater than ${lo}`;
          if (hi != null && value >= Number(hi)) message = `Must be less than ${hi}`;
          input.setCustomValidity(message);
        };
        input.addEventListener("input", check);
        check();
      });
    }

    function stationSeed(fuselage) {
      const shape = [
        [0, 0, 0, 0],
        [.18, .6875, .642857, .035714],
        [.42, 1, 1, .071429],
        [.68, .96875, .964286, .089286],
        [.84, .625, .607143, .142857],
        [1, .25, .25, .25],
      ];
      return shape.map(([fraction, widthScale, heightScale, offsetScale]) => ({
        x_over_length: fraction,
        width_m: round(number(fuselage.max_width_m) * widthScale),
        height_m: round(number(fuselage.max_height_m) * heightScale),
        z_offset_m: round(number(fuselage.max_height_m) * offsetScale),
        side_power: 2,
        top_power: 2,
        bottom_power: 2,
      }));
    }

    function defaultStations() {
      return stationSeed(design.fuselage);
    }

    function computedSketch(source = design) {
      const existing = source.sketch || {};
      const wing = source.wing;
      const fuselage = source.fuselage;
      const length = Math.max(number(fuselage.length_m), .001);
      return {
        ...clone(existing),
        treatment: existing.treatment || "requirement",
        hard_scale: number(existing.hard_scale, 3),
        fidelity_weight: number(existing.fidelity_weight, 1),
        span_over_length: round(number(wing.span_m) / length),
        span_over_length_tol: number(existing.span_over_length_tol, .10),
        root_over_length: round(number(wing.root_chord_m) / length),
        root_over_length_tol: number(existing.root_over_length_tol, .05),
        le_sweep_deg: round(number(wing.le_sweep_deg)),
        le_sweep_tol_deg: number(existing.le_sweep_tol_deg, 4),
        taper: round(number(wing.taper)),
        taper_tol: number(existing.taper_tol, .08),
        x_le_root_over_length: round(number(wing.x_le_root_m) / length),
        x_le_root_over_length_tol: number(existing.x_le_root_over_length_tol, .06),
        payload_bay_x_lo_m: existing.payload_bay_x_lo_m ?? null,
        payload_bay_x_hi_m: existing.payload_bay_x_hi_m ?? null,
        fuel_tank_x_lo_m: existing.fuel_tank_x_lo_m ?? null,
        fuel_tank_x_hi_m: existing.fuel_tank_x_hi_m ?? null,
        twist_tip_lo_deg: existing.twist_tip_lo_deg ?? null,
        twist_tip_hi_deg: existing.twist_tip_hi_deg ?? null,
      };
    }

    function readInput(input) {
      if (input.type === "checkbox") return input.checked;
      if (input.type === "number") return input.value === "" ? null : Number(input.value);
      return input.value;
    }

    function refreshInput(path) {
      $$("[data-path]").filter(node => node.dataset.path === path).forEach(input => {
        const value = getPath(path);
        if (input.type === "checkbox") input.checked = Boolean(value);
        else input.value = value ?? "";
      });
    }

    function updateAll() {
      renderViews();
      renderDerived();
      renderDiff();
      const preview = window.OpenAirPreviewMesh.build(design);
      $("#smoke-preview").textContent = JSON.stringify(preview.stats);
      document.body.dataset.previewReady = String(
        preview.stats.finite
        && preview.stats.triangles > 0
        && preview.stats.projectedWingArea > 0,
      );
      clearTimeout(viewportUpdateTimer);
      viewportUpdateTimer = window.setTimeout(() => {
        try {
          window.OpenAirViewport3D.update(design, quickBalance(), preview);
          document.body.dataset.viewportUpdated = "true";
          const viewportNotice = $("#viewport3d-notice");
          document.body.dataset.viewportUncovered = String(
            !window.OpenAirViewport3D.isAvailable()
            || (
              viewportNotice.hidden
              && getComputedStyle(viewportNotice).display === "none"
            ),
          );
        } catch (error) {
          document.body.dataset.viewportUpdated = "false";
          document.body.dataset.viewportError = error.message;
          const notice = $("#viewport3d-notice");
          notice.hidden = false;
          notice.textContent = `3D refresh failed (${error.message}). 2D editing remains active.`;
        }
      }, 60);
      const yaml = exportYaml();
      $("#smoke-yaml").textContent = yaml;
      document.body.dataset.ready = "true";
    }

    function wingGeometry() {
      const w = design.wing;
      const span = Math.max(number(w.span_m), .01);
      const root = Math.max(number(w.root_chord_m), .01);
      const taper = Math.max(number(w.taper), .001);
      const halfSpan = .5 * span;
      const xRoot = number(w.x_le_root_m);
      const sectioned = Array.isArray(w.sections) && w.sections.length >= 3;
      const sections = sectioned
        ? w.sections.map(section => ({
          eta: Math.min(Math.max(number(section.eta), 0), 1),
          chord: Math.max(number(section.chord_m), .001),
          xLe: number(section.x_le_m),
          zLe: number(section.z_le_m),
        }))
        : [
          {eta: 0, chord: root, xLe: xRoot, zLe: number(w.z_root_m)},
          {
            eta: 1,
            chord: root * taper,
            xLe: xRoot + halfSpan * Math.tan(radians(number(w.le_sweep_deg))),
            zLe: number(w.z_root_m) + halfSpan * Math.tan(radians(number(w.dihedral_deg))),
          },
        ];
      const tip = sections.at(-1).chord;
      const xTip = sections.at(-1).xLe;
      const equivalentTip = root * taper;
      let area;
      let mac;
      let yMac;
      let xLeMac;
      if (sectioned) {
        let chordIntegral = 0;
        let chordSquaredIntegral = 0;
        let etaChordIntegral = 0;
        let xChordIntegral = 0;
        for (let index = 0; index < sections.length - 1; index += 1) {
          const left = sections[index];
          const right = sections[index + 1];
          const delta = right.eta - left.eta;
          const chordMid = .5 * (left.chord + right.chord);
          const etaMid = .5 * (left.eta + right.eta);
          const xMid = .5 * (left.xLe + right.xLe);
          chordIntegral += .5 * delta * (left.chord + right.chord);
          chordSquaredIntegral += delta * (
            left.chord ** 2 + left.chord * right.chord + right.chord ** 2
          ) / 3;
          etaChordIntegral += delta * (
            left.eta * left.chord + 4 * etaMid * chordMid + right.eta * right.chord
          ) / 6;
          xChordIntegral += delta * (
            left.xLe * left.chord + 4 * xMid * chordMid + right.xLe * right.chord
          ) / 6;
        }
        area = span * chordIntegral;
        mac = chordSquaredIntegral / Math.max(chordIntegral, 1e-12);
        yMac = halfSpan * etaChordIntegral / Math.max(chordIntegral, 1e-12);
        xLeMac = xChordIntegral / Math.max(chordIntegral, 1e-12);
      } else {
        area = .5 * span * (root + equivalentTip);
        mac = (2 / 3) * root * (1 + taper + taper * taper) / (1 + taper);
        yMac = (span / 6) * (1 + 2 * taper) / (1 + taper);
        xLeMac = xRoot + yMac * Math.tan(radians(number(w.le_sweep_deg)));
      }
      const rightLe = sections.map(section => [section.xLe, section.eta * halfSpan]);
      const rightTe = sections.map(section => [section.xLe + section.chord, section.eta * halfSpan]);
      const leftLe = rightLe.map(([x, y]) => [x, -y]);
      const leftTe = rightTe.map(([x, y]) => [x, -y]);
      const planform = [
        ...rightLe,
        ...rightTe.slice().reverse(),
        ...leftTe.slice(1),
        ...leftLe.slice().reverse().slice(0, -1),
      ];
      return {
        span, root, taper, tip, equivalentTip, halfSpan, xRoot, xTip,
        area, mac, yMac, xLeMac,
        sectioned, sections, planform,
      };
    }

    function bodyProfile() {
      const f = design.fuselage;
      const length = Math.max(number(f.length_m), .01);
      if (Array.isArray(f.stations) && f.stations.length >= 2) {
        return f.stations.map(station => ({
          x: number(station.x_over_length) * length,
          width: Math.max(number(station.width_m), 0),
          height: Math.max(number(station.height_m), 0),
          z: number(station.z_offset_m),
          sidePower: number(station.side_power, 2),
          topPower: number(station.top_power, 2),
          bottomPower: number(station.bottom_power, 2),
          maxWidthLoc: number(station.max_width_loc, 0),
        }));
      }
      const fractions = [0, .25, .5, .75, 1];
      const scales = [.05, .45, 1, .9, .35];
      return fractions.map((fraction, index) => ({
        x: fraction * length,
        width: number(f.max_width_m) * scales[index],
        height: number(f.max_height_m) * scales[index],
        z: 0,
        sidePower: 2,
        topPower: 2,
        bottomPower: 2,
        maxWidthLoc: 0,
      }));
    }

    function fairingProfiles() {
      const length = Math.max(number(design.fuselage.length_m), .01);
      return (Array.isArray(design.fuselage.fairings) ? design.fuselage.fairings : [])
        .filter(fairing => Array.isArray(fairing.stations) && fairing.stations.length >= 2)
        .map(fairing => ({
          name: fairing.name,
          role: fairing.role,
          sections: fairing.stations.map(station => ({
            x: number(station.x_over_length) * length,
            width: Math.max(number(station.width_m), 0),
            height: Math.max(number(station.height_m), 0),
            z: number(station.z_offset_m),
            sidePower: number(station.side_power, 2),
            topPower: number(station.top_power, 2),
            bottomPower: number(station.bottom_power, 2),
            maxWidthLoc: number(station.max_width_loc, 0),
          })),
        }));
    }

    function makeFrame(xMin, xMax, yMin, yMax) {
      const pad = 34;
      const dx = Math.max(xMax - xMin, .01);
      const dy = Math.max(yMax - yMin, .01);
      const scale = Math.min((SVG_W - 2 * pad) / dx, (SVG_H - 2 * pad) / dy);
      const usedW = dx * scale;
      const usedH = dy * scale;
      const left = (SVG_W - usedW) / 2;
      const top = (SVG_H - usedH) / 2;
      return {
        xMin, xMax, yMin, yMax, scale, left, top,
        map(x, y) { return [left + (x - xMin) * scale, top + (yMax - y) * scale]; },
        unmap(px, py) { return [xMin + (px - left) / scale, yMax - (py - top) / scale]; },
      };
    }

    function stableViewFrame(view, candidate) {
      return drag?.view === view && drag.frame ? drag.frame : candidate;
    }

    function pathData(points, frame, close = true) {
      const mapped = points.map(point => frame.map(point[0], point[1]));
      if (!mapped.length) return "";
      return `M ${mapped.map(point => `${point[0].toFixed(2)} ${point[1].toFixed(2)}`).join(" L ")}${close ? " Z" : ""}`;
    }

    function line(x1, y1, x2, y2, frame, className = "datum") {
      const a = frame.map(x1, y1);
      const b = frame.map(x2, y2);
      return `<line class="${className}" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"></line>`;
    }

    function gridLines(frame, view) {
      const spacing = metresPerGridSquare(view);
      if (!Number.isFinite(spacing) || spacing <= 0) return "";
      const parts = [];
      const firstX = Math.ceil(frame.xMin / spacing) * spacing;
      const firstY = Math.ceil(frame.yMin / spacing) * spacing;
      for (let x = firstX, count = 0; x <= frame.xMax && count < 120; x += spacing, count += 1) {
        parts.push(line(x, frame.yMin, x, frame.yMax, frame, "trace-grid"));
      }
      for (let y = firstY, count = 0; y <= frame.yMax && count < 120; y += spacing, count += 1) {
        parts.push(line(frame.xMin, y, frame.xMax, y, frame, "trace-grid"));
      }
      return parts.join("");
    }

    function circle(x, y, frame, handle, extra = "", className = "") {
      const point = frame.map(x, y);
      return `<circle class="handle ${className}" cx="${point[0]}" cy="${point[1]}" r="5.5" data-handle="${handle}" ${extra}></circle>`;
    }

    function semanticHandles(view, frame) {
      return window.OpenAirHandles.instances(view, design).map(handle => circle(
        handle.position[0],
        handle.position[1],
        frame,
        handle.id,
        handle.index == null ? "" : `data-index="${handle.index}"`,
        handle.className,
      )).join("");
    }

    function balanceMarkers(frame, yMin, yMax) {
      const balance = quickBalance();
      return [
        line(balance.cg, yMin, balance.cg, yMax, frame, "balance-marker cg"),
        line(balance.reserveCg, yMin, balance.reserveCg, yMax, frame, "balance-marker reserve"),
        line(balance.np, yMin, balance.np, yMax, frame, "balance-marker np"),
      ].join("");
    }

    function renderTop() {
      const svg = $("#top-view");
      const wing = wingGeometry();
      const profile = bodyProfile();
      const fairings = fairingProfiles();
      const fairingSections = fairings.flatMap(fairing => fairing.sections);
      const f = design.fuselage;
      const length = number(f.length_m);
      const tail = design.htail;
      const tailHalfSpan = .5 * Math.max(number(tail.span_m), 0);
      const tailTipChord = number(tail.root_chord_m) * number(tail.taper);
      const tailTipX = number(tail.x_le_m) + tailHalfSpan * Math.tan(radians(number(tail.le_sweep_deg)));
      const maxY = Math.max(
        wing.halfSpan * 1.08,
        tailHalfSpan * 1.08,
        ...profile.map(section => section.width * .65),
        ...fairingSections.map(section => section.width * .65),
        .5,
      );
      const xMin = Math.min(
        0,
        ...wing.planform.map(point => point[0]),
        ...fairingSections.map(section => section.x),
      ) - .05 * length;
      const xMax = Math.max(
        length,
        ...wing.planform.map(point => point[0]),
        number(tail.x_le_m) + number(tail.root_chord_m),
        tailTipX + tailTipChord,
        ...fairingSections.map(section => section.x),
      ) + .05 * length;
      const frame = stableViewFrame(
        "top",
        makeFrame(xMin, xMax, -maxY, maxY),
      );
      frames.top = frame;
      const body = [
        ...profile.map(section => [section.x, .5 * section.width]),
        ...profile.slice().reverse().map(section => [section.x, -.5 * section.width]),
      ];
      const fairingPaths = fairings.map(fairing => {
        const points = [
          ...fairing.sections.map(section => [section.x, .5 * section.width]),
          ...fairing.sections.slice().reverse().map(section => [
            section.x,
            -.5 * section.width,
          ]),
        ];
        return `<path class="fairing-shape" d="${pathData(points, frame)}"></path>`;
      }).join("");
      const planform = wing.planform;
      const payloadX = number(f.payload_bay_x_m);
      const payloadEnd = payloadX + number(f.payload_bay_length_m);
      const payloadHalf = .5 * number(f.payload_bay_width_m);
      const payload = [[payloadX, -payloadHalf], [payloadEnd, -payloadHalf], [payloadEnd, payloadHalf], [payloadX, payloadHalf]];
      const fin = design.vtail;
      const finHalfY = window.OpenAirHandles.finAttachment(design).y;
      const finYs = Math.round(number(fin.count, 2)) === 1
        ? [0]
        : [finHalfY, -finHalfY];
      const finLines = finYs.map(y => line(
        number(fin.x_le_m),
        y,
        number(fin.x_le_m) + number(fin.root_chord_m),
        y,
        frame,
        "fin-shape",
      )).join("");
      const finRootGeometry = window.OpenAirPreviewMesh.finRootGeometry(design);
      const finRootExtensions = finRootGeometry.extensionRequired
        ? finYs.map((y, index) => {
          const sign = Math.round(number(fin.count, 2)) === 1
            ? 1
            : (index === 0 ? 1 : -1);
          const points = [
            [finRootGeometry.xLe, sign * finRootGeometry.y],
            [number(fin.x_le_m), y],
            [number(fin.x_le_m) + number(fin.root_chord_m), y],
            [finRootGeometry.xLe + finRootGeometry.chord, sign * finRootGeometry.y],
          ];
          return `<path class="fin-shape root-extension" d="${pathData(points, frame)}"></path>`;
        }).join("")
        : "";
      const htail = number(tail.span_m) > .05 ? [
        [number(tail.x_le_m), 0],
        [tailTipX, tailHalfSpan],
        [tailTipX + tailTipChord, tailHalfSpan],
        [number(tail.x_le_m) + number(tail.root_chord_m), 0],
        [tailTipX + tailTipChord, -tailHalfSpan],
        [tailTipX, -tailHalfSpan],
      ] : [];
      svg.innerHTML = [
        gridLines(frame, "top"),
        line(xMin, 0, xMax, 0, frame),
        `<path class="airframe" d="${pathData(planform, frame)}"></path>`,
        htail.length ? `<path class="airframe tail-shape" d="${pathData(htail, frame)}"></path>` : "",
        `<path class="body-shape" d="${pathData(body, frame)}"></path>`,
        fairingPaths,
        `<path class="bay" d="${pathData(payload, frame)}"></path>`,
        finRootExtensions,
        finLines,
        balanceMarkers(frame, -.16 * maxY, .16 * maxY),
        semanticHandles("top", frame),
      ].join("");
    }

    function renderSide() {
      const svg = $("#side-view");
      const wing = wingGeometry();
      const profile = bodyProfile();
      const fairings = fairingProfiles();
      const fairingSections = fairings.flatMap(fairing => fairing.sections);
      const f = design.fuselage;
      const v = design.vtail;
      const length = number(f.length_m);
      const topPoints = profile.map(section => [section.x, section.z + .5 * section.height]);
      const bottomPoints = profile.slice().reverse().map(section => [section.x, section.z - .5 * section.height]);
      const body = [...topPoints, ...bottomPoints];
      const finRootX = number(v.x_le_m);
      const finAttachment = window.OpenAirHandles.finAttachment(design);
      const finRootZ = finAttachment.z;
      const finVertical = number(v.span_m) * Math.cos(radians(number(v.cant_deg)));
      const finTipX = finRootX + number(v.span_m) * Math.tan(radians(number(v.le_sweep_deg)));
      const fin = [
        [finRootX, finRootZ],
        [finTipX, finRootZ + finVertical],
        [finTipX + number(v.root_chord_m) * number(v.taper), finRootZ + finVertical],
        [finRootX + number(v.root_chord_m), finRootZ],
      ];
      const finRootGeometry = window.OpenAirPreviewMesh.finRootGeometry(design);
      const finRootExtension = finRootGeometry.extensionRequired
        ? [
          [finRootGeometry.xLe, finRootGeometry.z],
          [finRootX, finRootZ],
          [finRootX + number(v.root_chord_m), finRootZ],
          [finRootGeometry.xLe + finRootGeometry.chord, finRootGeometry.z],
        ]
        : [];
      const yMin = Math.min(
        ...profile.map(section => section.z - .5 * section.height),
        ...fairingSections.map(section => section.z - .5 * section.height),
        ...wing.sections.map(section => section.zLe),
        finRootGeometry.z,
      ) - .12;
      const yMax = Math.max(
        ...profile.map(section => section.z + .5 * section.height),
        ...fairingSections.map(section => section.z + .5 * section.height),
        finRootZ + finVertical,
      ) + .10;
      const xMax = Math.max(
        length,
        finTipX + number(v.root_chord_m),
        ...wing.sections.map(section => section.xLe + section.chord),
        ...fairingSections.map(section => section.x),
      ) + .06 * length;
      const frame = stableViewFrame(
        "side",
        makeFrame(-.04 * length, xMax, yMin, yMax),
      );
      frames.side = frame;
      const wingSide = [
        ...wing.sections.map(section => [section.xLe, section.zLe]),
        ...wing.sections.slice().reverse().map(section => [
          section.xLe + section.chord,
          section.zLe,
        ]),
      ];
      const wingLine = `<path class="airframe" d="${pathData(wingSide, frame)}"></path>`;
      const fairingPaths = fairings.map(fairing => {
        const points = [
          ...fairing.sections.map(section => [section.x, section.z + .5 * section.height]),
          ...fairing.sections.slice().reverse().map(section => [
            section.x,
            section.z - .5 * section.height,
          ]),
        ];
        return `<path class="fairing-shape" d="${pathData(points, frame)}"></path>`;
      }).join("");
      svg.innerHTML = [
        gridLines(frame, "side"),
        line(0, 0, xMax, 0, frame),
        `<path class="body-shape" d="${pathData(body, frame)}"></path>`,
        fairingPaths,
        wingLine,
        finRootExtension.length
          ? `<path class="fin-shape root-extension" d="${pathData(finRootExtension, frame)}"></path>`
          : "",
        `<path class="fin-shape" d="${pathData(fin, frame)}"></path>`,
        balanceMarkers(frame, yMin, yMin + .18 * (yMax - yMin)),
        semanticHandles("side", frame),
      ].join("");
    }

    function renderFront() {
      const svg = $("#front-view");
      const wing = wingGeometry();
      const profile = bodyProfile();
      const fairings = fairingProfiles();
      const fairingSections = fairings.flatMap(fairing => fairing.sections);
      const v = design.vtail;
      const largest = profile.reduce((best, section) => section.width * section.height > best.width * best.height ? section : best, profile[0]);
      const halfSpan = wing.halfSpan;
      const finAttachment = window.OpenAirHandles.finAttachment(design);
      const finBaseY = finAttachment.y;
      const finBaseZ = finAttachment.z;
      const finDY = number(v.span_m) * Math.sin(radians(number(v.cant_deg)));
      const finDZ = number(v.span_m) * Math.cos(radians(number(v.cant_deg)));
      const envelopeHeight = number(design.fuselage.max_height_m);
      const maxZ = Math.max(
        ...wing.sections.map(section => section.zLe),
        largest.z + .5 * envelopeHeight,
        ...fairingSections.map(section => section.z + .5 * section.height),
        finBaseZ + finDZ,
      ) + .12;
      const minZ = Math.min(
        0,
        largest.z - .5 * envelopeHeight,
        ...wing.sections.map(section => section.zLe),
        ...fairingSections.map(section => section.z - .5 * section.height),
      ) - .10;
      const frame = stableViewFrame(
        "front",
        makeFrame(-halfSpan * 1.08, halfSpan * 1.08, minZ, maxZ),
      );
      frames.front = frame;
      const section = window.OpenAirPreviewMesh.sectionPolygon(largest, 96);
      const fairingPaths = fairings.flatMap(fairing => fairing.sections
        .filter(candidate => candidate.width > 0 && candidate.height > 0)
        .map(candidate => `<path class="fairing-shape" d="${pathData(
          window.OpenAirPreviewMesh.sectionPolygon(candidate, 96),
          frame,
        )}"></path>`)).join("");
      const wingPoints = [
        ...wing.sections.slice().reverse().map(section => [-section.eta * halfSpan, section.zLe]),
        ...wing.sections.slice(1).map(section => [section.eta * halfSpan, section.zLe]),
      ];
      const finLines = Math.round(number(v.count, 2)) === 1
        ? [line(finBaseY, finBaseZ, finBaseY + finDY, finBaseZ + finDZ, frame, "fin-shape")]
        : [
          line(finBaseY, finBaseZ, finBaseY + finDY, finBaseZ + finDZ, frame, "fin-shape"),
          line(-finBaseY, finBaseZ, -finBaseY - finDY, finBaseZ + finDZ, frame, "fin-shape"),
        ];
      const finRootGeometry = window.OpenAirPreviewMesh.finRootGeometry(design);
      const finRootLines = !finRootGeometry.extensionRequired
        ? []
        : Math.round(number(v.count, 2)) === 1
          ? [
            line(
              finRootGeometry.y,
              finRootGeometry.z,
              0,
              finBaseZ,
              frame,
              "fin-shape root-extension",
            ),
          ]
          : [
            line(
              finRootGeometry.y,
              finRootGeometry.z,
              finBaseY,
              finBaseZ,
              frame,
              "fin-shape root-extension",
            ),
            line(
              -finRootGeometry.y,
              finRootGeometry.z,
              -finBaseY,
              finBaseZ,
              frame,
              "fin-shape root-extension",
            ),
          ];
      svg.innerHTML = [
        gridLines(frame, "front"),
        line(-halfSpan, 0, halfSpan, 0, frame),
        `<path class="airframe" fill="none" d="${pathData(wingPoints, frame, false)}"></path>`,
        `<path class="body-shape" d="${pathData(section, frame)}"></path>`,
        fairingPaths,
        ...finRootLines,
        ...finLines,
        semanticHandles("front", frame),
      ].join("");
    }

    function renderViews() {
      renderTop();
      renderSide();
      renderFront();
    }

    function fuselageWettedArea() {
      const f = design.fuselage;
      const profile = bodyProfile();
      if (Array.isArray(f.stations)) {
        let area = 0;
        for (let index = 0; index < profile.length - 1; index += 1) {
          const left = profile[index];
          const right = profile[index + 1];
          const ds = Math.hypot(right.x - left.x, right.z - left.z);
          const leftPerimeter = window.OpenAirPreviewMesh.sectionMetrics(left).perimeter;
          const rightPerimeter = window.OpenAirPreviewMesh.sectionMetrics(right).perimeter;
          area += .5 * (leftPerimeter + rightPerimeter) * ds;
        }
        return area;
      }
      const a = .5 * number(f.length_m);
      const b = .5 * number(f.max_width_m);
      const c = .5 * number(f.max_height_m);
      const p = 1.6075;
      return 4 * Math.PI * ((a ** p * b ** p + a ** p * c ** p + b ** p * c ** p) / 3) ** (1 / p);
    }

    function quickMasses() {
      const wing = wingGeometry();
      const s = design.structures;
      const material = s.material;
      const fuel = number(design.mass.fuel_mass_kg);
      const payload = number(design.mission.payload_kg);
      const density = number(material.density_kg_m3);
      const wingMass = wing.area * (
        number(s.skin_thickness_m) + 2 * number(design.wing.t_over_c) * number(s.spar_thickness_m)
      ) * density * number(s.wing_weight_ratio);
      const vArea = number(design.vtail.span_m) * number(design.vtail.root_chord_m) * (1 + number(design.vtail.taper)) / 2;
      const hArea = number(design.htail.span_m) * number(design.htail.root_chord_m) * (1 + number(design.htail.taper)) / 2;
      const vtail = 4.8 * (number(design.vtail.count, 2) * vArea) ** .9;
      const htail = hArea > 0 ? 4.2 * hArea ** .9 : 0;
      let mtow = payload + fuel + wingMass + number(design.engine.dry_mass_kg) + 20;
      let values = {};
      for (let iteration = 0; iteration < 8; iteration += 1) {
        const fuselage = fuselageWettedArea() * .0012 * density * .55 + .025 * mtow + 1.5;
        const gear = number(design.mass.landing_gear_fraction) * mtow;
        const fuelSystem = .08 * fuel + .4;
        const fixed = wingMass + fuselage + vtail + htail + number(design.mass.systems_kg)
          + number(design.mass.avionics_kg) + gear + fuelSystem + number(design.engine.dry_mass_kg);
        const contingency = number(design.mass.contingency_fraction) * fixed;
        mtow = fixed + contingency + payload + fuel;
        values = {wingMass, fuselage, vtail, htail, gear, fuelSystem, contingency, mtow, fuel, payload};
      }
      return values;
    }

    function quickBalance() {
      const wing = wingGeometry();
      const masses = quickMasses();
      const f = design.fuselage;
      const v = design.vtail;
      const fuelDensity = number(design.engine.fuel_density_kg_m3, 800);
      const wingTankVolume = wing.area * number(design.wing.t_over_c) * .5 * .8 * .5;
      const fixedItems = [
        [masses.payload, number(f.payload_bay_x_m) + .5 * number(f.payload_bay_length_m)],
        [number(design.engine.dry_mass_kg), number(f.length_m) - .2 - .5 * number(design.engine.length_m)],
        [masses.wingMass, wing.xLeMac + .4 * wing.mac],
        [masses.fuselage, .5 * number(f.length_m)],
        [masses.vtail, number(v.x_le_m) + .5 * number(v.root_chord_m)],
        [masses.htail, number(design.htail.x_le_m) + .3],
        [number(design.mass.systems_kg), number(f.fuel_tank_x_m)],
        [number(design.mass.avionics_kg), .5 * number(f.length_m)],
        [masses.gear, .58 * number(f.length_m)],
        [masses.fuelSystem, number(f.fuel_tank_x_m)],
        [masses.contingency, .5 * number(f.length_m)],
      ].filter(item => item[0] > 0);

      function cgAtFuel(fuelMass) {
        const wingFuel = Math.min(fuelMass, wingTankVolume * fuelDensity);
        const fuseFuel = Math.max(fuelMass - wingFuel, 0);
        const items = [
          ...fixedItems,
          [wingFuel, wing.xLeMac + .32 * wing.mac],
          [fuseFuel, number(f.fuel_tank_x_m)],
        ].filter(item => item[0] > 0);
        return items.reduce((sum, item) => sum + item[0] * item[1], 0)
          / items.reduce((sum, item) => sum + item[0], 0);
      }

      const cg = cgAtFuel(masses.fuel);
      const reserveFuel = masses.fuel * number(design.mission.reserve_fuel_fraction);
      const reserveCg = cgAtFuel(reserveFuel);
      const np = wing.xLeMac + (.25 + number(design.solver.np_shift_mac)) * wing.mac;
      const sm = (np - cg) / wing.mac;
      const smReserve = (np - reserveCg) / wing.mac;
      const vTaper = number(v.taper);
      const vYMac = number(v.span_m) / 3 * (1 + 2 * vTaper) / (1 + vTaper);
      const vMac = 2 / 3 * number(v.root_chord_m) * (1 + vTaper + vTaper ** 2) / (1 + vTaper);
      const vAc = number(v.x_le_m) + vYMac * Math.tan(radians(number(v.le_sweep_deg))) + .25 * vMac;
      const arm = Math.max(vAc - cg, .01);
      const vArea = number(v.span_m) * number(v.root_chord_m) * (1 + vTaper) / 2;
      const vv = number(v.count, 2) * vArea * arm * Math.cos(radians(number(v.cant_deg))) / (wing.area * wing.span);
      return {masses, cg, reserveCg, np, sm, smReserve, vv};
    }

    function quickPacking() {
      const f = design.fuselage;
      const profile = bodyProfile();
      let bodyVolume = 0;
      if (Array.isArray(f.stations)) {
        for (let index = 0; index < profile.length - 1; index += 1) {
          const left = profile[index];
          const right = profile[index + 1];
          const a = window.OpenAirPreviewMesh.sectionMetrics(left).area;
          const b = window.OpenAirPreviewMesh.sectionMetrics(right).area;
          bodyVolume += .5 * (a + b) * (right.x - left.x);
        }
        bodyVolume *= .70;
      } else {
        bodyVolume = .70 * 4 / 3 * Math.PI * .5 * number(f.length_m) * .5 * number(f.max_width_m) * .5 * number(f.max_height_m);
      }
      const diameter = number(design.engine.diameter_m) + .04;
      const engineVolume = Math.PI * (.5 * diameter) ** 2 * (number(design.engine.length_m) + .08);
      const payloadVolume = number(f.payload_bay_length_m) * number(f.payload_bay_width_m) * number(f.payload_bay_height_m);
      const fuelVolume = number(design.mass.fuel_mass_kg) / number(design.engine.fuel_density_kg_m3, 800);
      const wing = wingGeometry();
      const wingVolume = wing.area * number(design.wing.t_over_c) * .5 * .8 * .5;
      const left = bodyVolume - engineVolume - payloadVolume - .15 * bodyVolume + wingVolume;
      return {bodyVolume, fuelVolume, margin: left - fuelVolume, ok: left >= fuelVolume};
    }

    function metric(label, value, note, good = null) {
      const status = good == null ? "" : good ? " good" : " warn";
      return `<article class="metric${status}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><em>${escapeHtml(note)}</em></article>`;
    }

    function renderDerived() {
      const wing = wingGeometry();
      const balance = quickBalance();
      const pack = quickPacking();
      const lo = number(design.mission.static_margin_min);
      const hi = number(design.mission.static_margin_max);
      const smGood = balance.sm >= lo && balance.sm <= hi && balance.smReserve >= lo && balance.smReserve <= hi;
      const vvGood = balance.vv >= .02 && balance.vv <= .09;
      const planformNote = wing.sectioned
        ? `${wing.sections.length}-section measured loft`
        : "trapezoid";
      $("#derived").innerHTML = [
        metric("Wing area S", `${wing.area.toFixed(3)} m²`, planformNote),
        metric("Aspect ratio", (wing.span ** 2 / wing.area).toFixed(3), "b² / S"),
        metric("Mean aerodynamic chord", `${wing.mac.toFixed(3)} m`, wing.sectioned ? "section-integrated MAC" : "trapezoid MAC"),
        metric("Estimated MTOW", `${balance.masses.mtow.toFixed(1)} kg`, "quick component buildup"),
        metric("Static margin", `${balance.sm.toFixed(3)} → ${balance.smReserve.toFixed(3)}`, `required ${lo.toFixed(2)}–${hi.toFixed(2)} MAC`, smGood),
        metric(`${number(design.vtail.count, 2) === 1 ? "Single-fin" : "Twin-fin"} volume Vv`, balance.vv.toFixed(4), "concept band 0.02–0.09", vvGood),
        metric("Usable body volume", `${pack.bodyVolume.toFixed(3)} m³`, "70% after taper/frames"),
        metric("Fuel packing margin", `${pack.margin.toFixed(3)} m³`, `fuel ${pack.fuelVolume.toFixed(3)} m³`, pack.ok),
      ].join("");
    }

    function pointerModelPoint(event, svg, frame) {
      const rect = svg.getBoundingClientRect();
      const px = (event.clientX - rect.left) * SVG_W / rect.width;
      const py = (event.clientY - rect.top) * SVG_H / rect.height;
      return frame.unmap(px, py);
    }

    function dragHandle(event) {
      if (!drag) return;
      const raw = pointerModelPoint(event, drag.svg, drag.frame);
      const target = [
        drag.startPosition[0] + (raw[0] - drag.startPointer[0]) * drag.gain,
        drag.startPosition[1] + (raw[1] - drag.startPointer[1]) * drag.gain,
      ];
      const patches = window.OpenAirHandles.drag(
        drag.kind,
        design,
        target,
        drag.index,
      );
      const entries = applyPatches(
        patches,
        {source: `handle:${drag.kind}`, record: false},
      );
      entries.forEach(entry => drag.paths.add(entry.path));
    }

    function pointerDown(event) {
      const target = event.target.closest("[data-handle]");
      if (!target || calibrationMode) return;
      event.preventDefault();
      const view = event.currentTarget.id.replace("-view", "");
      const index = target.dataset.index == null ? null : Number(target.dataset.index);
      const handle = window.OpenAirHandles.instances(view, design).find(
        candidate => candidate.id === target.dataset.handle
          && candidate.index === index,
      );
      if (!handle) return;
      const frame = frames[view];
      drag = {
        kind: target.dataset.handle,
        index,
        view,
        svg: event.currentTarget,
        frame,
        gain: handle.dragGain,
        startPointer: pointerModelPoint(event, event.currentTarget, frame),
        startPosition: [...handle.position],
        before: clone(design),
        paths: new Set(),
      };
    }

    function pointerUp() {
      if (!drag) return;
      const entries = Array.from(drag.paths).map(path => ({
        path,
        oldValue: cloneValue(getPath(path, drag.before)),
        newValue: cloneValue(getPath(path)),
      })).filter(entry => !valuesEqual(entry.oldValue, entry.newValue));
      recordHistory(entries, `handle:${drag.kind}`);
      drag = null;
      updateAll();
    }

    function scalarWithoutComment(raw) {
      let quote = null;
      let depth = 0;
      for (let index = 0; index < raw.length; index += 1) {
        const char = raw[index];
        if (quote) {
          if (char === quote && raw[index - 1] !== "\\") quote = null;
          continue;
        }
        if (char === '"' || char === "'") quote = char;
        else if (char === "[" || char === "{") depth += 1;
        else if (char === "]" || char === "}") depth -= 1;
        else if (char === "#" && depth === 0 && (index === 0 || /\s/.test(raw[index - 1]))) return raw.slice(0, index).trim();
      }
      return raw.trim();
    }

    function splitTopLevel(text, delimiter = ",") {
      const parts = [];
      let start = 0;
      let quote = null;
      let depth = 0;
      for (let index = 0; index < text.length; index += 1) {
        const char = text[index];
        if (quote) {
          if (char === quote && text[index - 1] !== "\\") quote = null;
        } else if (char === '"' || char === "'") quote = char;
        else if (char === "[" || char === "{") depth += 1;
        else if (char === "]" || char === "}") depth -= 1;
        else if (char === delimiter && depth === 0) {
          parts.push(text.slice(start, index).trim());
          start = index + 1;
        }
      }
      parts.push(text.slice(start).trim());
      return parts.filter(Boolean);
    }

    function splitKeyValue(text) {
      let quote = null;
      let depth = 0;
      for (let index = 0; index < text.length; index += 1) {
        const char = text[index];
        if (quote) {
          if (char === quote && text[index - 1] !== "\\") quote = null;
        } else if (char === '"' || char === "'") quote = char;
        else if (char === "[" || char === "{") depth += 1;
        else if (char === "]" || char === "}") depth -= 1;
        else if (char === ":" && depth === 0) return [text.slice(0, index).trim(), text.slice(index + 1).trim()];
      }
      throw new Error(`Expected key: value, got "${text}"`);
    }

    function parseScalar(raw) {
      const text = scalarWithoutComment(raw);
      if (text === "") return "";
      if (text.startsWith('"') && text.endsWith('"')) return JSON.parse(text);
      if (text.startsWith("'") && text.endsWith("'")) return text.slice(1, -1).replaceAll("''", "'");
      if (/^(true|false)$/i.test(text)) return text.toLowerCase() === "true";
      if (/^(null|~)$/i.test(text)) return null;
      if (/^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(text)) return Number(text);
      if (text.startsWith("[") && text.endsWith("]")) return splitTopLevel(text.slice(1, -1)).map(parseScalar);
      if (text.startsWith("{") && text.endsWith("}")) {
        const object = {};
        splitTopLevel(text.slice(1, -1)).forEach(part => {
          const [key, value] = splitKeyValue(part);
          object[key.replace(/^['"]|['"]$/g, "")] = parseScalar(value);
        });
        return object;
      }
      return text;
    }

    function parseYaml(text) {
      const rawLines = text.replaceAll("\t", "  ").split(/\r?\n/);
      const lines = rawLines.map((raw, index) => ({
        raw,
        index,
        indent: raw.match(/^ */)[0].length,
        content: raw.trim(),
      })).filter(line => line.content && !line.content.startsWith("#"));

      function parseBlock(start, indent) {
        if (lines[start] && lines[start].indent === indent && lines[start].content.startsWith("- ")) {
          const array = [];
          let cursor = start;
          while (cursor < lines.length && lines[cursor].indent === indent && lines[cursor].content.startsWith("- ")) {
            const itemText = lines[cursor].content.slice(2).trim();
            if (
              itemText
              && !itemText.startsWith("{")
              && !itemText.startsWith("[")
              && itemText.includes(":")
            ) {
              const item = {};
              const [firstKey, firstValue] = splitKeyValue(itemText);
              item[firstKey.replace(/^['"]|['"]$/g, "")] = parseScalar(firstValue);
              cursor += 1;
              while (cursor < lines.length && lines[cursor].indent > indent) {
                const child = lines[cursor];
                const [rawKey, rawValue] = splitKeyValue(child.content);
                const key = rawKey.replace(/^['"]|['"]$/g, "");
                if (rawValue === "") {
                  cursor += 1;
                  if (cursor < lines.length && lines[cursor].indent > child.indent) {
                    [item[key], cursor] = parseBlock(cursor, lines[cursor].indent);
                  } else {
                    item[key] = {};
                  }
                } else {
                  item[key] = parseScalar(rawValue);
                  cursor += 1;
                }
              }
              array.push(item);
              continue;
            }
            array.push(parseScalar(itemText));
            cursor += 1;
          }
          return [array, cursor];
        }
        const object = {};
        let cursor = start;
        while (cursor < lines.length) {
          const line = lines[cursor];
          if (line.indent < indent) break;
          if (line.indent > indent) throw new Error(`Unexpected indentation on line ${line.index + 1}`);
          const [rawKey, rawValue] = splitKeyValue(line.content);
          const key = rawKey.replace(/^['"]|['"]$/g, "");
          if (["|", "|-", ">", ">-"].includes(rawValue)) {
            cursor += 1;
            const values = [];
            while (cursor < lines.length && lines[cursor].indent > indent) {
              values.push(lines[cursor].raw.trim());
              cursor += 1;
            }
            object[key] = rawValue.startsWith(">") ? values.join(" ") : values.join("\n");
            continue;
          }
          if (rawValue === "") {
            cursor += 1;
            if (cursor < lines.length && lines[cursor].indent > indent) {
              [object[key], cursor] = parseBlock(cursor, lines[cursor].indent);
            } else {
              object[key] = {};
            }
            continue;
          }
          object[key] = parseScalar(rawValue);
          cursor += 1;
        }
        return [object, cursor];
      }

      if (!lines.length) return {};
      return parseBlock(0, lines[0].indent)[0];
    }

    function deepMerge(base, update) {
      if (Array.isArray(update)) return clone(update);
      if (update === null || typeof update !== "object") return update;
      const result = base && typeof base === "object" && !Array.isArray(base) ? clone(base) : {};
      Object.entries(update).forEach(([key, value]) => {
        result[key] = deepMerge(result[key], value);
      });
      return result;
    }

    function yamlScalar(value) {
      if (value === null || value === undefined) return "null";
      if (typeof value === "boolean") return value ? "true" : "false";
      if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
      return JSON.stringify(String(value));
    }

    function yamlLines(value, indent = 0) {
      const pad = " ".repeat(indent);
      const lines = [];
      Object.entries(value).forEach(([key, child]) => {
        if (child === undefined) return;
        if (typeof child === "string" && child.includes("\n")) {
          lines.push(`${pad}${key}: >-`);
          child.split("\n").forEach(line => lines.push(`${pad}  ${line}`));
        } else if (Array.isArray(child)) {
          if (!child.length) {
            lines.push(`${pad}${key}: []`);
          } else {
            lines.push(`${pad}${key}:`);
            child.forEach(item => {
              if (item && typeof item === "object" && !Array.isArray(item)) {
                // JSON flow mappings are valid YAML and preserve nested lists
                // such as control-surface mixing without "[object Object]".
                lines.push(`${pad}  - ${JSON.stringify(item)}`);
              } else {
                lines.push(`${pad}  - ${yamlScalar(item)}`);
              }
            });
          }
        } else if (child && typeof child === "object") {
          lines.push(`${pad}${key}:`);
          lines.push(...yamlLines(child, indent + 2));
        } else {
          lines.push(`${pad}${key}: ${yamlScalar(child)}`);
        }
      });
      return lines;
    }

    function exportObject() {
      const result = clone(design);
      result.sketch = computedSketch(result);
      return result;
    }

    function exportYaml() {
      return `${yamlLines(exportObject()).join("\n")}\n`;
    }

    const WORKSHEET_START = "<!-- OPENAIR_SKETCH_WORKSHEET_START -->";
    const WORKSHEET_END = "<!-- OPENAIR_SKETCH_WORKSHEET_END -->";

    function sketchWorksheet() {
      const sketch = computedSketch();
      const f = design.fuselage;
      const wing = design.wing;
      const wingModel = wingGeometry();
      const fin = design.vtail;
      const finRootGeometry = window.OpenAirPreviewMesh.finRootGeometry(design);
      const fairings = Array.isArray(f.fairings) ? f.fairings : [];
      const wingRows = [
        `| Wing ${wingModel.sectioned ? "actual tip chord" : "tip chord"} | ${wingModel.tip.toFixed(4)} m | ${wingModel.sectioned ? "outer wing section" : "derived from taper"} |`,
        `| Wing projected area | ${wingModel.area.toFixed(4)} m² | ${wingModel.sectioned ? `${wingModel.sections.length}-section integral` : "trapezoid"} |`,
        `| Wing mean aerodynamic chord | ${wingModel.mac.toFixed(4)} m | ${wingModel.sectioned ? "section integral" : "trapezoid"} |`,
      ];
      if (wingModel.sectioned) {
        wingRows.push(
          `| Wing equivalent tip chord | ${wingModel.equivalentTip.toFixed(4)} m | scalar area-equivalent descriptor, not physical tip |`,
        );
      }
      const lines = [
        WORKSHEET_START,
        "## Sketch measurement worksheet",
        "",
        "Generated by open-air Design Studio. Preserve source/inference notes in the brief above this section.",
        "",
        "### Rectification and scale",
        "",
      ];
      ["top", "side", "front"].forEach(view => {
        const state = overlayState(view);
        const points = state.points.length === 4
          ? state.points.map(point => `(${round(point.sourceX, 2)}, ${round(point.sourceY, 2)})`).join(", ")
          : "not rectified (no four-point control set)";
        lines.push(
          `- **${view}**: source \`${state.fileName || "not supplied"}\`; `
          + `control points ${points}; fuselage ${number(state.gridSquares).toFixed(2)} grid squares; `
          + `${metresPerGridSquare(view).toFixed(5)} m/grid square.`,
        );
      });
      lines.push(
        "",
        "### Measured geometry and tolerances",
        "",
        "| Quantity | Measured value | Tolerance |",
        "|---|---:|---:|",
        `| Fuselage length | ${number(f.length_m).toFixed(4)} m | source scale |`,
        `| Fuselage maximum width | ${number(f.max_width_m).toFixed(4)} m | station envelope |`,
        `| Fuselage maximum height | ${number(f.max_height_m).toFixed(4)} m | station envelope |`,
        `| Wing span | ${number(wing.span_m).toFixed(4)} m | source grid resolution |`,
        `| Wing root chord | ${number(wing.root_chord_m).toFixed(4)} m | source grid resolution |`,
        ...wingRows,
        `| Wing span / length | ${sketch.span_over_length.toFixed(6)} | ±${number(sketch.span_over_length_tol).toFixed(4)} |`,
        `| Wing root chord / length | ${sketch.root_over_length.toFixed(6)} | ±${number(sketch.root_over_length_tol).toFixed(4)} |`,
        `| Wing leading-edge sweep | ${number(sketch.le_sweep_deg).toFixed(4)} deg | ±${number(sketch.le_sweep_tol_deg).toFixed(4)} deg |`,
        `| Wing taper | ${number(sketch.taper).toFixed(6)} | ±${number(sketch.taper_tol).toFixed(4)} |`,
        `| Wing root LE | ${number(wing.x_le_root_m).toFixed(4)} m | source grid resolution |`,
        `| Wing root LE / length | ${sketch.x_le_root_over_length.toFixed(6)} | ±${number(sketch.x_le_root_over_length_tol).toFixed(4)} |`,
        `| Fin count | ${Math.round(number(fin.count, 2))} | centerline or symmetric pair |`,
        `| Fin span | ${number(fin.span_m).toFixed(4)} m | document source tolerance |`,
        `| Fin root chord | ${number(fin.root_chord_m).toFixed(4)} m | document source tolerance |`,
        `| Fin tip chord | ${(number(fin.root_chord_m) * number(fin.taper)).toFixed(4)} m | derived from taper |`,
        `| Fin leading-edge sweep | ${number(fin.le_sweep_deg).toFixed(4)} deg | document source tolerance |`,
        `| Fin cant | ${number(fin.cant_deg).toFixed(4)} deg | document source tolerance |`,
        `| Fin root location (x, y, z) | (${number(fin.x_le_m).toFixed(4)}, ${number(fin.y_root_m).toFixed(4)}, ${number(fin.z_root_m).toFixed(4)}) m | document source tolerance |`,
        `| Fin buried root extension | ${number(finRootGeometry.extension).toFixed(4)} m | derived from body/fairing containment (eccentricity ≤ 0.8 + 5 mm margin) |`,
        "",
        "### Fuselage stations",
        "",
      );
      if (Array.isArray(f.stations) && f.stations.length) {
        lines.push(
          "| x/L | Width (m) | Height (m) | z offset (m) | Side power | Top power | Bottom power | Max-width loc |",
          "|---:|---:|---:|---:|---:|---:|---:|---:|",
        );
        f.stations.forEach(station => {
          lines.push(
            `| ${number(station.x_over_length).toFixed(5)} `
            + `| ${number(station.width_m).toFixed(5)} `
            + `| ${number(station.height_m).toFixed(5)} `
            + `| ${number(station.z_offset_m).toFixed(5)} `
            + `| ${number(station.side_power, 2).toFixed(5)} `
            + `| ${number(station.top_power, 2).toFixed(5)} `
            + `| ${number(station.bottom_power, 2).toFixed(5)} `
            + `| ${number(station.max_width_loc, 0).toFixed(5)} |`,
          );
        });
      } else {
        lines.push("Legacy five-section fuselage selected; no explicit measured station loft.");
      }
      lines.push("", "### Measured body fairings", "");
      if (fairings.length) {
        fairings.forEach(fairing => {
          lines.push(
            `#### ${fairing.name} (${fairing.role})`,
            "",
            "| x/L | Width (m) | Height (m) | z offset (m) | Side power | Top power | Bottom power | Max-width loc |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
          );
          fairing.stations.forEach(station => {
            lines.push(
              `| ${number(station.x_over_length).toFixed(5)} `
              + `| ${number(station.width_m).toFixed(5)} `
              + `| ${number(station.height_m).toFixed(5)} `
              + `| ${number(station.z_offset_m).toFixed(5)} `
              + `| ${number(station.side_power, 2).toFixed(5)} `
              + `| ${number(station.top_power, 2).toFixed(5)} `
              + `| ${number(station.bottom_power, 2).toFixed(5)} `
              + `| ${number(station.max_width_loc, 0).toFixed(5)} |`,
            );
          });
          lines.push("");
        });
      } else {
        lines.push("No measured auxiliary body fairings.");
      }
      lines.push(
        "",
        "### Inference record",
        "",
        "Document every value inferred rather than directly traced (including hidden-view dimensions, airfoil, gauges, material, propulsion assumptions, and tolerances) in the narrative above.",
        "",
        WORKSHEET_END,
      );
      return lines.join("\n");
    }

    function briefWithWorksheet() {
      const editor = $("#brief-editor");
      let base = editor.value;
      const start = base.indexOf(WORKSHEET_START);
      const finish = base.indexOf(WORKSHEET_END);
      if (start >= 0 && finish >= start) {
        base = `${base.slice(0, start)}${base.slice(finish + WORKSHEET_END.length)}`;
      }
      return `${base.trim()}\n\n${sketchWorksheet()}\n`;
    }

    function pngBase64(canvas) {
      return canvas.toDataURL("image/png").split(",", 2)[1];
    }

    function sketchesForSave() {
      const sketches = [];
      ["top", "side", "front"].forEach(view => {
        const state = overlayState(view);
        if (!state.source) return;
        sketches.push({
          name: `sketch-${view}.png`,
          png_base64: pngBase64(state.source),
        });
        if (state.rectified) {
          sketches.push({
            name: `sketch-${view}-rectified.png`,
            png_base64: pngBase64(state.canvas),
          });
        }
      });
      return sketches;
    }

    function saveBlob(filename, blob) {
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
    }

    async function saveConcept() {
      const form = $("#schema-form");
      if (!form.reportValidity()) {
        toast("Correct the highlighted schema fields before saving.");
        return;
      }
      const button = $("#save-concept");
      const label = $("#save-label");
      const originalLabel = label.textContent;
      button.disabled = true;
      label.textContent = "Saving…";
      try {
        const brief = briefWithWorksheet();
        const response = await fetch("/api/save", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Openair-Token": CONFIG.saveToken,
          },
          body: JSON.stringify({
            design_yaml: exportYaml(),
            brief_md: brief,
            sketches: sketchesForSave(),
          }),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || `save returned ${response.status}`);
        }
        $("#brief-editor").value = brief;
        savedDesign = clone(design);
        label.textContent = "Save concept";
        renderDiff();
        $("#trace-status").textContent = `Saved ${result.directory}. Next: ${result.next}`;
        toast(`Saved designs/${result.concept}/ successfully.`);
      } catch (error) {
        label.textContent = originalLabel;
        toast(`Concept save failed: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    }

    function setVspButton(active) {
      const button = $("#edit-openvsp");
      vspSessionActive = active;
      button.disabled = active;
      button.textContent = active ? "OpenVSP active" : "Advanced: OpenVSP";
    }

    function applyVspGeometry(geometry) {
      const next = clone(design);
      ["wing", "fuselage", "vtail", "htail"].forEach(key => {
        if (geometry[key]) next[key] = deepMerge(next[key], geometry[key]);
      });
      replaceDesign(next, "openvsp");
    }

    async function pollVspStatus() {
      if (!vspSessionActive) return;
      try {
        const response = await fetch("/api/vsp/status", {
          headers: {"X-Openair-Token": CONFIG.saveToken},
        });
        const result = await response.json();
        if (!response.ok) {
          throw new Error(result.error || `status returned ${response.status}`);
        }
        if (result.changed && result.geometry) {
          applyVspGeometry(result.geometry);
          const summary = (result.changes || []).slice(0, 3).join("; ");
          toast(summary ? `OpenVSP: ${summary}` : "OpenVSP geometry is unchanged.");
          vspRejectionSignature = "";
        }
        if (result.rejected) {
          const signature = JSON.stringify(result.rejected);
          if (signature !== vspRejectionSignature) {
            toast(`OpenVSP edit rejected: ${result.rejected.join("; ")}`);
            vspRejectionSignature = signature;
          }
          $("#trace-status").textContent = `OpenVSP rejected: ${result.rejected.join("; ")}`;
        } else {
          $("#trace-status").textContent = result.message || "OpenVSP session active.";
        }
        if (result.running || result.pending) {
          vspPollTimer = window.setTimeout(pollVspStatus, 1500);
        } else {
          setVspButton(false);
          vspPollTimer = null;
        }
      } catch (error) {
        setVspButton(false);
        vspPollTimer = null;
        toast(`OpenVSP sync stopped: ${error.message}`);
      }
    }

    async function openVspEditor() {
      const form = $("#schema-form");
      if (!form.reportValidity()) {
        toast("Correct the highlighted schema fields before opening OpenVSP.");
        return;
      }
      const button = $("#edit-openvsp");
      button.disabled = true;
      button.textContent = "Opening…";
      try {
        const response = await fetch("/api/vsp/open", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Openair-Token": CONFIG.saveToken,
          },
          body: JSON.stringify({design_yaml: exportYaml()}),
        });
        const result = await response.json();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || `open returned ${response.status}`);
        }
        setVspButton(true);
        vspRejectionSignature = "";
        $("#trace-status").textContent = result.message;
        if ((result.warnings || []).length) {
          toast(`OpenVSP opened with warning: ${result.warnings.join("; ")}`);
        } else {
          toast("OpenVSP opened. Save there to sync geometry back.");
        }
        vspPollTimer = window.setTimeout(pollVspStatus, 500);
      } catch (error) {
        setVspButton(false);
        toast(`Could not open OpenVSP: ${error.message}`);
      }
    }

    function applyYaml(text) {
      const parsed = parseYaml(text);
      replaceDesign(deepMerge(ORIGINAL, parsed), "yaml-import");
      toast("Imported YAML and refreshed the views.");
    }

    function overlayState(view) {
      if (overlays[view]) return overlays[view];
      const canvas = $(`#${view}-underlay`);
      overlays[view] = {
        view, canvas, context: canvas.getContext("2d", {willReadFrequently: true}),
        image: null, source: null, points: [], rectified: null, display: null,
        fileName: null, gridSquares: 24.5,
      };
      return overlays[view];
    }

    function drawOverlay(state) {
      const {canvas, context} = state;
      context.clearRect(0, 0, canvas.width, canvas.height);
      if (state.rectified) {
        context.putImageData(state.rectified, 0, 0);
      } else if (state.image) {
        const scale = Math.min(canvas.width / state.image.width, canvas.height / state.image.height);
        const width = state.image.width * scale;
        const height = state.image.height * scale;
        const x = .5 * (canvas.width - width);
        const y = .5 * (canvas.height - height);
        context.drawImage(state.image, x, y, width, height);
        state.display = {x, y, width, height, scale};
      }
      if (calibrationMode && state.view === $("#trace-view").value) {
        context.save();
        context.fillStyle = "#e9673f";
        context.strokeStyle = "white";
        context.lineWidth = 2;
        state.points.forEach((point, index) => {
          context.beginPath();
          context.arc(point.canvasX, point.canvasY, 7, 0, Math.PI * 2);
          context.fill();
          context.stroke();
          context.fillStyle = "white";
          context.fillText(String(index + 1), point.canvasX - 3, point.canvasY + 3);
          context.fillStyle = "#e9673f";
        });
        context.restore();
      }
    }

    function solveLinear(matrix, vector) {
      const n = vector.length;
      const a = matrix.map((row, index) => [...row, vector[index]]);
      for (let column = 0; column < n; column += 1) {
        let pivot = column;
        for (let row = column + 1; row < n; row += 1) {
          if (Math.abs(a[row][column]) > Math.abs(a[pivot][column])) pivot = row;
        }
        if (Math.abs(a[pivot][column]) < 1e-12) throw new Error("Grid corners are degenerate.");
        [a[column], a[pivot]] = [a[pivot], a[column]];
        const divisor = a[column][column];
        for (let item = column; item <= n; item += 1) a[column][item] /= divisor;
        for (let row = 0; row < n; row += 1) {
          if (row === column) continue;
          const factor = a[row][column];
          for (let item = column; item <= n; item += 1) a[row][item] -= factor * a[column][item];
        }
      }
      return a.map((row, index) => row[n]);
    }

    function homographyDestinationToSource(points, width, height) {
      const destinations = [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]];
      const matrix = [];
      const vector = [];
      destinations.forEach(([u, v], index) => {
        const {sourceX: x, sourceY: y} = points[index];
        matrix.push([u, v, 1, 0, 0, 0, -x * u, -x * v]);
        vector.push(x);
        matrix.push([0, 0, 0, u, v, 1, -y * u, -y * v]);
        vector.push(y);
      });
      return [...solveLinear(matrix, vector), 1];
    }

    function rectifyOverlay(state) {
      if (!state.source || state.points.length !== 4) return;
      const {canvas, context, source} = state;
      const h = homographyDestinationToSource(state.points, canvas.width, canvas.height);
      const sourceContext = source.getContext("2d", {willReadFrequently: true});
      const sourceData = sourceContext.getImageData(0, 0, source.width, source.height).data;
      const output = context.createImageData(canvas.width, canvas.height);
      for (let v = 0; v < canvas.height; v += 1) {
        for (let u = 0; u < canvas.width; u += 1) {
          const denominator = h[6] * u + h[7] * v + 1;
          const x = Math.round((h[0] * u + h[1] * v + h[2]) / denominator);
          const y = Math.round((h[3] * u + h[4] * v + h[5]) / denominator);
          const targetIndex = 4 * (v * canvas.width + u);
          if (x >= 0 && x < source.width && y >= 0 && y < source.height) {
            const sourceIndex = 4 * (y * source.width + x);
            output.data[targetIndex] = sourceData[sourceIndex];
            output.data[targetIndex + 1] = sourceData[sourceIndex + 1];
            output.data[targetIndex + 2] = sourceData[sourceIndex + 2];
            output.data[targetIndex + 3] = sourceData[sourceIndex + 3];
          }
        }
      }
      state.rectified = output;
      calibrationMode = false;
      drawOverlay(state);
      $("#trace-status").textContent = "Rectified. Drag geometry handles to match the underlay.";
      toast("Perspective rectification applied.");
    }

    function loadSketchFile(file, view) {
      if (!file || !file.type.startsWith("image/")) {
        toast("Choose a PNG or JPEG sketch.");
        return;
      }
      const state = overlayState(view);
      const image = new Image();
      const url = URL.createObjectURL(file);
      image.onload = () => {
        state.image = image;
        state.fileName = file.name;
        state.rectified = null;
        state.points = [];
        const source = document.createElement("canvas");
        source.width = image.naturalWidth;
        source.height = image.naturalHeight;
        source.getContext("2d").drawImage(image, 0, 0);
        state.source = source;
        drawOverlay(state);
        URL.revokeObjectURL(url);
        $("#trace-status").textContent = `${view} photo loaded. Pick four grid corners clockwise from top-left.`;
      };
      image.src = url;
    }

    function calibrationClick(event) {
      if (!calibrationMode) return;
      const view = event.currentTarget.id.replace("-view", "");
      if (view !== $("#trace-view").value) return;
      const state = overlayState(view);
      if (!state.image || !state.display) {
        toast("Load a sketch into this view first.");
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      const canvasX = (event.clientX - rect.left) * state.canvas.width / rect.width;
      const canvasY = (event.clientY - rect.top) * state.canvas.height / rect.height;
      const sourceX = (canvasX - state.display.x) / state.display.scale;
      const sourceY = (canvasY - state.display.y) / state.display.scale;
      if (sourceX < 0 || sourceY < 0 || sourceX > state.source.width || sourceY > state.source.height) {
        toast("Pick a point inside the photo.");
        return;
      }
      state.points.push({canvasX, canvasY, sourceX, sourceY});
      drawOverlay(state);
      const remaining = 4 - state.points.length;
      $("#trace-status").textContent = remaining
        ? `Pick ${remaining} more corner${remaining === 1 ? "" : "s"} clockwise.`
        : "Rectifying…";
      if (!remaining) requestAnimationFrame(() => rectifyOverlay(state));
    }

    function metresPerGridSquare(view = $("#trace-view").value) {
      const state = overlayState(view);
      return number(design.fuselage.length_m) / Math.max(number(state.gridSquares, 1), .1);
    }

    $("#schema-form").addEventListener("input", event => {
      const input = event.target.closest("[data-path]");
      if (!input) return;
      applyPatches(
        [{path: input.dataset.path, value: readInput(input)}],
        {source: `form:${input.dataset.path}`, coalesce: true},
      );
    });

    $("#schema-form").addEventListener("click", event => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      if (action === "enable-stations") {
        applyPatches(
          [{path: "fuselage.stations", value: defaultStations()}],
          {source: "stations:enable"},
        );
        return;
      }
      if (action === "disable-stations") {
        applyPatches(
          [{path: "fuselage.stations", value: null}],
          {source: "stations:disable"},
        );
        return;
      }
      if (action === "add-station") {
        const stations = clone(design.fuselage.stations);
        if (Array.isArray(stations) && stations.length < 8) {
          const index = Math.max(1, stations.length - 1);
          const left = stations[index - 1];
          const right = stations[index];
          stations.splice(index, 0, {
            x_over_length: round(.5 * (number(left.x_over_length) + number(right.x_over_length))),
            width_m: round(.5 * (number(left.width_m) + number(right.width_m))),
            height_m: round(.5 * (number(left.height_m) + number(right.height_m))),
            z_offset_m: round(.5 * (number(left.z_offset_m) + number(right.z_offset_m))),
            side_power: round(.5 * (number(left.side_power, 2) + number(right.side_power, 2))),
            top_power: round(.5 * (number(left.top_power, 2) + number(right.top_power, 2))),
            bottom_power: round(.5 * (number(left.bottom_power, 2) + number(right.bottom_power, 2))),
          });
          applyPatches(
            [{path: "fuselage.stations", value: stations}],
            {source: "stations:add"},
          );
        }
        return;
      }
      if (action === "remove-station") {
        const stations = clone(design.fuselage.stations);
        const index = Number(button.dataset.index);
        if (Array.isArray(stations) && stations.length > 4 && index > 0 && index < stations.length - 1) {
          stations.splice(index, 1);
          applyPatches(
            [{path: "fuselage.stations", value: stations}],
            {source: "stations:remove"},
          );
        }
        return;
      }
      if (action === "toggle-optional") {
        const path = button.dataset.path;
        applyPatches(
          [{
            path,
            value: getPath(path) == null ? (path === "sketch" ? computedSketch() : {}) : null,
          }],
          {source: `optional:${path}`},
        );
      }
    });

    ["top", "side", "front"].forEach(view => {
      const svg = $(`#${view}-view`);
      svg.addEventListener("pointerdown", pointerDown);
      svg.addEventListener("click", calibrationClick);
      const viewport = svg.closest(".viewport");
      viewport.addEventListener("dragover", event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      });
      viewport.addEventListener("drop", event => {
        event.preventDefault();
        $("#trace-view").value = view;
        loadSketchFile(event.dataTransfer.files[0], view);
      });
      overlayState(view);
    });
    window.addEventListener("pointermove", dragHandle);
    window.addEventListener("pointerup", pointerUp);
    window.addEventListener("pointercancel", pointerUp);

    $("#reset-design").addEventListener("click", () => {
      replaceDesign(clone(ORIGINAL), "reset");
      $("#brief-editor").value = ORIGINAL_BRIEF;
      toast("Restored the generated starting design.");
    });
    $("#undo-design").addEventListener("click", undo);
    $("#redo-design").addEventListener("click", redo);
    window.addEventListener("keydown", event => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
    });
    $("#preview-yaml").addEventListener("click", () => {
      $("#yaml-preview").value = exportYaml();
      $("#yaml-modal").classList.add("open");
    });
    $("#close-modal").addEventListener("click", () => $("#yaml-modal").classList.remove("open"));
    $("#yaml-modal").addEventListener("click", event => {
      if (event.target.id === "yaml-modal") event.currentTarget.classList.remove("open");
    });
    $("#apply-preview").addEventListener("click", () => {
      try {
        applyYaml($("#yaml-preview").value);
        $("#yaml-modal").classList.remove("open");
      } catch (error) {
        toast(`YAML import failed: ${error.message}`);
      }
    });
    $("#export-yaml").addEventListener("click", () => {
      const yaml = exportYaml();
      saveBlob("design.yaml", new Blob([yaml], {type: "text/yaml"}));
      toast("Downloaded design.yaml with measured sketch bounds.");
    });
    $("#save-concept").addEventListener("click", saveConcept);
    $("#edit-openvsp").addEventListener("click", openVspEditor);
    $("#toggle-wireframe").addEventListener("change", event => {
      window.OpenAirViewport3D.setWireframe(event.target.checked);
    });
    $("#download-brief").addEventListener("click", () => {
      const brief = briefWithWorksheet();
      $("#brief-editor").value = brief;
      saveBlob("brief.md", new Blob([brief], {type: "text/markdown"}));
      toast("Downloaded brief.md with the current measurement worksheet.");
    });
    $("#download-preview").addEventListener("click", () =>
      saveBlob("design.yaml", new Blob([$("#yaml-preview").value], {type: "text/yaml"}))
    );
    $("#import-yaml").addEventListener("click", () => $("#yaml-file").click());
    $("#yaml-file").addEventListener("change", async event => {
      try {
        applyYaml(await event.target.files[0].text());
      } catch (error) {
        toast(`YAML import failed: ${error.message}`);
      }
      event.target.value = "";
    });
    $("#load-sketch").addEventListener("click", () => $("#sketch-file").click());
    $("#sketch-file").addEventListener("change", event => {
      loadSketchFile(event.target.files[0], $("#trace-view").value);
      event.target.value = "";
    });
    $("#rectify-sketch").addEventListener("click", () => {
      const state = overlayState($("#trace-view").value);
      if (!state.image) {
        toast("Load a photo into the selected view first.");
        return;
      }
      calibrationMode = true;
      state.rectified = null;
      state.points = [];
      drawOverlay(state);
      $("#trace-status").textContent = "Pick grid corners clockwise: top-left, top-right, bottom-right, bottom-left.";
    });
    $("#reset-sketch").addEventListener("click", () => {
      const view = $("#trace-view").value;
      const state = overlayState(view);
      state.image = null;
      state.source = null;
      state.points = [];
      state.rectified = null;
      state.fileName = null;
      calibrationMode = false;
      drawOverlay(state);
      $("#trace-status").textContent = `${view} underlay cleared.`;
    });
    $("#download-sketch").addEventListener("click", () => {
      const state = overlayState($("#trace-view").value);
      if (!state.image) {
        toast("No underlay is loaded.");
        return;
      }
      state.canvas.toBlob(blob => saveBlob(`sketch-${state.view}-rectified.png`, blob), "image/png");
    });
    $("#sketch-opacity").addEventListener("input", event => {
      $$(".viewport canvas").forEach(canvas => { canvas.style.opacity = event.target.value; });
    });
    $("#grid-squares").addEventListener("input", event => {
      const state = overlayState($("#trace-view").value);
      state.gridSquares = Math.max(number(event.target.value, 1), .1);
      $("#trace-status").textContent = `Scale: ${metresPerGridSquare().toFixed(4)} m per grid square.`;
      renderViews();
    });
    $("#trace-view").addEventListener("change", event => {
      const state = overlayState(event.target.value);
      $("#grid-squares").value = state.gridSquares;
      $("#trace-status").textContent = state.image
        ? `${event.target.value} underlay active.`
        : `Drop a ${event.target.value} sketch onto its view.`;
    });

    function setPathForHarness(source, path, value) {
      const keys = path.split(".");
      let cursor = source;
      keys.slice(0, -1).forEach(key => {
        cursor = cursor[key];
      });
      cursor[keys.at(-1)] = cloneValue(value);
    }

    function handleHarnessTarget(handle) {
      const [x, y] = handle.position;
      if (handle.id === "station-width" && (handle.index === 0 || handle.index === design.fuselage.stations.length - 1)) {
        return [x, y + .004];
      }
      if (handle.id === "station-upper" || handle.id === "station-center") return [x, y + .004];
      if (["wing-dihedral", "fuselage-height", "wing-z-root"].includes(handle.id)) return [x, y + .004];
      if (handle.id === "fuselage-width") return [x + .004, y];
      if (handle.id === "fin-cant") {
        const fin = design.vtail;
        const attachment = window.OpenAirHandles.finAttachment(design);
        const base = [attachment.y, attachment.z];
        const radius = Math.hypot(x - base[0], y - base[1]);
        const angle = radians(number(fin.cant_deg) + .5);
        return [base[0] + radius * Math.sin(angle), base[1] + radius * Math.cos(angle)];
      }
      if (handle.id === "fin-root") {
        const targetDesign = clone(design);
        targetDesign.vtail.x_le_m = x + .004;
        return window.OpenAirHandles.instances("side", targetDesign)
          .find(item => item.id === "fin-root").position;
      }
      if (["wing-tip-le", "fin-tip", "htail-tip-le"].includes(handle.id)) return [x + .004, y + .004];
      if (handle.id.startsWith("station-")) return [x + .004, y + .004];
      return [x + .004, y];
    }

    function runHandleHarness() {
      const harnessDesign = clone(design);
      if (!Array.isArray(harnessDesign.fuselage.stations)) {
        harnessDesign.fuselage.stations = stationSeed(harnessDesign.fuselage);
      }
      harnessDesign.htail.span_m = Math.max(number(harnessDesign.htail.span_m), .4);
      const failures = [];
      ["top", "side", "front"].forEach(view => {
        window.OpenAirHandles.instances(view, harnessDesign).forEach(handle => {
          const zeroPatches = window.OpenAirHandles.drag(
            handle.id,
            harnessDesign,
            handle.position,
            handle.index,
          );
          const zeroChanged = zeroPatches.some(
            patch => !valuesEqual(getPath(patch.path, harnessDesign), patch.value),
          );
          if (zeroChanged) failures.push(`${handle.id}: zero displacement changed a value`);

          const testDesign = clone(harnessDesign);
          const target = (() => {
            const previousDesign = design;
            design = harnessDesign;
            try {
              return handleHarnessTarget(handle);
            } finally {
              design = previousDesign;
            }
          })();
          window.OpenAirHandles.drag(handle.id, testDesign, target, handle.index)
            .forEach(patch => setPathForHarness(testDesign, patch.path, patch.value));
          const moved = window.OpenAirHandles.instances(view, testDesign).find(
            item => item.id === handle.id && item.index === handle.index,
          );
          if (!moved || Math.hypot(moved.position[0] - target[0], moved.position[1] - target[1]) > 2e-4) {
            failures.push(`${handle.id}: drag target did not round-trip`);
          }
        });
      });
      const measuredFin = clone(harnessDesign);
      measuredFin.vtail.count = 2;
      measuredFin.vtail.root_attachment = "measured";
      measuredFin.vtail.y_root_m = .123;
      measuredFin.vtail.z_root_m = .234;
      const attachment = window.OpenAirHandles.finAttachment(measuredFin);
      if (Math.abs(attachment.y - .123) > 1e-9 || Math.abs(attachment.z - .234) > 1e-9) {
        failures.push("measured fin attachment did not preserve declared y/z");
      }
      return {
        ok: failures.length === 0,
        definitions: window.OpenAirHandles.definitions().length,
        failures,
      };
    }

    function runHistoryHarness() {
      const path = "wing.span_m";
      const before = number(getPath(path));
      applyPatches(
        [{path, value: before + .001}],
        {source: "smoke:history"},
      );
      const changed = Math.abs(number(getPath(path)) - (before + .001)) < 1e-7;
      undo();
      const undone = Math.abs(number(getPath(path)) - before) < 1e-7;
      redo();
      const redone = Math.abs(number(getPath(path)) - (before + .001)) < 1e-7;
      undo();
      const restored = Math.abs(number(getPath(path)) - before) < 1e-7;
      undoStack.length = 0;
      redoStack.length = 0;
      refreshHistoryButtons();
      return changed && undone && redone && restored;
    }

    function runPatchHarness() {
      const path = "wing.span_m";
      const before = number(getPath(path));
      const node = schemaAtPath(path);
      const lower = Number(node.minimum ?? node.exclusiveMinimum ?? 0);
      applyPatches(
        [{path, value: lower - 10}],
        {source: "smoke:clamp", record: false, render: false},
      );
      const clamped = node.exclusiveMinimum != null
        ? number(getPath(path)) > Number(node.exclusiveMinimum)
        : number(getPath(path)) >= lower;
      let rejected = false;
      try {
        applyPatches(
          [{path, value: Number.POSITIVE_INFINITY}],
          {source: "smoke:invalid", record: false, render: false},
        );
      } catch (error) {
        rejected = error.message.includes("finite number");
      }
      applyPatches(
        [{path, value: before}],
        {source: "smoke:restore", record: false, render: false},
      );
      return clamped && rejected && number(getPath(path)) === before;
    }

    function runDragControlHarness() {
      const previousDrag = drag;
      const frozen = makeFrame(0, 3, -2, 2);
      drag = {view: "top", frame: frozen};
      const stable = stableViewFrame(
        "top",
        makeFrame(-5, 8, -7, 7),
      ) === frozen;
      drag = previousDrag;
      const tipHandles = window.OpenAirHandles.instances("top", design)
        .filter(handle => ["wing-tip-le", "wing-tip-te"].includes(handle.id));
      return stable
        && tipHandles.length === 2
        && tipHandles.every(handle => handle.dragGain > 0 && handle.dragGain < 1);
    }

    window.designStudio = {
      exportYaml,
      exportObject,
      importYaml: applyYaml,
      parseYaml,
      getDesign: () => clone(design),
      applyPatches,
      undo,
      redo,
      history: () => ({undo: undoStack.length, redo: redoStack.length}),
      briefWithWorksheet,
      sketchesForSave,
      openVspEditor,
      pollVspStatus,
      applyVspGeometry,
      previewMesh: () => window.OpenAirPreviewMesh.build(design),
      runHandleHarness,
      fieldPaths: CONFIG.fieldPaths,
      homographyDestinationToSource,
    };

    const browserRoundTrip = parseYaml(exportYaml());
    const expectedStationCount = Array.isArray(design.fuselage.stations) ? design.fuselage.stations.length : 0;
    const parsedStationCount = Array.isArray(browserRoundTrip.fuselage.stations) ? browserRoundTrip.fuselage.stations.length : 0;
    if (
      browserRoundTrip.name !== design.name
      || browserRoundTrip.wing.airfoil !== design.wing.airfoil
      || parsedStationCount !== expectedStationCount
    ) {
      throw new Error("Internal YAML round-trip failed.");
    }
    const blockListSmoke = parseYaml("items:\n  - x: 0\n    y: 1\n  - x: 2\n    y: 3\n");
    if (blockListSmoke.items[1].y !== 3) throw new Error("Block-list YAML import failed.");
    const identityHomography = homographyDestinationToSource(
      [
        {sourceX: 0, sourceY: 0},
        {sourceX: SVG_W - 1, sourceY: 0},
        {sourceX: SVG_W - 1, sourceY: SVG_H - 1},
        {sourceX: 0, sourceY: SVG_H - 1},
      ],
      SVG_W,
      SVG_H,
    );
    if (Math.abs(identityHomography[0] - 1) > 1e-9 || Math.abs(identityHomography[4] - 1) > 1e-9) {
      throw new Error("Internal homography solve failed.");
    }
    document.body.dataset.yamlRoundtrip = "true";
    document.body.dataset.homographyReady = "true";
    $("#brief-editor").value = ORIGINAL_BRIEF;
    const servedMode = ["new", "edit"].includes(CONFIG.mode)
      && window.location.protocol.startsWith("http")
      && Boolean(CONFIG.saveToken);
    if (servedMode) {
      const saveButton = $("#save-concept");
      saveButton.hidden = false;
      $("#save-label").textContent = CONFIG.mode === "new" ? "Create concept" : "Save concept";
      $("#edit-openvsp").hidden = false;
    }
    const worksheetSmoke = briefWithWorksheet();
    if (!worksheetSmoke.includes("## Sketch measurement worksheet")) {
      throw new Error("Internal sketch worksheet generation failed.");
    }
    $("#smoke-brief").textContent = worksheetSmoke;
    document.body.dataset.worksheetReady = "true";
    $("#concept-label").textContent = `${CONFIG.concept} · ${CONFIG.sourceName} · ${CONFIG.fieldPaths.length} schema fields`;
    const handleSmoke = runHandleHarness();
    const previewSmoke = window.OpenAirPreviewMesh.propertyHarness(design, 50);
    $("#smoke-handles").textContent = JSON.stringify({handles: handleSmoke, preview: previewSmoke});
    document.body.dataset.handlesReady = String(handleSmoke.ok);
    document.body.dataset.previewProperties = String(previewSmoke.ok);
    window.OpenAirViewport3D.init();
    refreshHistoryButtons();
    renderForm();
    updateAll();
    document.body.dataset.historyReady = String(runHistoryHarness());
    document.body.dataset.patchesReady = String(runPatchHarness());
    document.body.dataset.dragControlReady = String(runDragControlHarness());
    document.body.dataset.formValid = String($("#schema-form").checkValidity());
  })();

