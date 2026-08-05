"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { durationPage, easeOut } from "@/lib/motion/tokens";

interface FadeInProps {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}

export function FadeIn({ children, delay = 0, y = 12, className }: FadeInProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: durationPage, delay, ease: easeOut }}
    >
      {children}
    </motion.div>
  );
}
