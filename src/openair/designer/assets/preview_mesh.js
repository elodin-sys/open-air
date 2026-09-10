(() => {
  "use strict";

  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const radians = value => number(value) * Math.PI / 180;
  const clone = value => JSON.parse(JSON.stringify(value));

  function bodyProfile(design) {
    if (window.OpenAirHandles && window.OpenAirHandles.bodyProfile) {
      return window.OpenAirHandles.bodyProfile(design);
    }
    const fuselage = design.fuselage;
    const length = Math.max(number(fuselage.length_m), .01);
    const fractions = [0, .25, .5, .75, 1];
    const scales = [.05, .45, 1, .9, .35];
    return fractions.map((fraction, index) => ({
      x: fraction * length,
      width: number(fuselage.max_width_m) * scales[index],
      height: number(fuselage.max_height_m) * scales[index],
      z: 0,
      sidePower: 2,
      topPower: 2,
      bottomPower: 2,
      maxWidthLoc: 0,
    }));
  }

  function profileFromStations(stations, length) {
    return stations.map(station => ({
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

  function fairingProfiles(design) {
    const length = Math.max(number(design.fuselage.length_m), .01);
    return (Array.isArray(design.fuselage.fairings) ? design.fuselage.fairings : [])
      .filter(fairing => Array.isArray(fairing.stations) && fairing.stations.length >= 2)
      .map(fairing => ({
        name: fairing.name,
        profile: profileFromStations(fairing.stations, length),
      }));
  }

  function sectionPolygon(section, samples = 256) {
    const width = Math.max(number(section.width), 0);
    const height = Math.max(number(section.height), 0);
    const zCenter = number(section.z);
    const sidePower = Math.max(number(section.sidePower, 2), .01);
    const topPower = Math.max(number(section.topPower, 2), .01);
    const bottomPower = Math.max(number(section.bottomPower, 2), .01);
    const maxWidthLoc = Math.min(Math.max(number(section.maxWidthLoc, 0), -1), 1);
    const maxWidthZ = zCenter + .5 * height * maxWidthLoc;
    const topHeight = .5 * height * (1 - maxWidthLoc);
    const bottomHeight = .5 * height * (1 + maxWidthLoc);
    const signedPower = (value, power) => (
      Math.abs(value) < 1e-12 ? 0 : Math.sign(value) * Math.abs(value) ** (2 / power)
    );
    return Array.from({length: samples}, (_, index) => {
      const angle = 2 * Math.PI * index / samples;
      const cosine = Math.cos(angle);
      const sine = Math.sin(angle);
      const verticalPower = sine >= 0 ? topPower : bottomPower;
      const verticalHeight = sine >= 0 ? topHeight : bottomHeight;
      const y = .5 * width * signedPower(cosine, sidePower);
      const z = maxWidthZ + verticalHeight * signedPower(sine, verticalPower);
      return [y, z];
    });
  }

  function sectionMetrics(section, samples = 256) {
    const width = Math.max(number(section.width), 0);
    const height = Math.max(number(section.height), 0);
    if (!width || !height) return {area: 0, perimeter: 0, areaFactor: 0};
    const sidePower = number(section.sidePower, 2);
    const topPower = number(section.topPower, 2);
    const bottomPower = number(section.bottomPower, 2);
    const maxWidthLoc = number(section.maxWidthLoc, 0);
    if (sidePower === 2 && topPower === 2 && bottomPower === 2 && maxWidthLoc === 0) {
      const semiA = .5 * width;
      const semiB = .5 * height;
      const h = ((semiA - semiB) / (semiA + semiB)) ** 2;
      const area = Math.PI * width * height / 4;
      const perimeter = Math.PI * (semiA + semiB)
        * (1 + 3 * h / (10 + Math.sqrt(4 - 3 * h)));
      return {area, perimeter, areaFactor: area / (width * height)};
    }
    const points = sectionPolygon(section, samples);
    let doubleArea = 0;
    let perimeter = 0;
    points.forEach((point, index) => {
      const next = points[(index + 1) % points.length];
      doubleArea += point[0] * next[1] - next[0] * point[1];
      perimeter += Math.hypot(next[0] - point[0], next[1] - point[1]);
    });
    const area = .5 * Math.abs(doubleArea);
    return {area, perimeter, areaFactor: area / (width * height)};
  }

  function nacaThickness(x, thickness) {
    const value = Math.min(Math.max(x, 0), 1);
    return 5 * thickness * (
      .2969 * Math.sqrt(value)
      - .1260 * value
      - .3516 * value ** 2
      + .2843 * value ** 3
      - .1015 * value ** 4
    );
  }

  function nacaCamber(x, code) {
    if (!/^\d{4}$/.test(String(code || ""))) return 0;
    const m = Number(String(code)[0]) / 100;
    const p = Number(String(code)[1]) / 10;
    if (!m || !p) return 0;
    if (x < p) return m / p ** 2 * (2 * p * x - x ** 2);
    return m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x ** 2);
  }

  function createCollector() {
    const positions = [];
    const normals = [];

    function triangle(a, b, c) {
      const ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
      const ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
      const cross = [
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
      ];
      const length = Math.hypot(...cross) || 1;
      const normal = cross.map(value => value / length);
      positions.push(...a, ...b, ...c);
      normals.push(...normal, ...normal, ...normal);
    }

    function quad(a, b, c, d) {
      triangle(a, b, c);
      triangle(a, c, d);
    }

    return {positions, normals, triangle, quad};
  }

  function loftStationBody(profile, collector) {
    const segments = 48;
    const rings = profile.map(section => sectionPolygon(section, segments).map(
      point => [section.x, point[0], point[1]],
    ));
    for (let ring = 0; ring < rings.length - 1; ring += 1) {
      for (let index = 0; index < segments; index += 1) {
        const next = (index + 1) % segments;
        collector.quad(
          rings[ring][index],
          rings[ring + 1][index],
          rings[ring + 1][next],
          rings[ring][next],
        );
      }
    }
    const first = profile[0];
    const last = profile.at(-1);
    const noseCenter = [first.x, 0, first.z];
    const tailCenter = [last.x, 0, last.z];
    for (let index = 0; index < segments; index += 1) {
      const next = (index + 1) % segments;
      collector.triangle(noseCenter, rings[0][next], rings[0][index]);
      collector.triangle(tailCenter, rings.at(-1)[index], rings.at(-1)[next]);
    }
  }

  function loftFuselage(design, collector) {
    loftStationBody(bodyProfile(design), collector);
    fairingProfiles(design).forEach(fairing => {
      loftStationBody(fairing.profile, collector);
    });
  }

  function sectionPoint(section, xFraction, surface) {
    const thickness = nacaThickness(xFraction, section.tOverC) * section.chord;
    const camber = nacaCamber(xFraction, section.airfoil) * section.chord;
    const localZ = camber + surface * thickness;
    const dx = (xFraction - .25) * section.chord;
    const twist = radians(section.twist);
    return [
      section.xLe + .25 * section.chord + dx * Math.cos(twist) + localZ * Math.sin(twist),
      section.y,
      section.z - dx * Math.sin(twist) + localZ * Math.cos(twist),
    ];
  }

  function loftSurface(collector, root, tip, {capRoot = true, capTip = true} = {}) {
    const chordSegments = 16;
    const upperRoot = [];
    const upperTip = [];
    const lowerRoot = [];
    const lowerTip = [];
    for (let index = 0; index <= chordSegments; index += 1) {
      const xFraction = index / chordSegments;
      upperRoot.push(sectionPoint(root, xFraction, 1));
      upperTip.push(sectionPoint(tip, xFraction, 1));
      lowerRoot.push(sectionPoint(root, xFraction, -1));
      lowerTip.push(sectionPoint(tip, xFraction, -1));
    }
    for (let index = 0; index < chordSegments; index += 1) {
      const next = index + 1;
      collector.quad(upperRoot[index], upperTip[index], upperTip[next], upperRoot[next]);
      collector.quad(lowerRoot[next], lowerTip[next], lowerTip[index], lowerRoot[index]);
    }
    collector.quad(upperRoot[0], lowerRoot[0], lowerTip[0], upperTip[0]);
    collector.quad(upperTip.at(-1), lowerTip.at(-1), lowerRoot.at(-1), upperRoot.at(-1));
    if (capRoot) {
      collector.quad(upperRoot.at(-1), lowerRoot.at(-1), lowerRoot[0], upperRoot[0]);
    }
    if (capTip) {
      collector.quad(upperTip[0], lowerTip[0], lowerTip.at(-1), upperTip.at(-1));
    }
  }

  function loftWing(design, collector) {
    const wing = design.wing;
    const halfSpan = .5 * Math.max(number(wing.span_m), .01);
    if (Array.isArray(wing.sections) && wing.sections.length >= 3) {
      [-1, 1].forEach(side => {
        const sections = wing.sections.map(section => {
          const eta = Math.min(Math.max(number(section.eta), 0), 1);
          return {
            xLe: number(section.x_le_m),
            y: side * eta * halfSpan,
            z: number(section.z_le_m),
            chord: Math.max(number(section.chord_m), .001),
            twist: number(wing.twist_root_deg)
              + eta * (number(wing.twist_tip_deg) - number(wing.twist_root_deg)),
            tOverC: Math.max(number(section.t_over_c ?? wing.t_over_c), .001),
            airfoil: wing.airfoil,
          };
        });
        for (let index = 0; index < sections.length - 1; index += 1) {
          loftSurface(
            collector,
            sections[index],
            sections[index + 1],
            {capRoot: index === 0, capTip: index === sections.length - 2},
          );
        }
      });
      return;
    }
    const rootChord = Math.max(number(wing.root_chord_m), .01);
    const tipChord = rootChord * Math.max(number(wing.taper), .001);
    const rootX = number(wing.x_le_root_m);
    const tipX = rootX + halfSpan * Math.tan(radians(wing.le_sweep_deg));
    const rootZ = number(wing.z_root_m);
    const tipZ = rootZ + halfSpan * Math.tan(radians(wing.dihedral_deg));
    [-1, 1].forEach(side => loftSurface(
      collector,
      {
        xLe: rootX,
        y: 0,
        z: rootZ,
        chord: rootChord,
        twist: number(wing.twist_root_deg),
        tOverC: Math.max(number(wing.t_over_c), .001),
        airfoil: wing.airfoil,
      },
      {
        xLe: tipX,
        y: side * halfSpan,
        z: tipZ,
        chord: tipChord,
        twist: number(wing.twist_tip_deg),
        tOverC: Math.max(number(wing.t_over_c), .001),
        airfoil: wing.airfoil,
      },
    ));
  }

  function loftHorizontalTail(design, collector) {
    const tail = design.htail;
    if (number(tail.span_m) <= .05) return;
    const halfSpan = .5 * number(tail.span_m);
    const rootChord = Math.max(number(tail.root_chord_m), .01);
    const tipChord = rootChord * Math.max(number(tail.taper), .001);
    const rootX = number(tail.x_le_m);
    const tipX = rootX + halfSpan * Math.tan(radians(tail.le_sweep_deg));
    [-1, 1].forEach(side => loftSurface(
      collector,
      {
        xLe: rootX,
        y: 0,
        z: number(tail.z_m),
        chord: rootChord,
        twist: number(tail.incidence_deg),
        tOverC: Math.max(number(tail.t_over_c), .001),
        airfoil: "0012",
      },
      {
        xLe: tipX,
        y: side * halfSpan,
        z: number(tail.z_m),
        chord: tipChord,
        twist: number(tail.incidence_deg),
        tOverC: Math.max(number(tail.t_over_c), .001),
        airfoil: "0012",
      },
    ));
  }

  function interpolateProfile(profile, x) {
    const xValue = Math.min(Math.max(x, profile[0].x), profile.at(-1).x);
    for (let index = 0; index < profile.length - 1; index += 1) {
      const left = profile[index];
      const right = profile[index + 1];
      if (xValue < left.x || xValue > right.x) continue;
      const fraction = (xValue - left.x) / Math.max(right.x - left.x, 1e-9);
      return {
        width: left.width + fraction * (right.width - left.width),
        height: left.height + fraction * (right.height - left.height),
        z: left.z + fraction * (right.z - left.z),
        sidePower: left.sidePower + fraction * (right.sidePower - left.sidePower),
        topPower: left.topPower + fraction * (right.topPower - left.topPower),
        bottomPower: left.bottomPower + fraction * (right.bottomPower - left.bottomPower),
        maxWidthLoc: left.maxWidthLoc + fraction * (right.maxWidthLoc - left.maxWidthLoc),
      };
    }
    return profile.at(-1);
  }

  function sectionEccentricity(section, y, z) {
    if (section.width <= 0 || section.height <= 0) return Infinity;
    const maxWidthLoc = Math.min(Math.max(number(section.maxWidthLoc, 0), -1), 1);
    const maxWidthZ = section.z + .5 * section.height * maxWidthLoc;
    const relativeZ = z - maxWidthZ;
    const lateral = Math.abs(y / (.5 * section.width)) ** number(section.sidePower, 2);
    if (Math.abs(relativeZ) <= 1e-12) return lateral;
    const verticalHeight = relativeZ > 0
      ? .5 * section.height * (1 - maxWidthLoc)
      : .5 * section.height * (1 + maxWidthLoc);
    if (verticalHeight <= 1e-12) return Infinity;
    const verticalPower = relativeZ > 0
      ? number(section.topPower, 2)
      : number(section.bottomPower, 2);
    return lateral + Math.abs(relativeZ / verticalHeight) ** verticalPower;
  }

  function minBodyEccentricity(design, x, y, z) {
    const profiles = [
      {name: "fuselage", profile: bodyProfile(design)},
      ...fairingProfiles(design),
    ];
    let minimum = Infinity;
    let support = null;
    profiles.forEach(item => {
      if (
        item.name !== "fuselage"
        && (x < item.profile[0].x - 1e-12 || x > item.profile.at(-1).x + 1e-12)
      ) return;
      const eccentricity = sectionEccentricity(interpolateProfile(item.profile, x), y, z);
      if (eccentricity < minimum) {
        minimum = eccentricity;
        support = item.name;
      }
    });
    return {minimum, support};
  }

  function rootGeometryAtExtension(design, baseY, baseZ, extension) {
    const tail = design.vtail;
    const span = Math.max(number(tail.span_m), .01);
    const rootChord = Math.max(number(tail.root_chord_m), .01);
    const tanLE = Math.tan(radians(tail.le_sweep_deg));
    const tanTE = (
      span * tanLE + rootChord * number(tail.taper) - rootChord
    ) / span;
    const buriedY = baseY - extension * Math.sin(radians(tail.cant_deg));
    const buriedZ = baseZ - extension * Math.cos(radians(tail.cant_deg));
    const xLe = number(tail.x_le_m) - extension * tanLE;
    const chord = rootChord + extension * (tanLE - tanTE);
    const stations = [xLe, xLe + .5 * chord, xLe + chord].map(x => ({
      x,
      ...minBodyEccentricity(design, x, buriedY, buriedZ),
    }));
    const tipJunctionGap = Math.hypot(
      xLe + extension * tanLE - number(tail.x_le_m),
      buriedY + extension * Math.sin(radians(tail.cant_deg)) - baseY,
      buriedZ + extension * Math.cos(radians(tail.cant_deg)) - baseZ,
    );
    return {
      extension,
      xLe,
      y: buriedY,
      z: buriedZ,
      chord,
      stations,
      tipJunctionGap,
      buried: stations.every(station => station.minimum <= .8),
    };
  }

  function finRootGeometry(design) {
    const tail = design.vtail;
    const rootX = number(tail.x_le_m);
    const rootChord = Math.max(number(tail.root_chord_m), .01);
    const core = bodyProfile(design);
    const attachmentSections = [
      interpolateProfile(core, rootX),
      interpolateProfile(core, rootX + .5 * rootChord),
      interpolateProfile(core, rootX + rootChord),
    ];
    const count = Math.round(number(tail.count, 2)) === 1 ? 1 : 2;
    const measured = tail.root_attachment === "measured";
    const baseY = count === 1
      ? 0
      : measured
        ? Math.abs(number(tail.y_root_m))
        : .3 * Math.min(...attachmentSections.map(section => section.width));
    const baseZ = measured
      ? number(tail.z_root_m)
      : Math.min(...attachmentSections.map(section => section.z + .3 * section.height));
    const visible = rootGeometryAtExtension(design, baseY, baseZ, 0);
    const reproduction = design.sketch?.treatment === "reproduction";
    if (visible.buried || !reproduction) {
      return {...visible, baseY, baseZ, extensionRequired: false};
    }
    const maximum = .5 * Math.max(number(tail.span_m), .01);
    let firstInside = null;
    for (let extension = .001; extension <= maximum + 1e-12; extension += .001) {
      const candidate = rootGeometryAtExtension(
        design,
        baseY,
        baseZ,
        Math.min(extension, maximum),
      );
      if (!candidate.buried) continue;
      if (firstInside == null) firstInside = candidate.extension;
      if (candidate.extension + 1e-12 >= firstInside + .005) {
        return {...candidate, baseY, baseZ, extensionRequired: true};
      }
    }
    throw new Error("Vertical-tail root cannot be buried within half the declared fin span.");
  }

  function finSectionPoint(section, xFraction, surface) {
    const thickness = nacaThickness(xFraction, section.tOverC) * section.chord;
    const chordX = section.xLe + xFraction * section.chord;
    return [
      chordX,
      section.y + surface * thickness * section.normal[1],
      section.z + surface * thickness * section.normal[2],
    ];
  }

  function loftFin(collector, root, tip) {
    const segments = 16;
    const upperRoot = [];
    const upperTip = [];
    const lowerRoot = [];
    const lowerTip = [];
    for (let index = 0; index <= segments; index += 1) {
      const xFraction = index / segments;
      upperRoot.push(finSectionPoint(root, xFraction, 1));
      upperTip.push(finSectionPoint(tip, xFraction, 1));
      lowerRoot.push(finSectionPoint(root, xFraction, -1));
      lowerTip.push(finSectionPoint(tip, xFraction, -1));
    }
    for (let index = 0; index < segments; index += 1) {
      const next = index + 1;
      collector.quad(upperRoot[index], upperTip[index], upperTip[next], upperRoot[next]);
      collector.quad(lowerRoot[next], lowerTip[next], lowerTip[index], lowerRoot[index]);
    }
    collector.quad(upperRoot[0], lowerRoot[0], lowerTip[0], upperTip[0]);
    collector.quad(upperTip.at(-1), lowerTip.at(-1), lowerRoot.at(-1), upperRoot.at(-1));
    collector.quad(upperRoot.at(-1), lowerRoot.at(-1), lowerRoot[0], upperRoot[0]);
    collector.quad(upperTip[0], lowerTip[0], lowerTip.at(-1), upperTip.at(-1));
  }

  function loftVerticalTails(design, collector) {
    const tail = design.vtail;
    const span = Math.max(number(tail.span_m), .01);
    const rootChord = Math.max(number(tail.root_chord_m), .01);
    const tipChord = rootChord * Math.max(number(tail.taper), .001);
    const rootX = number(tail.x_le_m);
    const tipX = rootX + span * Math.tan(radians(tail.le_sweep_deg));
    const rootGeometry = finRootGeometry(design);
    const count = Math.round(number(tail.count, 2)) === 1 ? 1 : 2;
    const baseY = rootGeometry.baseY;
    const baseZ = rootGeometry.baseZ;
    const dy = span * Math.sin(radians(tail.cant_deg));
    const dz = span * Math.cos(radians(tail.cant_deg));
    const sides = count === 1 ? [1] : [-1, 1];
    sides.forEach(side => {
      const normal = [
        0,
        -Math.cos(radians(tail.cant_deg)),
        side * Math.sin(radians(tail.cant_deg)),
      ];
      if (rootGeometry.extensionRequired) {
        loftFin(
          collector,
          {
            xLe: rootGeometry.xLe,
            y: count === 1 ? rootGeometry.y : side * rootGeometry.y,
            z: rootGeometry.z,
            chord: rootGeometry.chord,
            tOverC: Math.max(number(tail.t_over_c), .001),
            normal,
          },
          {
            xLe: rootX,
            y: side * baseY,
            z: baseZ,
            chord: rootChord,
            tOverC: Math.max(number(tail.t_over_c), .001),
            normal,
          },
        );
      }
      loftFin(collector, {
        xLe: rootX,
        y: side * baseY,
        z: baseZ,
        chord: rootChord,
        tOverC: Math.max(number(tail.t_over_c), .001),
        normal,
      }, {
        xLe: tipX,
        y: side * (baseY + dy),
        z: baseZ + dz,
        chord: tipChord,
        tOverC: Math.max(number(tail.t_over_c), .001),
        normal,
      });
    });
  }

  function statsFor(design, positions) {
    const bounds = {
      min: [Infinity, Infinity, Infinity],
      max: [-Infinity, -Infinity, -Infinity],
    };
    let finite = true;
    for (let index = 0; index < positions.length; index += 3) {
      for (let axis = 0; axis < 3; axis += 1) {
        const value = positions[index + axis];
        finite &&= Number.isFinite(value);
        bounds.min[axis] = Math.min(bounds.min[axis], value);
        bounds.max[axis] = Math.max(bounds.max[axis], value);
      }
    }
    const wing = design.wing;
    const root = number(wing.root_chord_m);
    const tip = root * number(wing.taper);
    const profile = bodyProfile(design);
    const dominantSection = profile.reduce(
      (best, section) => (
        section.width * section.height > best.width * best.height ? section : best
      ),
      profile[0],
    );
    const dominantMetrics = sectionMetrics(dominantSection);
    const rootGeometry = finRootGeometry(design);
    return {
      finite,
      triangles: positions.length / 9,
      vertices: positions.length / 3,
      bbox: bounds,
      length: bounds.max[0] - bounds.min[0],
      span: bounds.max[1] - bounds.min[1],
      height: bounds.max[2] - bounds.min[2],
      projectedWingArea: .5 * number(wing.span_m) * (root + tip),
      symmetryError: Math.abs(bounds.max[1] + bounds.min[1]),
      sectionArea: dominantMetrics.area,
      sectionAreaFactor: dominantMetrics.areaFactor,
      sectionPerimeter: dominantMetrics.perimeter,
      sectionPowers: {
        side: dominantSection.sidePower,
        top: dominantSection.topPower,
        bottom: dominantSection.bottomPower,
        maxWidthLoc: dominantSection.maxWidthLoc,
      },
      fairingCount: fairingProfiles(design).length,
      finRootExtensionM: rootGeometry.extension,
      finRootTipJunctionGapM: rootGeometry.tipJunctionGap,
    };
  }

  function build(design) {
    const collector = createCollector();
    loftFuselage(design, collector);
    loftWing(design, collector);
    loftHorizontalTail(design, collector);
    loftVerticalTails(design, collector);
    const positions = new Float32Array(collector.positions);
    return {
      positions,
      normals: new Float32Array(collector.normals),
      stats: statsFor(design, positions),
    };
  }

  function propertyHarness(baseDesign, count = 50, seed = 0x0a17c0de) {
    let state = seed >>> 0;
    const random = () => {
      state = (1664525 * state + 1013904223) >>> 0;
      return state / 0x100000000;
    };
    const failures = [];
    for (let index = 0; index < count; index += 1) {
      const design = clone(baseDesign);
      design.fuselage.length_m = 1.8 + 2.5 * random();
      design.fuselage.max_width_m = .18 + .5 * random();
      design.fuselage.max_height_m = .16 + .45 * random();
      design.wing.span_m = 1.2 + 5.5 * random();
      design.wing.root_chord_m = .35 + 1.5 * random();
      design.wing.taper = .18 + .75 * random();
      design.wing.le_sweep_deg = -25 + 75 * random();
      design.wing.dihedral_deg = -8 + 20 * random();
      design.wing.twist_root_deg = -4 + 8 * random();
      design.wing.twist_tip_deg = -12 + 16 * random();
      design.vtail.cant_deg = 45 * random();
      design.vtail.span_m = .2 + .8 * random();
      // Randomized envelope dimensions do not preserve a source-measured
      // fin junction. Exercise the generic attachment policy in this property
      // harness; measured-root parity is covered by deterministic fixtures.
      design.vtail.root_attachment = "derived";
      if (Array.isArray(design.fuselage.stations)) {
        design.fuselage.stations.forEach((station, stationIndex, stations) => {
          const envelope = Math.sin(Math.PI * stationIndex / (stations.length - 1));
          station.width_m = Math.max(.005, design.fuselage.max_width_m * envelope);
          station.height_m = Math.max(.005, design.fuselage.max_height_m * envelope);
          station.side_power = .5 + 9.5 * random();
          station.top_power = .5 + 9.5 * random();
          station.bottom_power = .5 + 9.5 * random();
        });
      }
      const result = build(design);
      if (
        !result.stats.finite
        || result.stats.triangles <= 0
        || result.stats.projectedWingArea <= 0
        || (
          Math.round(number(design.vtail.count, 2)) === 2
          && result.stats.symmetryError > 1e-4
        )
      ) {
        failures.push({index, stats: result.stats});
      }
    }
    return {ok: failures.length === 0, count, failures};
  }

  window.OpenAirPreviewMesh = Object.freeze({
    build,
    nacaThickness,
    propertyHarness,
    fairingProfiles,
    finRootGeometry,
    sectionMetrics,
    sectionPolygon,
  });
})();
