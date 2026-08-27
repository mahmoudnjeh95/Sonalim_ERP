import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { motion } from "framer-motion";
import { cn } from "../../lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        "relative inline-flex items-center gap-1 rounded-lg border border-border bg-muted/60 p-1",
        className,
      )}
      {...props}
    />
  );
}

interface TabsTriggerProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> {
  active: boolean;
  layoutId: string;
}

export function TabsTrigger({ className, children, active, layoutId, ...props }: TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "relative z-10 rounded-md px-3.5 py-1.5 text-sm font-medium text-muted-foreground outline-none transition-colors",
        "data-[state=active]:text-foreground",
        className,
      )}
      {...props}
    >
      {active && (
        <motion.span
          layoutId={layoutId}
          className="absolute inset-0 -z-10 rounded-md bg-background shadow-soft"
          transition={{ type: "spring", stiffness: 500, damping: 35 }}
        />
      )}
      {children}
    </TabsPrimitive.Trigger>
  );
}

export const TabsContent = TabsPrimitive.Content;
