(() => {
  "use strict";

  let renderer = null;
  let scene = null;
  let camera = null;
  let controls = null;
  let aircraft = null;
  let overlays = null;
  let shadedMaterial = null;
  let wireMaterial = null;
  let raf = 0;
  let initialized = false;
  let available = false;

  function notice(message) {
    const node = document.getElementById("viewport3d-notice");
    if (!node) return;
    node.hidden = !message;
    node.textContent = message || "";
  }

  function render() {
    if (!available || !renderer || !scene || !camera) return;
    const canvas = renderer.domElement;
    const width = Math.max(canvas.clientWidth, 320);
    const height = Math.max(canvas.clientHeight, 180);
    if (canvas.width !== Math.round(width * devicePixelRatio)
      || canvas.height !== Math.round(height * devicePixelRatio)) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
    renderer.render(scene, camera);
  }

  function animate() {
    if (!available) return;
    controls.update();
    render();
    raf = requestAnimationFrame(animate);
  }

  function grid() {
    const THREE = window.THREE;
    const helper = new THREE.GridHelper(12, 24, 0x8fa5aa, 0xd8dfdf);
    helper.rotation.x = Math.PI / 2;
    helper.position.z = -.35;
    helper.material.transparent = true;
    helper.material.opacity = .55;
    return helper;
  }

  function init() {
    if (initialized) return available;
    initialized = true;
    const canvas = document.getElementById("three-canvas");
    const THREE = window.THREE;
    const bundleReady = Boolean(
      THREE
      && typeof THREE.WebGLRenderer === "function"
      && typeof THREE.OrbitControls === "function",
    );
    document.body.dataset.threeRevision = String(THREE?.REVISION || "");
    document.body.dataset.threeBundleReady = String(bundleReady);
    if (
      !canvas
      || !bundleReady
    ) {
      document.body.dataset.threeReady = "false";
      notice("3D preview is unavailable; 2D editing and mesh checks remain active.");
      return false;
    }
    try {
      renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: false,
        powerPreference: "high-performance",
      });
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
      renderer.setClearColor(0xf8faf6, 1);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(36, 1000 / 420, .01, 100);
      camera.up.set(0, 0, 1);
      camera.position.set(4.4, -5.5, 3.2);
      controls = new THREE.OrbitControls(camera, canvas);
      controls.enableDamping = true;
      controls.dampingFactor = .08;
      controls.target.set(1.4, 0, .05);
      controls.minDistance = .5;
      controls.maxDistance = 30;
      scene.add(new THREE.HemisphereLight(0xffffff, 0x50616a, 2.25));
      const key = new THREE.DirectionalLight(0xffffff, 2.4);
      key.position.set(-3, -4, 7);
      scene.add(key);
      scene.add(grid());
      aircraft = new THREE.Group();
      overlays = new THREE.Group();
      scene.add(aircraft, overlays);
      shadedMaterial = new THREE.MeshStandardMaterial({
        color: 0x34798e,
        roughness: .65,
        metalness: .04,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
      });
      wireMaterial = new THREE.MeshBasicMaterial({
        color: 0x163e4d,
        wireframe: true,
        transparent: true,
        opacity: .32,
      });
      available = true;
      document.body.dataset.threeReady = "true";
      notice("");
      animate();
      return true;
    } catch (error) {
      available = false;
      document.body.dataset.threeReady = "false";
      notice(`WebGL unavailable (${error.message}). 2D editing remains active.`);
      return false;
    }
  }

  function disposeGroup(group) {
    while (group.children.length) {
      const child = group.children.pop();
      child.geometry?.dispose();
      if (child.material && child.material !== shadedMaterial && child.material !== wireMaterial) {
        child.material.dispose();
      }
    }
  }

  function addMarker(x, color, label, z = 0) {
    const THREE = window.THREE;
    if (!Number.isFinite(x)) return;
    const material = new THREE.MeshBasicMaterial({color});
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(.045, 14, 9), material);
    sphere.position.set(x, 0, z);
    sphere.userData.label = label;
    overlays.add(sphere);
    const points = [
      new THREE.Vector3(x, 0, z - .25),
      new THREE.Vector3(x, 0, z + .25),
    ];
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({color, transparent: true, opacity: .8}),
    );
    overlays.add(line);
  }

  function addBox(center, size, color) {
    const THREE = window.THREE;
    if (![...center, ...size].every(Number.isFinite) || size.some(value => value <= 0)) return;
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(...size),
      new THREE.MeshBasicMaterial({
        color,
        wireframe: true,
        transparent: true,
        opacity: .7,
      }),
    );
    box.position.set(...center);
    overlays.add(box);
  }

  function updateOverlays(design, balance) {
    disposeGroup(overlays);
    const fuselage = design.fuselage;
    const bodyZ = 0;
    addMarker(Number(balance?.cg), 0xe9673f, "CG", bodyZ);
    addMarker(Number(balance?.reserveCg), 0xe4a738, "reserve CG", bodyZ);
    addMarker(Number(balance?.np), 0x34765a, "NP", bodyZ);
    addBox(
      [
        Number(fuselage.payload_bay_x_m) + .5 * Number(fuselage.payload_bay_length_m),
        0,
        0,
      ],
      [
        Number(fuselage.payload_bay_length_m),
        Number(fuselage.payload_bay_width_m),
        Number(fuselage.payload_bay_height_m),
      ],
      0x34765a,
    );
    addBox(
      [Number(fuselage.fuel_tank_x_m), 0, 0],
      [
        Math.max(.15, .12 * Number(fuselage.length_m)),
        .65 * Number(fuselage.max_width_m),
        .65 * Number(fuselage.max_height_m),
      ],
      0x926fc0,
    );
  }

  function fitCamera(stats) {
    if (controls.userData?.fitted) return;
    const center = [
      .5 * (stats.bbox.min[0] + stats.bbox.max[0]),
      .5 * (stats.bbox.min[1] + stats.bbox.max[1]),
      .5 * (stats.bbox.min[2] + stats.bbox.max[2]),
    ];
    const size = Math.max(stats.length, stats.span, stats.height, 1);
    controls.target.set(...center);
    camera.position.set(center[0] + .75 * size, center[1] - 1.05 * size, center[2] + .58 * size);
    camera.near = Math.max(size / 1000, .001);
    camera.far = size * 20;
    camera.updateProjectionMatrix();
    controls.userData = {fitted: true};
  }

  function update(design, balance, prepared = null) {
    const preview = prepared || window.OpenAirPreviewMesh.build(design);
    if (!init()) return preview;
    const THREE = window.THREE;
    disposeGroup(aircraft);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(preview.positions, 3));
    geometry.setAttribute("normal", new THREE.BufferAttribute(preview.normals, 3));
    geometry.computeBoundingSphere();
    aircraft.add(new THREE.Mesh(geometry, shadedMaterial));
    const wireGeometry = geometry.clone();
    const wire = new THREE.Mesh(wireGeometry, wireMaterial);
    wire.visible = document.getElementById("toggle-wireframe")?.checked !== false;
    wire.userData.wireframeLayer = true;
    aircraft.add(wire);
    updateOverlays(design, balance);
    fitCamera(preview.stats);
    render();
    return preview;
  }

  function setWireframe(visible) {
    if (!aircraft) return;
    aircraft.children.forEach(child => {
      if (child.userData.wireframeLayer) child.visible = Boolean(visible);
    });
    render();
  }

  function destroy() {
    cancelAnimationFrame(raf);
    renderer?.dispose();
    initialized = false;
    available = false;
  }

  window.OpenAirViewport3D = Object.freeze({
    init,
    update,
    setWireframe,
    destroy,
    isAvailable: () => available,
  });
})();
