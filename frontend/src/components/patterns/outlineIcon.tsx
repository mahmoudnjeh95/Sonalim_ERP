import type { ComponentType, SVGProps } from "react";

export type OutlineIcon = ComponentType<SVGProps<SVGSVGElement>>;

// The supplied outline icons are drawn at stroke-width 3 on a 64px grid, which
// is under 1px at 16-20px and reads much lighter than the lucide icons beside
// them. This gives them comparable weight without editing the assets.
const STROKE_WIDTH = 5;

export function outlineIcon(Icon: OutlineIcon): OutlineIcon {
  return function OutlineIconWithWeight(props) {
    return <Icon strokeWidth={STROKE_WIDTH} {...props} />;
  };
}
