import * as React from "react";
import { cn } from "../../lib/utils";

/**
 * Keeps a page's top-level tab bar pinned to the top of the scrolling <main>
 * so the user can switch tabs without scrolling back up. The translucent
 * background + blur lets content slide underneath without clashing with it.
 */
export function StickyTabBar({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("sticky top-0 z-20 -mx-1 bg-background/85 px-1 py-2 backdrop-blur-sm", className)} {...props} />;
}
