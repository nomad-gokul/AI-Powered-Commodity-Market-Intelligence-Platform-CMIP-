"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { durationPage, easeOut } from "@/lib/motion/tokens";

/**
 * Entrance-only page transition wrapper. A full exit/enter crossfade via
 * AnimatePresence keyed on the App Router segment is deferred to the F6
 * polish pass — it needs a client-side pathname key threaded through the
 * shared shell layout, which isn't worth the added complexity until every
 * route exists.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: durationPage, ease: easeOut }}
    >
      {children}
    </motion.div>
  );
}
