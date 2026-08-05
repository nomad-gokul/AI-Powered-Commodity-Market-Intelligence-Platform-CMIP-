"use client";

import { useEffect, useRef } from "react";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";

interface CountUpProps {
  value: number;
  decimals?: number;
  suffix?: string;
  prefix?: string;
  duration?: number;
  className?: string;
}

export function CountUp({
  value,
  decimals = 0,
  suffix = "",
  prefix = "",
  duration = 1.1,
  className,
}: CountUpProps) {
  const motionValue = useMotionValue(0);
  const hasAnimated = useRef(false);
  const rounded = useTransform(motionValue, (latest) =>
    `${prefix}${latest.toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })}${suffix}`
  );

  useEffect(() => {
    if (hasAnimated.current) {
      motionValue.set(value);
      return;
    }
    hasAnimated.current = true;
    const controls = animate(motionValue, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [value, duration, motionValue]);

  return (
    <motion.span className={className} suppressHydrationWarning>
      {rounded}
    </motion.span>
  );
}
