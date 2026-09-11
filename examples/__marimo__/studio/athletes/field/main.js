import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.185.1/build/three.module.js";
import Shower from "https://cdn.jsdelivr.net/npm/@shower/core@3.6.0/lib/shower.js";

const canvas = document.querySelector("#field-canvas");
const source = document.querySelector("#athlete-data");
const sportSelectionSource = document.querySelector("#sport-selection");
const dataStatus = document.querySelector("#data-status");
const athleteCredit = document.querySelector("#athlete-credit");
const athleteName = document.querySelector("#athlete-name");
const athleteMeta = document.querySelector("#athlete-meta");
const slideCount = document.querySelector("#slide-count");
const previousButton = document.querySelector("#previous-button");
const nextButton = document.querySelector("#next-button");
const overviewButton = document.querySelector("#overview-button");
const fullscreenButton = document.querySelector("#fullscreen-button");
const fullscreenStatus = document.querySelector("#fullscreen-status");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
const numberFormat = new Intl.NumberFormat("en-US");
const goldenAngle = Math.PI * (3 - Math.sqrt(5));
const palette = {
  chalk: [0.956, 0.945, 0.918],
  blue: [0.267, 0.565, 1],
  faint: [0.08, 0.09, 0.11],
};

let rows = [];
let layouts;
let points;
let transition;
let activeMode = "roster";
let selectedSport;
let hoveredIndex = -1;
let animationFrame;

const renderer = new THREE.WebGLRenderer({
  canvas,
  alpha: false,
  antialias: true,
  preserveDrawingBuffer: true,
  powerPreference: "high-performance",
});
renderer.setClearColor(0x060606, 1);
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
camera.position.set(0, 0, 23);
const field = new THREE.Group();
scene.add(field);

const orbitMaterial = new THREE.LineBasicMaterial({
  color: 0x242832,
  transparent: true,
  opacity: 0.58,
});
const profileMaterial = new THREE.LineBasicMaterial({
  color: 0x4490ff,
  transparent: true,
  opacity: 0,
});
const orbitGuides = new THREE.Group();
[2.4, 4.7, 7].forEach((radius, index) => {
  const curve = new THREE.EllipseCurve(0, 0, radius, radius, 0, Math.PI * 2);
  const geometry = new THREE.BufferGeometry().setFromPoints(
    curve.getPoints(160),
  );
  const ring = new THREE.LineLoop(geometry, orbitMaterial);
  ring.rotation.x = index === 1 ? Math.PI / 2 : 0;
  ring.rotation.y = index === 2 ? Math.PI / 2 : 0;
  orbitGuides.add(ring);
});
field.add(orbitGuides);

const profileBox = new THREE.LineSegments(
  new THREE.EdgesGeometry(new THREE.BoxGeometry(12, 8, 7)),
  profileMaterial,
);
field.add(profileBox);

const material = new THREE.PointsMaterial({
  size: 0.075,
  sizeAttenuation: true,
  transparent: true,
  opacity: 0.92,
  depthWrite: false,
  vertexColors: true,
});

const raycaster = new THREE.Raycaster();
raycaster.params.Points.threshold = 0.16;
const pointer = new THREE.Vector2(2, 2);
let pointerVisible = false;

const observeMarimoValue = (host, { onValue, onError = () => {} }) => {
  const sync = (event) => onValue(event.detail.value);
  const fail = (event) => onError(event.detail);
  host.addEventListener("marimo-value-updated", sync);
  host.addEventListener("marimo-value-error", fail);
  if (host.marimoValue !== undefined) onValue(host.marimoValue);
  return () => {
    host.removeEventListener("marimo-value-updated", sync);
    host.removeEventListener("marimo-value-error", fail);
  };
};

const seeded = (index, salt = 0) => {
  let value = Math.imul(index + 1, 0x9e3779b1) ^ salt;
  value = Math.imul(value ^ (value >>> 16), 0x21f0aaad);
  value = Math.imul(value ^ (value >>> 15), 0x735a2d97);
  return ((value ^ (value >>> 15)) >>> 0) / 4294967295;
};

