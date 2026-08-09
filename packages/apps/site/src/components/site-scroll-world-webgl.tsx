'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { chapters, progressFromScroll, ChapterSpec } from '@/lib/site-scroll-world-chapters';

/**
 * Spark Path WebGL — original FlintTrade restrained 3D enrichment.
 * One persistent scene, native scroll conductor, graceful fallback.
 * Procedural geometry only (no remote textures/fonts).
 * DPR capped, context-loss handled, visibility/reduced-motion respected.
 * Abstract market/data/risk geometry (workspace plates, safety arches, risk horizon).
 * Enriches Graphite bands; does not replace DOM or CTA.
 * TDD: implements the capability policy.
 */

export default function SiteScrollWorldWebGL() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rafRef = useRef<number | null>(null);
  const targetPos = useRef(new THREE.Vector3());
  const targetLook = useRef(new THREE.Vector3());
  const smoothPos = useRef(new THREE.Vector3());
  const smoothLook = useRef(new THREE.Vector3());
  const isPaused = useRef(false);
  const sectionTops = useRef<number[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Capability re-check (defensive)
    if (typeof window === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(dpr);
    renderer.setSize(canvas.offsetWidth, canvas.offsetHeight, false);
    renderer.shadowMap.enabled = false; // pilot budget
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x0a0a0f, 0.015);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(55, canvas.offsetWidth / canvas.offsetHeight, 0.1, 100);
    cameraRef.current = camera;

    // Lighting (restrained, practical)
    const hemi = new THREE.HemisphereLight(0x1a1a2e, 0x0a0a0f, 0.6);
    scene.add(hemi);
    const dir = new THREE.DirectionalLight(0x22c55e, 0.4);
    dir.position.set(5, 10, 3);
    scene.add(dir);

    // === Flint facet (angular Box, emissive emerald spark core) ===
    const facetGeo = new THREE.BoxGeometry(1.2, 1.8, 0.6);
    const facetMat = new THREE.MeshStandardMaterial({
      color: 0x111114,
      roughness: 0.85,
      metalness: 0.15,
      emissive: 0x0a2a12,
      emissiveIntensity: 0.3,
    });
    const facet = new THREE.Mesh(facetGeo, facetMat);
    facet.position.set(0, 0.8, 0);
    scene.add(facet);

    // Emerald spark (small emissive sphere + points)
    const sparkGeo = new THREE.SphereGeometry(0.12, 8, 8);
    const sparkMat = new THREE.MeshStandardMaterial({
      color: 0x22c55e,
      emissive: 0x22c55e,
      emissiveIntensity: 0.8,
      roughness: 0.4,
    });
    const spark = new THREE.Mesh(sparkGeo, sparkMat);
    spark.position.set(0.1, 1.6, 0.2);
    scene.add(spark);

    // === Safety arches (3 instanced simple frames for Explore/Practice/Live) ===
    const archGeo = new THREE.BoxGeometry(2.2, 2.8, 0.15);
    const archMat = new THREE.MeshStandardMaterial({
      color: 0x1f2937,
      roughness: 0.9,
      metalness: 0.1,
      emissive: 0x15803d,
      emissiveIntensity: 0.15,
    });
    const arches: THREE.Mesh[] = [];
    for (let i = 0; i < 3; i++) {
      const arch = new THREE.Mesh(archGeo, archMat);
      arch.position.set(-2.5 + i * 2.5, 1.4, -3 - i * 1.5);
      arch.rotation.y = (i - 1) * 0.2;
      scene.add(arch);
      arches.push(arch);
    }

    // === Workspace plates (abstract market/data/risk geometry — thin boxes, no numbers) ===
    const plateGeo = new THREE.BoxGeometry(1.8, 0.08, 1.4);
    const plateMat = new THREE.MeshStandardMaterial({
      color: 0x1f2937,
      roughness: 0.95,
      metalness: 0.05,
    });
    const plates: THREE.Mesh[] = [];
    for (let i = 0; i < 4; i++) {
      const plate = new THREE.Mesh(plateGeo, plateMat);
      plate.position.set(-1.5 + (i % 2) * 3, 0.3 + Math.floor(i / 2) * 0.6, -1 - i * 0.8);
      plate.rotation.x = 0.1;
      scene.add(plate);
      plates.push(plate);
    }

    // Risk horizon line (abstract risk geometry)
    const riskGeo = new THREE.BoxGeometry(6, 0.05, 0.05);
    const riskMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, emissive: 0x1e40af, emissiveIntensity: 0.2 });
    const riskLine = new THREE.Mesh(riskGeo, riskMat);
    riskLine.position.set(0, 0.2, -7);
    scene.add(riskLine);

    // === Horizon desk (abstract evaluate/install pedestal) ===
    const deskGeo = new THREE.BoxGeometry(3.5, 0.2, 2);
    const deskMat = new THREE.MeshStandardMaterial({ color: 0x111114, roughness: 0.8 });
    const desk = new THREE.Mesh(deskGeo, deskMat);
    desk.position.set(0, 0.1, -6);
    scene.add(desk);

    // === Embers (procedural point sprites, low energy drift) ===
    const emberCount = 180;
    const emberGeo = new THREE.BufferGeometry();
    const emberPos = new Float32Array(emberCount * 3);
    const emberVel: { x: number; y: number; z: number }[] = [];
    for (let i = 0; i < emberCount; i++) {
      emberPos[i * 3] = (Math.random() - 0.5) * 12;
      emberPos[i * 3 + 1] = Math.random() * 6 + 0.2;
      emberPos[i * 3 + 2] = (Math.random() - 0.5) * 10 - 2;
      emberVel.push({
        x: (Math.random() - 0.5) * 0.008,
        y: (Math.random() - 0.5) * 0.004,
        z: (Math.random() - 0.5) * 0.006,
      });
    }
    emberGeo.setAttribute('position', new THREE.BufferAttribute(emberPos, 3));
    const emberMat = new THREE.PointsMaterial({
      color: 0x22c55e,
      size: 0.035,
      transparent: true,
      opacity: 0.6,
      depthWrite: false,
    });
    const embers = new THREE.Points(emberGeo, emberMat);
    scene.add(embers);

    // Initial camera
    camera.position.set(0, 1.5, 8);
    camera.lookAt(0, 0.5, 0);
    smoothPos.current.copy(camera.position);
    smoothLook.current.copy(camera.position).add(new THREE.Vector3(0, 0, -1));

    // Resize handler
    const onResize = () => {
      if (!canvas || !renderer || !camera) return;
      const w = canvas.offsetWidth;
      const h = canvas.offsetHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    window.addEventListener('resize', onResize);

    // Scroll conductor — measure section tops once settled
    const measureSections = () => {
      const tops: number[] = [];
      chapters.forEach((ch) => {
        const el = document.querySelector(`[data-scroll-chapter="${ch.id}"]`) as HTMLElement | null;
        if (el) tops.push(el.getBoundingClientRect().top + window.scrollY);
      });
      sectionTops.current = tops.length ? tops : [0, 1000, 2000, 3000, 4000, 5000];
    };
    // Delay measure for layout
    setTimeout(measureSections, 800);
    window.addEventListener('resize', measureSections);

    // Visibility / pause
    const onVisibility = () => {
      isPaused.current = document.hidden;
    };
    document.addEventListener('visibilitychange', onVisibility);

    // Context loss handler (WebGL failure path)
    const onContextLost = (event: Event) => {
      event.preventDefault();
      try {
        sessionStorage.setItem('ft-site-scroll-world-failed', '1');
      } catch {}
      // Trigger fallback by unmounting (parent will see via re-render or flag)
      if (rendererRef.current) {
        rendererRef.current.dispose();
      }
      // Dispatch for hero-cinematic resume
      window.dispatchEvent(new CustomEvent('ft-scroll-world-fallback'));
    };
    canvas.addEventListener('webglcontextlost', onContextLost as EventListener, false);

    // Animation loop with lerp and ember drift
    const animate = () => {
      if (isPaused.current || !renderer || !scene || !camera) {
        rafRef.current = requestAnimationFrame(animate);
        return;
      }

      // Scroll progress
      const scrollY = window.scrollY;
      const progress = progressFromScroll(scrollY, sectionTops.current);
      const idx = Math.floor(progress);
      const frac = progress - idx;
      const chA = chapters[Math.min(idx, chapters.length - 1)];
      const chB = chapters[Math.min(idx + 1, chapters.length - 1)];

      // Target from chapter lerp
      const t = frac;
      targetPos.current.set(
        chA.camera.position[0] * (1 - t) + chB.camera.position[0] * t,
        chA.camera.position[1] * (1 - t) + chB.camera.position[1] * t,
        chA.camera.position[2] * (1 - t) + chB.camera.position[2] * t
      );
      targetLook.current.set(
        chA.camera.target[0] * (1 - t) + chB.camera.target[0] * t,
        chA.camera.target[1] * (1 - t) + chB.camera.target[1] * t,
        chA.camera.target[2] * (1 - t) + chB.camera.target[2] * t
      );

      // Restrained damping (smooth = target under reduced, but already gated)
      const lerpFactor = 0.04;
      smoothPos.current.lerp(targetPos.current, lerpFactor);
      smoothLook.current.lerp(targetLook.current, lerpFactor);

      camera.position.copy(smoothPos.current);
      camera.lookAt(smoothLook.current);

      // Ember drift (low energy ambient)
      const posAttr = emberGeo.attributes.position as THREE.BufferAttribute;
      const posArr = posAttr.array as Float32Array;
      for (let i = 0; i < emberCount; i++) {
        const base = i * 3;
        posArr[base] += emberVel[i].x;
        posArr[base + 1] += emberVel[i].y;
        posArr[base + 2] += emberVel[i].z;
        // Gentle bounds wrap
        if (posArr[base + 1] > 7) posArr[base + 1] = 0.3;
        if (Math.abs(posArr[base]) > 7) posArr[base] = (Math.random() - 0.5) * 10;
      }
      posAttr.needsUpdate = true;

      // Subtle facet rotation for depth
      facet.rotation.y = Math.sin(Date.now() * 0.0002) * 0.08;

      renderer.render(scene, camera);
      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);

    // First frame success → pause HeroCinematic Canvas2D (via class on html)
    setTimeout(() => {
      document.documentElement.classList.add('ft-scroll-world-on');
    }, 300);

    // Cleanup
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('resize', measureSections);
      document.removeEventListener('visibilitychange', onVisibility);
      canvas.removeEventListener('webglcontextlost', onContextLost as EventListener);
      // Full dispose
      emberGeo.dispose();
      emberMat.dispose();
      facetGeo.dispose();
      facetMat.dispose();
      sparkGeo.dispose();
      sparkMat.dispose();
      archGeo.dispose();
      archMat.dispose();
      plateGeo.dispose();
      plateMat.dispose();
      deskGeo.dispose();
      deskMat.dispose();
      riskGeo.dispose();
      riskMat.dispose();
      if (renderer) {
        renderer.dispose();
        const gl = renderer.getContext();
        if (gl) gl.getExtension('WEBGL_lose_context')?.loseContext();
      }
      // Resume Graphite baseline
      document.documentElement.classList.remove('ft-scroll-world-on');
      document.documentElement.classList.add('ft-scroll-world-fallback');
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="site-scroll-world-canvas"
      aria-hidden="true"
      role="presentation"
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  );
}
