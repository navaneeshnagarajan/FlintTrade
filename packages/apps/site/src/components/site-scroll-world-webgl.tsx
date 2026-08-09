'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

import type { ScrollWorldFailureReason } from './site-scroll-world';
import { createScrollWorldLifecycle } from './site-scroll-world-lifecycle';
import { chapters, interpolateChapterState, progressFromScroll } from '@/lib/site-scroll-world-chapters';
import { chooseScrollWorldQuality, nextScrollWorldQuality } from '@/lib/site-scroll-world-quality';

interface SiteScrollWorldWebGLProps {
  onReady: () => void;
  onFallback: (reason: ScrollWorldFailureReason) => void;
}

const MAX_EMBERS = 180;
const FRAME_SAMPLE_SIZE = 90;

function createSeededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1_664_525 + 1_013_904_223) >>> 0;
    return state / 4_294_967_296;
  };
}

function percentile95(values: readonly number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * 0.95)];
}

/**
 * Original FlintTrade Spark Path world: an angular flint core, modular data
 * plates, three explicit safety gates, bounded market-flow traces and a quiet
 * evaluation horizon. All assets are procedural and the canvas is decorative.
 */
export default function SiteScrollWorldWebGL({ onReady, onFallback }: SiteScrollWorldWebGLProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (motionQuery.matches) {
      onFallback('reduced-motion');
      return undefined;
    }

    const lifecycle = createScrollWorldLifecycle(onFallback);
    let setupComplete = false;
    let setupFailureReason: ScrollWorldFailureReason = 'renderer-error';

    try {
      const renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
        failIfMajorPerformanceCaveat: true,
      });
      lifecycle.setRenderer(renderer);
      setupFailureReason = 'setup-error';

    const scene = new THREE.Scene();
    const fog = new THREE.FogExp2(0x0a0a0f, chapters[0].world.fog);
    scene.fog = fog;

    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 80);
    const smoothPosition = new THREE.Vector3();
    const smoothTarget = new THREE.Vector3();
    const desiredPosition = new THREE.Vector3();
    const desiredTarget = new THREE.Vector3();

    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.9;
    renderer.shadowMap.enabled = false;

    const trackGeometry = <T extends THREE.BufferGeometry>(geometry: T): T => lifecycle.track(geometry);
    const trackMaterial = <T extends THREE.Material>(material: T): T => lifecycle.track(material);

    const graphite = new THREE.Color(0x111318);
    const emerald = new THREE.Color(0x22c55e);
    const sky = new THREE.Color(0x38bdf8);
    const horizon = new THREE.Color(0xa3e635);

    const hemisphere = new THREE.HemisphereLight(0x243047, 0x08090d, 0.55);
    scene.add(hemisphere);
    const keyLight = new THREE.DirectionalLight(emerald, 0.75);
    keyLight.position.set(5, 9, 5);
    scene.add(keyLight);
    const rimLight = new THREE.PointLight(sky, 2.2, 18, 2);
    rimLight.position.set(-4, 3, -4);
    scene.add(rimLight);

    const flintMaterial = trackMaterial(
      new THREE.MeshStandardMaterial({
        color: graphite,
        emissive: 0x0a2a12,
        emissiveIntensity: 0.42,
        flatShading: true,
        metalness: 0.24,
        roughness: 0.78,
      }),
    );
    const flint = new THREE.Mesh(trackGeometry(new THREE.DodecahedronGeometry(1.05, 0)), flintMaterial);
    flint.scale.set(0.72, 1.2, 0.58);
    flint.position.set(0, 1.05, 0);
    flint.rotation.set(0.18, -0.45, -0.12);
    scene.add(flint);

    const sparkMaterial = trackMaterial(
      new THREE.MeshStandardMaterial({
        color: emerald,
        emissive: emerald,
        emissiveIntensity: 2.1,
        roughness: 0.28,
      }),
    );
    const spark = new THREE.Mesh(trackGeometry(new THREE.OctahedronGeometry(0.16, 0)), sparkMaterial);
    spark.position.set(0.32, 1.78, 0.28);
    scene.add(spark);

    const orbitMaterial = trackMaterial(
      new THREE.MeshBasicMaterial({ color: emerald, transparent: true, opacity: 0.28 }),
    );
    const orbit = new THREE.Mesh(trackGeometry(new THREE.TorusGeometry(1.7, 0.018, 4, 48)), orbitMaterial);
    orbit.position.set(0, 1.05, -0.15);
    orbit.rotation.set(Math.PI / 2.8, 0.15, 0.1);
    scene.add(orbit);

    const plateGeometry = trackGeometry(new THREE.BoxGeometry(1.8, 0.08, 1.15));
    const plateMaterial = trackMaterial(
      new THREE.MeshStandardMaterial({ color: 0x1b2029, metalness: 0.12, roughness: 0.88 }),
    );
    const plates = new THREE.InstancedMesh(plateGeometry, plateMaterial, 8);
    const plateTransform = new THREE.Object3D();
    for (let index = 0; index < 8; index += 1) {
      const column = index % 2;
      const row = Math.floor(index / 2);
      plateTransform.position.set((column * 2 - 1) * (1.35 + row * 0.08), 0.45 + row * 0.52, -1.5 - row * 0.9);
      plateTransform.rotation.set(0.08 + row * 0.015, column ? -0.2 : 0.2, column ? 0.05 : -0.05);
      plateTransform.scale.setScalar(1 - row * 0.055);
      plateTransform.updateMatrix();
      plates.setMatrixAt(index, plateTransform.matrix);
    }
    plates.instanceMatrix.needsUpdate = true;
    scene.add(plates);

    const gateMaterial = trackMaterial(
      new THREE.MeshStandardMaterial({
        color: 0x252a32,
        emissive: 0x0d3b1b,
        emissiveIntensity: 0.36,
        metalness: 0.2,
        roughness: 0.7,
      }),
    );
    const postGeometry = trackGeometry(new THREE.BoxGeometry(0.12, 2.35, 0.16));
    const lintelGeometry = trackGeometry(new THREE.BoxGeometry(2.15, 0.12, 0.16));
    const gateGroup = new THREE.Group();
    for (let index = 0; index < 3; index += 1) {
      const gate = new THREE.Group();
      const leftPost = new THREE.Mesh(postGeometry, gateMaterial);
      const rightPost = new THREE.Mesh(postGeometry, gateMaterial);
      const lintel = new THREE.Mesh(lintelGeometry, gateMaterial);
      leftPost.position.set(-1, 1.15, 0);
      rightPost.position.set(1, 1.15, 0);
      lintel.position.set(0, 2.27, 0);
      gate.add(leftPost, rightPost, lintel);
      gate.position.set((index - 1) * 2.8, 0, -4.2 - index * 1.15);
      gate.rotation.y = (index - 1) * -0.13;
      gateGroup.add(gate);
    }
    scene.add(gateGroup);

    const flowMaterial = trackMaterial(
      new THREE.LineBasicMaterial({ color: sky, transparent: true, opacity: 0.42 }),
    );
    const flowCurves = [
      [[-4, 0.25, -1], [-2, 1.2, -2.6], [0, 0.5, -4.6], [3.4, 1.6, -7]],
      [[3.8, 0.4, -0.8], [2.4, 1.5, -3], [0.4, 0.9, -5.5], [-2.7, 1.2, -7.5]],
      [[-3.5, 2.3, -2], [-1.2, 2.8, -4], [1.3, 2.2, -6], [3.2, 2.7, -8]],
    ] as const;
    for (const points of flowCurves) {
      const curve = new THREE.CatmullRomCurve3(points.map(([x, y, z]) => new THREE.Vector3(x, y, z)));
      const geometry = trackGeometry(new THREE.BufferGeometry().setFromPoints(curve.getPoints(56)));
      scene.add(new THREE.Line(geometry, flowMaterial));
    }

    const boundaryMaterial = trackMaterial(
      new THREE.MeshBasicMaterial({ color: horizon, transparent: true, opacity: 0.34 }),
    );
    const riskBoundary = new THREE.Mesh(
      trackGeometry(new THREE.BoxGeometry(7.2, 0.035, 0.035)),
      boundaryMaterial,
    );
    riskBoundary.position.set(0, 0.32, -7.3);
    scene.add(riskBoundary);

    const pedestalMaterial = trackMaterial(
      new THREE.MeshStandardMaterial({ color: 0x151820, metalness: 0.16, roughness: 0.82 }),
    );
    const pedestal = new THREE.Mesh(
      trackGeometry(new THREE.CylinderGeometry(1.65, 2.05, 0.28, 8)),
      pedestalMaterial,
    );
    pedestal.position.set(0, 0.12, -8.1);
    scene.add(pedestal);

    const seal = new THREE.Mesh(
      trackGeometry(new THREE.TorusGeometry(0.52, 0.055, 6, 32)),
      orbitMaterial,
    );
    seal.position.set(0, 0.42, -8.1);
    seal.rotation.x = Math.PI / 2;
    scene.add(seal);

    const random = createSeededRandom(20_260_809);
    const emberPositions = new Float32Array(MAX_EMBERS * 3);
    const emberVelocities = new Float32Array(MAX_EMBERS * 3);
    for (let index = 0; index < MAX_EMBERS; index += 1) {
      const offset = index * 3;
      emberPositions[offset] = (random() - 0.5) * 13;
      emberPositions[offset + 1] = random() * 6.5 + 0.15;
      emberPositions[offset + 2] = random() * -11 + 1;
      emberVelocities[offset] = (random() - 0.5) * 0.004;
      emberVelocities[offset + 1] = 0.002 + random() * 0.004;
      emberVelocities[offset + 2] = (random() - 0.5) * 0.003;
    }
    const emberGeometry = trackGeometry(new THREE.BufferGeometry());
    emberGeometry.setAttribute('position', new THREE.BufferAttribute(emberPositions, 3));
    const emberMaterial = trackMaterial(
      new THREE.PointsMaterial({
        color: emerald,
        size: 0.035,
        transparent: true,
        opacity: 0.55,
        depthWrite: false,
        sizeAttenuation: true,
      }),
    );
    const embers = new THREE.Points(emberGeometry, emberMaterial);
    scene.add(embers);

    let quality = chooseScrollWorldQuality(window.devicePixelRatio || 1);
    let chapterTops: number[] = [];
    let animationFrame: number | null = null;
    let visible = !document.hidden;
    let intersecting = true;
    let ready = false;
    let lastFrameTime: number | null = null;
    const frameTimes: number[] = [];
    let intersectionObserver: IntersectionObserver | null = null;

    const resize = () => {
      const width = Math.max(1, canvas.clientWidth || window.innerWidth);
      const height = Math.max(1, canvas.clientHeight || window.innerHeight);
      renderer.setPixelRatio(quality.dpr);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      canvas.dataset.dpr = quality.dpr.toFixed(2);
    };

    const measureChapters = (): boolean => {
      const measured = chapters.map((chapter) => {
        const anchor = document.querySelector<HTMLElement>(`[data-scroll-chapter="${chapter.id}"]`);
        return anchor ? anchor.getBoundingClientRect().top + window.scrollY : null;
      });
      if (measured.some((top) => top === null)) return false;
      chapterTops = measured as number[];
      return true;
    };

    const currentProgress = () =>
      progressFromScroll(
        window.scrollY,
        chapterTops,
        document.documentElement.scrollHeight,
        window.innerHeight,
      );

    const applyExactStoryState = () => {
      const state = interpolateChapterState(currentProgress());
      smoothPosition.set(...state.position);
      smoothTarget.set(...state.target);
      camera.position.copy(smoothPosition);
      camera.lookAt(smoothTarget);
      camera.fov = state.fov;
      camera.updateProjectionMatrix();
    };

    const stop = () => {
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
      animationFrame = null;
      canvas.dataset.animationState = 'paused';
    };

    lifecycle.addCleanup(stop);
    const fail = lifecycle.fail;

    const updateQuality = () => {
      const p95 = percentile95(frameTimes);
      frameTimes.length = 0;
      canvas.dataset.p95FrameMs = p95.toFixed(2);
      const nextQuality = nextScrollWorldQuality(quality, p95);
      if (nextQuality.dpr !== quality.dpr || nextQuality.emberCount !== quality.emberCount) {
        quality = nextQuality;
        resize();
      }
    };

    const draw = (time: number) => {
      animationFrame = null;
      if (lifecycle.isDisposed() || !visible || !intersecting) return;

      if (lastFrameTime !== null) {
        frameTimes.push(Math.min(100, time - lastFrameTime));
        if (frameTimes.length >= FRAME_SAMPLE_SIZE) updateQuality();
      }
      const deltaSeconds = Math.min(0.05, Math.max(0, (time - (lastFrameTime ?? time)) / 1_000));
      lastFrameTime = time;

      const state = interpolateChapterState(currentProgress());
      desiredPosition.set(...state.position);
      desiredTarget.set(...state.target);
      const damping = 1 - Math.exp(-deltaSeconds * 4.8);
      smoothPosition.lerp(desiredPosition, damping);
      smoothTarget.lerp(desiredTarget, damping);
      camera.position.copy(smoothPosition);
      camera.lookAt(smoothTarget);
      camera.fov += (state.fov - camera.fov) * damping;
      camera.updateProjectionMatrix();

      fog.density += (state.fog - fog.density) * damping;
      keyLight.intensity = 0.55 + state.key * 0.65;
      keyLight.color.lerpColors(emerald, horizon, state.key);
      rimLight.intensity = 1.6 + state.key * 1.2;
      orbitMaterial.opacity = 0.2 + state.key * 0.18;
      const chapterEmbers = Math.min(quality.emberCount, Math.max(20, Math.round(state.embers * 0.6)));
      emberGeometry.setDrawRange(0, chapterEmbers);

      const positionAttribute = emberGeometry.getAttribute('position') as THREE.BufferAttribute;
      const positions = positionAttribute.array as Float32Array;
      for (let index = 0; index < quality.emberCount; index += 1) {
        const offset = index * 3;
        positions[offset] += emberVelocities[offset];
        positions[offset + 1] += emberVelocities[offset + 1];
        positions[offset + 2] += emberVelocities[offset + 2];
        if (positions[offset + 1] > 7) positions[offset + 1] = 0.15;
      }
      positionAttribute.needsUpdate = true;

      flint.rotation.y += deltaSeconds * 0.08;
      spark.rotation.y -= deltaSeconds * 0.35;
      orbit.rotation.z += deltaSeconds * 0.025;
      seal.rotation.z -= deltaSeconds * 0.018;

      try {
        renderer.render(scene, camera);
      } catch {
        fail('render-error');
        return;
      }

      canvas.dataset.drawCalls = String(renderer.info.render.calls);
      canvas.dataset.triangles = String(renderer.info.render.triangles);
      canvas.dataset.chapter = String(Math.round(currentProgress()));
      if (!ready) {
        ready = true;
        onReady();
      }
      animationFrame = requestAnimationFrame(draw);
      canvas.dataset.animationState = 'running';
    };

    const start = () => {
      if (lifecycle.isDisposed() || animationFrame !== null || !visible || !intersecting) return;
      lastFrameTime = null;
      animationFrame = requestAnimationFrame(draw);
      canvas.dataset.animationState = 'running';
    };

    const onResize = () => {
      if (!measureChapters()) {
        fail('missing-chapters');
        return;
      }
      resize();
    };
    const onVisibilityChange = () => {
      visible = !document.hidden;
      if (visible) start();
      else stop();
    };
    const onMotionChange = (event: MediaQueryListEvent) => {
      if (event.matches) fail('reduced-motion');
    };
    const onContextLost = lifecycle.onContextLost;

    if (!measureChapters()) {
      fail('missing-chapters');
      return lifecycle.dispose;
    }
    resize();
    applyExactStoryState();

    lifecycle.addCleanup(() => {
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      motionQuery.removeEventListener('change', onMotionChange);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      intersectionObserver?.disconnect();
    });
    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibilityChange);
    motionQuery.addEventListener('change', onMotionChange);
    canvas.addEventListener('webglcontextlost', onContextLost);

    if (typeof IntersectionObserver === 'function') {
      intersectionObserver = new IntersectionObserver(([entry]) => {
        intersecting = entry?.isIntersecting ?? true;
        if (intersecting) start();
        else stop();
      });
      intersectionObserver.observe(canvas);
    }

    void document.fonts?.ready.then(() => {
      if (!lifecycle.isDisposed() && measureChapters()) resize();
    });
    start();
    setupComplete = true;

    return lifecycle.dispose;
    } catch {
      lifecycle.fail(setupFailureReason);
      return lifecycle.dispose;
    } finally {
      if (!setupComplete) lifecycle.dispose();
    }
  }, [onFallback, onReady]);

  return (
    <canvas
      ref={canvasRef}
      className="site-scroll-world-canvas"
      aria-hidden="true"
      role="presentation"
    />
  );
}