const writePoint = (layout, index, x, y, z, color) => {
  const offset = index * 3;
  layout.positions[offset] = x;
  layout.positions[offset + 1] = y;
  layout.positions[offset + 2] = z;
  layout.colors[offset] = color[0];
  layout.colors[offset + 1] = color[1];
  layout.colors[offset + 2] = color[2];
};

const createLayout = (length) => ({
  positions: new Float32Array(length * 3),
  colors: new Float32Array(length * 3),
});

const isMedalist = (row) => Number(row.medal_awards) > 0;
const pointColor = (row) => (isMedalist(row) ? palette.blue : palette.chalk);

const rosterLayout = () => {
  const layout = createLayout(rows.length);
  rows.forEach((row, index) => {
    const y = 1 - ((index + 0.5) / rows.length) * 2;
    const radius = Math.sqrt(1 - y * y);
    const angle = goldenAngle * index;
    const depth = 6.35 + (seeded(index, 13) - 0.5) * 0.35;
    writePoint(
      layout,
      index,
      Math.cos(angle) * radius * depth,
      y * depth,
      Math.sin(angle) * radius * depth,
      pointColor(row),
    );
  });
  return { ...layout, camera: [0, 0, 23], speed: 0.0007 };
};

const sportsLayout = () => {
  const layout = createLayout(rows.length);
  const groups = new Map();
  rows.forEach((row, index) => {
    const sport = String(row.sport);
    if (!groups.has(sport)) groups.set(sport, []);
    groups.get(sport).push(index);
  });
  const ordered = [...groups.entries()].sort(
    (a, b) => b[1].length - a[1].length,
  );
  const hasSelection = groups.has(selectedSport);
  ordered.forEach(([sport, indices], clusterIndex) => {
    const isSelected = hasSelection && sport === selectedSport;
    const centerAngle = clusterIndex * goldenAngle;
    const ringRadius = isSelected
      ? 0
      : (hasSelection ? 2.2 : 1.2) +
        Math.sqrt((clusterIndex + 0.5) / ordered.length) *
          (hasSelection ? 4.6 : 5.7);
    const centerX = Math.cos(centerAngle) * ringRadius;
    const centerY = Math.sin(centerAngle) * ringRadius;
    const clusterRadius = isSelected
      ? 1.85
      : 0.32 + Math.sqrt(indices.length / ordered[0][1].length);
    indices.forEach((rowIndex, localIndex) => {
      const localAngle = localIndex * goldenAngle;
      const localRadius =
        Math.sqrt((localIndex + 0.5) / indices.length) * clusterRadius;
      const row = rows[rowIndex];
      writePoint(
        layout,
        rowIndex,
        centerX + Math.cos(localAngle) * localRadius,
        centerY + Math.sin(localAngle) * localRadius,
        (seeded(rowIndex, 47) - 0.5) * (isSelected ? 0.7 : 1.15) -
          (hasSelection && !isSelected ? 1.2 : 0),
        hasSelection
          ? isSelected
            ? palette.blue
            : palette.faint
          : pointColor(row),
      );
    });
  });
  return { ...layout, camera: [0, 0, 23.5], speed: 0.00025 };
};

