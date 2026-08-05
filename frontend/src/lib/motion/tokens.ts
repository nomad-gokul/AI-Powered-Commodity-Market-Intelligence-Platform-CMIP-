/**
 * Shared motion tokens — tuned once, reused everywhere, per the
 * "physics-based, purposeful, nothing gratuitous" motion philosophy.
 */
export const springSnappy = { type: "spring" as const, stiffness: 420, damping: 38, mass: 0.9 };
export const springSoft = { type: "spring" as const, stiffness: 220, damping: 30, mass: 1 };
export const durationMicro = 0.18;
export const durationPage = 0.36;

export const easeOut = [0.16, 1, 0.3, 1] as const;
