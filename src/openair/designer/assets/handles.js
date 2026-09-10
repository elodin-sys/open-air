(() => {
  "use strict";

  const definitions = new Map();
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const round = (value, digits = 6) => Number(Number(value).toFixed(digits));
  const clamp = (value, lo, hi) => Math.min(Math.max(value, lo), hi);
  const radians = value => number(value) * Math.PI / 180;
  const degrees = value => value * 180 / Math.PI;

  function bodyProfile(design) {
    const fuselage = design.fuselage;
    const length = Math.max(number(fuselage.length_m), .01);
    if (Array.isArray(fuselage.stations) && fuselage.stations.length >= 2) {
      return fuselage.stations.map((station, index) => ({
        index,
        x: number(station.x_over_length) * length,
        width: Math.max(number(station.width_m), 0),
        height: Math.max(number(station.height_m), 0),
        z: number(station.z_offset_m),
        sidePower: number(station.side_power, 2),
        topPower: number(station.top_power, 2),
        bottomPower: number(station.bottom_power, 2),
      }));
    }
    const fractions = [0, .25, .5, .75, 1];
    const scales = [.05, .45, 1, .9, .35];
    return fractions.map((fraction, index) => ({
      index,
      x: fraction * length,
      width: number(fuselage.max_width_m) * scales[index],
      height: number(fuselage.max_height_m) * scales[index],
      z: 0,
      sidePower: 2,
      topPower: 2,
      bottomPower: 2,
    }));
  }

  function interpolateBody(design, x) {
    const profile = bodyProfile(design);
    const xValue = clamp(number(x), profile[0].x, profile.at(-1).x);
    for (let index = 0; index < profile.length - 1; index += 1) {
      const left = profile[index];
      const right = profile[index + 1];
      if (xValue >= left.x && xValue <= right.x) {
        const fraction = (xValue - left.x) / Math.max(right.x - left.x, 1e-9);
        const width = left.width + fraction * (right.width - left.width);
        const height = left.height + fraction * (right.height - left.height);
        const z = left.z + fraction * (right.z - left.z);
        return {width, height, z, top: z + .5 * height, bottom: z - .5 * height};
      }
    }
    const last = profile.at(-1);
    return {
      width: last.width,
      height: last.height,
      z: last.z,
      top: last.z + .5 * last.height,
      bottom: last.z - .5 * last.height,
    };
  }

  function finAttachment(design) {
    const fin = design.vtail;
    const count = Math.round(number(fin.count, 2));
    if (fin.root_attachment === "measured") {
      return {
        y: count === 1 ? 0 : Math.abs(number(fin.y_root_m)),
        z: number(fin.z_root_m),
      };
    }
    const x = number(fin.x_le_m);
    const root = Math.max(number(fin.root_chord_m), .01);
    const sections = [
      interpolateBody(design, x),
      interpolateBody(design, x + .5 * root),
      interpolateBody(design, x + root),
    ];
    return {
      y: count === 1
        ? 0
        : .3 * Math.min(...sections.map(section => section.width)),
      z: Math.min(...sections.map(section => section.z + .3 * section.height)),
    };
  }

  function wingGeometry(design) {
    const wing = design.wing;
    const span = Math.max(number(wing.span_m), .01);
    const root = Math.max(number(wing.root_chord_m), .01);
    const taper = Math.max(number(wing.taper), .001);
    const halfSpan = .5 * span;
    const xRoot = number(wing.x_le_root_m);
    return {
      span,
      root,
      taper,
      tip: root * taper,
      halfSpan,
      xRoot,
      xTip: xRoot + halfSpan * Math.tan(radians(wing.le_sweep_deg)),
    };
  }

  function htailGeometry(design) {
    const tail = design.htail;
    const span = Math.max(number(tail.span_m), 0);
    const root = Math.max(number(tail.root_chord_m), .01);
    const halfSpan = .5 * span;
    const xRoot = number(tail.x_le_m);
    return {
      span,
      root,
      tip: root * Math.max(number(tail.taper), .001),
      halfSpan,
      xRoot,
      xTip: xRoot + halfSpan * Math.tan(radians(tail.le_sweep_deg)),
    };
  }

  function registerHandle(definition) {
    if (!definition || !definition.id || !definition.view) {
      throw new Error("A semantic handle requires id and view");
    }
    if (definitions.has(definition.id)) {
      throw new Error(`Duplicate semantic handle: ${definition.id}`);
    }
    definitions.set(definition.id, Object.freeze({...definition}));
  }

  function singleton() {
    return [null];
  }

  function scalarWingInstances(design) {
    return Array.isArray(design.wing.sections) && design.wing.sections.length >= 3
      ? []
      : [null];
  }

  function stationInstances(design) {
    return Array.isArray(design.fuselage.stations)
      ? design.fuselage.stations.map((_, index) => index)
      : [];
  }

  function htailInstances(design) {
    return number(design.htail.span_m) > .05 ? [null] : [];
  }

  registerHandle({
    id: "wing-root-le",
    view: "top",
    instances: scalarWingInstances,
    position: design => [wingGeometry(design).xRoot, 0],
    drag: (design, [x]) => [
      {path: "wing.x_le_root_m", value: round(clamp(x, 0, number(design.fuselage.length_m)))},
    ],
  });
  registerHandle({
    id: "wing-root-te",
    view: "top",
    instances: scalarWingInstances,
    position: design => {
      const wing = wingGeometry(design);
      return [wing.xRoot + wing.root, 0];
    },
    drag: (design, [x]) => [
      {path: "wing.root_chord_m", value: round(Math.max(x - number(design.wing.x_le_root_m), .05))},
    ],
  });
  registerHandle({
    id: "wing-tip-le",
    view: "top",
    dragGain: .45,
    instances: scalarWingInstances,
    position: design => {
      const wing = wingGeometry(design);
      return [wing.xTip, wing.halfSpan];
    },
    drag: (design, [x, y]) => {
      const halfSpan = Math.max(Math.abs(y), .1);
      return [
        {path: "wing.span_m", value: round(2 * halfSpan)},
        {
          path: "wing.le_sweep_deg",
          value: round(degrees(Math.atan2(x - number(design.wing.x_le_root_m), halfSpan))),
        },
      ];
    },
  });
  registerHandle({
    id: "wing-tip-te",
    view: "top",
    dragGain: .45,
    instances: scalarWingInstances,
    position: design => {
      const wing = wingGeometry(design);
      return [wing.xTip + wing.tip, wing.halfSpan];
    },
    drag: (design, [x]) => {
      const wing = wingGeometry(design);
      return [{
        path: "wing.taper",
        value: round(clamp(
          Math.max(x - wing.xTip, .02) / Math.max(number(design.wing.root_chord_m), .01),
          .03,
          1,
        )),
      }];
    },
  });
  registerHandle({
    id: "payload-x",
    view: "top",
    instances: singleton,
    position: design => [number(design.fuselage.payload_bay_x_m), 0],
    drag: (design, [x]) => [{
      path: "fuselage.payload_bay_x_m",
      value: round(clamp(
        x,
        0,
        number(design.fuselage.length_m) - number(design.fuselage.payload_bay_length_m),
      )),
    }],
  });
  registerHandle({
    id: "fuel-x",
    view: "top",
    instances: singleton,
    position: design => [number(design.fuselage.fuel_tank_x_m), 0],
    drag: (design, [x]) => [{
      path: "fuselage.fuel_tank_x_m",
      value: round(clamp(x, 0, number(design.fuselage.length_m))),
    }],
  });
  registerHandle({
    id: "station-width",
    view: "top",
    className: "station",
    instances: stationInstances,
    position: (design, index) => {
      const station = design.fuselage.stations[index];
      return [
        number(station.x_over_length) * number(design.fuselage.length_m),
        .5 * number(station.width_m),
      ];
    },
    drag: (design, [x, y], index) => {
      const stations = design.fuselage.stations;
      const station = stations[index];
      const patches = [{
        path: `fuselage.stations.${index}.width_m`,
        value: round(Math.max(0, 2 * Math.abs(y))),
      }];
      if (index > 0 && index < stations.length - 1) {
        patches.push({
          path: `fuselage.stations.${index}.x_over_length`,
          value: round(clamp(
            x / Math.max(number(design.fuselage.length_m), .01),
            number(stations[index - 1].x_over_length) + .005,
            number(stations[index + 1].x_over_length) - .005,
          )),
        });
      }
      return patches;
    },
  });
  registerHandle({
    id: "station-upper",
    view: "side",
    className: "station",
    instances: stationInstances,
    position: (design, index) => {
      const station = design.fuselage.stations[index];
      return [
        number(station.x_over_length) * number(design.fuselage.length_m),
        number(station.z_offset_m) + .5 * number(station.height_m),
      ];
    },
    drag: (design, [x, y], index) => {
      const stations = design.fuselage.stations;
      const station = stations[index];
      const oldBottom = number(station.z_offset_m) - .5 * number(station.height_m);
      const top = Math.max(y, oldBottom);
      const patches = [
        {path: `fuselage.stations.${index}.height_m`, value: round(top - oldBottom)},
        {path: `fuselage.stations.${index}.z_offset_m`, value: round(.5 * (top + oldBottom))},
      ];
      if (index > 0 && index < stations.length - 1) {
        patches.push({
          path: `fuselage.stations.${index}.x_over_length`,
          value: round(clamp(
            x / Math.max(number(design.fuselage.length_m), .01),
            number(stations[index - 1].x_over_length) + .005,
            number(stations[index + 1].x_over_length) - .005,
          )),
        });
      }
      return patches;
    },
  });
  registerHandle({
    id: "station-center",
    view: "side",
    className: "station",
    instances: stationInstances,
    position: (design, index) => {
      const station = design.fuselage.stations[index];
      return [
        number(station.x_over_length) * number(design.fuselage.length_m),
        number(station.z_offset_m),
      ];
    },
    drag: (design, [x, y], index) => {
      const stations = design.fuselage.stations;
      const patches = [
        {path: `fuselage.stations.${index}.z_offset_m`, value: round(y)},
      ];
      if (index > 0 && index < stations.length - 1) {
        patches.push({
          path: `fuselage.stations.${index}.x_over_length`,
          value: round(clamp(
            x / Math.max(number(design.fuselage.length_m), .01),
            number(stations[index - 1].x_over_length) + .005,
            number(stations[index + 1].x_over_length) - .005,
          )),
        });
      }
      return patches;
    },
  });
  registerHandle({
    id: "fin-root",
    view: "side",
    className: "fin",
    instances: singleton,
    position: design => {
      const x = number(design.vtail.x_le_m);
      return [x, finAttachment(design).z];
    },
    drag: (design, [x]) => [
      {path: "vtail.x_le_m", value: round(clamp(x, 0, number(design.fuselage.length_m)))},
    ],
  });
  registerHandle({
    id: "fin-tip",
    view: "side",
    className: "fin",
    instances: singleton,
    position: design => {
      const fin = design.vtail;
      const x = number(fin.x_le_m);
      const rootZ = finAttachment(design).z;
      return [
        x + number(fin.span_m) * Math.tan(radians(fin.le_sweep_deg)),
        rootZ + number(fin.span_m) * Math.cos(radians(fin.cant_deg)),
      ];
    },
    drag: (design, [x, y]) => {
      const fin = design.vtail;
      const rootX = number(fin.x_le_m);
      const rootZ = finAttachment(design).z;
      const cosine = Math.max(Math.cos(radians(fin.cant_deg)), .05);
      const span = Math.max((y - rootZ) / cosine, .02);
      return [
        {path: "vtail.span_m", value: round(span)},
        {path: "vtail.le_sweep_deg", value: round(degrees(Math.atan2(x - rootX, span)))},
      ];
    },
  });
  registerHandle({
    id: "wing-dihedral",
    view: "front",
    instances: scalarWingInstances,
    position: design => {
      const wing = wingGeometry(design);
      return [
        wing.halfSpan,
        number(design.wing.z_root_m) + wing.halfSpan * Math.tan(radians(design.wing.dihedral_deg)),
      ];
    },
    drag: (design, [, z]) => {
      const wing = wingGeometry(design);
      return [{
        path: "wing.dihedral_deg",
        value: round(degrees(Math.atan2(z - number(design.wing.z_root_m), wing.halfSpan))),
      }];
    },
  });
  registerHandle({
    id: "fin-cant",
    view: "front",
    className: "fin",
    instances: singleton,
    position: design => {
      const fin = design.vtail;
      const attachment = finAttachment(design);
      const baseY = attachment.y;
      const baseZ = attachment.z;
      return [
        baseY + number(fin.span_m) * Math.sin(radians(fin.cant_deg)),
        baseZ + number(fin.span_m) * Math.cos(radians(fin.cant_deg)),
      ];
    },
    drag: (design, [y, z]) => {
      const attachment = finAttachment(design);
      const baseY = attachment.y;
      const baseZ = attachment.z;
      return [{
        path: "vtail.cant_deg",
        value: round(degrees(Math.atan2(Math.max(y - baseY, 0), Math.max(z - baseZ, .01)))),
      }];
    },
  });
  registerHandle({
    id: "fuselage-width",
    view: "front",
    className: "station",
    instances: singleton,
    position: design => {
      const profile = bodyProfile(design);
      const largest = profile.reduce(
        (best, section) => section.width * section.height > best.width * best.height ? section : best,
        profile[0],
      );
      return [.5 * number(design.fuselage.max_width_m), largest.z];
    },
    drag: (design, [y]) => {
      const width = round(Math.max(2 * Math.abs(y), .01));
      const patches = [{path: "fuselage.max_width_m", value: width}];
      if (Array.isArray(design.fuselage.stations)) {
        const profile = bodyProfile(design);
        const widest = profile.reduce(
          (best, section) => section.width > best.width ? section : best,
          profile[0],
        );
        patches.push({path: `fuselage.stations.${widest.index}.width_m`, value: width});
      }
      return patches;
    },
  });
  registerHandle({
    id: "fuselage-height",
    view: "front",
    className: "station",
    instances: singleton,
    position: design => {
      const profile = bodyProfile(design);
      const largest = profile.reduce(
        (best, section) => section.width * section.height > best.width * best.height ? section : best,
        profile[0],
      );
      return [0, largest.z + .5 * number(design.fuselage.max_height_m)];
    },
    drag: (design, [, z]) => {
      const profile = bodyProfile(design);
      const largest = profile.reduce(
        (best, section) => section.width * section.height > best.width * best.height ? section : best,
        profile[0],
      );
      const height = round(Math.max(2 * (z - largest.z), .01));
      const patches = [{path: "fuselage.max_height_m", value: height}];
      if (Array.isArray(design.fuselage.stations)) {
        const tallest = profile.reduce(
          (best, section) => section.height > best.height ? section : best,
          profile[0],
        );
        patches.push({path: `fuselage.stations.${tallest.index}.height_m`, value: height});
      }
      return patches;
    },
  });
  registerHandle({
    id: "wing-z-root",
    view: "side",
    instances: scalarWingInstances,
    position: design => [number(design.wing.x_le_root_m), number(design.wing.z_root_m)],
    drag: (_design, [, z]) => [{path: "wing.z_root_m", value: round(z)}],
  });

  [
    ["htail-root-le", htailInstances, design => [htailGeometry(design).xRoot, 0], (design, [x]) => [
      {path: "htail.x_le_m", value: round(clamp(x, 0, number(design.fuselage.length_m)))},
    ]],
    ["htail-root-te", htailInstances, design => {
      const tail = htailGeometry(design);
      return [tail.xRoot + tail.root, 0];
    }, (design, [x]) => [
      {path: "htail.root_chord_m", value: round(Math.max(x - number(design.htail.x_le_m), .03))},
    ]],
    ["htail-tip-le", htailInstances, design => {
      const tail = htailGeometry(design);
      return [tail.xTip, tail.halfSpan];
    }, (design, [x, y]) => {
      const halfSpan = Math.max(Math.abs(y), .03);
      return [
        {path: "htail.span_m", value: round(2 * halfSpan)},
        {
          path: "htail.le_sweep_deg",
          value: round(degrees(Math.atan2(x - number(design.htail.x_le_m), halfSpan))),
        },
      ];
    }],
    ["htail-tip-te", htailInstances, design => {
      const tail = htailGeometry(design);
      return [tail.xTip + tail.tip, tail.halfSpan];
    }, (design, [x]) => {
      const tail = htailGeometry(design);
      return [{
        path: "htail.taper",
        value: round(clamp(
          Math.max(x - tail.xTip, .01) / Math.max(number(design.htail.root_chord_m), .01),
          .03,
          1,
        )),
      }];
    }],
  ].forEach(([id, instances, position, drag]) => registerHandle({
    id,
    view: "top",
    className: "tail",
    instances,
    position,
    drag,
  }));

  function instances(view, design) {
    const result = [];
    definitions.forEach(definition => {
      if (definition.view !== view) return;
      (definition.instances || singleton)(design).forEach(index => {
        const position = definition.position(design, index);
        if (position.every(Number.isFinite)) {
          result.push({
            id: definition.id,
            view,
            index,
            className: definition.className || "",
            dragGain: definition.dragGain ?? 1,
            position,
          });
        }
      });
    });
    return result;
  }

  function drag(id, design, target, index = null) {
    const definition = definitions.get(id);
    if (!definition) throw new Error(`Unknown semantic handle: ${id}`);
    return definition.drag(design, target, index).filter(
      patch => patch && typeof patch.path === "string" && patch.path && Number.isFinite(Number(patch.value)),
    );
  }

  window.OpenAirHandles = Object.freeze({
    registerHandle,
    definitions: () => Array.from(definitions.values()),
    instances,
    drag,
    bodyProfile,
    finAttachment,
    wingGeometry,
  });
})();