const medalsLayout = () => {
  const layout = createLayout(rows.length);
  const medalGroups = [[], [], []];
  const fieldIndices = [];
  rows.forEach((row, index) => {
    if (Number(row.gold) > 0) medalGroups[1].push(index);
    else if (Number(row.silver) > 0) medalGroups[0].push(index);
    else if (Number(row.bronze) > 0) medalGroups[2].push(index);
    else fieldIndices.push(index);
  });
  fieldIndices.forEach((rowIndex, localIndex) => {
    const angle = localIndex * goldenAngle;
    const radius = 7.2 + seeded(rowIndex, 83) * 0.8;
    writePoint(
      layout,
      rowIndex,
      Math.cos(angle) * radius,
      Math.sin(angle) * radius * 0.72,
      (seeded(rowIndex, 97) - 0.5) * 1.6,
      palette.faint,
    );
  });
  [-3, 0, 3].forEach((centerX, groupIndex) => {
    const indices = medalGroups[groupIndex];
    indices.forEach((rowIndex, localIndex) => {
      const progress = (localIndex + 0.5) / indices.length;
      const angle = localIndex * goldenAngle;
      const radius = 0.28 + Math.sqrt(progress) * 1.2;
      writePoint(
        layout,
        rowIndex,
        centerX + Math.cos(angle) * radius,
        -3.4 + progress * 6.8,
        Math.sin(angle) * radius,
        palette.blue,
      );
    });
  });
  return { ...layout, camera: [0, 0, 23], speed: 0.00018 };
};

const quantile = (values, position) => {
  const sorted = values
    .map(Number)
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  if (!sorted.length) return undefined;
  const index = (sorted.length - 1) * position;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
};

const profileLayout = () => {
  const layout = createLayout(rows.length);
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const robustExtent = (name) => {
    const values = rows.map((row) => row[name]);
    return [quantile(values, 0.01), quantile(values, 0.99)];
  };
  const heightExtent = robustExtent("height");
  const weightExtent = robustExtent("weight");
  const ageExtent = robustExtent("age");
  const scale = (value, [low, high], span) =>
    ((clamp(value, low, high) - low) / (high - low)) * span - span / 2;
  rows.forEach((row, index) => {
    const height = Number(row.height);
    const weight = Number(row.weight);
    const age = Number(row.age);
    const complete =
      Number.isFinite(height) &&
      height > 0 &&
      Number.isFinite(weight) &&
      weight > 0 &&
      Number.isFinite(age) &&
      age > 0;
    if (!complete) {
      const angle = index * goldenAngle;
      const radius = 7.4 + seeded(index, 109) * 0.45;
      writePoint(
        layout,
        index,
        Math.cos(angle) * radius,
        Math.sin(angle) * radius * 0.58,
        -3.8,
        palette.faint,
      );
      return;
    }
    const x = scale(height, heightExtent, 12);
    const y = scale(weight, weightExtent, 8);
    const z = scale(age, ageExtent, 7);
    writePoint(
      layout,
      index,
      x + (seeded(index, 127) - 0.5) * 0.1,
      y + (seeded(index, 149) - 0.5) * 0.1,
      z + (seeded(index, 167) - 0.5) * 0.1,
      pointColor(row),
    );
  });
  return { ...layout, camera: [0, 0, 24.5], speed: 0.00008 };
};

const calculateLayouts = () =>
  new Map([
    ["roster", rosterLayout()],
    ["sports", sportsLayout()],
    ["medals", medalsLayout()],
    ["profile", profileLayout()],
  ]);

const buildField = () => {
  if (points) {
    field.remove(points);
    points.geometry.dispose();
  }
  layouts = calculateLayouts();
  const initial = layouts.get(activeMode) ?? layouts.get("roster");
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(initial.positions.slice(), 3),
  );
  geometry.setAttribute(
    "color",
    new THREE.BufferAttribute(initial.colors.slice(), 3),
  );
  points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  field.add(points);
  camera.position.fromArray(initial.camera);
  transition = undefined;
};

const beginTransition = (mode) => {
  const target = layouts?.get(mode);
  if (!points || !target) return;
  const position = points.geometry.getAttribute("position");
  const color = points.geometry.getAttribute("color");
  transition = {
    started: performance.now(),
    duration: reducedMotion.matches ? 0 : 1050,
    positions: position.array.slice(),
    colors: color.array.slice(),
    camera: camera.position.toArray(),
    target,
  };
  requestRender();
};

