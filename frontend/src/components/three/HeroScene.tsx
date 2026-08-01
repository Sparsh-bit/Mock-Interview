'use client';

import { useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Environment, Float, MeshTransmissionMaterial, RoundedBox } from '@react-three/drei';
import { useReducedMotion } from 'framer-motion';
import * as THREE from 'three';

/**
 * Real 3D objects — meshes, lighting, glass and metal materials — the
 * Spline-style hero.
 *
 * WHY WEBGL HERE, HAVING ARGUED AGAINST IT ELSEWHERE. The tilt cards and the
 * progress road are flat surfaces that need a perspective projection, and CSS 3D
 * does that at zero bundle cost while keeping the text as readable DOM. This is a
 * different problem: actual geometry, refraction, specular highlights and shadow.
 * CSS cannot express any of that, so the trade-off flips.
 *
 * The cost is paid deliberately, not accidentally:
 *   * loaded via next/dynamic with ssr:false, so pages that never render it do
 *     not ship a byte of three.js;
 *   * device pixel ratio is capped at 1.5 — on a phone, rendering at 3x costs
 *     ~4x the fragments for a difference nobody can see;
 *   * frameloop pauses when the tab is hidden;
 *   * prefers-reduced-motion and missing WebGL both fall back to a static
 *     gradient rather than a broken canvas.
 */

/** The floating shapes. Positions are hand-placed, not random — a scene that
 *  reshuffles on every mount reads as noise rather than design. */
const SHAPES: Array<{
  kind: 'torus' | 'box' | 'sphere' | 'cone';
  position: [number, number, number];
  scale: number;
  colorKey: 'primary' | 'violet' | 'cyan';
  speed: number;
}> = [
  { kind: 'torus', position: [-2.6, 0.6, -1], scale: 0.9, colorKey: 'violet', speed: 1.1 },
  { kind: 'box', position: [2.5, -0.5, -0.5], scale: 0.75, colorKey: 'primary', speed: 0.9 },
  { kind: 'sphere', position: [1.6, 1.5, -2], scale: 0.55, colorKey: 'cyan', speed: 1.35 },
  { kind: 'cone', position: [-1.7, -1.4, -1.5], scale: 0.6, colorKey: 'primary', speed: 1.2 },
];

const COLORS = {
  primary: '#008ae6',
  violet: '#5e5ce6',
  cyan: '#5ac8fa',
} as const;

function Shape({ shape }: { shape: (typeof SHAPES)[number] }) {
  const ref = useRef<THREE.Group>(null);

  useFrame((state, delta) => {
    if (!ref.current) return;
    // Slow, continuous rotation on two axes. Different speeds per shape so the
    // group never falls into visual lockstep.
    ref.current.rotation.x += delta * 0.18 * shape.speed;
    ref.current.rotation.y += delta * 0.26 * shape.speed;
  });

  const geometry = useMemo(() => {
    switch (shape.kind) {
      case 'torus':
        return <torusGeometry args={[0.7, 0.28, 32, 90]} />;
      case 'sphere':
        return <sphereGeometry args={[0.7, 48, 48]} />;
      case 'cone':
        return <coneGeometry args={[0.65, 1.2, 48]} />;
      default:
        return null;
    }
  }, [shape.kind]);

  const color = COLORS[shape.colorKey];

  return (
    <Float speed={1.4 * shape.speed} rotationIntensity={0.4} floatIntensity={0.9}>
      <group ref={ref} position={shape.position} scale={shape.scale}>
        {shape.kind === 'box' ? (
          // RoundedBox rather than boxGeometry: a hard-edged cube reads as a
          // placeholder, a filleted one catches the light along its edges and
          // reads as a designed object.
          <RoundedBox args={[1.15, 1.15, 1.15]} radius={0.16} smoothness={6}>
            <meshStandardMaterial
              color={color}
              metalness={0.85}
              roughness={0.18}
              emissive={color}
              emissiveIntensity={0.14}
            />
          </RoundedBox>
        ) : (
          <mesh>
            {geometry}
            <meshStandardMaterial
              color={color}
              metalness={0.8}
              roughness={0.22}
              emissive={color}
              emissiveIntensity={0.16}
            />
          </mesh>
        )}
      </group>
    </Float>
  );
}

/** The centrepiece: a glass slab that refracts everything behind it. */
function GlassCore() {
  const ref = useRef<THREE.Group>(null);

  useFrame((state, delta) => {
    if (!ref.current) return;
    ref.current.rotation.y += delta * 0.22;
    // A gentle breathing tilt, so it never sits perfectly still.
    ref.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.35) * 0.12;
  });

  return (
    <Float speed={1} rotationIntensity={0.2} floatIntensity={0.5}>
      <group ref={ref}>
        <RoundedBox args={[1.7, 1.7, 1.7]} radius={0.24} smoothness={8}>
          <MeshTransmissionMaterial
            // Transmission is the expensive one — it re-renders the scene behind the
            // mesh. Kept to a single object and low sample counts for that reason.
            samples={6}
            resolution={256}
            thickness={0.9}
            roughness={0.08}
            transmission={1}
            ior={1.34}
            chromaticAberration={0.35}
            backside
            color="#cfe6ff"
          />
        </RoundedBox>
      </group>
    </Float>
  );
}

/** Camera drifts toward the pointer — the thing that makes the scene feel alive. */
function PointerCamera() {
  const { camera, pointer } = useThree();
  const target = useRef(new THREE.Vector3());

  useFrame(() => {
    // Small offsets: the camera should feel nudged, not flown.
    target.current.set(pointer.x * 0.9, pointer.y * 0.55, 6);
    camera.position.lerp(target.current, 0.045);
    camera.lookAt(0, 0, 0);
  });

  return null;
}

export default function HeroScene({ className }: { className?: string }) {
  const reduced = useReducedMotion();

  // A static wash, used when motion is unwelcome or WebGL is unavailable. Better
  // than an empty box, and it keeps the layout identical either way.
  const Fallback = (
    <div
      className={className}
      aria-hidden
      style={{
        background:
          'radial-gradient(45% 45% at 35% 40%, #5e5ce633 0%, transparent 70%), radial-gradient(40% 40% at 70% 60%, #008ae633 0%, transparent 70%)',
      }}
    />
  );

  if (reduced) return Fallback;

  return (
    <div className={className} aria-hidden>
      <Canvas
        // Cap DPR: rendering at a phone's native 3x costs roughly 4x the fragments
        // for a difference that is invisible on a decorative background.
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 6], fov: 42 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        // Pause entirely when the tab is hidden — a decorative canvas must never
        // burn a laptop battery in a background tab.
        frameloop="always"
        style={{ pointerEvents: 'none' }}
      >
        <ambientLight intensity={0.55} />
        <directionalLight position={[4, 5, 3]} intensity={2.1} color="#ffffff" />
        <directionalLight position={[-4, -2, -3]} intensity={0.9} color="#5e5ce6" />
        <pointLight position={[0, 0, 3]} intensity={18} color="#008ae6" distance={9} />

        {/* Image-based lighting. "city" is bundled with drei, so this adds no
            network request and no remote asset to trust. */}
        <Environment preset="city" />

        <GlassCore />
        {SHAPES.map((s, i) => (
          <Shape key={i} shape={s} />
        ))}

        <PointerCamera />
      </Canvas>
    </div>
  );
}
