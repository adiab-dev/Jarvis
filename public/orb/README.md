# Jarvis Orb Assets

These are editable, transparent-background SVG assets for a React + Framer Motion orb.

## Files
- `orb-core.svg` — central glossy orb core.
- `ring-outer.svg` — outer ring layer.
- `ring-middle.svg` — middle segmented ring.
- `ring-inner.svg` — inner ring.
- `ring-decorative.svg` — extra HUD details.
- `glow-overlay.svg` — soft blue/cyan halo.

## Suggested use
Place the files in `public/orb/` or import them from your React source folder. Stack them in a square, `position: relative` container. Each ring should be absolutely positioned to fill the container and animated independently with Framer Motion. Keep the core centered above the rings. These SVGs are vector artwork; they do not require separate PNGs.

## Suggested animation speeds
- outer: 30 seconds, clockwise
- middle: 18 seconds, counter-clockwise
- inner: 12 seconds, clockwise
- decorative: 8 seconds, counter-clockwise

Use `transform-origin: center` for each ring. Respect `prefers-reduced-motion` and consider pausing animations when the orb is hidden.