const setMode = (mode) => {
  activeMode = mode;
  document.body.dataset.mode = mode;
  orbitMaterial.opacity = mode === "profile" ? 0.12 : 0.58;
  profileMaterial.opacity = mode === "profile" ? 0.4 : 0;
  beginTransition(mode);
};

const resize = () => {
  const width = innerWidth;
  const height = innerHeight;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  const narrow = width <= 760;
  field.position.set(narrow ? 0 : 3.2, narrow ? 3.05 : 0, 0);
  field.scale.setScalar(narrow ? 0.44 : 1);
  material.size = narrow ? 0.15 : 0.075;
  requestRender();
};

const updateTransition = (now) => {
  if (!transition || !points) return;
  const elapsed = transition.duration
    ? (now - transition.started) / transition.duration
    : 1;
  const progress = Math.min(1, elapsed);
  const eased = 1 - Math.pow(1 - progress, 3);
  const position = points.geometry.getAttribute("position");
  const color = points.geometry.getAttribute("color");
  for (let index = 0; index < position.array.length; index += 1) {
    position.array[index] =
      transition.positions[index] +
      (transition.target.positions[index] - transition.positions[index]) *
        eased;
    color.array[index] =
      transition.colors[index] +
      (transition.target.colors[index] - transition.colors[index]) * eased;
  }
  camera.position.set(
    transition.camera[0] +
      (transition.target.camera[0] - transition.camera[0]) * eased,
    transition.camera[1] +
      (transition.target.camera[1] - transition.camera[1]) * eased,
    transition.camera[2] +
      (transition.target.camera[2] - transition.camera[2]) * eased,
  );
  position.needsUpdate = true;
  color.needsUpdate = true;
  if (progress === 1) transition = undefined;
};

const inspectPoint = () => {
  if (!pointerVisible || !points || innerWidth <= 760) {
    if (hoveredIndex !== -1) {
      hoveredIndex = -1;
      athleteCredit.hidden = true;
    }
    return;
  }
  raycaster.setFromCamera(pointer, camera);
  const match = raycaster.intersectObject(points, false)[0];
  const index = match?.index ?? -1;
  if (index === hoveredIndex) return;
  hoveredIndex = index;
  if (index < 0 || !rows[index]) {
    athleteCredit.hidden = true;
    return;
  }
  const row = rows[index];
  const awards = Number(row.medal_awards) || 0;
  athleteName.textContent = String(row.name);
  athleteMeta.textContent = `${row.sport} · ${row.nationality}${
    awards ? ` · ${awards} medal award${awards === 1 ? "" : "s"}` : ""
  }`;
  athleteCredit.hidden = false;
};

const render = (now) => {
  animationFrame = undefined;
  updateTransition(now);
  const speed = layouts?.get(activeMode)?.speed ?? 0;
  if (!reducedMotion.matches && points) field.rotation.y += speed;
  if (reducedMotion.matches) field.rotation.x = 0;
  else {
    field.rotation.x +=
      ((pointerVisible ? -pointer.y * 0.08 : 0) - field.rotation.x) * 0.025;
  }
  inspectPoint();
  renderer.render(scene, camera);
  if (!reducedMotion.matches) requestRender();
};

const requestRender = () => {
  if (animationFrame === undefined) {
    animationFrame = requestAnimationFrame(render);
  }
};

canvas.addEventListener("pointermove", (event) => {
  pointer.x = (event.clientX / innerWidth) * 2 - 1;
  pointer.y = -(event.clientY / innerHeight) * 2 + 1;
  pointerVisible = true;
  requestRender();
});
canvas.addEventListener("pointerleave", () => {
  pointer.set(2, 2);
  pointerVisible = false;
  requestRender();
});

const updateMotionPreference = () => {
  if (reducedMotion.matches) {
    if (animationFrame !== undefined) cancelAnimationFrame(animationFrame);
    animationFrame = undefined;
    if (transition) transition.duration = 0;
  }
  requestRender();
};
reducedMotion.addEventListener("change", updateMotionPreference);

