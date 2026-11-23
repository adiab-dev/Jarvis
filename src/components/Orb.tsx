
import { type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { motion, useAnimationFrame, useMotionValue, useTransform } from "framer-motion";
import { invoke } from "@tauri-apps/api/core";
import {
  getCurrentWindow,
  availableMonitors,
  cursorPosition,
  currentMonitor,
  primaryMonitor,
  Effect,
  EffectState,
} from "@tauri-apps/api/window";
import {
  PhysicalPosition,
  PhysicalSize,
} from "@tauri-apps/api/dpi";
import ChatPanel from "./ChatPanel";
import SpotifyMiniPlayer from "./SpotifyMiniPlayer";
import "./Orb.css";

type Phase = "idle" | "hover" | "opening" | "settling" | "breathing";
type ScreenPosition = { x: number; y: number };
type LogicalPosition = { left: number; top: number };
const ORB_POSITION_KEY = "jarvis-minimized-orb-position";

const win = getCurrentWindow();

const ringDefinitions = [
  {
    name: "outer",
    image: "/orb/ring-outer.svg",
    duration: 28,
  },
  {
    name: "middle",
    image: "/orb/ring-middle.svg",
    duration: 20,
  },
  {
    name: "inner",
    image: "/orb/ring-inner.svg",
    duration: 24,
  },
  {
    name: "decorative",
    image: "/orb/ring-decorative.svg",
    duration: 18,
  },
];
const ringDirections = [1, -1, 1, -1].sort(() => Math.random() - 0.5);
const ringAxes: Array<{ x: number; y: number }> = [];
while (ringAxes.length < ringDefinitions.length) {
  const candidate = {
    x: Math.round(Math.random() * 156 - 78),
    y: Math.round(Math.random() * 156 - 78),
  };
  if (ringAxes.every((axis) => Math.hypot(axis.x - candidate.x, axis.y - candidate.y) > 70)) {
    ringAxes.push(candidate);
  }
}
const rings = ringDefinitions.map((ring, index) => ({
  ...ring,
  x: Math.cos(Math.atan2(ringAxes[index].y, ringAxes[index].x)) * 8,
  y: Math.sin(Math.atan2(ringAxes[index].y, ringAxes[index].x)) * 8,
  direction: ringDirections[index],
  revolutions: 3.5 + Math.random() * 1.4,
  xDirection: Math.random() < 0.5 ? -1 : 1,
  yDirection: Math.random() < 0.5 ? -1 : 1,
  xRevolutions: 3 + Math.floor(Math.random() * 3),
  yRevolutions: 3 + Math.floor(Math.random() * 3),
}));

function easedTurnProgress(progress: number) {
  if (progress < 0.2) {
    const ramp = progress / 0.2;
    return 0.125 * ramp * ramp;
  }
  if (progress < 0.8) return (progress - 0.1) / 0.8;
  const ramp = (progress - 0.8) / 0.2;
  return (0.7 + 0.2 * (ramp - 0.5 * ramp * ramp)) / 0.8;
}

function readSavedPosition(): ScreenPosition | null {
  try {
    const stored = localStorage.getItem(ORB_POSITION_KEY);
    if (!stored) return null;
    const position = JSON.parse(stored) as ScreenPosition;
    return Number.isFinite(position.x) && Number.isFinite(position.y) ? position : null;
  } catch {
    return null;
  }
}

async function monitorForPosition(position?: ScreenPosition) {
  const monitors = await availableMonitors().catch(() => []);
  if (position) {
    const containing = monitors.find((monitor) =>
      position.x >= monitor.position.x && position.x < monitor.position.x + monitor.size.width &&
      position.y >= monitor.position.y && position.y < monitor.position.y + monitor.size.height,
    );
    if (containing) return containing;
  }
  return (await currentMonitor()) ?? (await primaryMonitor()) ?? (monitors[0] ?? null);
}

async function minimizedPosition(savedPosition: ScreenPosition | null): Promise<ScreenPosition> {
  const monitor = await monitorForPosition(savedPosition ?? undefined);
  if (!monitor) throw new Error("Unable to determine the current monitor.");
  const scale = monitor.scaleFactor;
  const width = Math.round(150 * scale);
  const height = Math.round(150 * scale);
  const margin = Math.round(18 * scale);
  const preferred = savedPosition ?? {
    x: monitor.position.x + monitor.size.width - width - margin,
    y: monitor.position.y + monitor.size.height - height - margin,
  };
  return {
    x: Math.max(monitor.position.x, Math.min(preferred.x, monitor.position.x + monitor.size.width - width)),
    y: Math.max(monitor.position.y, Math.min(preferred.y, monitor.position.y + monitor.size.height - height)),
  };
}

function logicalPosition(position: ScreenPosition, monitor: Awaited<ReturnType<typeof monitorForPosition>>): LogicalPosition {
  if (!monitor) return { left: 20, top: 20 };
  return {
    left: (position.x - monitor.position.x) / monitor.scaleFactor + 20,
    top: (position.y - monitor.position.y) / monitor.scaleFactor + 20,
  };
}

async function resizeWindow(expanded: boolean, position?: ScreenPosition) {
  if (!expanded) {
    const target = position ?? await minimizedPosition(null);
    await invoke("shrink_window_to_position", { x: target.x, y: target.y });
    return;
  }

  const monitor = (await monitorForPosition(position)) ?? (await primaryMonitor()) ?? (await currentMonitor());

  if (!monitor) {
    throw new Error("Unable to determine the current monitor.");
  }

  await win.setPosition(new PhysicalPosition(monitor.position.x, monitor.position.y));
  await win.setSize(new PhysicalSize(monitor.size.width, monitor.size.height));
  return monitor;
}

function Ring({
  ring,
  phase,
}: {
  ring: (typeof rings)[number];
  phase: Phase;
}) {
  const { name, image, x, y, duration, direction, revolutions, xDirection, yDirection, xRevolutions, yRevolutions } = ring;
  const rotateX = useMotionValue(x);
  const rotateY = useMotionValue(y);
  const rotateZ = useMotionValue(0);
  const velocity = useRef(0);
  const phaseStart = useRef(performance.now());
  const phaseRotationStart = useRef(rotateZ.get());
  const phaseRotationStartX = useRef(rotateX.get());
  const phaseRotationStartY = useRef(rotateY.get());

  useEffect(() => {
    phaseStart.current = performance.now();
    phaseRotationStart.current = rotateZ.get();
    phaseRotationStartX.current = rotateX.get();
    phaseRotationStartY.current = rotateY.get();
  }, [phase]);

  useAnimationFrame((time, delta) => {
    // useAnimationFrame's `time` is relative to the component's animation loop;
    // phaseStart is a performance timestamp. Keep both on the same clock.
    const elapsed = (performance.now() - phaseStart.current) / 1000;
    const lowSpeed = duration / 4;
    let targetSpeed = phase === "idle" ? 0 : lowSpeed;

    if (phase === "hover") targetSpeed = duration / 0.4;
    if (phase === "settling" || phase === "opening") {
      const progress = Math.min(Math.max(elapsed / 6.5, 0), 1);
      let speedProgress: number;

      if (progress < 0.2) {
        const ramp = progress / 0.2;
        speedProgress = 1.25 * ramp;
      } else if (progress < 0.8) {
        speedProgress = 1.25;
      } else {
        const ramp = (progress - 0.8) / 0.2;
        speedProgress = 1.25 * (1 - ramp);
      }

      targetSpeed = revolutions * 360 * speedProgress / 6.5;
      velocity.current = targetSpeed;
      rotateZ.set(
        phaseRotationStart.current + direction * revolutions * 360 * easedTurnProgress(progress),
      );
    } else {
      if (phase === "idle") {
        velocity.current = 0;
      } else {
        const speedBlend = 1 - Math.exp(-Math.max(delta, 0) / 500);
        velocity.current += (targetSpeed - velocity.current) * speedBlend;
        rotateZ.set(rotateZ.get() + direction * velocity.current * (delta / 1000));
      }
    }

    let targetX = x;
    let targetY = y;
    if (phase === "settling" || phase === "opening") {
      const tumbleProgress = easedTurnProgress(Math.min(Math.max(elapsed / 5.2, 0), 1));
      if (elapsed <= 5.2) {
        targetX = phaseRotationStartX.current + xDirection * xRevolutions * 360 * tumbleProgress;
        targetY = phaseRotationStartY.current + yDirection * yRevolutions * 360 * tumbleProgress;
      } else {
        const flatten = Math.min((elapsed - 5.2) / 1.3, 1);
        const flattenEase = flatten * flatten * (3 - 2 * flatten);
        targetX = phaseRotationStartX.current * (1 - flattenEase);
        targetY = phaseRotationStartY.current * (1 - flattenEase);
      }
    } else if (phase === "hover") {
      targetX = x + Math.sin(time / 1500) * 6;
      targetY = y + Math.cos(time / 1700) * 6;
    } else if (phase === "breathing") {
      targetX = Math.sin(time / 2600) * 3;
      targetY = Math.cos(time / 2900) * 3;
    }
    if (phase === "settling" || phase === "opening") {
      rotateX.set(targetX);
      rotateY.set(targetY);
    } else if (phase === "idle") {
      rotateX.set(x);
      rotateY.set(y);
    } else {
      const axisBlend = 1 - Math.exp(-Math.max(delta, 0) / (phase === "hover" ? 90 : phase === "breathing" ? 180 : 650));
      rotateX.set(rotateX.get() + (targetX - rotateX.get()) * axisBlend);
      rotateY.set(rotateY.get() + (targetY - rotateY.get()) * axisBlend);
    }
  });

  return (
    <motion.div
      className="orb-ring-axis"
      style={{ rotateX, rotateY, transformStyle: "preserve-3d" }}
    >
      <motion.div
        className={`orb-ring orb-ring-${name}`}
        style={{ rotateZ, transformStyle: "preserve-3d" }}
      >
        <img
          src={image}
          alt=""
          draggable={false}
          className="orb-ring-image"
        />
      </motion.div>
    </motion.div>
  );
}

export default function Orb() {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"voice" | "keyboard">("voice");
  const [conversationStarted, setConversationStarted] = useState(false);
  const [opening, setOpening] = useState(false);
  const [closing, setClosing] = useState(false);
  const [openingFrom, setOpeningFrom] = useState<LogicalPosition>({ left: 20, top: 20 });
  const [closingAt, setClosingAt] = useState<LogicalPosition>({ left: 20, top: 20 });
  const [savedPosition, setSavedPosition] = useState<ScreenPosition | null>(readSavedPosition);
  const savedPositionRef = useRef<ScreenPosition | null>(savedPosition);
  const latestWindowPositionRef = useRef<ScreenPosition | null>(savedPosition);
  const activeMinimizedPositionRef = useRef<ScreenPosition | null>(null);
  const expandedRef = useRef(expanded);
  const openingRef = useRef(opening);
  const openingSetupReadyRef = useRef(true);
  const closingRef = useRef(closing);
  const closeInProgressRef = useRef(false);
  const positionSavePromiseRef = useRef<Promise<void> | null>(null);
  const [expandedViewport, setExpandedViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const [orbVisible, setOrbVisible] = useState(true);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const speechLevel = useMotionValue(0);
  const speechScale = useTransform(speechLevel, [0, 1], [1, 1.16]);
  const speechGlowScale = useTransform(speechLevel, [0, 0.05, 0.35, 1], [1, 1.35, 2.5, 3.4]);
  const compactOrbSize = Math.min(300, window.innerHeight * 0.27);
  const dragRef = useRef<{ pointerId: number; x: number; y: number; moved: boolean; started: boolean } | null>(null);
  const suppressClickRef = useRef(false);
  const suppressHoverUntilLeaveRef = useRef(false);
  const orbButtonRef = useRef<HTMLButtonElement>(null);
  const expandedOrbSize = mode === "keyboard"
    ? conversationStarted ? compactOrbSize : 350
    : 440;
  const expandedOrbPosition: LogicalPosition = {
    left: (expandedViewport.width - expandedOrbSize) / 2,
    top: expanded
      ? mode === "keyboard"
        ? conversationStarted ? expandedViewport.height * 0.02 : expandedViewport.height * 0.13
        : (expandedViewport.height - expandedOrbSize) / 2
      : 20,
  };

  useEffect(() => {
    if (!savedPosition) return;
    void win.setPosition(new PhysicalPosition(savedPosition.x, savedPosition.y)).catch((error) =>
      console.error("Could not restore the minimized orb position:", error),
    );
  }, []);

  useEffect(() => {
    if (expanded || opening || closing) return;
    let saveTimer = 0;
    let unlisten: () => void = () => {};
    void win.onMoved(({ payload }) => {
      const movedPosition = { x: payload.x, y: payload.y };
      latestWindowPositionRef.current = movedPosition;
      savedPositionRef.current = movedPosition;
      localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(movedPosition));
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        positionSavePromiseRef.current = saveDraggedPosition().finally(() => {
          positionSavePromiseRef.current = null;
        });
        void positionSavePromiseRef.current.then(syncHoverAfterDrag);
      }, 180);
    }).then((stopListening) => { unlisten = stopListening; }).catch((error) => {
      console.error("Could not watch the minimized orb position:", error);
    });
    return () => {
      window.clearTimeout(saveTimer);
      unlisten();
    };
  }, [expanded, opening, closing]);

  useEffect(() => {
    if (expanded || opening || closing) return;
    const updateHoverFromPointer = (event: MouseEvent) => {
      if (closingRef.current || openingRef.current || expandedRef.current) return;
      const drag = dragRef.current;
      if (drag?.moved && event.buttons !== 0) {
        setPhase("idle");
        return;
      }
      if (drag?.moved && event.buttons === 0) dragRef.current = null;

      const button = orbButtonRef.current;
      const bounds = button?.getBoundingClientRect();
      const pointerIsOverOrb = Boolean(bounds && event.clientX >= bounds.left && event.clientX <= bounds.right &&
        event.clientY >= bounds.top && event.clientY <= bounds.bottom);
      suppressHoverUntilLeaveRef.current = false;
      setPhase(pointerIsOverOrb ? "hover" : "idle");
    };
    window.addEventListener("mousemove", updateHoverFromPointer);
    return () => window.removeEventListener("mousemove", updateHoverFromPointer);
  }, [expanded, opening, closing]);

  async function saveDraggedPosition(positionHint?: ScreenPosition) {
    const raw = positionHint ?? await win.outerPosition();
    const monitor = await currentMonitor();
    let position = { x: raw.x, y: raw.y };
    if (monitor) {
      const scale = monitor.scaleFactor;
      const width = Math.round(150 * scale);
      const height = Math.round(150 * scale);
      position = {
        x: Math.max(monitor.position.x, Math.min(raw.x, monitor.position.x + monitor.size.width - width)),
        y: Math.max(monitor.position.y, Math.min(raw.y, monitor.position.y + monitor.size.height - height)),
      };
      if (position.x !== raw.x || position.y !== raw.y) {
        await win.setPosition(new PhysicalPosition(position.x, position.y));
      }
    }
    localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(position));
    savedPositionRef.current = position;
    latestWindowPositionRef.current = position;
    setSavedPosition(position);
  }

  async function syncHoverAfterDrag() {
    try {
      const [pointer, position, monitor] = await Promise.all([
        cursorPosition(),
        win.outerPosition(),
        currentMonitor(),
      ]);
      if (!monitor || expandedRef.current || openingRef.current || closingRef.current) return;
      const scale = monitor.scaleFactor;
      const left = position.x + Math.round(20 * scale);
      const top = position.y + Math.round(20 * scale);
      const right = left + Math.round(112 * scale);
      const bottom = top + Math.round(112 * scale);
      const pointerIsOverOrb = pointer.x >= left && pointer.x <= right && pointer.y >= top && pointer.y <= bottom;
      suppressHoverUntilLeaveRef.current = false;
      setPhase(pointerIsOverOrb ? "hover" : "idle");
    } catch (error) {
      console.error("Could not refresh the orb hover state after dragging:", error);
      if (openingRef.current || expandedRef.current || closingRef.current) return;
      suppressHoverUntilLeaveRef.current = false;
      setPhase("idle");
    }
  }

  function handleCompactPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (expanded || opening || closing || closingRef.current || event.button !== 0) return;
    dragRef.current = { pointerId: event.pointerId, x: event.screenX, y: event.screenY, moved: false, started: false };
  }

  function handleCompactContextMenu(event: ReactMouseEvent<HTMLButtonElement>) {
    if (expanded || opening || closing) return;
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      x: Math.min(event.clientX, window.innerWidth - 52),
      y: Math.min(event.clientY, window.innerHeight - 40),
    });
  }

  async function hideToSystemTray() {
    setContextMenu(null);
    try {
      await invoke("hide_to_system_tray");
    } catch (error) {
      console.error("Could not hide Jarvis to the system tray:", error);
    }
  }

  function handleCompactPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (expanded || closing || closingRef.current) return;
    if (drag?.pointerId === event.pointerId) {
      if (Math.hypot(event.screenX - drag.x, event.screenY - drag.y) > 5) {
        drag.moved = true;
        suppressHoverUntilLeaveRef.current = true;
        setPhase("idle");
        if (!drag.started) {
          drag.started = true;
          void win.startDragging().catch((error) => console.error("Could not drag the minimized orb:", error));
        }
      }
      return;
    }
    if (!suppressHoverUntilLeaveRef.current) setPhase("hover");
  }

  function handleCompactPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    if (drag.moved) {
      suppressClickRef.current = true;
      positionSavePromiseRef.current = saveDraggedPosition().finally(() => {
        positionSavePromiseRef.current = null;
      });
      void positionSavePromiseRef.current.catch((error) => console.error("Could not save the minimized orb position:", error));
      window.setTimeout(() => { suppressClickRef.current = false; }, 0);
      const bounds = event.currentTarget.getBoundingClientRect();
      const pointerIsOverOrb = event.clientX >= bounds.left && event.clientX <= bounds.right &&
        event.clientY >= bounds.top && event.clientY <= bounds.bottom;
      suppressHoverUntilLeaveRef.current = false;
      setPhase(pointerIsOverOrb ? "hover" : "idle");
      window.setTimeout(() => { void syncHoverAfterDrag(); }, 50);
    }
    dragRef.current = null;
  }

  function changeMode(next: "voice" | "keyboard") {
    if (next === "keyboard" && mode !== "keyboard") setConversationStarted(false);
    setMode(next);
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key.toLowerCase() === "k" && expanded) {
        event.preventDefault();
        changeMode(mode === "voice" ? "keyboard" : "voice");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [expanded, mode]);

  useEffect(() => {
    if (!expanded || phase !== "settling") return;

    const timer = window.setTimeout(() => {
      setPhase("breathing");
    }, 6500);

    return () => window.clearTimeout(timer);
  }, [expanded, phase]);

  useEffect(() => {
    if (!expanded || !opening) return;
    const timer = window.setTimeout(() => {
      openingRef.current = false;
      setPhase("settling");
      setOpening(false);
    }, 1400);
    return () => window.clearTimeout(timer);
  }, [expanded, opening]);

  async function openOrb() {
    if (expandedRef.current || openingRef.current || closingRef.current) return;

    openingRef.current = true;
    openingSetupReadyRef.current = false;
    setConversationStarted(false);
    speechLevel.set(0);
    setOpening(true);
    setPhase("opening");
    setOrbVisible(false);

    try {
      await positionSavePromiseRef.current?.catch(() => undefined);
      const actual = await win.outerPosition();
      const preferredPosition = latestWindowPositionRef.current ?? savedPositionRef.current ?? { x: actual.x, y: actual.y };
      const position = await minimizedPosition(preferredPosition);
      localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(position));
      savedPositionRef.current = position;
      activeMinimizedPositionRef.current = position;
      setSavedPosition(position);
      const monitor = await monitorForPosition(position);
      if (!monitor) throw new Error("Unable to determine the current monitor.");
      setOpeningFrom(logicalPosition(position, monitor));
      setExpandedViewport({
        width: monitor.size.width / monitor.scaleFactor,
        height: monitor.size.height / monitor.scaleFactor,
      });
      await resizeWindow(true, position);
      expandedRef.current = true;
      setExpanded(true);
      setOrbVisible(true);
    } catch (error) {
      console.error("Could not expand the Jarvis window:", error);
      openingRef.current = false;
      openingSetupReadyRef.current = true;
      expandedRef.current = false;
      setPhase("idle");
      setOpening(false);
      setOrbVisible(true);
      return;
    }

    await new Promise<void>((resolve) => window.setTimeout(resolve, 600));
    await win.setEffects({
      effects: [Effect.Acrylic],
      state: EffectState.Active,
      color: [18, 28, 48, 190],
    }).catch((error) => console.error("Could not apply the glass effect:", error));
    openingSetupReadyRef.current = true;
  }

  async function closeOrb() {
    if (closeInProgressRef.current || closingRef.current) return;
    closeInProgressRef.current = true;
    try {
      while (openingRef.current || !openingSetupReadyRef.current) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 40));
      }
      if (!expandedRef.current) return;

      const position = await minimizedPosition(activeMinimizedPositionRef.current ?? savedPositionRef.current);
      const monitor = await monitorForPosition(position);
      setClosingAt(logicalPosition(position, monitor));
      closingRef.current = true;
      setClosing(true);
      expandedRef.current = false;
      setExpanded(false);
      setConversationStarted(false);
      speechLevel.set(0);
      setPhase("idle");
      await win.clearEffects().catch(console.error);

      await new Promise<void>((resolve) => window.setTimeout(resolve, 1500));
      setOrbVisible(false);
      await resizeWindow(false, position);
      activeMinimizedPositionRef.current = position;
    } catch (error) {
      console.error("Could not shrink the Jarvis window:", error);
    } finally {
      closingRef.current = false;
      setClosing(false);
      window.requestAnimationFrame(() => setOrbVisible(true));
      closeInProgressRef.current = false;
    }
  }

  function handleHoverStart() {
    if (!expanded && !opening && !suppressHoverUntilLeaveRef.current) setPhase("hover");
  }

  function handleHoverEnd() {
    if (dragRef.current?.moved) {
      setPhase("idle");
      return;
    }
    suppressHoverUntilLeaveRef.current = false;
    if (!expanded && !opening) setPhase("idle");
  }

  const visible = expanded || opening;

  return (
    <>
      {visible && (
        <motion.div
          className="orb-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1.4, ease: "easeOut" }}
        />
      )}

      <motion.div
        className="orb-position"
        animate={{
          opacity: orbVisible ? 1 : 0,
          transition: { opacity: { duration: 0.12 } },
          ...(closing
            ? { left: closingAt.left, top: closingAt.top, x: 0, y: 0, width: 112, height: 112 }
            : expanded && opening
              ? {
                  left: [openingFrom.left, expandedOrbPosition.left],
                  top: [openingFrom.top, expandedOrbPosition.top],
                  x: 0,
                  y: 0,
                  width: [112, expandedOrbSize],
                  height: [112, expandedOrbSize],
                }
            : expanded
            ? { ...expandedOrbPosition, x: 0, y: 0, width: expandedOrbSize, height: expandedOrbSize }
            : { left: 20, top: 20, x: 0, y: 0, width: 112, height: 112 }),
        }}
        transition={{
          duration: !orbVisible && !closing && !opening ? 0 : 1.4,
          ease: [0.22, 1, 0.36, 1],
        }}
        onHoverStart={handleHoverStart}
        onHoverEnd={handleHoverEnd}
      >
        <motion.button
          ref={orbButtonRef}
          type="button"
          className={`orb-button ${phase !== "idle" ? "orb-button-active" : ""} ${phase === "hover" ? "orb-button-hover" : ""} ${phase === "breathing" ? "orb-button-breathing" : ""}`}
          aria-label="Open Jarvis"
          onClick={(event) => {
            event.stopPropagation();
            if (closingRef.current) return;
            if (suppressClickRef.current) {
              suppressClickRef.current = false;
              return;
            }

            if (!expanded) {
              void openOrb();
            }
          }}
          onPointerDown={handleCompactPointerDown}
          onContextMenu={handleCompactContextMenu}
          onPointerMove={handleCompactPointerMove}
          onPointerUp={handleCompactPointerUp}
          onPointerCancel={handleCompactPointerUp}
          animate={{
            width: expanded ? (mode === "keyboard" ? (conversationStarted ? compactOrbSize : 350) : 440) : 112,
            height: expanded ? (mode === "keyboard" ? (conversationStarted ? compactOrbSize : 350) : 440) : 112,
          }}
          transition={{
            duration: 1.4,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          <div
            className="orb-scene"
          >
            <div className="orb-3d-scene">
            <motion.div
              className="orb-glow-audio"
              style={{ scale: speechGlowScale }}
            >
              <motion.div
                className="orb-glow"
                animate={
                  phase === "breathing"
                    ? { opacity: [0.65, 1, 0.65], scale: [1, 1.15, 1] }
                    : phase === "hover"
                      ? { opacity: 1, scale: 1.15 }
                      : { opacity: 0.7, scale: 1 }
                }
                transition={
                  phase === "breathing"
                    ? { duration: 3.5, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.4, ease: "easeOut" }
                }
              />
            </motion.div>

            {rings.map((ring) => (
              <Ring
                key={ring.name}
                ring={ring}
                phase={phase}
              />
            ))}

            <motion.div
              className="orb-core"
              animate={
                phase === "settling"
                  ? { scale: [0.9, 1.06, 1] }
                  : phase === "breathing"
                    ? { scale: [1, 1.045, 1] }
                    : phase === "hover"
                      ? { scale: 1.04 }
                      : { scale: 1 }
              }
              transition={
                phase === "breathing"
                  ? {
                      duration: 3,
                      repeat: Infinity,
                      ease: "easeInOut",
                    }
                  : {
                      duration: 2.5,
                      ease: "easeInOut",
                    }
              }
            >
              <motion.img
                src="/orb/orb-core.svg"
                alt=""
                draggable={false}
                className="orb-core-image"
                style={{ scale: speechScale }}
              />
            </motion.div>

            </div>
          </div>
        </motion.button>

      </motion.div>

      {contextMenu && !expanded && (
        <>
          <button
            type="button"
            className="orb-context-dismiss"
            aria-label="Dismiss menu"
            onClick={() => setContextMenu(null)}
            onContextMenu={(event) => { event.preventDefault(); setContextMenu(null); }}
          />
          <div
            className="orb-context-menu"
            role="menu"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button type="button" role="menuitem" onClick={() => void hideToSystemTray()}>
              Hide
            </button>
          </div>
        </>
      )}

      {expanded && !opening && !closing && (
        <>
          <SpotifyMiniPlayer />
          <button
            type="button"
            className="orb-close"
            aria-label="Minimize Jarvis"
            title="Minimize Jarvis"
            onClick={() => void closeOrb()}
          >×</button>
          <ChatPanel
              visible={mode === "keyboard"}
              onConversationStart={() => setConversationStarted(true)}
              onSpeechLevel={(level) => speechLevel.set(level)}
          />
          <div className="orb-mode-switch">
            <span>{mode === "voice" ? "Voice mode" : "Keyboard mode"}</span>
            <button type="button" onClick={() => changeMode(mode === "voice" ? "keyboard" : "voice")}>
              {mode === "voice" ? "Open chat" : "Voice mode"}<kbd>Ctrl K</kbd>
            </button>
          </div>
        </>
      )}
    </>
  );
}
