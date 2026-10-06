/* Full-site 3D world — black / white / brinjal */
(function () {
  const canvas = document.getElementById("world3d");
  const shell = document.getElementById("appShell");
  if (!canvas || typeof THREE === "undefined") return;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xf5f5f5, 8, 28);

  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 3.2, 10);

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
  });
  renderer.setClearColor(0xf5f5f5, 1);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 0.7);
  sun.position.set(5, 12, 6);
  scene.add(sun);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(40, 40),
    new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.92, metalness: 0 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.02;
  scene.add(floor);

  const grid = new THREE.GridHelper(40, 40, 0x111111, 0xe0e0e0);
  grid.position.y = 0.01;
  scene.add(grid);

  const matWhite = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.35,
    metalness: 0.05,
  });
  const matBlack = new THREE.MeshStandardMaterial({
    color: 0x0a0a0a,
    roughness: 0.45,
    metalness: 0.1,
  });
  const matBrinjal = new THREE.MeshStandardMaterial({
    color: 0x5c1a4a,
    roughness: 0.4,
    metalness: 0.08,
  });
  const matBrinjalSoft = new THREE.MeshStandardMaterial({
    color: 0x8b3a72,
    roughness: 0.5,
    metalness: 0,
  });
  const matGray = new THREE.MeshStandardMaterial({
    color: 0xe8e8e8,
    roughness: 0.55,
    metalness: 0,
  });

  const floats = [];

  function makePlatform(w, h, d, mat, x, y, z) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.set(x, y, z);
    scene.add(mesh);
    floats.push({
      mesh,
      baseY: y,
      speed: 0.4 + Math.random() * 0.8,
      amp: 0.08 + Math.random() * 0.18,
      spin: (Math.random() - 0.5) * 0.25,
    });
    return mesh;
  }

  makePlatform(2.4, 0.08, 1.6, matWhite, -4.2, 1.4, -2);
  makePlatform(1.8, 0.08, 1.2, matWhite, 4.5, 2.1, -3);
  makePlatform(1.2, 0.08, 1.2, matBrinjal, -2.8, 2.6, -5);
  makePlatform(3.2, 0.1, 0.12, matBlack, 0, 0.6, -1.5);
  makePlatform(0.9, 0.9, 0.9, matGray, 3.2, 1.2, -6);
  makePlatform(0.7, 0.7, 0.7, matBrinjalSoft, -5.2, 2.0, -4);
  makePlatform(2.0, 0.06, 2.0, matWhite, 1.5, 3.0, -8);
  makePlatform(1.4, 0.06, 0.9, matBrinjal, 5.5, 1.0, -1.5);
  makePlatform(0.35, 1.8, 0.35, matBlack, -1.2, 1.0, -3.5);
  makePlatform(0.35, 1.2, 0.35, matBlack, 2.4, 0.7, -4.2);

  function frame(w, h, x, y, z) {
    const g = new THREE.Group();
    const t = 0.05;
    const parts = [
      [w, t, t, 0, h / 2, 0],
      [w, t, t, 0, -h / 2, 0],
      [t, h, t, -w / 2, 0, 0],
      [t, h, t, w / 2, 0, 0],
    ];
    parts.forEach(([a, b, c, px, py, pz]) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(a, b, c), matBlack);
      m.position.set(px, py, pz);
      g.add(m);
    });
    g.position.set(x, y, z);
    scene.add(g);
    floats.push({
      mesh: g,
      baseY: y,
      speed: 0.5 + Math.random() * 0.5,
      amp: 0.12,
      spin: 0.15,
    });
  }
  frame(1.6, 1.0, -3.5, 3.4, -2.5);
  frame(1.2, 0.8, 4.0, 3.6, -5.5);

  function resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resize();
  window.addEventListener("resize", resize);

  let mx = 0;
  let my = 0;
  let tx = 0;
  let ty = 0;
  window.addEventListener("pointermove", (e) => {
    tx = (e.clientX / window.innerWidth) * 2 - 1;
    ty = (e.clientY / window.innerHeight) * 2 - 1;
  });

  const clock = new THREE.Clock();
  function animate() {
    requestAnimationFrame(animate);
    const t = clock.getElapsedTime();
    mx += (tx - mx) * 0.05;
    my += (ty - my) * 0.05;

    camera.position.x = mx * 1.4;
    camera.position.y = 3.2 - my * 0.6;
    camera.lookAt(0, 1.2, -2);

    floats.forEach((f, i) => {
      f.mesh.position.y = f.baseY + Math.sin(t * f.speed + i) * f.amp;
      f.mesh.rotation.y = Math.sin(t * 0.3 + i) * f.spin;
      if (f.mesh.rotation.x !== undefined && f.spin) {
        f.mesh.rotation.x = Math.cos(t * 0.25 + i) * f.spin * 0.4;
      }
    });

    if (shell) shell.style.transform = "none";

    renderer.render(scene, camera);
  }
  animate();

  window.MeridianWorld = {
    pulse(tier) {
      floats.forEach((f, i) => {
        if (i % 3 === 0) f.amp = tier === 1 ? 0.28 : tier === 3 ? 0.1 : 0.16;
      });
    },
  };
})();