// Shower sees shadow hosts as event targets. Keep projected control keys
// inside their output after native handlers run, preserving default actions.
for (const host of document.querySelectorAll("marimo-cell, marimo-output")) {
  host.addEventListener("keydown", (event) => event.stopPropagation());
}

const shower = new Shower({ containerSelector: "#app-shell" });
const updateControls = () => {
  const index = Math.max(0, shower.activeSlideIndex);
  slideCount.textContent = `${String(index + 1).padStart(2, "0")} / ${String(
    shower.slides.length,
  ).padStart(2, "0")}`;
  previousButton.disabled = index === 0;
  nextButton.disabled = index === shower.slides.length - 1;
  overviewButton.textContent = shower.isFullMode ? "All" : "Present";
  const mode = shower.activeSlide?.element.dataset.mode;
  if (mode) setMode(mode);
};
shower.addEventListener("slidechange", updateControls);
shower.addEventListener("modechange", updateControls);
shower.start();
const sanitizeLiveRegion = () => {
  const region = document.querySelector(".region");
  region?.querySelectorAll("[data-marimo-studio-site]").forEach((host) => {
    host.removeAttribute("data-marimo-studio-site");
    host.removeAttribute("mo-value");
    if (host.matches("marimo-cell")) {
      host.replaceWith(document.createTextNode("Sport filter"));
    }
  });
};
// Shower clones slide markup for announcements. Remove projection identity
// before Studio's observer can treat the clone as another mount site.
sanitizeLiveRegion();
shower.addEventListener("slidechange", sanitizeLiveRegion);
if (!shower.activeSlide) shower.first();
shower.enterFullMode();
updateControls();

previousButton.addEventListener("click", () => shower.prev());
nextButton.addEventListener("click", () => shower.next());
overviewButton.addEventListener("click", () => {
  if (shower.isFullMode) shower.exitFullMode();
  else shower.enterFullMode();
});
const updateFullscreenControl = () => {
  fullscreenButton.textContent = document.fullscreenElement ? "Exit" : "Full";
  fullscreenButton.disabled = !document.fullscreenEnabled;
  fullscreenStatus.textContent = document.fullscreenEnabled
    ? ""
    : "Fullscreen unavailable";
};
fullscreenButton.addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    fullscreenStatus.textContent = "Fullscreen request failed";
  }
});
document.addEventListener("fullscreenchange", updateFullscreenControl);
updateFullscreenControl();

const failData = () => {
  dataStatus.textContent = "Roster unavailable";
  dataStatus.dataset.ready = "false";
};
const stopSelection = observeMarimoValue(sportSelectionSource, {
  onValue: (value) => {
    selectedSport = String(value);
    if (!rows.length || !layouts) return;
    layouts.set("sports", sportsLayout());
    if (activeMode === "sports") beginTransition("sports");
  },
});
const stopValue = observeMarimoValue(source, {
  onValue: (value) => {
    if (!value || typeof value.toArray !== "function") {
      failData();
      return;
    }
    rows = value.toArray();
    if (!rows.length) {
      failData();
      return;
    }
    buildField();
    dataStatus.textContent = `${numberFormat.format(rows.length)} athletes`;
    dataStatus.dataset.ready = "true";
    setMode(activeMode);
  },
  onError: failData,
});

resize();
addEventListener("resize", resize);
document.querySelector("#app-shell")?.setAttribute("data-ready", "");

addEventListener(
  "pagehide",
  () => {
    stopValue();
    stopSelection();
    if (animationFrame !== undefined) cancelAnimationFrame(animationFrame);
    animationFrame = undefined;
    removeEventListener("resize", resize);
    reducedMotion.removeEventListener("change", updateMotionPreference);
    points?.geometry.dispose();
    orbitGuides.children.forEach((ring) => ring.geometry.dispose());
    profileBox.geometry.dispose();
    material.dispose();
    orbitMaterial.dispose();
    profileMaterial.dispose();
    renderer.dispose();
  },
  { once: true },
);
