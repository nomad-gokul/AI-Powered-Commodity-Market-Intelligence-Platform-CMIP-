import {
  LayoutDashboard,
  LineChart,
  FileText,
  Share2,
  Search,
  Sparkles,
  Bot,
  Bell,
  Database,
  Workflow,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Shown as a small pill next to the label; omit for none. */
  badge?: string;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Markets", href: "/markets", icon: LineChart },
  { label: "Reports", href: "/reports", icon: FileText },
  { label: "Intelligence Graph", href: "/intelligence-graph", icon: Share2 },
  { label: "Search", href: "/search", icon: Search },
  { label: "Executive Intelligence", href: "/executive-intelligence", icon: Sparkles },
  { label: "AI Analyst", href: "/ai-analyst", icon: Bot },
  { label: "Alerts", href: "/alerts", icon: Bell, badge: "3" },
  { label: "Data Sources", href: "/data-sources", icon: Database },
  { label: "Architecture", href: "/architecture", icon: Workflow },
  { label: "Settings", href: "/settings", icon: Settings },
];
